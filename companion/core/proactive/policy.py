"""Deterministic eligibility checks for proactive events."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from .events import ACTIVE_APP, GREETING, IDLE, REMINDER, Event


@dataclass(frozen=True)
class PolicyConfig:
    enabled_kinds: frozenset[str] = frozenset({IDLE, GREETING, REMINDER})
    cooldowns: Mapping[str, timedelta] = field(
        default_factory=lambda: {
            IDLE: timedelta(minutes=30),
            GREETING: timedelta(hours=4),
            REMINDER: timedelta(0),
        }
    )
    quiet_start: time | None = None
    quiet_end: time | None = None
    user_active_grace: timedelta = timedelta(minutes=2)


class ProactivePolicy:
    def __init__(self, config: PolicyConfig):
        self.config = config
        self._last_fired: dict[str, datetime] = {}

    def allow(self, event: Event, *, last_user_activity: datetime | None, busy: bool) -> tuple[bool, str]:
        """Check eligibility without recording a fire or changing policy state.

        Datetimes must use compatible timezone conventions. Quiet hours use the
        event's wall-clock time, with an inclusive start and exclusive end.
        """
        if event.kind not in self.config.enabled_kinds:
            return False, "disabled"
        if busy:
            return False, "busy"
        if last_user_activity is not None and event.at - last_user_activity < self.config.user_active_grace:
            return False, "user_active"

        start, end = self.config.quiet_start, self.config.quiet_end
        if event.kind != REMINDER and start is not None and end is not None:
            at = event.at.time()
            # Equal bounds describe an empty window.
            quiet = start <= at < end if start <= end else at >= start or at < end
            if quiet:
                return False, "quiet_hours"

        last_fired = self._last_fired.get(event.kind)
        # Active-app monitoring remains opt-in, with a default when enabled.
        default_cooldown = timedelta(minutes=60) if event.kind == ACTIVE_APP else timedelta(0)
        cooldown = self.config.cooldowns.get(event.kind, default_cooldown)
        if last_fired is not None and event.at - last_fired < cooldown:
            return False, "cooldown"
        return True, "ok"

    def record_fired(self, event: Event) -> None:
        """Record an actual fire independently of eligibility checks."""
        self._last_fired[event.kind] = event.at
