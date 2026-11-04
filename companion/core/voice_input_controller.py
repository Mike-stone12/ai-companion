"""Synchronous push-to-talk orchestration without devices or network defaults."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Literal

from companion.core.voice_input import PushToTalkRecorder

if TYPE_CHECKING:
    from companion.core.config import AppConfig

VoiceInputState = Literal["idle", "recording", "transcribing"]
VoiceInputStatus = Literal[
    "idle", "recording", "transcribing", "disabled", "ok", "too_short", "empty_transcript", "error",
]


@dataclass(frozen=True)
class VoiceInputResult:
    """An operation's outcome; only ``ok`` carries text for the caller to submit."""

    status: VoiceInputStatus
    text: str = ""
    message: str = ""


class VoiceInputController:
    """Coordinate one turn using the recorder's format and duration limits.

    ``transcribe`` accepts WAV bytes and returns text. The existing transcription
    client can be injected with its connection/model arguments bound using
    ``functools.partial``. No transcriber is installed by default.

    ``stop`` blocks during transcription and may be called from a worker thread.
    Other operations remain available: busy starts/stops are ignored, and cancel
    suppresses the pending result without interrupting the callable. Terminal
    outcomes are returned by ``stop``; the live ``state`` returns to idle.
    An injected recorder is owned exclusively by this controller.
    """

    def __init__(
        self,
        config: AppConfig,
        transcribe: Callable[[bytes], str] | None = None,
        *,
        recorder: PushToTalkRecorder | None = None,
    ):
        self._config = config
        self._transcribe = transcribe
        self._recorder = recorder if recorder is not None else PushToTalkRecorder()
        self._state: VoiceInputState = "idle"
        self._cancelled = False
        self._lock = Lock()

    @property
    def state(self) -> VoiceInputState:
        with self._lock:
            return self._state

    def start(self) -> VoiceInputResult:
        """Begin capture if enabled and idle, preserving any active turn."""
        with self._lock:
            if self._state != "idle":
                return VoiceInputResult(self._state)
            if not self._config.voice_input_usable:
                return VoiceInputResult("disabled")
            self._recorder.press()
            self._state = "recording"
            return VoiceInputResult("recording")

    def feed(self, chunk: bytes) -> bool:
        """Feed PCM using the recorder's semantics: False means the cap was hit."""
        with self._lock:
            return self._recorder.feed(chunk)

    def stop(self) -> VoiceInputResult:
        """Finalize capture and transcribe once, returning only nonempty text."""
        with self._lock:
            if self._state != "recording":
                return VoiceInputResult(self._state)
            clip = self._recorder.release()
            if clip is None:
                self._state = "idle"
                return VoiceInputResult("too_short")
            self._state = "transcribing"

        # Do not hold the lock while executing an injected, potentially slow call.
        try:
            if self._transcribe is None:
                result = VoiceInputResult("error", message="No transcribe callable configured")
            else:
                text = self._transcribe(clip.wav).strip()
                result = VoiceInputResult("ok", text=text) if text else VoiceInputResult("empty_transcript")
        except Exception as exc:
            result = VoiceInputResult("error", message=str(exc) or type(exc).__name__)
        finally:
            with self._lock:
                cancelled = self._cancelled
                self._cancelled = False
                self._state = "idle"
        return VoiceInputResult("idle") if cancelled else result

    def cancel(self) -> VoiceInputResult:
        """Discard capture, or suppress an in-flight transcription's result."""
        with self._lock:
            self._recorder.cancel()
            if self._state == "transcribing":
                self._cancelled = True
            else:
                self._state = "idle"
            return VoiceInputResult(self._state)
