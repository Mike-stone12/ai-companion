"""Quoting an earlier message: what the model sees and what the bubble shows."""

import pytest

from companion.core.chat.history import display_text
from companion.core.chat.quote import (
    MAX_QUOTE_CHARS,
    clip_quote,
    quote_display,
    quote_turn_text,
    split_quote,
)


def test_quoting_her_tells_the_model_whose_line_it_was():
    text = quote_turn_text("我最喜欢草莓", own=False, text="那你上次怎么说喜欢芒果")
    assert text == "[引用你说的：「我最喜欢草莓」]\n那你上次怎么说喜欢芒果"


def test_quoting_yourself_says_so():
    assert quote_turn_text("我下周五考六级", own=True, text="就这个").startswith("[引用我自己说的：「我下周五考六级」]")


def test_long_or_multiline_quotes_are_clipped_to_one_line():
    clipped = clip_quote("第一行\n第二行" + "很长" * 80)
    assert "\n" not in clipped
    assert len(clipped) == MAX_QUOTE_CHARS + 1 and clipped.endswith("…")
    assert clip_quote("  短句  ") == "短句"


def test_a_quote_round_trips_and_shows_as_a_reply_marker():
    content = quote_turn_text("我最喜欢草莓", own=False, text="真的假的")
    assert split_quote(content) == ("我最喜欢草莓", False, "真的假的")
    assert quote_display("我最喜欢草莓", "真的假的") == "↪ 我最喜欢草莓\n真的假的"
    assert display_text({"role": "user", "content": content}) == "↪ 我最喜欢草莓\n真的假的"


@pytest.mark.parametrize("content", ["普通的一句话", "[你发来一张图片：一只猫]\n看", "[引用你说的：没有结尾"])
def test_other_turns_are_not_quotes(content):
    assert split_quote(content) is None
    assert display_text({"role": "user", "content": content}) == content


def test_an_empty_reply_to_a_quote_still_works():
    content = quote_turn_text("晚安", own=False, text="")
    assert content == "[引用你说的：「晚安」]"
    assert split_quote(content) == ("晚安", False, "")
