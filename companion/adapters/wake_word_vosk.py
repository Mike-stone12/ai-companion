"""Optional offline speech recognition without audio capture or Qt dependencies."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)


class WakeWordRecognizerUnavailable(RuntimeError):
    """The optional recognizer dependency or model directory is unavailable."""


class VoskWakeWordRecognizer:
    """Recognize wake phrases from 16-bit little-endian mono PCM chunks.

    Call synchronously. After each feed, pass the returned text (or "") and
    is_final to WakeWordController.feed_transcript, even for empty finals so
    the controller can close the utterance.
    """

    def __init__(
        self,
        model_path: str | Path,
        phrases: Sequence[str],
        sample_rate: int = 16000,
    ):
        path = Path(model_path)
        if not path.is_dir():
            raise WakeWordRecognizerUnavailable(f"Vosk model directory does not exist: {path}")
        grammar = json.dumps([phrase.strip().lower() for phrase in phrases] + ["[unk]"])
        try:
            import vosk

            self._model = vosk.Model(str(path))
            self._recognizer = vosk.KaldiRecognizer(self._model, sample_rate, grammar)
        except ImportError as exc:
            raise WakeWordRecognizerUnavailable("Vosk or a required dependency is not installed") from exc
        self._is_final = False

    @property
    def is_final(self) -> bool:
        """Whether the most recent PCM chunk completed an utterance."""
        return self._is_final

    def feed(self, pcm: bytes) -> str | None:
        """Accept raw PCM at the configured sample rate and return its transcript."""
        self._is_final = bool(self._recognizer.AcceptWaveform(pcm))
        raw = self._recognizer.Result() if self._is_final else self._recognizer.PartialResult()
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("Vosk returned malformed JSON")
            return None
        text = result.get("text" if self._is_final else "partial") if isinstance(result, dict) else None
        if not isinstance(text, str):
            return None
        text = text.strip()
        if not text or all(token == "[unk]" for token in text.split()):
            return None
        return text

    def reset(self) -> None:
        """Clear recognition state when supported by the installed Vosk version."""
        reset = getattr(self._recognizer, "Reset", None)
        if callable(reset):
            reset()
        self._is_final = False
