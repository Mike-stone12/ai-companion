from datetime import UTC, datetime, timedelta

import pytest

from companion.core.proactive import ACTIVE_APP, Event, PolicyConfig, ProactivePolicy, compose, compose_message
from companion.core.proactive.active_app import ActiveAppTrigger
from companion.core.proactive.triggers import TriggerAggregator

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)


def test_default_threshold_and_no_repeat_with_continuous_samples():
    trigger = ActiveAppTrigger()
    aggregator = TriggerAggregator([trigger])
    assert aggregator.poll(NOW) == []
    for minute in range(0, 81, 2):
        at = NOW + timedelta(minutes=minute)
        trigger.record_sample("Game", at)
        expected = [Event(ACTIVE_APP, at, {"app_name": "Game", "minutes": 40})] if minute == 40 else []
        assert aggregator.poll(at) == expected
        assert aggregator.poll(at) == []


@pytest.mark.parametrize("reset", ["app_change", "none", "gap"])
@pytest.mark.parametrize("already_fired", [False, True])
def test_resets_and_fires_after_a_full_new_streak(reset, already_fired):
    trigger = ActiveAppTrigger(threshold=timedelta(minutes=2))
    trigger.record_sample("Game", NOW)
    previous = NOW + timedelta(minutes=2 if already_fired else 1)
    trigger.record_sample("Game", previous)
    expected = [Event(ACTIVE_APP, previous, {"app_name": "Game", "minutes": 2})] if already_fired else []
    assert trigger.poll(previous) == expected

    start = previous + timedelta(seconds=1)
    app_name = "Game"
    if reset == "app_change":
        app_name = "Editor"
    elif reset == "none":
        trigger.record_sample(None, start)
        assert trigger.poll(start) == []
        start += timedelta(seconds=1)
    else:
        start = previous + timedelta(minutes=2, microseconds=1)

    trigger.record_sample(app_name, start)
    assert trigger.poll(start) == []
    before = start + timedelta(minutes=2) - timedelta(microseconds=1)
    trigger.record_sample(app_name, before)
    assert trigger.poll(before) == []
    due = start + timedelta(minutes=2)
    trigger.record_sample(app_name, due)
    assert trigger.poll(due) == [Event(ACTIVE_APP, due, {"app_name": app_name, "minutes": 2})]
    assert trigger.poll(due) == []


@pytest.mark.parametrize("allowlist, expected", [(None, True), (["Game"], True), (["game"], False), ([], False)])
def test_allowlist(allowlist, expected):
    trigger = ActiveAppTrigger(threshold=timedelta(minutes=1), allowlist=allowlist)
    trigger.record_sample("Game", NOW)
    due = NOW + timedelta(minutes=1)
    trigger.record_sample("Game", due)
    events = [Event(ACTIVE_APP, due, {"app_name": "Game", "minutes": 1})] if expected else []
    assert trigger.poll(due) == events


def test_unwatched_app_resets_a_watched_streak():
    trigger = ActiveAppTrigger(threshold=timedelta(minutes=2), allowlist=["Game"])
    for minute, app in enumerate(["Game", "Game", "Editor", "Editor", "Editor", "Game", "Game", "Game"]):
        at = NOW + timedelta(minutes=minute)
        trigger.record_sample(app, at)
        expected = [Event(ACTIVE_APP, at, {"app_name": "Game", "minutes": 2})] if minute == 7 else []
        assert trigger.poll(at) == expected


def test_custom_gap_and_threshold_with_minimal_whole_minutes_payload():
    trigger = ActiveAppTrigger(threshold=timedelta(seconds=90), max_gap=timedelta(seconds=90))
    trigger.record_sample("Game", NOW)
    due = NOW + timedelta(seconds=90)
    trigger.record_sample("Game", due)
    event, = trigger.poll(due)
    assert event == Event(ACTIVE_APP, due, {"app_name": "Game", "minutes": 1})
    assert type(event.payload["minutes"]) is int


def test_polling_does_not_extend_sampled_time_or_propose_stale_samples():
    trigger = ActiveAppTrigger(threshold=timedelta(minutes=1))
    trigger.record_sample("Game", NOW)
    assert trigger.poll(NOW + timedelta(minutes=1)) == []
    due = NOW + timedelta(minutes=1)
    trigger.record_sample("Game", due)
    assert trigger.poll(NOW) == []
    assert trigger.poll(due + timedelta(minutes=2, microseconds=1)) == []
    resumed = due + timedelta(minutes=3)
    trigger.record_sample("Game", resumed)
    assert trigger.poll(resumed) == []
    trigger.record_sample("Game", resumed + timedelta(minutes=1))
    assert trigger.poll(resumed + timedelta(minutes=1)) == [
        Event(ACTIVE_APP, resumed + timedelta(minutes=1), {"app_name": "Game", "minutes": 1})
    ]


