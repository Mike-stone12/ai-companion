from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from companion.adapters import tts_edge, tts_openai
from companion.core.chat.emotion import EmotionTagParser
from companion.core.chat.history import ConversationSummary
from companion.core.chat.summary import request_summary, update_conversation_summary
from companion.core.config import AppConfig
from companion.core.diary import clean_diary_text
from companion.core.llm.client import OpenAICompatibleClient, chat_request_options
from companion.core.llm.transcription import transcribe
from companion.core.memory.consolidate_pipeline import consolidate_store
from companion.core.memory.consolidator import ConsolidationDecision, build_consolidation_messages
from companion.core.memory.extractor import (
    MEMORY_RETRY_DELAYS,
    extract_memories_with_llm,
    extraction_request_options,
)
from companion.core.memory.self_memory import SELF_MEMORY_LIMIT, extract_self_memories
from companion.core.memory.store import MemoryStore
from companion.core.state import appraise
from companion.core.text import SentenceSplitter
from companion.core.tools.loop import run_tool_rounds
from companion.core.tools.registry import ToolRegistry
from companion.core.tts_provider import CustomVoice, rate_to_speed
from companion.core.vision import describe_image
from companion.core.voice_input_controller import VoiceInputController
from companion.paths import MEMORY_PATH, SELF_MEMORY_PATH

logger = logging.getLogger(__name__)

DEMO_REPLY = (
    "Demo mode is active. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL to enable live responses."
)


class ChatStreamWorker(QObject):
    """Stream a reply, emitting raw text deltas and each speakable sentence as it completes."""

    emotion = pyqtSignal(str)
    delta = pyqtSignal(str)
    sentence = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self, client: OpenAICompatibleClient,
        messages: list[dict[str, str]] | Callable[[], list[dict[str, str]]],
        *, registry: ToolRegistry | None = None,
    ) -> None:
        super().__init__()
        self.client = client
        self.messages = messages
        self.registry = registry

    @pyqtSlot()
    def run(self) -> None:
        tags = EmotionTagParser()
        splitter = SentenceSplitter()
        parts: list[str] = []
        emotion_sent = False

        def publish(text: str) -> None:
            nonlocal emotion_sent
            if tags.emotion and not emotion_sent:
                self.emotion.emit(tags.emotion)
                emotion_sent = True
            if not text:
                return
            parts.append(text)
            self.delta.emit(text)
            for sentence in splitter.feed(text):
                self.sentence.emit(sentence)

        try:
            # Deferred memory context (including embedding I/O) runs on this worker's QThread.
            if callable(self.messages):
                self.messages = self.messages()
            if self.client.config.chat_tools and self.client.config.api_key:
                if self.registry is None:
                    raise ValueError("Chat tools require a session registry")
                run_tool_rounds(
                    self.messages, self.registry, self.client.stream_chat_chunks,
                    on_text=lambda text: publish(tags.feed(text)), max_rounds=3,
                )
            else:
                stream = self.client.stream_chat(self.messages) if self.client.config.api_key else iter([DEMO_REPLY])
                for text in stream:
                    publish(tags.feed(text))
            publish(tags.flush())
            for sentence in splitter.flush():
                self.sentence.emit(sentence)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit("".join(parts))


class TranscriptionWorker(QObject):
    """Transcribe one WAV on a QThread, using the existing client socket timeout.

    As with the other workers, move this object to a QThread and connect that
    thread's started signal to run. Both terminal signals should quit the thread.
    The client's default 30-second timeout bounds socket waits, not total time;
    thread owners should use bounded waits during shutdown.

    Pass ``wav=None`` and ``session`` to finalize a controller on this thread;
    that mode uses its injected transcriber and emits only ``session_finished``.
    """

    finished = pyqtSignal(str)
    failed = pyqtSignal(str)
    session_finished = pyqtSignal(object)

    def __init__(
        self, wav: bytes | None, config: AppConfig, *, session: VoiceInputController | None = None,
    ) -> None:
        super().__init__()
        self.wav = wav
        self.session = session
        # Snapshot settings so edits cannot change an in-flight request.
        self.base_url = config.base_url
        self.api_key = config.api_key
        self.model = config.transcription_model

    @pyqtSlot()
    def run(self) -> None:
        if self.session is not None:
            # stop() owns WAV finalization, empty/error handling, and cancellation.
            self.session_finished.emit(self.session.stop())
            return
        try:
            text = transcribe(
                self.wav, base_url=self.base_url, api_key=self.api_key, model=self.model,
            )
        except Exception as exc:
            # Do not log audio, transcripts, credentials, or provider error bodies.
            logger.info("Transcription worker failed")
            self.failed.emit(str(exc) or type(exc).__name__)
            return
        self.finished.emit(text)


class VisionWorker(QObject):
    """Describe one picture with the vision model; emits the description or ""."""

    finished = pyqtSignal(str)

    def __init__(self, client: OpenAICompatibleClient, data_url: str, caption: str) -> None:
        super().__init__()
        self.client = client
        self.data_url = data_url
        self.caption = caption

    def complete(self, messages: list[dict]) -> str:
        return self.client.complete(messages, extra=chat_request_options(self.client.config))

    @pyqtSlot()
    def run(self) -> None:
        self.finished.emit(describe_image(self.complete, self.data_url, self.caption) or "")


class TTSWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    # The custom voice failed and Edge TTS spoke instead; carries the (key-free) reason.
    fellBack = pyqtSignal(str)

    def __init__(
        self, text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz", custom: CustomVoice | None = None,
    ) -> None:
        super().__init__()
        self.text = text
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.custom = custom

    @pyqtSlot()
    def run(self) -> None:
        if self.custom is not None:
            try:
                self.finished.emit(tts_openai.synthesize_to_file(self.custom, self.text, rate_to_speed(self.rate)))
                return
            except Exception as exc:  # noqa: BLE001 - fall back to the default voice
                logger.warning("Custom voice failed, using Edge TTS: %s", exc)
                self.fellBack.emit(str(exc))
        try:
            audio_path = asyncio.run(
                tts_edge.synthesize_to_file(self.text, self.voice, rate=self.rate, pitch=self.pitch)
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit(audio_path)


class SelfMemoryWorker(QObject):
    """Extract what the companion said about itself and merge it into self_memory.json."""

    finished = pyqtSignal(list)

    def __init__(self, client: OpenAICompatibleClient, user_text: str, assistant_text: str) -> None:
        super().__init__()
        self.client = client
        self.user_text = user_text
        self.assistant_text = assistant_text

    def complete(self, messages: list[dict[str, str]]) -> str:
        return self.client.complete(
            messages, extra=extraction_request_options(self.client.config.base_url), retry_delays=MEMORY_RETRY_DELAYS,
        )

    def request_consolidation(self, candidate: str, existing: list[str]) -> ConsolidationDecision | str | None:
        if not existing:
            return ConsolidationDecision("ADD", None, candidate)
        return self.complete(build_consolidation_messages(candidate, existing))

    @pyqtSlot()
    def run(self) -> None:
        memories: list[dict[str, str]] = []
        try:
            memories = extract_self_memories(self.complete, self.user_text, self.assistant_text)
            if memories:
                store = MemoryStore(SELF_MEMORY_PATH, SELF_MEMORY_LIMIT)
                if self.client.config.memory_consolidation:
                    consolidate_store(store, memories, self.request_consolidation)
                else:
                    store.upsert_many(memories)
        except Exception as exc:  # noqa: BLE001 - an optional background step must not crash the app
            logger.info("Self-memory update failed (%s)", type(exc).__name__)
        self.finished.emit(memories)


class DiaryWorker(QObject):
    """Write one diary entry in the persona's voice; emits the cleaned text or ""."""

    finished = pyqtSignal(str)

    def __init__(self, client: OpenAICompatibleClient, messages: list[dict[str, str]]) -> None:
        super().__init__()
        self.client = client
        self.messages = messages

    @pyqtSlot()
    def run(self) -> None:
        try:
            options = extraction_request_options(self.client.config.base_url)
            options.pop("response_format", None)  # prose, not JSON
            options.pop("temperature", None)  # let the persona's voice vary
            text = clean_diary_text(self.client.complete(self.messages, extra=options))
        except Exception as exc:  # noqa: BLE001
            logger.info("Diary request failed (%s)", type(exc).__name__)
            text = ""
        self.finished.emit(text)


class AppraisalWorker(QObject):
    """Ask the LLM what happened emotionally in one turn; emits an Appraisal or None."""

    finished = pyqtSignal(object)

    def __init__(
        self, client: OpenAICompatibleClient, user_text: str, assistant_text: str, grievances: dict[str, list[str]],
    ) -> None:
        super().__init__()
        self.client = client
        self.user_text = user_text
        self.assistant_text = assistant_text
        self.grievances = grievances

    def complete(self, messages: list[dict[str, str]]) -> str:
        # JSON mode with reasoning off, like memory extraction; no retries, it is optional.
        return self.client.complete(messages, extra=extraction_request_options(self.client.config.base_url))

    @pyqtSlot()
    def run(self) -> None:
        self.finished.emit(appraise(self.complete, self.user_text, self.assistant_text, self.grievances))


class SummaryWorker(QObject):
    """Run one snapshot update on the window's dedicated summary QThread."""

    finished = pyqtSignal(object)

    def __init__(
        self,
        client: OpenAICompatibleClient,
        turns: list[dict[str, str]],
        summary: ConversationSummary | None,
        window: int,
    ) -> None:
        super().__init__()
        # Use the existing client's bounded retries and a positive, capped socket timeout.
        self.client = OpenAICompatibleClient(replace(
            client.config, request_timeout=max(1, min(client.config.request_timeout, 60)),
        ))
        self.turns = turns
        self.summary = summary
        self.window = window

    @pyqtSlot()
    def run(self) -> None:
        result = self.summary
        try:
            if self.client.config.api_key:
                result = update_conversation_summary(
                    self.turns, self.summary,
                    lambda turns, previous: request_summary(self.client, turns, previous),
                    window=self.window,
                )
                if result is not self.summary:
                    logger.info("Conversation summary updated: covered=%d", result.summarized_count)
        except Exception:
            logger.info("Conversation summary worker failed")
        self.finished.emit(result)


class MemoryWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client: OpenAICompatibleClient, user_text: str, assistant_text: str) -> None:
        super().__init__()
        self.client = client
        self.user_text = user_text
        self.assistant_text = assistant_text

    def request_consolidation(self, candidate: str, existing: list[str]) -> ConsolidationDecision | str | None:
        if not self.client.config.api_key:
            return None
        if not existing:
            return ConsolidationDecision("ADD", None, candidate)
        return self.client.complete(
            build_consolidation_messages(candidate, existing),
            extra=extraction_request_options(self.client.config.base_url),
            retry_delays=MEMORY_RETRY_DELAYS,
        )

    @pyqtSlot()
    def run(self) -> None:
        try:
            memories = extract_memories_with_llm(self.client, self.user_text, self.assistant_text)
            if self.client.config.memory_consolidation:
                store = MemoryStore(MEMORY_PATH, self.client.config.memory_limit)
                result = consolidate_store(store, memories, self.request_consolidation)
                logger.info(
                    "Memory consolidation: added=%d updated=%d unchanged=%d fallback=%d",
                    result.added, result.updated, result.unchanged, result.fallback_count,
                )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit(memories)
