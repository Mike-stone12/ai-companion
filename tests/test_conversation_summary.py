from copy import deepcopy

import pytest

from companion.core.chat.summary import (
    DEFAULT_SUMMARY_MAX_CHARS,
    build_summary_messages,
    parse_summary,
    split_for_summary,
)


@pytest.fixture
def messages():
    return [
        {"role": "user", "content": "I plan to learn piano."},
        {"role": "assistant", "content": "[happy] What will you practice?"},
        {"role": "user", "content": "Scales tomorrow. I feel nervous."},
        {"role": "assistant", "content": "[shy] Let's start slowly."},
    ]


@pytest.mark.parametrize("keep_recent", [4, 6])
def test_no_overflow(messages, keep_recent):
    assert split_for_summary(messages, keep_recent) == ([], messages)


def test_empty_history():
    assert split_for_summary([], 2) == ([], [])


def test_exact_boundary(messages):
    assert split_for_summary(messages, 2) == (messages[:2], messages[2:])


@pytest.mark.parametrize("keep_recent, boundary", [(1, 2), (3, 0)])
def test_boundary_keeps_user_with_assistant_reply(messages, keep_recent, boundary):
    assert split_for_summary(messages, keep_recent) == (messages[:boundary], messages[boundary:])


def test_zero_recent_summarizes_everything(messages):
    assert split_for_summary(messages, 0) == (messages, [])


def test_pending_user_message_stays_recent(messages):
    messages.append({"role": "user", "content": "Where should I start?"})
    assert split_for_summary(messages, 1) == (messages[:-1], messages[-1:])


def test_inputs_are_not_mutated(messages):
    original = deepcopy(messages)
    split_for_summary(messages, 1)
    build_summary_messages("Previous facts.", messages, 100)
    assert messages == original


def test_prompt_includes_previous_summary_and_plain_turns(messages):
    prompt = build_summary_messages("The user enjoys music.", messages, 321)
    assert [message["role"] for message in prompt] == ["system", "user"]
    assert "Previous summary:\nThe user enjoys music." in prompt[1]["content"]
    assert "User: I plan to learn piano." in prompt[1]["content"]
    assert "Companion: What will you practice?" in prompt[1]["content"]
    assert "321" in prompt[0]["content"]


@pytest.mark.parametrize("previous", [None, "", " \n "])
def test_prompt_omits_absent_previous_summary(messages, previous):
    content = build_summary_messages(previous, messages, 400)[1]["content"]
    assert content.startswith("Conversation turns:\nUser:")
    assert "Previous summary:" not in content
    assert "None" not in content


def test_prompt_strips_only_leading_assistant_emotion_tags():
    turns = [
        {"role": "user", "content": "[happy] My own tag."},
        {"role": "assistant", "content": "  [happy] Hello [sad] is an example."},
        {"role": "assistant", "content": "【shy】 你好！"},
        {"role": "assistant", "content": "No tag here."},
    ]
    content = build_summary_messages(None, turns, 400)[1]["content"]
    assert "User: [happy] My own tag." in content
    assert "Companion: Hello [sad] is an example." in content
    assert "Companion: 你好！" in content
    assert "Companion: No tag here." in content


def test_default_summary_limit():
    assert DEFAULT_SUMMARY_MAX_CHARS == 400


@pytest.mark.parametrize("text", ["", " \n\t ", '""', "```\n \n```", '```text\n"  "\n```'])
def test_parse_empty_summary(text):
    assert parse_summary(text, 400) is None


@pytest.mark.parametrize(
    "text",
    [
        "  Likes music. \n",
        '"Likes music."',
        "'Likes music.'",
        "“Likes music.”",
        "```\nLikes music.\n```",
        "```text\nLikes music.\n```",
        '```text\n"Likes music."\n```',
        '"```\nLikes music.\n```"',
    ],
)
def test_parse_strips_surrounding_whitespace_fences_and_quotes(text):
    assert parse_summary(text, 400) == "Likes music."


@pytest.mark.parametrize("ending", list("。！？.!?"))
def test_parse_truncates_at_last_sentence_end(ending):
    text = f"One{ending} Two{ending} unfinished thought"
    assert parse_summary(text, 13) == f"One{ending} Two{ending}"


def test_parse_keeps_sentence_end_exactly_at_limit():
    assert parse_summary("Done. More text.", 5) == "Done."


def test_parse_hard_cuts_without_sentence_end_before_limit():
    assert parse_summary("abcdefghijk.", 6) == "abcdef"


def test_parse_preserves_text_at_limit():
    assert parse_summary("One. Two", 8) == "One. Two"


def test_negative_recent_count_is_rejected(messages):
    with pytest.raises(ValueError):
        split_for_summary(messages, -1)


@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_character_limit_is_rejected(limit):
    with pytest.raises(ValueError):
        build_summary_messages(None, [], limit)
    with pytest.raises(ValueError):
        parse_summary("Summary", limit)
