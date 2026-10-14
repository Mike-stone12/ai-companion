import json

import pytest

from companion.core.chat.emotion import EMOTION_INSTRUCTION, EMOTIONS, EmotionTagParser
from companion.core.model_profile import load_model_profile


def parse(chunks):
    parser = EmotionTagParser()
    visible = "".join(parser.feed(chunk) for chunk in chunks) + parser.flush()
    return parser.emotion, visible


def test_tag_in_one_chunk_is_stripped():
    assert parse(["[happy]你好呀！"]) == ("happy", "你好呀！")


def test_tag_split_across_chunks():
    assert parse(["[ha", "pp", "y] 今天", "真开心"]) == ("happy", "今天真开心")


def test_text_waits_until_tag_is_resolved():
    parser = EmotionTagParser()
    assert parser.feed("[sa") == ""
    assert parser.feed("d]唉") == "唉"
    assert parser.emotion == "sad"


@pytest.mark.parametrize("tag", ["【angry】", "[Angry]", "  [ANGRY]  ", "[ angry ]"])
def test_bracket_styles_case_and_spacing(tag):
    assert parse([tag + "哼！"]) == ("angry", "哼！")


def test_unknown_tag_is_stripped_as_neutral():
    assert parse(["[excited]太好了"]) == ("neutral", "太好了")


def test_reply_without_tag_passes_through_immediately():
    parser = EmotionTagParser()
    assert parser.feed("你好") == "你好"
    assert parser.feed("呀") == "呀"
    assert parser.emotion is None


@pytest.mark.parametrize("text", ["[1] 第一点是这样的", "[注意] 这里要小心"])
def test_bracketed_text_that_is_not_a_tag_is_kept(text):
    assert parse([text]) == (None, text)


def test_unclosed_bracket_is_released_after_a_short_prefix():
    text = "[这是一个很长的方括号开头但是一直没有闭合的句子"
    parser = EmotionTagParser()
    assert parser.feed(text) == text
    assert parser.emotion is None


def test_stream_ending_inside_a_tag_returns_the_text():
    assert parse(["[hap"]) == (None, "[hap")


def test_only_the_leading_tag_is_parsed():
    assert parse(["[happy]我很开心[sad]"]) == ("happy", "我很开心[sad]")


def test_instruction_lists_every_emotion():
    for emotion in EMOTIONS:
        assert f"[{emotion}]" in EMOTION_INSTRUCTION


def test_profile_reads_expression_mapping(tmp_path):
    (tmp_path / "m.model3.json").write_text("{}", encoding="utf-8")
    (tmp_path / "companion.json").write_text(
        json.dumps({"expressions": {"happy": "expressions/开心.exp3.json", "bad": 3}}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert load_model_profile(tmp_path).expressions == {"happy": "expressions/开心.exp3.json"}


def test_profile_without_expressions(tmp_path):
    (tmp_path / "m.model3.json").write_text("{}", encoding="utf-8")
    assert load_model_profile(tmp_path).expressions == {}
