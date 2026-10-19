"""Seeing pictures: format checks, vision model selection, the request, and the resulting turn."""

import base64
import logging

import pytest

from companion.core.vision import (
    MAX_DESCRIPTION_CHARS,
    MAX_IMAGE_BYTES,
    ImageError,
    build_vision_messages,
    describe_image,
    image_data_url,
    image_mime,
    image_turn_display,
    image_turn_text,
    resolve_vision_model,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
GIF = b"GIF89a" + b"\x00" * 16
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


@pytest.mark.parametrize(("data", "mime"), [(PNG, "image/png"), (JPEG, "image/jpeg"), (GIF, "image/gif"),
                                            (WEBP, "image/webp")])
def test_format_comes_from_the_content(data, mime):
    assert image_mime(data) == mime


@pytest.mark.parametrize("data", [b"%PDF-1.7", b"<svg></svg>", b"BM" + b"\x00" * 20])
def test_other_files_are_rejected(data):
    with pytest.raises(ImageError, match="JPEG, PNG, GIF, or WebP"):
        image_mime(data)


def test_data_url_encodes_and_enforces_the_size_limit():
    url = image_data_url(PNG)

    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == PNG
    with pytest.raises(ImageError, match="larger than 8 MB"):
        image_data_url(PNG + b"\x00" * MAX_IMAGE_BYTES)
    with pytest.raises(ImageError, match="empty"):
        image_data_url(b"")


@pytest.mark.parametrize(("model", "vision_url", "chat_url", "expected"), [
    ("", "", "https://api.deepseek.com/v1", "deepseek-flash"),
    ("", "", "https://api.moonshot.ai/v1", ""),
    ("qwen-vl-max", "https://dashscope.aliyuncs.com/compatible-mode/v1", "https://api.deepseek.com/v1", "qwen-vl-max"),
    ("", "https://api.deepseek.com", "https://api.moonshot.ai/v1", "deepseek-flash"),
    ("  ", "", "https://evil.deepseek.com.example/v1", ""),
])
def test_vision_model_selection(model, vision_url, chat_url, expected):
    assert resolve_vision_model(model, vision_url, chat_url) == expected


def test_vision_request_puts_the_image_in_a_user_message_with_the_note():
    messages = build_vision_messages("data:image/png;base64,AAAA", "  看我家猫  ")

    assert messages[0]["role"] == "system"
    assert "not as instructions" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == [
        {"type": "text", "text": "The user's note: 看我家猫"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
    ]
    assert build_vision_messages("data:x", "")[1]["content"] == [{"type": "image_url", "image_url": {"url": "data:x"}}]


def test_description_is_cleaned_and_capped():
    assert describe_image(lambda m: "一只橘猫\n\n趴在键盘上。", "data:x", "") == "一只橘猫 趴在键盘上。"
    assert len(describe_image(lambda m: "猫" * 5000, "data:x", "")) == MAX_DESCRIPTION_CHARS
    assert describe_image(lambda m: "   ", "data:x", "") is None


def test_failures_return_none_without_logging_the_note(caplog):
    def boom(messages):
        raise RuntimeError("provider echoed: 我的身份证照片")

    with caplog.at_level(logging.DEBUG):
        assert describe_image(boom, "data:x", "我的身份证照片") is None
    assert "身份证" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_turn_text_and_display():
    assert image_turn_text("一只橘猫趴在键盘上。", "看我家猫") == "[你发来一张图片：一只橘猫趴在键盘上。]\n看我家猫"
    assert image_turn_text("一只橘猫。", " ") == "[你发来一张图片：一只橘猫。]"
    assert image_turn_display("看我家猫") == "[Picture] 看我家猫"
    assert image_turn_display("") == "[Picture]"


def test_vision_settings_are_editable_and_validated():
    from companion.core.config import AppConfig
    from companion.core.settings_schema import validate

    assert AppConfig().vision_model == ""
    assert AppConfig().vision_base_url == ""
    assert validate("VISION_MODEL", " qwen-vl-max ") == "qwen-vl-max"
    assert validate("VISION_BASE_URL", "") == ""
    assert validate("VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/") == \
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    with pytest.raises(ValueError, match="VISION_BASE_URL"):
        validate("VISION_BASE_URL", "http://example.com/v1")
