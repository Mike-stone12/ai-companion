from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class AvatarBridge(QObject):
    """QWebChannel object shared with live2d_renderer.html as `avatar`.

    Python drives the renderer through the command signals; the renderer reports back by
    calling the report* slots, which are re-emitted as Python-side event signals.
    """

    # Python -> renderer
    playAudio = pyqtSignal(str)
    stopAudio = pyqtSignal()
    setTalking = pyqtSignal(bool)
    playRandomMotion = pyqtSignal()

    # renderer -> Python
    ready = pyqtSignal()
    audioStarted = pyqtSignal(float)
    audioFinished = pyqtSignal()
    audioFailed = pyqtSignal(str)

    @pyqtSlot()
    def reportReady(self) -> None:
        self.ready.emit()

    @pyqtSlot(float)
    def reportAudioStarted(self, duration: float) -> None:
        self.audioStarted.emit(duration)

    @pyqtSlot()
    def reportAudioFinished(self) -> None:
        self.audioFinished.emit()

    @pyqtSlot(str)
    def reportAudioError(self, message: str) -> None:
        self.audioFailed.emit(message)
