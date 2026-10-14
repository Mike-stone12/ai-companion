from __future__ import annotations

import asyncio

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from companion.adapters import tts_edge
from companion.core.llm.client import OpenAICompatibleClient
from companion.core.memory.extractor import extract_memories_with_llm
from companion.core.text import SentenceSplitter

DEMO_REPLY = (
    "Demo mode is active. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL to enable live responses."
)


class ChatStreamWorker(QObject):
    """Stream a reply, emitting raw text deltas and each speakable sentence as it completes."""

    delta = pyqtSignal(str)
    sentence = pyqtSignal(str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client: OpenAICompatibleClient, messages: list[dict[str, str]]) -> None:
        super().__init__()
        self.client = client
        self.messages = messages

    @pyqtSlot()
    def run(self) -> None:
        splitter = SentenceSplitter()
        parts: list[str] = []
        try:
            stream = self.client.stream_chat(self.messages) if self.client.config.api_key else iter([DEMO_REPLY])
            for text in stream:
                parts.append(text)
                self.delta.emit(text)
                for sentence in splitter.feed(text):
                    self.sentence.emit(sentence)
            for sentence in splitter.flush():
                self.sentence.emit(sentence)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit("".join(parts))


class TTSWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, text: str, voice: str) -> None:
        super().__init__()
        self.text = text
        self.voice = voice

    @pyqtSlot()
    def run(self) -> None:
        try:
            audio_path = asyncio.run(tts_edge.synthesize_to_file(self.text, self.voice))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit(audio_path)


class MemoryWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client: OpenAICompatibleClient, user_text: str, assistant_text: str) -> None:
        super().__init__()
        self.client = client
        self.user_text = user_text
        self.assistant_text = assistant_text

    @pyqtSlot()
    def run(self) -> None:
        try:
            memories = extract_memories_with_llm(self.client, self.user_text, self.assistant_text)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit(memories)
