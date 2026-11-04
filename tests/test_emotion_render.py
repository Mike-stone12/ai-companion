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


def test_worst_case_context_keeps_whole_sentences_and_mandatory_parts():
    state = feeling("jealousy", 0.9, reasons=["y" * 60, "z" * 60, "w" * 60], activity="x" * 300,
                    availability="asleep", last_user_message=NOW - timedelta(days=3), day_mood=-0.9, day_mood_at=NOW)
    feelings = dict(state.feelings)
    feelings["hurt"] = Feeling(0.6, NOW)
    state = replace(state, feelings=feelings)

    text = render(state, Traits(candor=0.1))

    assert len(text) <= MAX_CONTEXT_CHARS
    assert text.endswith(".")
    assert STRONG_LINE in text and TSUNDERE in text and GUARDRAIL in text
    # Optional parts are dropped whole, from the lowest priority, never cut mid-sentence.
    activity = "Right now you are " + "x" * 80 + "."
    assert activity in text or "Right now you are" not in text
    for whole in ("You were asleep and this message woke you", "The user last wrote to you 3 days ago.",
                  "Overall today has felt a bit rough.", "You two are close."):
        assert whole in text or whole.split()[2] not in text.split(GUARDRAIL)[-1]


def test_care_first_on_the_distress_turn_replaces_the_strong_line():
    from companion.core.state.model import enter_care_mode

    angry = feeling("anger", 0.75)
    cared = enter_care_mode(angry, NOW)
    text = render(cared)

    assert CARE_FIRST in text
    assert STRONG_LINE not in text
    # A second call extends the window without halving again.
    again = enter_care_mode(cared, NOW + timedelta(minutes=5))
    assert again.feelings["anger"].value == cared.feelings["anger"].value


@pytest.mark.parametrize("text", [
    "我今天被老板骂了，好难过", "压力好大", "I'm so stressed",
    "我今天被老板骂了", "被他狠狠骂了一顿", "明天面试，好紧张", "我有点害怕", "今天好累",
    "感觉活着没意思", "我不想活了", "I'm so nervous", "I'm scared",
])
def test_distress_pre_check(text):
    from companion.core.state.appraisal import looks_distressed

    assert looks_distressed(text)
    assert should_appraise(text)


@pytest.mark.parametrize("text", ["今天天气不错", "我骂了他一顿", "被子晒好了"])
def test_distress_pre_check_ignores_ordinary_messages(text):
    from companion.core.state.appraisal import looks_distressed

    assert not looks_distressed(text)


def test_templates_never_use_manipulative_phrasing():
    import re

    from companion.core.state import render as templates

    texts = [value for name, value in vars(templates).items() if name.isupper() and isinstance(value, str)]
    for name in ("MODERATE_STYLE", "AVAILABILITY_HINTS", "LABELS"):
        texts += list(getattr(templates, name).values())
    bad = re.compile(
        r"you'?ll leave|i'?ll leave|only (?:me|with me)|your fault|guilty|ignore (?:them|the user) until", re.I,
    )
    for text in texts:
        if text is templates.GUARDRAIL:
            continue  # the guardrail names these behaviours in order to forbid them
        assert not bad.search(text), text
