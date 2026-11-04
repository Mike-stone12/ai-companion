"""Waiting for a burst of user messages before replying to all of them at once."""

import pytest

from companion.core.chat.merge import (
    MAX_WAIT,
    QUIET_CLOSED,
    QUIET_OPEN,
    QUIET_PLAIN,
    MessageMerger,
    looks_unfinished,
    merged_text,
    quiet_after,
)


@pytest.mark.parametrize("text", [
    "我跟你说，", "然后", "今天去吃饭然后", "还有", "就是…", "所以...", "等一下",
    "在吗", "诶", "hi", "and", "so,", "I mean", "话说",
])
def test_unfinished_messages_wait_longer(text):
    assert looks_unfinished(text)
    assert quiet_after(text) == QUIET_OPEN


@pytest.mark.parametrize("text", ["今天好累啊！", "你吃饭了吗？", "好的。", "ok!", "晚安~"])
def test_finished_sentences_go_quickly(text):
    assert not looks_unfinished(text)
    assert quiet_after(text) == QUIET_CLOSED


@pytest.mark.parametrize("text", ["今天好累", "我刚下班", "what are you doing"])
def test_plain_messages_wait_a_little(text):
    assert not looks_unfinished(text)
    assert quiet_after(text) == QUIET_PLAIN


def test_quiet_tiers_are_ordered():
    assert 0 < QUIET_CLOSED < QUIET_PLAIN < QUIET_OPEN < MAX_WAIT


def test_empty_merger_has_nothing_to_wait_for():
    merger = MessageMerger()
    assert not merger
    assert merger.wait(0.0) is None
    assert merger.take() == []


def test_single_message_waits_its_quiet_time():
    merger = MessageMerger()
    merger.add("今天好累", now=10.0)
    assert merger
    assert merger.wait(10.0) == pytest.approx(QUIET_PLAIN)
    assert merger.wait(10.0 + QUIET_PLAIN + 1) == 0.0


def test_quiet_time_restarts_with_each_message_and_follows_the_last_one():
    merger = MessageMerger()
    merger.add("我跟你说，", now=0.0)
    assert merger.wait(0.0) == pytest.approx(QUIET_OPEN)
    merger.add("今天被老板骂了。", now=2.0)
    assert merger.wait(2.0) == pytest.approx(QUIET_CLOSED)
    assert merger.pending == ("我跟你说，", "今天被老板骂了。")


def test_a_long_burst_is_capped_from_its_first_message():
    merger = MessageMerger()
    for second in range(0, 6):
        merger.add("然后", now=float(second))
    assert merger.wait(5.0) == pytest.approx(MAX_WAIT - 5.0)
    assert merger.wait(MAX_WAIT + 1) == 0.0


def test_take_returns_the_burst_in_order_and_starts_a_new_one():
    merger = MessageMerger()
    merger.add("在吗", now=0.0)
    merger.add("问你个事", now=1.0)
    assert merger.take() == ["在吗", "问你个事"]
    assert not merger
    merger.add("好的。", now=50.0)
    assert merger.wait(50.0) == pytest.approx(QUIET_CLOSED)


def test_blank_messages_are_ignored():
    merger = MessageMerger()
    merger.add("   ", now=0.0)
    assert not merger


def test_disabled_merger_flushes_at_once():
    merger = MessageMerger(enabled=False)
    merger.add("然后", now=0.0)
    assert merger.wait(0.0) == 0.0


def test_merged_text_joins_lines():
    assert merged_text(["在吗", "问你个事"]) == "在吗\n问你个事"
    assert merged_text(["一条"]) == "一条"
