"""Synchronous proactive orchestration using only caller-supplied time."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from .events import Event
from .policy import ProactivePolicy
from .triggers import Trigger


@dataclass(frozen=True)
class ProactiveContext:
    last_user_activity: datetime | None
    busy: bool


@dataclass(frozen=True)
class ProactiveResult:
    event: Event
    messages: list[dict[str, str]]


class ProactiveEngine:
    """Select at most one allowed proposal and compose it for chat.

    The composer follows ``compose_message(event) -> dict[str, str]``.
    Trigger order takes precedence over event time (earliest first); equal
    times retain the trigger's event order. All triggers are polled each tick.
    Proposals are not queued or retried: trigger deduplication still applies
    even when an event is rejected or loses priority.
    """

    def __init__(
        self,
        triggers: Iterable[Trigger],
        policy: ProactivePolicy,
        composer: Callable[[Event], dict[str, str]],
    ):
        self._triggers = tuple(triggers)
        self._policy = policy
        self._composer = composer

    def tick(self, now: datetime, context: ProactiveContext) -> ProactiveResult | None:
        """Poll, check every candidate, and return the highest-priority result.

        Times must use compatible timezone conventions, as required by the
        triggers and policy. Record only successfully composed events; composer
        exceptions propagate without consuming a policy cooldown.
        """
        candidates = [
            event
            for trigger in self._triggers
            for event in sorted(trigger.poll(now), key=lambda event: event.at)
        ]
        selected = None
        for event in candidates:
            allowed, _ = self._policy.allow(
                event, last_user_activity=context.last_user_activity, busy=context.busy
            )
            if allowed and selected is None:
                selected = event

        if selected is None:
            return None

        result = ProactiveResult(event=selected, messages=[self._composer(selected)])
        self._policy.record_fired(selected)
        return result
