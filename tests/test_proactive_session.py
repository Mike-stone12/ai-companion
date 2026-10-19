from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from companion.core.proactive.engine import ProactiveContext, ProactiveResult
from companion.core.proactive.events import GREETING, IDLE, REMINDER, Event
from companion.core.proactive.session import ProactiveSession, proactive_request
from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)


@pytest.fixture
def session():
    return ProactiveSession(ReminderStore(clock=lambda: NOW), NOW)


def test_default_triggers_greet_then_check_in_after_thirty_minutes(session):
    result = session.tick(NOW, busy=False, input_has_text=False)
    assert result.event.kind == GREETING
    assert "morning" in result.messages[0]["content"]
    assert session.tick(NOW + timedelta(minutes=29), busy=False, input_has_text=False) is None
    assert session.tick(NOW + timedelta(minutes=30), busy=False, input_has_text=False).event.kind == IDLE
    assert session.tick(NOW + timedelta(minutes=31), busy=False, input_has_text=False) is None


def test_user_activity_rearms_idle_and_respects_policy_grace(session):
    session.record_activity(NOW)
    assert session.tick(NOW, busy=False, input_has_text=False) is None
    assert session.tick(NOW + timedelta(minutes=30), busy=False, input_has_text=False).event.kind == IDLE
    session.record_activity(NOW + timedelta(minutes=31))
    assert session.tick(NOW + timedelta(minutes=60), busy=False, input_has_text=False) is None
    assert session.tick(NOW + timedelta(minutes=61), busy=False, input_has_text=False).event.kind == IDLE


@pytest.mark.parametrize("busy, typing", [(False, False), (True, False), (False, True), (True, True)])
def test_adapter_passes_current_time_and_activity_to_engine(session, busy, typing):
    session.record_activity(NOW)
    session.engine = Mock()
    later = NOW + timedelta(seconds=30)
    assert session.tick(later, busy=busy, input_has_text=typing) is session.engine.tick.return_value
    session.engine.tick.assert_called_once_with(later, ProactiveContext(NOW, busy or typing))


def test_reminders_use_shared_store_and_take_priority_without_consuming_store():
    store = ReminderStore(clock=lambda: NOW)
    session = ProactiveSession(store, NOW)
    reminder = store.add("Drink water", NOW + timedelta(minutes=1))
    due = NOW + timedelta(minutes=1)
    result = session.tick(due, busy=False, input_has_text=False)
    assert result.event.kind == REMINDER
    assert "Drink water" in result.messages[0]["content"]
    assert session.tick(due, busy=False, input_has_text=False) is None
    assert store.due(due) == [reminder]


def test_request_defers_context_and_does_not_add_synthetic_turn_to_history():
    history = [{"role": "system", "content": "Companion"}, {"role": "assistant", "content": "Hello"}]
    context = Mock(return_value=history)
    result = ProactiveResult(Event(IDLE, NOW), [{"role": "user", "content": "Check in"}])
    request = proactive_request(context, result)
    context.assert_not_called()
    assert request() == [*history, {"role": "user", "content": "Check in"}]
    context.assert_called_once_with()
    assert len(history) == 2
