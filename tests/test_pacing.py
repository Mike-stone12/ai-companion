"""Reply pacing: splitting a streamed reply into chat messages and timing them like typing."""

import random

import pytest

from companion.core.chat.pacing import (
    MAX_MESSAGES,
    MAX_REPLY_DELAY,
    MessageSplitter,
    reply_delay,
    split_for_display,
    typing_delay,
)


def test_messages_complete_at_line_breaks_while_streaming():
    splitter = MessageSplitter()

    assert splitter.feed("你来") == []
    assert splitter.feed("啦！\n我等你好久") == ["你来啦！"]
    assert splitter.feed("了\n\n") == ["我等你好久了"]
    assert splitter.finish() == []


def test_finish_returns_the_last_unterminated_message():
    splitter = MessageSplitter()
    splitter.feed("第一条\n第二条没换行")

    assert splitter.finish() == ["第二条没换行"]
    assert splitter.finish() == []


def test_extra_lines_are_folded_into_the_last_message():
    splitter = MessageSplitter()
    messages = splitter.feed("一\n二\n三\n四\n五\n") + splitter.finish()

    assert len(messages) == MAX_MESSAGES
    assert messages[-1] == "四 五"


def test_blank_and_whitespace_lines_are_skipped():
    splitter = MessageSplitter()

    assert splitter.feed("  \n\n好呀\n   \n") == ["好呀"]


def test_split_for_display_matches_the_live_split():
    assert split_for_display("一\n\n二\n三\n四\n五") == ["一", "二", "三", "四 五"]
    assert split_for_display("单条") == ["单条"]
    assert split_for_display("  ") == []


def test_typing_delay_scales_with_length_jitters_and_is_bounded():
    rng = random.Random(1)
    short = typing_delay("嗯", rng)
    long = typing_delay("今天的课好无聊啊，老师一直在念PPT，我都快睡着了", random.Random(1))

    assert 0.6 <= short < long <= 4.0
    assert typing_delay("x" * 500, random.Random(1)) == 4.0
    medium = "今天的课好无聊，我都快睡着了"
    assert typing_delay(medium, random.Random(1), slow=1.5) > typing_delay(medium, random.Random(1))


@pytest.mark.parametrize(("availability", "low", "high"), [("busy", 4, 15), ("asleep", 3, 8)])
def test_busy_or_asleep_replies_come_a_little_later(availability, low, high):
    delays = [reply_delay(availability, random.Random(seed)) for seed in range(20)]

    assert all(low <= delay <= high for delay in delays)
    assert max(delays) <= MAX_REPLY_DELAY


@pytest.mark.parametrize("availability", ["", "free", "drowsy"])
def test_free_replies_start_at_once(availability):
    assert reply_delay(availability, random.Random(1)) == 0.0
