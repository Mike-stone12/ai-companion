"""Pure-Python wake-phrase matching without speech recognition or audio access."""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass


def normalize_wake_text(text: str) -> str:
    """Normalize width and case, removing Unicode whitespace and punctuation."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    return "".join(
        char for char in normalized
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


@dataclass(frozen=True)
class WakeWordHit:
    """The original configured phrase and the clock value when it matched."""

    phrase: str
    at: float


class WakeWordMatcher:
    """Match recognized text at most once per utterance, subject to a cooldown.

    Each feed is a partial or final transcript, not a chunk to concatenate.
    A final result closes the utterance, including when empty or suppressed.
    Only emitted hits start the cooldown and latch the current utterance.
    """

    def __init__(
        self,
        phrases: Sequence[str],
        cooldown_seconds: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not phrases:
            raise ValueError("phrases must not be empty")
        self._phrases = tuple((phrase, normalize_wake_text(phrase)) for phrase in phrases)
        if any(not normalized for _, normalized in self._phrases):
            raise ValueError("each phrase must normalize to nonempty text")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be nonnegative")
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._utterance_hit = False
        self._last_hit_at: float | None = None

    def feed(self, text: str, *, final: bool) -> WakeWordHit | None:
        """Return the earliest matching phrase when armed and outside cooldown."""
        already_hit = self._utterance_hit
        if final:
            self._utterance_hit = False
        if already_hit:
            return None
        normalized = normalize_wake_text(text)
        if not normalized:
            return None

        phrase = None
        earliest = len(normalized)
        for original, wake_text in self._phrases:
            position = normalized.find(wake_text)
            if 0 <= position < earliest:
                phrase = original
                earliest = position
        if phrase is None:
            return None

        now = self._clock()
        if self._last_hit_at is not None and now - self._last_hit_at < self._cooldown_seconds:
            return None
        self._last_hit_at = now
        self._utterance_hit = not final
        return WakeWordHit(phrase=phrase, at=now)

    def reset(self) -> None:
        """Clear the current utterance's hit and the cooldown."""
        self._utterance_hit = False
        self._last_hit_at = None
