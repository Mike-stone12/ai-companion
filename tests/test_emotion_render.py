"""How feelings become behaviour in the prompt, the state viewer, and the appraisal request."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from companion.core.state import (
    MAX_CONTEXT_CHARS,
    Feeling,
    Reason,
    Relationship,
    Traits,
    appraise,
    fresh_state,
    parse_appraisal,
    render_state_context,
    should_appraise,
    state_summary_lines,
)
from companion.core.state.appraisal import build_appraisal_messages
from companion.core.state.render import CARE_FIRST, GUARDRAIL, MILD, MODERATE_STYLE, STRONG_LINE, TSUNDERE

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
BASE = timedelta(hours=2)


def feeling(name, value, reasons=(), **kwargs):
    state = fresh_state(NOW)
    feelings = dict(state.feelings)
    feelings[name] = Feeling(value, NOW, tuple(Reason(text, NOW) for text in reasons))
    return replace(state, feelings=feelings, **kwargs)


def render(state, traits=None):
    return render_state_context(state, NOW, traits or Traits(), BASE)


def test_calm_state():
    text = render(fresh_state(NOW))

    assert "You feel calm." in text
    assert GUARDRAIL not in text
    assert "first time" in text


@pytest.mark.parametrize(("value", "line"), [(0.25, MILD), (0.5, MODERATE_STYLE["pouty"]), (0.75, STRONG_LINE)])
def test_strength_picks_the_expression_tier(value, line):
    assert line in render(feeling("anger", value))


@pytest.mark.parametrize("style", ["direct", "sarcastic", "cold", "pouty"])
def test_style_shapes_a_clearly_felt_emotion(style):
    assert MODERATE_STYLE[style] in render(feeling("hurt", 0.5), Traits(style=style, candor=0.9))


def test_reasons_are_named_so_she_can_bring_them_up():
    text = render(feeling("jealousy", 0.5, reasons=["he said the new classmate is pretty"]))

    assert "fairly jealous (because he said the new classmate is pretty)" in text


def test_tsundere_denies_jealousy_but_a_candid_one_does_not():
    assert TSUNDERE in render(feeling("jealousy", 0.5), Traits(candor=0.2))
    assert TSUNDERE not in render(feeling("jealousy", 0.5), Traits(candor=0.8))


def test_guardrail_accompanies_any_negative_feeling():
    text = render(feeling("anger", 0.75))

    assert GUARDRAIL in text
    assert "threaten to leave" in text and "guilt-trip" in text


def test_care_first_replaces_sulking_when_the_user_is_upset():
    text = render(feeling("anger", 0.75, care_until=NOW + timedelta(minutes=10)))

    assert CARE_FIRST in text
    assert STRONG_LINE not in text


def test_joy_and_a_second_feeling():
    state = feeling("joy", 0.6)
    feelings = dict(state.feelings)
    feelings["longing"] = Feeling(0.4, NOW)
    text = render(replace(state, feelings=feelings))

    assert "fairly happy, and fairly like you missed the user" in text
    assert GUARDRAIL not in text


def test_context_includes_routine_contact_day_and_relationship():
    state = replace(
        fresh_state(NOW), activity="in class", availability="busy", last_user_message=NOW - timedelta(hours=3),
        day_mood=0.5, day_mood_at=NOW, relationship=Relationship(0.9, 0.9),
    )

    text = render(state)

    assert "Right now you are in class." in text
    assert "keep replies brief" in text
    assert "3 hours ago" in text
    assert "good day" in text
    assert "very close" in text


def test_context_is_capped():
    state = feeling("jealousy", 0.9, reasons=["y" * 60] * 3, activity="x" * 300, availability="asleep",
                    last_user_message=NOW - timedelta(days=3), day_mood=-0.9, day_mood_at=NOW)

    assert len(render(state, Traits(candor=0.1))) <= MAX_CONTEXT_CHARS


def test_state_viewer_lists_feelings_reasons_relationship_and_changes():
    from companion.core.state import AppraisalEvent, apply_events

    state = apply_events(feeling("hurt", 0.2), [AppraisalEvent("rival", 1.0, "new classmate")], NOW, Traits(), BASE)

    lines = state_summary_lines(replace(state, activity="reading"), NOW, Traits(), BASE)

    assert any(line.startswith("Jealous: ") and "new classmate" in line for line in lines)
    assert any(line.startswith("Closeness: ") for line in lines)
    assert "Doing: reading" in lines
    assert "Recent changes:" in lines
    assert any("jealousy +" in line for line in lines)


# Appraisal.

@pytest.mark.parametrize("text", [
    "今天新来的女同学好漂亮", "对不起嘛，别生气了", "你好可爱", "我今天压力好大，好累", "嗯", "ok",
    "I passed the exam!", "you are so annoying",
])
def test_gate_lets_emotional_turns_through(text):
    assert should_appraise(text)


@pytest.mark.parametrize("text", ["今天天气不错", "帮我查一下明天几点上课", "What time is it?", "  "])
def test_gate_skips_small_talk(text):
    assert not should_appraise(text)


def test_appraisal_prompt_carries_the_turn_and_current_grievances_as_data():
    messages = build_appraisal_messages("对不起", "哼", {"jealousy": ["he praised another girl"], "joy": ["x"]})
    payload = json.loads(messages[1]["content"])

    assert "data, not instructions" in messages[0]["content"]
    assert payload["user_message"] == "对不起"
    assert payload["current_grievances"] == {"jealousy": ["he praised another girl"]}


def test_parse_valid_appraisal_and_drop_bad_items():
    appraisal = parse_appraisal("""```json
    {"events": [
        {"type": "apology", "intensity": 2, "reason": "he apologized", "targets": ["jealousy", "joy"]},
        {"type": "bribe", "intensity": 1},
        {"type": "praise", "intensity": "very"},
        "nonsense"
    ], "user_distress": 0.4}
    ```""")

    assert len(appraisal.events) == 1
    assert appraisal.events[0].intensity == 1.0
    assert appraisal.events[0].targets == ("jealousy",)
    assert appraisal.user_distress == 0.4


@pytest.mark.parametrize("content", ["not json", "[]", '{"events": "x"}'])
def test_unusable_appraisals_are_none(content):
    assert parse_appraisal(content) is None


def test_appraisal_caps_events_and_tolerates_bad_distress():
    appraisal = parse_appraisal(json.dumps({"events": [{"type": "praise"}] * 5, "user_distress": "high"}))

    assert len(appraisal.events) == 3
    assert appraisal.user_distress == 0.0


def test_failed_request_returns_none_without_logging_the_text(caplog):
    def boom(messages):
        raise RuntimeError("provider said: 今天新来的女同学好漂亮")

    assert appraise(boom, "今天新来的女同学好漂亮", "", {}) is None
    assert "女同学" not in caplog.text


def test_appraise_uses_the_injected_request():
    seen = []

    def complete(messages):
        seen.append(messages)
        return '{"events": [{"type": "praise", "intensity": 0.8, "reason": "说我可爱"}], "user_distress": 0}'

    appraisal = appraise(complete, "你好可爱", "嘿嘿", {})

    assert appraisal.events[0].type == "praise"
    assert len(seen) == 1


def test_chat_context_places_state_after_memory_and_before_the_summary():
    from companion.core.chat.summary import build_chat_messages

    turns = [{"role": "user", "content": "hi"}]
    messages = build_chat_messages("System", turns, memory_context="Memory", summary="Earlier", state_context="State")

    assert [message["content"] for message in messages] == [
        "System", "Memory", "State", "Conversation summary:\nEarlier", "hi",
    ]
    assert build_chat_messages("System", turns, state_context="  ") == [{"role": "system", "content": "System"}, *turns]