def test_repeated_and_stale_samples_do_not_reset_or_rearm():
    trigger = ActiveAppTrigger(threshold=timedelta(minutes=1))
    trigger.record_sample("Game", NOW)
    trigger.record_sample(None, NOW - timedelta(seconds=1))
    due = NOW + timedelta(minutes=1)
    trigger.record_sample("Game", due)
    assert trigger.poll(due) == [Event(ACTIVE_APP, due, {"app_name": "Game", "minutes": 1})]
    trigger.record_sample("Editor", due)
    trigger.record_sample(None, NOW)
    trigger.record_sample("Game", due + timedelta(minutes=1))
    assert trigger.poll(due + timedelta(minutes=1)) == []


@pytest.mark.parametrize("field", ["threshold", "max_gap"])
def test_negative_durations_are_rejected(field):
    with pytest.raises(ValueError, match="nonnegative"):
        ActiveAppTrigger(**{field: timedelta(microseconds=-1)})


def test_zero_threshold_and_gap():
    trigger = ActiveAppTrigger(threshold=timedelta(0), max_gap=timedelta(0))
    trigger.record_sample("Game", NOW)
    assert trigger.poll(NOW) == [Event(ACTIVE_APP, NOW, {"app_name": "Game", "minutes": 0})]
    assert trigger.poll(NOW) == []


def test_policy_requires_opt_in_and_defaults_to_a_sixty_minute_cooldown():
    event = Event(ACTIVE_APP, NOW, {"app_name": "Game", "minutes": 40})
    assert ProactivePolicy(PolicyConfig()).allow(event, last_user_activity=None, busy=False) == (False, "disabled")
    policy = ProactivePolicy(PolicyConfig(enabled_kinds=frozenset({ACTIVE_APP})))
    assert policy.allow(event, last_user_activity=None, busy=False) == (True, "ok")
    policy.record_fired(event)
    boundary = NOW + timedelta(minutes=60)
    before = Event(ACTIVE_APP, boundary - timedelta(microseconds=1))
    assert policy.allow(before, last_user_activity=None, busy=False) == (False, "cooldown")
    assert policy.allow(Event(ACTIVE_APP, boundary), last_user_activity=None, busy=False) == (True, "ok")


def test_policy_can_override_active_app_cooldown():
    policy = ProactivePolicy(PolicyConfig(enabled_kinds=frozenset({ACTIVE_APP}), cooldowns={ACTIVE_APP: timedelta(0)}))
    event = Event(ACTIVE_APP, NOW)
    policy.record_fired(event)
    assert policy.allow(event, last_user_activity=None, busy=False) == (True, "ok")


def test_composer_mentions_app_duration_and_break_and_ignores_extra_payload():
    event = Event(ACTIVE_APP, NOW, {"app_name": "Game", "minutes": 40})
    expected = (
        "The user has kept Game active for 40 minutes; "
        "give a short, friendly check-in and gently suggest a break."
    )
    assert compose(event) == expected
    assert compose_message(event) == {"role": "user", "content": expected}
    extra = {**event.payload, "processes": ["SECRET_PROCESS"]}
    assert compose(Event(ACTIVE_APP, NOW, extra)) == expected
    assert extra == {"app_name": "Game", "minutes": 40, "processes": ["SECRET_PROCESS"]}


@pytest.mark.parametrize("value", [None, "", "   ", [], 42])
def test_composer_rejects_invalid_app_name(value):
    with pytest.raises(ValueError, match="app_name"):
        compose(Event(ACTIVE_APP, NOW, {"app_name": value, "minutes": 40}))


@pytest.mark.parametrize("value", [None, -1, 1.5, "40", True])
def test_composer_rejects_invalid_minutes(value):
    with pytest.raises(ValueError, match="minutes"):
        compose(Event(ACTIVE_APP, NOW, {"app_name": "Game", "minutes": value}))


@pytest.mark.parametrize("payload, field", [({}, "app_name"), ({"app_name": "Game"}, "minutes")])
def test_composer_rejects_missing_fields(payload, field):
    with pytest.raises(ValueError, match=field):
        compose(Event(ACTIVE_APP, NOW, payload))
