"""Track caller-supplied foreground samples and propose a break once per streak."""

from collections.abc import Iterable
from datetime import datetime, timedelta

from .events import ACTIVE_APP, Event


class ActiveAppTrigger:
    """A foreground-app tracker implementing the trigger ``poll(now)`` API.

    Record samples in chronological order using compatible timezone conventions.
    Repeated or stale timestamps are ignored. Only sampled time counts toward the
    threshold; polling never assumes an app remained active after its last sample.
    Allowlist names match exactly; an empty allowlist watches no apps.
    Deduplication records proposals even if policy later rejects them.
    """

    def __init__(
        self,
        threshold: timedelta = timedelta(minutes=40),
        max_gap: timedelta = timedelta(minutes=2),
        allowlist: Iterable[str] | None = None,
    ):
        if threshold < timedelta(0):
            raise ValueError("Active app threshold must be nonnegative")
        if max_gap < timedelta(0):
            raise ValueError("Maximum sample gap must be nonnegative")
        self._threshold = threshold
        self._max_gap = max_gap
        self._allowlist = None if allowlist is None else frozenset(allowlist)
        self._app_name: str | None = None
        self._started_at: datetime | None = None
        self._last_sample: datetime | None = None
        self._proposed = False

    def record_sample(self, app_name: str | None, now: datetime) -> None:
        """Update the streak, resetting on app change, absence, or a sample gap."""
        if self._last_sample is not None and now <= self._last_sample:
            return
        if (
            app_name is None
            or app_name != self._app_name
            or self._last_sample is None
            or now - self._last_sample > self._max_gap
        ):
            self._started_at = now if app_name is not None else None
            self._proposed = False
        self._app_name = app_name
        self._last_sample = now

    def poll(self, now: datetime) -> list[Event]:
        """Propose once for a qualifying streak with a recent foreground sample."""
        if self._proposed or self._app_name is None or self._started_at is None or self._last_sample is None:
            return []
        if not timedelta(0) <= now - self._last_sample <= self._max_gap:
            return []
        if self._allowlist is not None and self._app_name not in self._allowlist:
            return []
        elapsed = self._last_sample - self._started_at
        if elapsed < self._threshold:
            return []
        self._proposed = True
        return [Event(ACTIVE_APP, now, {"app_name": self._app_name, "minutes": elapsed // timedelta(minutes=1)})]
