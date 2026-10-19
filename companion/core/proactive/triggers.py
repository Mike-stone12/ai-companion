"""Deterministic event proposals, independent of scheduling and policy.

All polling uses the caller's current time. Use compatible timezone conventions
for activity and polling, and aware datetimes for reminders. Deduplication lasts
for each trigger instance's lifetime and records proposals, even if policy later
rejects them.
"""

from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from .events import GREETING, IDLE, MOOD, REMINDER, Event

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


class AwakeGate:
    """Skip polling the wrapped trigger while the companion is asleep.

    Not polling (rather than rejecting in policy) keeps the trigger's deduplication
    unspent, so a morning greeting is proposed once the companion wakes up. Other
    attributes, such as an active-app trigger's ``record_sample``, pass through.
    """

    def __init__(self, trigger: Trigger, awake: Callable[[datetime], bool]):
        self._trigger = trigger
        self._awake = awake

    def poll(self, now: datetime) -> list[Event]:
        return self._trigger.poll(now) if self._awake(now) else []

    def __getattr__(self, name: str):
        return getattr(self._trigger, name)


FeelingProbe = Callable[[datetime], tuple[str | None, float]]
SULKING = frozenset({"anger", "jealousy"})
SULK_THRESHOLD = 0.5
MOOD_THRESHOLDS = {"longing": 0.5, "joy": 0.6}


class MoodGate(AwakeGate):
    """Skip polling while the companion is clearly annoyed or jealous: it waits to be coaxed."""

    def __init__(self, trigger: Trigger, feeling: FeelingProbe):
        def not_sulking(now: datetime) -> bool:
            name, value = feeling(now)
            return not (name in SULKING and value >= SULK_THRESHOLD)
        super().__init__(trigger, not_sulking)


class MoodTrigger:
    """Propose reaching out when the companion misses the user or is in a great mood.

    It proposes while the feeling is high and the user has been quiet for ``min_quiet``.
    At most one such message goes unanswered: after ``mark_sent``, nothing more is
    proposed until the user has written since then (no "I miss you" every two hours
    while they are away).
    """

    def __init__(
        self, feeling: FeelingProbe, last_activity: Callable[[], datetime | None],
        min_quiet: timedelta = timedelta(minutes=10),
    ):
        self._feeling = feeling
        self._last_activity = last_activity
        self._min_quiet = min_quiet
        self._sent_at: datetime | None = None

    def mark_sent(self, at: datetime) -> None:
        self._sent_at = at

    def poll(self, now: datetime) -> list[Event]:
        last = self._last_activity()
        if self._sent_at is not None and (last is None or last <= self._sent_at):
            return []
        name, value = self._feeling(now)
        threshold = MOOD_THRESHOLDS.get(name or "")
        if threshold is None or value < threshold:
            return []
        if last is not None and now - last < self._min_quiet:
            return []
        return [Event(MOOD, now, {"feeling": name})]


class TriggerAggregator:
    """Poll in supplied trigger order, preserving each trigger's event order."""

    def __init__(self, triggers: Iterable[Trigger]):
        self._triggers = tuple(triggers)

    def poll(self, now: datetime) -> list[Event]:
        return [event for trigger in self._triggers for event in trigger.poll(now)]
