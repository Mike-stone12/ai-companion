import pytest

from main import sanitize_reply_text, sanitize_tts_text


@pytest.mark.parametrize("sanitize", [sanitize_reply_text, sanitize_tts_text])
@pytest.mark.parametrize(
    "text",
    ["你今天过得好吗?", "你今天过得好吗？", "What do you want to play today?"],
)
def test_question_marks_are_kept(sanitize, text):
    assert sanitize(text) == text


@pytest.mark.parametrize("sanitize", [sanitize_reply_text, sanitize_tts_text])
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("好呀😊", "好呀"),
        ("加油👍🏻！", "加油！"),
        ("全家👨‍👩‍👧出游", "全家出游"),
        ("爱你❤️", "爱你"),
        ("今天⭐很棒★☆", "今天很棒"),
        ("中国🇨🇳", "中国"),
        ("晚安 🌙 明天见", "晚安 明天见"),
    ],
)
def test_emoji_are_removed(sanitize, text, expected):
    assert sanitize(text) == expected


def test_reply_strips_markdown():
    assert sanitize_reply_text("```python\nprint(1)\n```") == "print(1)"
    assert sanitize_reply_text("用 `pip` 安装，**很简单**") == "用 pip 安装，很简单"


def test_tts_strips_urls_and_markdown():
    assert sanitize_tts_text("看这里 https://example.com 好吗?") == "看这里 好吗?"
    assert sanitize_tts_text("# 标题 **重点**") == "标题 重点"


def test_plain_chinese_is_untouched():
    text = "我们明天下午三点见，记得带伞。"
    assert sanitize_reply_text(text) == text
    assert sanitize_tts_text(text) == text
