import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

from companion.core.proactive.events import GREETING, IDLE, REMINDER, Event
from companion.core.proactive.triggers import GreetingTrigger, IdleTrigger, ReminderTrigger, TriggerAggregator
from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)
THRESHOLD = timedelta(minutes=5)


def test_idle_threshold_once_and_rearming():
    trigger = IdleTrigger(idle_threshold=THRESHOLD, last_user_interaction=NOW)
    due = NOW + THRESHOLD
    assert trigger.poll(NOW) == []
    assert trigger.poll(due - timedelta(microseconds=1)) == []
    assert trigger.poll(due) == [Event(IDLE, due)]
    for seconds in (30, 60, 3600):
        assert trigger.poll(due + timedelta(seconds=seconds)) == []

    # Repeated or stale activity timestamps must not re-arm the trigger.
    trigger.record_interaction(NOW)
    trigger.record_interaction(NOW - timedelta(seconds=1))
    assert trigger.poll(due) == []
    interaction = due + timedelta(hours=1)
    trigger.record_interaction(interaction)
    assert trigger.poll(interaction + THRESHOLD - timedelta(microseconds=1)) == []
    next_due = interaction + THRESHOLD
    assert trigger.poll(next_due) == [Event(IDLE, next_due)]
    assert trigger.poll(next_due + timedelta(seconds=30)) == []


def test_idle_without_activity_and_activity_before_first_proposal():
    trigger = IdleTrigger(idle_threshold=THRESHOLD)
    assert trigger.poll(NOW) == []
    trigger.record_interaction(NOW)
    interaction = NOW + timedelta(minutes=4)
    trigger.record_interaction(interaction)
    assert trigger.poll(NOW + THRESHOLD) == []
    due = interaction + THRESHOLD
    assert trigger.poll(due) == [Event(IDLE, due)]


def test_idle_threshold_validation_and_zero_boundary():
    with pytest.raises(ValueError):
        IdleTrigger(idle_threshold=timedelta(seconds=-1))
    trigger = IdleTrigger(idle_threshold=timedelta(0), last_user_interaction=NOW)
    assert trigger.poll(NOW - timedelta(microseconds=1)) == []
    assert trigger.poll(NOW) == [Event(IDLE, NOW)]
    assert trigger.poll(NOW) == []


def test_greeting_once_per_part_per_date_even_when_revisiting_dates():
    trigger = GreetingTrigger()
    for day in (18, 19):
        for hour, part in ((0, "night"), (6, "morning"), (12, "afternoon"), (18, "evening")):
            at = NOW.replace(day=day, hour=hour)
            assert trigger.poll(at) == [Event(GREETING, at, {"part_of_day": part})]
            assert trigger.poll(at) == []
            assert trigger.poll(at + timedelta(hours=6) - timedelta(microseconds=1)) == []
    assert trigger.poll(NOW) == []


def test_greeting_uses_injected_local_calendar_date_and_hour():
    trigger = GreetingTrigger()
    at = datetime.fromisoformat("2026-10-18T23:30:00-07:00")
    assert trigger.poll(at) == [Event(GREETING, at, {"part_of_day": "evening"})]
    next_date = at + timedelta(days=1)
    assert trigger.poll(next_date) == [Event(GREETING, next_date, {"part_of_day": "evening"})]


def test_reminders_due_once_with_minimal_payload_and_no_clock_read():
    store = ReminderStore(clock=lambda: NOW)
    later = store.add("Later", NOW + timedelta(hours=2))
    first = store.add("Take a break", NOW + timedelta(hours=1))
    duplicate_text = store.add("Take a break", NOW + timedelta(hours=1))

    def unexpected_clock_read():
        raise AssertionError("Polling must use the injected time")

    store.clock = unexpected_clock_read
    trigger = ReminderTrigger(store)
    assert trigger.poll(NOW) == []
    due = NOW + timedelta(hours=1)
    assert trigger.poll(due - timedelta(microseconds=1)) == []
    assert trigger.poll(due) == [
        Event(REMINDER, due, {"text": item.text, "due_at": item.due_at})
        for item in (first, duplicate_text)
    ]
    assert trigger.poll(due + timedelta(seconds=30)) == []
    overdue = NOW + timedelta(hours=3)
    assert trigger.poll(overdue) == [
        Event(REMINDER, overdue, {"text": later.text, "due_at": later.due_at})
    ]
    assert trigger.poll(overdue + timedelta(days=1)) == []
    assert store.due(overdue) == [first, duplicate_text, later]


def test_reminder_added_after_poll_is_proposed():
    store = ReminderStore(clock=lambda: NOW)
    trigger = ReminderTrigger(store)
    assert trigger.poll(NOW) == []
    reminder = store.add("New reminder", NOW)
    assert trigger.poll(NOW) == [
        Event(REMINDER, NOW, {"text": reminder.text, "due_at": reminder.due_at})
    ]
    assert trigger.poll(NOW) == []


def test_aggregator_preserves_trigger_and_reminder_order():
    store = ReminderStore(clock=lambda: NOW - timedelta(hours=2))
    later = store.add("Later", NOW)
    earlier = store.add("Earlier", NOW - timedelta(hours=1))
    aggregator = TriggerAggregator([
        GreetingTrigger(),
        ReminderTrigger(store),
        IdleTrigger(idle_threshold=THRESHOLD, last_user_interaction=NOW - THRESHOLD),
    ])
    assert aggregator.poll(NOW) == [
        Event(GREETING, NOW, {"part_of_day": "morning"}),
        Event(REMINDER, NOW, {"text": earlier.text, "due_at": earlier.due_at}),
        Event(REMINDER, NOW, {"text": later.text, "due_at": later.due_at}),
        Event(IDLE, NOW),
    ]
    assert aggregator.poll(NOW) == []
    assert TriggerAggregator([]).poll(NOW) == []


def test_import_without_pyqt6():
    # A fresh interpreter detects even attempted Qt imports hidden by a fallback.
    script = """
import sys

class NoQt:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'PyQt6' or fullname.startswith('PyQt6.'):
            raise AssertionError('Triggers must not import PyQt6')

sys.meta_path.insert(0, NoQt())
import companion.core.proactive.triggers
assert not any(name == 'PyQt6' or name.startswith('PyQt6.') for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
