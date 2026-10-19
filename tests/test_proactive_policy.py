from dataclasses import FrozenInstanceError
from datetime import datetime, time, timedelta

import pytest

from companion.core.proactive import ACTIVE_APP, GREETING, IDLE, REMINDER, Event, PolicyConfig, ProactivePolicy

AT = datetime(2026, 10, 18, 12)


def test_defaults_and_frozen_dataclasses():
    config = PolicyConfig()
    assert config.enabled_kinds == frozenset({IDLE, GREETING, REMINDER})
    assert config.cooldowns == {
        IDLE: timedelta(minutes=30),
        GREETING: timedelta(hours=4),
        REMINDER: timedelta(0),
    }
    assert config.quiet_start is None
    assert config.quiet_end is None
    assert config.user_active_grace == timedelta(minutes=2)
    event = Event(IDLE, AT)
    assert event.payload == {}
    event.payload["message"] = "hello"
    assert Event(IDLE, AT).payload == {}
    assert PolicyConfig().cooldowns is not config.cooldowns
    with pytest.raises(FrozenInstanceError):
        event.kind = GREETING
    with pytest.raises(FrozenInstanceError):
        config.quiet_start = time(23)


@pytest.mark.parametrize(
    ("enabled", "busy", "active", "quiet", "fired", "expected"),
    [
        (False, True, True, True, True, (False, "disabled")),
        (True, True, True, True, True, (False, "busy")),
        (True, False, True, True, True, (False, "user_active")),
        (True, False, False, True, True, (False, "quiet_hours")),
        (True, False, False, False, True, (False, "cooldown")),
        (True, False, False, False, False, (True, "ok")),
    ],
)
def test_rejection_precedence(enabled, busy, active, quiet, fired, expected):
    config = PolicyConfig(
        enabled_kinds=frozenset({IDLE}) if enabled else frozenset(),
        quiet_start=time(11) if quiet else None,
        quiet_end=time(13) if quiet else None,
    )
    policy = ProactivePolicy(config)
    if fired:
        policy.record_fired(Event(IDLE, AT - timedelta(minutes=1)))
    activity = AT - timedelta(minutes=1) if active else None
    assert policy.allow(Event(IDLE, AT), last_user_activity=activity, busy=busy) == expected


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(0), (False, "user_active")),
        (timedelta(seconds=119), (False, "user_active")),
        (timedelta(minutes=2), (True, "ok")),
        (timedelta(minutes=3), (True, "ok")),
    ],
)
def test_user_activity_grace_boundary(elapsed, expected):
    policy = ProactivePolicy(PolicyConfig())
    assert policy.allow(Event(IDLE, AT), last_user_activity=AT - elapsed, busy=False) == expected


def test_custom_user_activity_grace():
    policy = ProactivePolicy(PolicyConfig(user_active_grace=timedelta(minutes=5)))
    assert policy.allow(Event(IDLE, AT), last_user_activity=AT - timedelta(minutes=3), busy=False) == (
        False, "user_active"
    )


@pytest.mark.parametrize(
    ("start", "end", "hour", "minute", "quiet"),
    [
        (time(9), time(17), 8, 59, False),
        (time(9), time(17), 9, 0, True),
        (time(9), time(17), 12, 0, True),
        (time(9), time(17), 16, 59, True),
        (time(9), time(17), 17, 0, False),
        (time(23), time(7), 22, 59, False),
        (time(23), time(7), 23, 0, True),
        (time(23), time(7), 0, 0, True),
        (time(23), time(7), 6, 59, True),
        (time(23), time(7), 7, 0, False),
        (time(23), time(7), 12, 0, False),
        (time(9), time(9), 9, 0, False),
    ],
)
def test_quiet_hours(start, end, hour, minute, quiet):
    policy = ProactivePolicy(PolicyConfig(quiet_start=start, quiet_end=end))
    event = Event(GREETING, AT.replace(hour=hour, minute=minute))
    expected = (False, "quiet_hours") if quiet else (True, "ok")
    assert policy.allow(event, last_user_activity=None, busy=False) == expected


@pytest.mark.parametrize(("start", "end"), [(time(9), None), (None, time(17)), (None, None)])
def test_partial_quiet_hours_are_disabled(start, end):
    policy = ProactivePolicy(PolicyConfig(quiet_start=start, quiet_end=end))
    assert policy.allow(Event(IDLE, AT), last_user_activity=None, busy=False) == (True, "ok")


@pytest.mark.parametrize("busy", [False, True])
def test_reminders_bypass_quiet_hours_but_not_busy(busy):
    policy = ProactivePolicy(PolicyConfig(quiet_start=time(23), quiet_end=time(7)))
    event = Event(REMINDER, AT.replace(hour=1))
    expected = (False, "busy") if busy else (True, "ok")
    assert policy.allow(event, last_user_activity=None, busy=busy) == expected


def test_reminders_still_respect_user_activity():
    policy = ProactivePolicy(PolicyConfig())
    assert policy.allow(Event(REMINDER, AT), last_user_activity=AT, busy=False) == (False, "user_active")


