"""Qt bridge for optional offline wake-word recognition on a dedicated QThread."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QCoreApplication, QObject, QThread, pyqtSignal, pyqtSlot

from companion.adapters.wake_word_vosk import VoskWakeWordRecognizer
from companion.core.config import AppConfig
from companion.core.wake_word_audio import Pcm16ChunkBuffer
from companion.core.wake_word_controller import WakeWordController

logger = logging.getLogger(__name__)


class WakeWordWorker(QObject):
    """Receive 16 kHz mono signed 16-bit little-endian PCM on a worker thread.

    Move this parentless object to a dedicated QThread before starting it.
    Connect thread.started to start, Microphone.pcm_ready to feed, and an owner's
    stop-request signal to stop, using Qt.ConnectionType.QueuedConnection.
    Connect finished to thread.quit and thread.finished to worker.deleteLater.
    Keep both objects alive until thread.finished; use bounded shutdown waits.
    Do not call these slots directly from the UI thread.

    started indicates that the model is ready for capture. Disabled/incomplete
    settings finish without loading Vosk. Errors emit error followed by finished.
    The owner controls microphone capture and should stop it when we finish.
    No audio is captured or recognizer constructed in __init__.
    """

    wakeDetected = pyqtSignal(str)
    error = pyqtSignal(str)
    started = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        # Settings edits apply to the next worker, not an in-flight session.
        self._enabled = config.wake_word_usable
        self._phrases = tuple(config.wake_word_phrases)
        self._model_dir = config.wake_word_model_dir
        self._recognizer: VoskWakeWordRecognizer | None = None
        self._controller: WakeWordController | None = None
        self._pcm = Pcm16ChunkBuffer()
        self._active = False

    def _check_thread(self) -> None:
        current = QThread.currentThread()
        app = QCoreApplication.instance()
        if current != self.thread() or (app is not None and current == app.thread()):
            raise RuntimeError("Wake-word worker must run on its background QThread.")

    @pyqtSlot()
    def start(self) -> None:
        """Initialize recognition on this thread; repeated starts are harmless."""
        if self._active:
            return
        self._active = True
        try:
            self._check_thread()
            if not self._enabled:
                self.stop()
                return
            self._controller = WakeWordController(self._phrases, self.wakeDetected.emit)
            self._recognizer = VoskWakeWordRecognizer(self._model_dir, self._phrases, sample_rate=16000)
            self._controller.start()
        except Exception as exc:
            self._fail(exc)
            return
        self.started.emit()

    @pyqtSlot(bytes)
    def feed(self, chunk: bytes) -> None:
        """Consume streamed audio; ignore input before start or after stop."""
        if self._recognizer is None:
            return
        try:
            self._check_thread()
            pcm = self._pcm.feed(chunk)
            if not pcm:
                return
            text = self._recognizer.feed(pcm)
            # Empty finals must reach the controller to close the utterance.
            self._controller.feed_transcript(text or "", final=self._recognizer.is_final)
        except Exception as exc:
            self._fail(exc)

    @pyqtSlot()
    def stop(self) -> None:
        """Release recognition on this thread, discarding incomplete audio."""
        if not self._active:
            return
        self._active = False
        # The adapter owns native Vosk objects; dropping it releases both model
        # and recognizer. reset() alone would retain the loaded model.
        self._recognizer = None
        if self._controller is not None:
            self._controller.stop()
            self._controller = None
        self._pcm.reset()
        self.finished.emit()

    def _fail(self, exc: Exception) -> None:
        # Do not log PCM or recognized transcripts.
        logger.info("Wake-word worker failed")
        try:
            self.error.emit(str(exc) or type(exc).__name__)
        finally:
            self.stop()
