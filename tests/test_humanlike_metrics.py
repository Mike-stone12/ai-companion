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
        "exclamations": 0, "emoji": 0, "tilde": 0, "questions": 0, "either_or": False, "stage_direction": False,
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


def test_answering_a_burst_halfway_is_counted():
    halfway = {
        "user": ["我今天在地铁上", "看到一只猫"], "reply": ["然后呢", "哇"],
        "timeline": [[0, "user", "我今天在地铁上"], [1, "her", "然后呢"], [2, "user", "看到一只猫"], [3, "her", "哇"]],
    }
    waited = {
        "user": ["我今天在地铁上", "看到一只猫"], "reply": ["哇"],
        "timeline": [[0, "user", "我今天在地铁上"], [2, "user", "看到一只猫"], [4, "her", "哇"]],
    }
    single = {"user": ["嗯"], "reply": ["干嘛"], "timeline": [[0, "user", "嗯"], [1, "her", "干嘛"]]}
    m = transcript_metrics([halfway, waited, single])
    assert m["burst_turns"] == 2
    assert m["bursts_interrupted"] == 1
    assert m["bubbles_before_user_finished"] == 1


@pytest.mark.parametrize("text", ["是时间不对还是地方不对", "辣锅还是清汤？", "是复习太累，还是紧张？"])
def test_either_or_guesses_are_counted(text):
    assert message_metrics(text)["either_or"]


@pytest.mark.parametrize("text", ["我还是喜欢草莓", "还是你最好", "算了还是睡吧"])
def test_still_and_rather_are_not_either_or(text):
    assert not message_metrics(text)["either_or"]


def test_questions_anywhere_and_stage_directions_are_counted():
    assert message_metrics("你吃了吗？我刚吃完")["questions"] == 1
    assert message_metrics("你吃了吗？睡了吗？")["questions"] == 2
    assert message_metrics("（把手机架高了一点）")["stage_direction"]
    assert message_metrics("*翻了个白眼*")["stage_direction"]
    assert not message_metrics("我（真的）没生气")["stage_direction"]


def test_echoing_the_users_words_back_as_a_question_is_counted():
    turn = {"user": ["我今天在地铁上", "看到一个人抱着一只猫"], "reply": ["抱着一只猫？", "那猫凶吗"]}
    assert transcript_metrics([turn])["echo_questions"] == 1
    turn = {"user": ["帮我写个请假条呗"], "reply": ["写请假条？", "你又想翘课"]}
    assert transcript_metrics([turn])["echo_questions"] == 1
    turn = {"user": ["你猜我吃了啥"], "reply": ["火锅？"]}
    assert transcript_metrics([turn])["echo_questions"] == 0


def test_listening_templates_count_as_assistant_phrases():
    for line in ("我在这听着呢", "说吧，我这边正好闲着", "想说话再喊我"):
        assert message_metrics(line)["assistant_phrases"], line


def test_new_counts_are_summed():
    a = transcript_metrics([{"user": ["嗯"], "reply": ["是累了还是困了？", "（打了个哈欠）"]}])
    total = summarize([a, a])
    assert total["either_or"] == 2
    assert total["stage_directions"] == 2
    assert total["questions"] == 2
