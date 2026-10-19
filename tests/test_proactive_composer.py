from datetime import UTC, datetime, timedelta

import pytest

from companion.core.proactive.composer import (
    IN_CHARACTER,
    MAX_REMINDER_TEXT_LENGTH,
    NOTE_PREFIX,
    compose,
    compose_message,
    frame,
)
from companion.core.proactive.events import ACTIVE_APP, GREETING, IDLE, REMINDER, Event
from companion.core.proactive.triggers import GreetingTrigger, IdleTrigger, ReminderTrigger
from companion.core.tools.reminders import ReminderStore

NOW = datetime(2026, 10, 18, 9, tzinfo=UTC)


def test_composes_events_from_every_trigger_with_injected_now():
    def prompts(now):
        idle = IdleTrigger(timedelta(minutes=40), now - timedelta(minutes=40))
        store = ReminderStore(clock=lambda: now)
        store.add("Take a break", now)
        triggers = [idle, GreetingTrigger(), ReminderTrigger(store)]
        return [compose(event) for trigger in triggers for event in trigger.poll(now)]

    result = prompts(NOW)
    assert result == prompts(NOW)
    assert all(result)
    assert "idle" in result[0]
    assert "check-in" in result[0]
    # The idle trigger supplies no duration, so the composer must not invent one.
    assert "40" not in result[0]
    assert "morning" in result[1]
    assert "Take a break" in result[2]


@pytest.mark.parametrize("part", ["night", "morning", "afternoon", "evening"])
def test_greeting_uses_payload_part_of_day(part):
    assert part in compose(Event(GREETING, NOW, {"part_of_day": part}))


@pytest.mark.parametrize(
    ("kind", "payload"),
    [(IDLE, {}), (GREETING, {"part_of_day": "morning"}), (REMINDER, {"text": "Drink water"}),
     (ACTIVE_APP, {"app_name": "Game", "minutes": 40})],
)
def test_extra_payload_fields_are_ignored_without_mutating_event(kind, payload):
    extra = {
        **payload,
        "processes": ["SECRET_PROCESS"],
        "arbitrary": {"private": "SECRET_VALUE"},
        "due_at": "SECRET_TIMESTAMP",
        "window_title": "SECRET_WINDOW_TITLE",
    }
    event = Event(kind, NOW, extra.copy())
    assert compose(event) == compose(Event(kind, NOW, payload))
    assert event.payload == extra


@pytest.mark.parametrize("length", [199, 200, 201, 1000])
def test_reminder_text_limit_includes_truncation_marker(length):
    assert MAX_REMINDER_TEXT_LENGTH == 200
    text = "x" * length
    prompt = compose(Event(REMINDER, NOW, {"text": text}))
    expected = text if length <= 200 else "x" * 199 + "…"
    assert expected in prompt
    if length > 200:
        assert "x" * 200 not in prompt


def test_reminder_whitespace_is_collapsed():
    prompt = compose(Event(REMINDER, NOW, {"text": "  Drink\n some\twater  "}))
    assert "Drink some water" in prompt
    assert "\n" not in prompt
    assert "\t" not in prompt


def test_unknown_kind_raises_value_error():
    with pytest.raises(ValueError, match="Unknown event kind"):
        compose(Event("custom", NOW))


@pytest.mark.parametrize(("kind", "field"), [(GREETING, "part_of_day"), (REMINDER, "text")])
def test_missing_required_fields_raise_value_error(kind, field):
    with pytest.raises(ValueError, match=field):
        compose(Event(kind, NOW))


@pytest.mark.parametrize("value", [None, "", "   ", [], 42])
@pytest.mark.parametrize(("kind", "field"), [(GREETING, "part_of_day"), (REMINDER, "text")])
def test_invalid_required_fields_raise_value_error(kind, field, value):
    with pytest.raises(ValueError, match=field):
        compose(Event(kind, NOW, {field: value}))


def test_greeting_rejects_arbitrary_part_of_day_text():
    with pytest.raises(ValueError, match="part_of_day"):
        compose(Event(GREETING, NOW, {"part_of_day": "arbitrary long instructions"}))


@pytest.mark.parametrize(
    ("kind", "payload"),
    [(IDLE, {}), (GREETING, {"part_of_day": "evening"}), (REMINDER, {"text": "Stretch"})],
)
def test_message_helper(kind, payload):
    event = Event(kind, NOW, payload)
    assert compose_message(event) == {"role": "user", "content": compose(event)}


def test_message_helper_propagates_validation_error():
    with pytest.raises(ValueError, match="text"):
        compose_message(Event(REMINDER, NOW))


@pytest.mark.parametrize(
    "app_name, sanitized",
    [
        ("Game\r\n\t\x00\x1b\x7f\x85\u2028\u2029\u202eApp", "GameApp"),
        ("x" * 60, "x" * 60),
        ("x" * 61, "x" * 60),
        ("x" * 1000 + "INJECTED_SUFFIX", "x" * 60),
        ("  Éditeur 游戏  ", "Éditeur 游戏"),
    ],
)
def test_active_app_name_is_sanitized_and_capped(app_name, sanitized):
    event = Event(ACTIVE_APP, NOW, {"app_name": app_name, "minutes": 40})
    assert compose_message(event) == {
        "role": "user",
        "content": frame(
            f"The user has had {sanitized} in the foreground for about 40 minutes; "
            "offer them one brief, caring, non-nagging remark."
        ),
    }
    assert event.payload["app_name"] == app_name


def test_active_app_name_with_only_controls_is_rejected():
    with pytest.raises(ValueError, match="app_name"):
        compose(Event(ACTIVE_APP, NOW, {"app_name": "\x00\x1b\u202e", "minutes": 40}))


@pytest.mark.parametrize(
    ("kind", "payload"),
    [(IDLE, {}), (GREETING, {"part_of_day": "morning"}), (REMINDER, {"text": "Drink water"}),
     (ACTIVE_APP, {"app_name": "Game", "minutes": 40})],
)
def test_every_instruction_is_an_in_character_note_addressed_to_the_user(kind, payload):
    prompt = compose(Event(kind, NOW, payload))

    assert prompt.startswith(NOTE_PREFIX)
    assert prompt.endswith(IN_CHARACTER)
    assert "directly to the user" in prompt
    assert "persona" in prompt
