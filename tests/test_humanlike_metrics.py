"""Rule-based signals of an assistant voice in a transcript (no model needed)."""

import pytest

from evals.humanlike.metrics import (
    ASSISTANT_PHRASES,
    message_metrics,
    summarize,
    transcript_metrics,
)


def reply(*messages):
    return {"user": ["hi"], "reply": list(messages)}


def test_assistant_phrases_and_formatting_are_flagged():
    m = message_metrics("别担心，有什么可以帮你的吗？")
    assert set(m["assistant_phrases"]) == {"有什么可以帮你", "别担心"}
    assert m["ends_with_question"]
    assert message_metrics("**重点**：先休息")["markdown"]
    assert message_metrics("1. 先休息\n2. 再吃饭")["markdown"]
    assert message_metrics("- 第一点")["markdown"]
    assert not message_metrics("切，谁等你了")["markdown"]


def test_ai_self_reference_counts_as_an_assistant_phrase():
    assert message_metrics("作为一个AI，我没有感情")["assistant_phrases"]


def test_exclamations_emoji_and_tilde_are_counted():
    m = message_metrics("太好了！！真的~😄")
    assert m["exclamations"] == 2
    assert m["emoji"] == 1
    assert m["tilde"] == 1


def test_a_plain_message_is_clean():
    m = message_metrics("啧，又加班")
    assert m == {
        "chars": 5, "ends_with_question": False, "assistant_phrases": [], "markdown": False,
        "exclamations": 0, "emoji": 0, "tilde": 0,
    }


def test_transcript_metrics_cover_length_questions_and_repeats():
    turns = [
        reply("哟，还知道回来啊", "忙什么去了？"),
        reply("哟，今天这么早", "行吧"),
        reply("行吧"),
    ]
    m = transcript_metrics(turns)
    assert m["replies"] == 3
    assert m["messages"] == 5
    assert m["messages_per_reply"] == pytest.approx(5 / 3)
    assert m["question_endings"] == 1
    assert m["replies_ending_with_question"] == 1
    # The second reply opens like the first ("哟，"); "行吧" is sent twice word for word.
    assert m["repeated_openers"] == 1
    assert m["verbatim_repeats"] == 1
    assert m["assistant_phrase_hits"] == 0
    assert m["median_chars"] == 6  # 8, 6, 6, 2, 2


def test_empty_replies_are_counted_as_missing():
    m = transcript_metrics([reply(), reply("嗯")])
    assert m["missing_replies"] == 1


def test_summarize_adds_up_scenarios():
    a = transcript_metrics([reply("别担心！", "加油哦")])
    b = transcript_metrics([reply("嗯？")])
    total = summarize([a, b])
    assert total["replies"] == 2
    assert total["messages"] == 3
    assert total["assistant_phrase_hits"] == 2
    assert total["question_endings"] == 1
    assert total["exclamations"] == 1


def test_phrase_list_matches_the_persona_ban_list():
    from companion.core.persona import VOICE_RULES

    for phrase in ("有什么可以帮你", "我理解你的感受", "别担心", "加油哦", "照顾好自己", "记得早点休息"):
        assert phrase in VOICE_RULES
        assert phrase in ASSISTANT_PHRASES


def test_the_scenario_file_is_valid():
    from evals.humanlike.__main__ import load_scenarios

    scenarios = load_scenarios()
    assert len(scenarios) >= 8
    assert any(len(turn["user"]) > 1 for s in scenarios for turn in s["turns"])
