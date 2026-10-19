"""Deterministic event proposals, independent of scheduling and policy.

All polling uses the caller's current time. Use compatible timezone conventions
for activity and polling, and aware datetimes for reminders. Deduplication lasts
for each trigger instance's lifetime and records proposals, even if policy later
rejects them.
"""

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from .events import GREETING, IDLE, REMINDER, Event

if TYPE_CHECKING:
    from companion.core.tools.reminders import ReminderStore


class Trigger(Protocol):
    def poll(self, now: datetime) -> list[Event]:
        """Propose events using only the supplied current time."""
        ...


class IdleTrigger:
    """Propose once when time since the latest interaction reaches the threshold."""

    def __init__(self, idle_threshold: timedelta, last_user_interaction: datetime | None = None):
        if idle_threshold < timedelta(0):
            raise ValueError("Idle threshold must be nonnegative")
        self._idle_threshold = idle_threshold
        self._last_user_interaction = last_user_interaction
        self._proposed = False

    def record_interaction(self, at: datetime) -> None:
        """Re-arm for a newer interaction; ignore repeated or stale timestamps."""
        if self._last_user_interaction is None or at > self._last_user_interaction:
            self._last_user_interaction = at
            self._proposed = False

    def poll(self, now: datetime) -> list[Event]:
        if self._proposed or self._last_user_interaction is None:
            return []
        if now - self._last_user_interaction < self._idle_threshold:
            return []
        self._proposed = True
        return [Event(IDLE, now)]


class GreetingTrigger:
    """Propose once per local date and part of day in the supplied datetime.

    Parts begin at 00:00 (night), 06:00 (morning), 12:00 (afternoon), and
    18:00 (evening). Quiet hours remain the policy's responsibility.
    """

    def __init__(self):
        self._proposed: set[tuple[date, str]] = set()

    def poll(self, now: datetime) -> list[Event]:
        part = ("night", "morning", "afternoon", "evening")[now.hour // 6]
        key = (now.date(), part)
        if key in self._proposed:
            return []
        self._proposed.add(key)
        return [Event(GREETING, now, {"part_of_day": part})]


class ReminderTrigger:
    """Propose each due reminder ID once, persisting proposal IDs when enabled.

    The store is queried without consuming reminders. Payloads preserve its
    short reminder text and ISO due timestamp, omitting IDs and creation times.
    """

    def __init__(self, store: "ReminderStore"):
        self._store = store
        self._proposed: set[str] = set()

    def poll(self, now: datetime) -> list[Event]:
        events = []
        for reminder in self._store.due(now):
            if reminder.id not in self._proposed:
                self._proposed.add(reminder.id)
                self._store.mark_proposed(reminder.id)
                events.append(Event(REMINDER, now, {"text": reminder.text, "due_at": reminder.due_at}))
        return events


class TriggerAggregator:
    """Poll in supplied trigger order, preserving each trigger's event order."""

    def __init__(self, triggers: Iterable[Trigger]):
        self._triggers = tuple(triggers)

    def poll(self, now: datetime) -> list[Event]:
        return [event for trigger in self._triggers for event in trigger.poll(now)]
