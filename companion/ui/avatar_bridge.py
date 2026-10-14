from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class AvatarBridge(QObject):
    """QWebChannel object shared with live2d_renderer.html as `avatar`.

    Python drives the renderer through the command signals; the renderer reports back by
    calling the report* slots, which are re-emitted as Python-side event signals. playAudio
    queues a clip; every clip is reported back by URL exactly once (finished or failed).
    """

    # Python -> renderer
    playAudio = pyqtSignal(str)
    stopAudio = pyqtSignal()
    setTalking = pyqtSignal(bool)
    setEmotion = pyqtSignal(str)
    playRandomMotion = pyqtSignal()

    # renderer -> Python
    ready = pyqtSignal()
    audioStarted = pyqtSignal(str, float)
    audioFinished = pyqtSignal(str)
    audioFailed = pyqtSignal(str, str)

    @pyqtSlot()
    def reportReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(str, float)
    def reportAudioStarted(self, url: str, duration: float) -> None:
        self.audioStarted.emit(url, duration)

    @pyqtSlot(str)
    def reportAudioFinished(self, url: str) -> None:
        self.audioFinished.emit(url)

    @pyqtSlot(str, str)
    def reportAudioError(self, url: str, message: str) -> None:
        self.audioFailed.emit(url, message)
