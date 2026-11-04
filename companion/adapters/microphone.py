"""Qt microphone capture; create and operate this object on its Qt thread."""

from __future__ import annotations

import logging

from PyQt6.QtCore import QIODevice, QObject, pyqtSignal, pyqtSlot
from PyQt6.QtMultimedia import QAudio, QAudioFormat, QAudioSource, QMediaDevices

from companion.core.voice_input import AudioFormat

logger = logging.getLogger(__name__)


class Microphone(QObject):
    """Emit raw PCM for ``PushToTalkRecorder.feed`` or ``VoiceInputController.feed``.

    The format matches the default recorder exactly; unsupported devices are
    rejected rather than silently substituting a different rate or encoding.
    Connect ``pcm_ready`` and ``failed`` before starting. Stop capture before
    releasing the recorder so the final buffered bytes are included. The owner
    must keep this object alive until stopped; no audio is captured at import.
    """

    pcm_ready = pyqtSignal(bytes)
    failed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source: QAudioSource | None = None
        self._device: QIODevice | None = None

    def start(self) -> bool:
        """Start once; return False and emit a message if capture cannot start."""
        if self._source is not None:
            return True
        try:
            device = QMediaDevices.defaultAudioInput()
            if device.isNull():
                self._fail("No audio input device is available.")
                return False
            expected = AudioFormat()
            fmt = QAudioFormat()
            fmt.setSampleRate(expected.sample_rate)
            fmt.setChannelCount(expected.channels)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not device.isFormatSupported(fmt):
                self._fail(
                    f"Audio input device does not support {expected.sample_rate} Hz mono 16-bit PCM."
                )
                return False
            self._source = QAudioSource(device, fmt, self)
            self._device = self._source.start()
            if self._device is None or self._source.error() != QAudio.Error.NoError:
                self._fail("Could not start audio input. Check microphone access and device availability.")
                return False
            self._device.readyRead.connect(self._read_ready)
            self._source.stateChanged.connect(self._state_changed)
            self._read_ready()
            return self._source is not None
        except Exception:
            self._fail("Could not initialize audio input. Check microphone access and device availability.")
            return False

    def stop(self) -> None:
        """Deliver remaining available PCM and release the device; safe when idle."""
        source, device = self._source, self._device
        self._source = self._device = None
        if source is None:
            return
        try:
            chunk = bytes(device.readAll()) if device is not None else b""
        except Exception:
            chunk = b""
            self.failed.emit("Could not read the final microphone audio.")
        finally:
            self._dispose(source, device)
        if chunk:
            self.pcm_ready.emit(chunk)

    @pyqtSlot()
    def _read_ready(self) -> None:
        if self._device is None:
            return
        try:
            chunk = bytes(self._device.readAll())
        except Exception:
            self._fail("Could not read microphone audio.")
            return
        if chunk:
            self.pcm_ready.emit(chunk)

    def _state_changed(self, state: QAudio.State) -> None:
        if self._source is not None and self._source.error() != QAudio.Error.NoError:
            self._fail(f"Audio input failed ({self._source.error().name}). Check the microphone connection.")

    def _fail(self, message: str) -> None:
        source, device = self._source, self._device
        self._source = self._device = None
        if source is not None:
            self._dispose(source, device)
        logger.info("Microphone capture failed")
        self.failed.emit(message)

    def _dispose(self, source: QAudioSource, device: QIODevice | None) -> None:
        # Disconnect before stop(), which can emit stateChanged synchronously.
        for signal, slot in (
            (source.stateChanged, self._state_changed),
            (device.readyRead if device is not None else None, self._read_ready),
        ):
            if signal is not None:
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass  # start() may have failed before connecting the signals.
        try:
            source.stop()
        except Exception:
            logger.info("Microphone capture cleanup failed")
        finally:
            source.deleteLater()
