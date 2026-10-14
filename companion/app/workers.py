from __future__ import annotations

import asyncio

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from companion.adapters import tts_edge
from companion.core.llm.client import OpenAICompatibleClient
from companion.core.memory.extractor import extract_memories_with_llm


class ChatWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client: OpenAICompatibleClient, messages: list[dict[str, str]]) -> None:
        super().__init__()
        self.client = client
        self.messages = messages

    @pyqtSlot()
    def run(self) -> None:
        try:
            reply = self.client.chat(self.messages)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit(reply)


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
