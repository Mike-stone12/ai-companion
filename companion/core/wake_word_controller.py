"""Synchronous wake-word orchestration without audio devices or recognizers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from enum import StrEnum

from companion.core.wake_word import WakeWordMatcher

logger = logging.getLogger(__name__)


class WakeWordState(StrEnum):
    """Listening status for the always-on indicator."""

    STOPPED = "stopped"
    LISTENING = "listening"
    SUSPENDED = "suspended"


class WakeWordController:
    """Gate transcripts by state and notify callers of matched phrases.

    The owned matcher handles cooldowns and partial/final de-duplication using
    the injected clock. Suspension preserves its utterance and cooldown; stop
    resets both for a fresh listening session. Call methods synchronously.
    """

    def __init__(
        self,
        phrases: Sequence[str],
        on_wake: Callable[[str], None],
        *,
        cooldown_seconds: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
        on_state_changed: Callable[[WakeWordState], None] | None = None,
    ):
        self._matcher = WakeWordMatcher(phrases, cooldown_seconds=cooldown_seconds, clock=clock)
        self._on_wake = on_wake
        self._on_state_changed = on_state_changed
        self._state = WakeWordState.STOPPED

    @property
    def state(self) -> WakeWordState:
        return self._state

    def _set_state(self, state: WakeWordState) -> None:
        if self._state == state:
            return
        self._state = state
        if self._on_state_changed is not None:
            self._on_state_changed(state)

    def start(self) -> None:
        """Start listening only when stopped."""
        if self._state == WakeWordState.STOPPED:
            self._set_state(WakeWordState.LISTENING)

    def stop(self) -> None:
        """Stop listening and clear the current utterance and cooldown."""
        self._matcher.reset()
        self._set_state(WakeWordState.STOPPED)

    def suspend(self) -> None:
        """Pause matching if currently listening."""
        if self._state == WakeWordState.LISTENING:
            self._set_state(WakeWordState.SUSPENDED)

    def resume(self) -> None:
        """Resume a suspension, leaving a stopped controller stopped."""
        if self._state == WakeWordState.SUSPENDED:
            self._set_state(WakeWordState.LISTENING)

    def feed_transcript(self, text: str, final: bool) -> bool:
        """Return whether a wake callback was invoked, even if it raised.

        Each final transcript closes an utterance while listening, including
        an empty final. Inactive input is ignored without reaching the matcher.
        """
        if self._state != WakeWordState.LISTENING:
            return False
        hit = self._matcher.feed(text, final=final)
        if hit is None:
            return False
        try:
            self._on_wake(hit.phrase)
        except Exception:
            logger.exception("Wake-word callback failed")
        return True
