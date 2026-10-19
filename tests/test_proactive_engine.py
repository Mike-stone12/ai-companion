from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from companion.core.proactive.composer import compose_message
from companion.core.proactive.engine import ProactiveContext, ProactiveEngine
from companion.core.proactive.events import ACTIVE_APP, GREETING, IDLE, REMINDER, Event
from companion.core.proactive.policy import PolicyConfig, ProactivePolicy
from companion.core.proactive.session import ProactiveSession
from companion.core.proactive.triggers import IdleTrigger, Trigger
from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)
CONTEXT = ProactiveContext(last_user_activity=None, busy=False)


def source(*events):
    return Mock(spec=Trigger, poll=Mock(return_value=list(events)))


def tracked_policy():
    return Mock(wraps=ProactivePolicy(PolicyConfig()))


@pytest.mark.parametrize("triggers", [[], [source(), source()]])
def test_no_events(triggers):
    policy = tracked_policy()
    composer = Mock(wraps=compose_message)
    engine = ProactiveEngine(iter(triggers), policy, composer)

    assert engine.tick(NOW, CONTEXT) is None
    for trigger in triggers:
        trigger.poll.assert_called_once_with(NOW)
    policy.allow.assert_not_called()
    policy.record_fired.assert_not_called()
    composer.assert_not_called()


def test_allowed_event_is_composed_and_recorded():
    activity = NOW - timedelta(minutes=10)
    trigger = IdleTrigger(timedelta(minutes=5), activity)
    context = ProactiveContext(last_user_activity=activity, busy=False)
    policy = tracked_policy()
    composer = Mock(wraps=compose_message)
    engine = ProactiveEngine([trigger], policy, composer)
    event = Event(IDLE, NOW)

    result = engine.tick(NOW, context)

    assert result.event == event
    assert result.messages == [compose_message(event)]
    policy.allow.assert_called_once_with(event, last_user_activity=activity, busy=False)
    policy.record_fired.assert_called_once_with(event)
    composer.assert_called_once_with(event)


@pytest.mark.parametrize(
    "context",
    [ProactiveContext(last_user_activity=None, busy=True),
     ProactiveContext(last_user_activity=NOW, busy=False)],
)
def test_blocked_event_is_not_composed_or_recorded(context):
    event = Event(IDLE, NOW)
    policy = tracked_policy()
    composer = Mock(wraps=compose_message)
    engine = ProactiveEngine([source(event)], policy, composer)

    assert engine.tick(NOW, context) is None
    policy.allow.assert_called_once_with(
        event, last_user_activity=context.last_user_activity, busy=context.busy
    )
    policy.record_fired.assert_not_called()
    composer.assert_not_called()
    assert policy.allow(event, last_user_activity=None, busy=False) == (True, "ok")


def test_trigger_order_has_priority_over_event_time_and_all_candidates_are_checked():
    first = Event(IDLE, NOW)
    second = Event(GREETING, NOW - timedelta(minutes=1), {"part_of_day": "morning"})
    triggers = [source(first), source(second)]
    policy = tracked_policy()
    composer = Mock(wraps=compose_message)
    engine = ProactiveEngine(iter(triggers), policy, composer)

    result = engine.tick(NOW, CONTEXT)

    assert result.event is first
    for trigger in triggers:
        trigger.poll.assert_called_once_with(NOW)
    assert policy.allow.call_count == 2
    policy.allow.assert_any_call(first, last_user_activity=None, busy=False)
    policy.allow.assert_any_call(second, last_user_activity=None, busy=False)
    policy.record_fired.assert_called_once_with(first)
    composer.assert_called_once_with(first)


@pytest.mark.parametrize("difference", [timedelta(minutes=1), timedelta(0)])
def test_event_time_breaks_ties_within_trigger_and_equal_times_keep_source_order(difference):
    first = Event(REMINDER, NOW, {"text": "First"})
    second = Event(REMINDER, NOW - difference, {"text": "Second"})
    policy = tracked_policy()
    engine = ProactiveEngine([source(first, second)], policy, compose_message)
    expected = second if difference else first

    assert engine.tick(NOW, CONTEXT).event is expected
    policy.record_fired.assert_called_once_with(expected)


def test_blocked_higher_priority_event_does_not_prevent_allowed_event():
    blocked = Event("disabled", NOW)
    allowed = Event(IDLE, NOW)
    policy = tracked_policy()
    engine = ProactiveEngine([source(blocked), source(allowed)], policy, compose_message)

    assert engine.tick(NOW, CONTEXT).event is allowed
    policy.record_fired.assert_called_once_with(allowed)


def test_cooldown_suppresses_second_tick_and_allows_firing_at_boundary():
    trigger = Mock(spec=Trigger, poll=Mock(side_effect=lambda now: [Event(IDLE, now)]))
    policy = tracked_policy()
    composer = Mock(wraps=compose_message)
    engine = ProactiveEngine(iter([trigger]), policy, composer)

    assert engine.tick(NOW, CONTEXT).event == Event(IDLE, NOW)
    assert engine.tick(NOW + timedelta(seconds=1), CONTEXT) is None
    assert engine.tick(NOW + timedelta(minutes=30) - timedelta(microseconds=1), CONTEXT) is None
    policy.record_fired.assert_called_once_with(Event(IDLE, NOW))
    composer.assert_called_once_with(Event(IDLE, NOW))

    later = NOW + timedelta(minutes=30)
    assert engine.tick(later, CONTEXT).event == Event(IDLE, later)
    assert policy.record_fired.call_count == 2
    policy.record_fired.assert_called_with(Event(IDLE, later))
    assert composer.call_count == 2


def test_composition_failure_is_not_recorded_as_fired():
    event = Event(REMINDER, NOW)
    policy = tracked_policy()
    engine = ProactiveEngine([source(event)], policy, compose_message)

    with pytest.raises(ValueError, match="text"):
        engine.tick(NOW, CONTEXT)

    policy.record_fired.assert_not_called()


@pytest.mark.parametrize("busy, input_has_text", [(True, False), (False, True), (True, True)])
def test_active_app_is_blocked_during_reply_or_typing(busy, input_has_text):
    event = Event(ACTIVE_APP, NOW, {"app_name": "Game", "minutes": 40})
    policy = Mock(wraps=ProactivePolicy(PolicyConfig(enabled_kinds=frozenset({ACTIVE_APP}))))
    composer = Mock(wraps=compose_message)
    session = ProactiveSession(ReminderStore(clock=lambda: NOW), NOW)
    session.engine = ProactiveEngine([source(event)], policy, composer)

    assert session.tick(NOW, busy=busy, input_has_text=input_has_text) is None
    composer.assert_not_called()
    policy.record_fired.assert_not_called()
    result = session.tick(NOW, busy=False, input_has_text=False)
    assert result.event == event
    assert result.messages == [compose_message(event)]
