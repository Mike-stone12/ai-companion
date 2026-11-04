"""In-memory PCM recording and WAV encoding without audio device access."""

from __future__ import annotations

import io
import math
import wave
from dataclasses import dataclass


def _validate_format(sample_rate: int, channels: int, sample_width: int) -> None:
    if not isinstance(sample_rate, int) or sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer")
    if not isinstance(channels, int) or channels < 1:
        raise ValueError("channels must be a positive integer")
    if not isinstance(sample_width, int) or sample_width not in (1, 2, 3, 4):
        raise ValueError("sample_width must be 1, 2, 3, or 4 bytes")


def encode_wav(pcm: bytes, sample_rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap complete PCM frames in a WAV file suitable for ``audio/wav``."""
    _validate_format(sample_rate, channels, sample_width)
    if len(pcm) % (channels * sample_width):
        raise ValueError("pcm must contain whole frames")
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setframerate(sample_rate)
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.writeframes(pcm)
    return output.getvalue()


@dataclass(frozen=True)
class AudioFormat:
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * self.sample_width


@dataclass(frozen=True)
class RecordedClip:
    """WAV bytes usable with the transcription client's ``speech.wav`` default."""

    wav: bytes
    duration_seconds: float
    truncated: bool = False


_DEFAULT_FORMAT = AudioFormat()


class PushToTalkRecorder:
    """Collect PCM between press and release, measuring time by complete frames.

    The cap rounds down to whole frames. A partial frame is carried to the next
    feed and discarded on release. Reaching the cap keeps the recording active
    until release or cancel, but subsequent feeds cannot append more audio.
    """

    def __init__(
        self,
        fmt: AudioFormat = _DEFAULT_FORMAT,
        min_seconds: float = 0.3,
        max_seconds: float = 60.0,
    ):
        if not isinstance(fmt, AudioFormat):
            raise ValueError("fmt must be an AudioFormat")
        _validate_format(fmt.sample_rate, fmt.channels, fmt.sample_width)
        if not isinstance(min_seconds, (int, float)) or not math.isfinite(min_seconds) or min_seconds < 0:
            raise ValueError("min_seconds must be finite and nonnegative")
        if not isinstance(max_seconds, (int, float)) or not math.isfinite(max_seconds) or max_seconds <= 0:
            raise ValueError("max_seconds must be finite and positive")
        if min_seconds > max_seconds:
            raise ValueError("min_seconds must not exceed max_seconds")
        self._fmt = fmt
        self._min_seconds = min_seconds
        self._frame_size = fmt.channels * fmt.sample_width
        self._max_bytes = int(max_seconds * fmt.sample_rate) * self._frame_size
        self._buffer = bytearray()
        self._pending = b""
        self._truncated = False
        self._is_recording = False

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def press(self) -> None:
        """Start fresh, including when already recording."""
        self.cancel()
        self._is_recording = True

    def feed(self, chunk: bytes) -> bool:
        """Append PCM; return False at the cap, or True for ignored idle feeds."""
        if not self._is_recording:
            return True
        if self._truncated:
            return False
        remaining = self._max_bytes - len(self._buffer)
        data = self._pending + chunk[:remaining - len(self._pending)]
        aligned_size = len(data) - len(data) % self._frame_size
        self._buffer.extend(data[:aligned_size])
        self._pending = data[aligned_size:]
        self._truncated = len(self._buffer) >= self._max_bytes
        return not self._truncated

    def release(self) -> RecordedClip | None:
        """Stop and return a WAV clip unless the recording was too short."""
        if not self._is_recording:
            return None
        duration = len(self._buffer) / self._fmt.bytes_per_second
        pcm = bytes(self._buffer)
        truncated = self._truncated
        self.cancel()
        if duration < self._min_seconds:
            return None
        return RecordedClip(
            wav=encode_wav(pcm, self._fmt.sample_rate, self._fmt.channels, self._fmt.sample_width),
            duration_seconds=duration,
            truncated=truncated,
        )

    def cancel(self) -> None:
        """Stop and discard complete frames, partial frames, and cap state."""
        self._is_recording = False
        self._buffer.clear()
        self._pending = b""
        self._truncated = False
