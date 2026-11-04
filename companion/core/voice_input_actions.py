"""Desktop voice-input decisions without GUI dependencies."""

from collections.abc import Callable

from companion.core.voice_input_controller import VoiceInputResult


def can_start_voice_input(*, busy: bool, worker_active: bool, closing: bool) -> bool:
    return not (busy or worker_active or closing)


def deliver_voice_input_result(
    result: VoiceInputResult,
    submit: Callable[[str], None],
    notice: Callable[[str], None],
) -> None:
    """Route terminal results to the existing chat submission and notice paths."""
    if result.status == "ok":
        submit(result.text)
    elif result.status == "too_short":
        notice("Recording too short. Hold to talk a little longer.")
    elif result.status == "empty_transcript":
        notice("No speech recognized. Please try again.")
    elif result.status == "error":
        notice("Voice transcription failed. Please try again.")