@pytest.mark.parametrize("kind", [IDLE, GREETING, REMINDER])
def test_default_cooldown_boundary(kind):
    config = PolicyConfig()
    policy = ProactivePolicy(config)
    policy.record_fired(Event(kind, AT))
    boundary = AT + config.cooldowns[kind]
    if config.cooldowns[kind] > timedelta(0):
        event = Event(kind, boundary - timedelta(microseconds=1))
        assert policy.allow(event, last_user_activity=None, busy=False) == (False, "cooldown")
    for at in (boundary, boundary + timedelta(seconds=1)):
        assert policy.allow(Event(kind, at), last_user_activity=None, busy=False) == (True, "ok")


def test_record_fired_updates_only_the_matching_kind():
    policy = ProactivePolicy(PolicyConfig(cooldowns={IDLE: timedelta(minutes=10)}))
    policy.record_fired(Event(IDLE, AT))
    policy.record_fired(Event(IDLE, AT + timedelta(minutes=5)))
    at = AT + timedelta(minutes=10)
    assert policy.allow(Event(IDLE, at), last_user_activity=None, busy=False) == (False, "cooldown")
    assert policy.allow(Event(GREETING, at), last_user_activity=None, busy=False) == (True, "ok")
    assert policy.allow(Event(IDLE, at + timedelta(minutes=5)), last_user_activity=None, busy=False) == (True, "ok")


def test_unknown_kind_is_disabled_unless_enabled_and_has_zero_cooldown():
    event = Event("custom", AT)
    assert ProactivePolicy(PolicyConfig()).allow(event, last_user_activity=None, busy=False) == (False, "disabled")
    policy = ProactivePolicy(PolicyConfig(enabled_kinds=frozenset({"custom"})))
    policy.record_fired(event)
    assert policy.allow(event, last_user_activity=None, busy=False) == (True, "ok")


def test_allow_does_not_mutate_state():
    policy = ProactivePolicy(PolicyConfig())
    event = Event(IDLE, AT)
    for _ in range(2):
        assert policy.allow(event, last_user_activity=None, busy=False) == (True, "ok")
    assert policy.allow(event, last_user_activity=None, busy=True) == (False, "busy")
    assert policy.allow(event, last_user_activity=None, busy=False) == (True, "ok")
    policy.record_fired(event)
    later = Event(IDLE, AT + timedelta(minutes=29))
    assert policy.allow(later, last_user_activity=None, busy=False) == (False, "cooldown")
    boundary = Event(IDLE, AT + timedelta(minutes=30))
    assert policy.allow(boundary, last_user_activity=None, busy=False) == (True, "ok")
    assert policy.allow(boundary, last_user_activity=None, busy=False) == (True, "ok")
    other_policy = ProactivePolicy(PolicyConfig())
    assert other_policy.allow(event, last_user_activity=None, busy=False) == (True, "ok")


@pytest.mark.parametrize("first, second", [(IDLE, ACTIVE_APP), (ACTIVE_APP, IDLE)])
def test_active_app_and_idle_cooldowns_are_independent(first, second):
    policy = ProactivePolicy(PolicyConfig(enabled_kinds=frozenset({IDLE, ACTIVE_APP})))
    policy.record_fired(Event(first, AT))
    later = AT + timedelta(minutes=1)
    assert policy.allow(Event(second, later), last_user_activity=None, busy=False) == (True, "ok")
    policy.record_fired(Event(second, later))
    for kind in (first, second):
        assert policy.allow(Event(kind, later), last_user_activity=None, busy=False) == (False, "cooldown")


@pytest.mark.parametrize(
    "busy, elapsed, expected",
    [
        (True, None, (False, "busy")),
        (False, timedelta(seconds=119), (False, "user_active")),
        (False, timedelta(minutes=2), (True, "ok")),
        (False, None, (True, "ok")),
    ],
)
def test_active_app_busy_and_grace_rules_match_idle(busy, elapsed, expected):
    policy = ProactivePolicy(PolicyConfig(enabled_kinds=frozenset({IDLE, ACTIVE_APP})))
    activity = AT - elapsed if elapsed is not None else None
    for kind in (IDLE, ACTIVE_APP):
        assert policy.allow(Event(kind, AT), last_user_activity=activity, busy=busy) == expected


@pytest.mark.parametrize(
    "hour, expected", [(23, (False, "quiet_hours")), (6, (False, "quiet_hours")), (7, (True, "ok"))],
)
def test_active_app_quiet_hours_match_idle(hour, expected):
    policy = ProactivePolicy(PolicyConfig(
        enabled_kinds=frozenset({IDLE, ACTIVE_APP}), quiet_start=time(23), quiet_end=time(7),
    ))
    for kind in (IDLE, ACTIVE_APP):
        assert policy.allow(Event(kind, AT.replace(hour=hour)), last_user_activity=None, busy=False) == expected
