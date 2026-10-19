"""Run the window's picture flow with Qt stand-ins (Qt is unavailable in CI)."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import Signal, load_class

from companion.core import vision
from companion.core.api_key import service_api_key
from companion.core.config import AppConfig

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.fixture
def window():
    thread = Mock(started=Signal(), finished=Signal())
    worker = Mock(finished=Signal())
    clients = []
    own_key = {"value": ""}
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {}), replace=replace, QThread=Mock(return_value=thread),
        VisionWorker=Mock(return_value=worker), OpenAICompatibleClient=lambda config: clients.append(config) or Mock(),
        ImageError=vision.ImageError, image_data_url=vision.image_data_url,
        image_turn_display=vision.image_turn_display, image_turn_text=vision.image_turn_text,
        PICTURE_TIP="tip", service_api_key=service_api_key, VISION_ACCOUNT="VISION_API_KEY",
        ApiKeyStore=lambda **kwargs: Mock(resolve=Mock(return_value=Mock(value=own_key["value"]))),
        logger=Mock(),
    )
    instance = cls.__new__(cls)
    instance.thread, instance.clients = thread, clients
    instance.config = AppConfig(base_url="https://api.deepseek.com/v1", model="deepseek-flash", api_key="k")
    instance.vision_model = "deepseek-flash"
    instance.vision_api_key = "k"
    instance.own_key = own_key
    instance.setAcceptDrops = Mock()
    instance.pending_image = None
    instance.picture_button = Mock()
    instance.vision_thread = instance.vision_worker = None
    instance.busy = instance.closing = False
    for name in ("chat_input", "send_button", "chat_panel", "set_status", "pause_wake_word", "finish_interaction"):
        setattr(instance, name, Mock())
    instance.submit_message = Mock()
    return instance


def test_attaching_a_picture_changes_the_button_and_hint(window):
    window.attach_image(PNG)

    assert window.pending_image.startswith("data:image/png;base64,")
    window.picture_button.setText.assert_called_with("Picture ✕")


def test_unsupported_files_show_a_notice_instead(window):
    window.attach_image(b"%PDF-1.7")

    assert window.pending_image is None
    window.chat_panel.add_notice.assert_called_once()


def test_sending_describes_first_and_shows_the_users_bubble(window):
    window.attach_image(PNG)
    window.chat_input.text.return_value = " 看我家猫 "

    window.send_message()

    assert window.busy
    window.chat_panel.add_user.assert_called_once_with("[Picture] 看我家猫")
    window.set_status.assert_called_with("Looking at the picture…")
    window.thread.start.assert_called_once()
    assert window.pending_image is None
    assert window.clients[0].model == "deepseek-flash"
    assert window.clients[0].base_url == "https://api.deepseek.com/v1"
    assert window.clients[0].api_key == "k"
    window.submit_message.assert_not_called()


def test_the_description_becomes_the_users_turn_without_a_second_bubble(window):
    window.pending_caption = "看我家猫"
    window.busy = True

    window.on_picture_described("一只橘猫趴在键盘上。")

    window.submit_message.assert_called_once_with("[你发来一张图片：一只橘猫趴在键盘上。]\n看我家猫", display="")


def test_a_failed_description_says_so_and_frees_the_input(window):
    window.pending_caption = ""
    window.busy = True

    window.on_picture_described("")

    window.chat_panel.add_notice.assert_called_once()
    window.finish_interaction.assert_called_once()
    window.submit_message.assert_not_called()


def test_a_separate_vision_endpoint_is_used_when_configured(window):
    window.config = replace(window.config, vision_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    window.vision_model = "qwen-vl-max"
    window.vision_api_key = "sk-dashscope"
    window.attach_image(PNG)
    window.chat_input.text.return_value = ""

    window.send_message()

    assert window.clients[0].base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert window.clients[0].model == "qwen-vl-max"
    assert window.clients[0].api_key == "sk-dashscope"
    window.chat_panel.add_user.assert_called_once_with("[Picture]")


def test_plain_text_still_goes_straight_to_chat(window):
    window.chat_input.text.return_value = "你好"

    window.send_message()

    window.submit_message.assert_called_once_with("你好")


def test_same_host_reuses_the_chat_key(window):
    window.refresh_vision_access()

    assert window.vision_api_key == "k"
    window.picture_button.setVisible.assert_called_with(True)


def test_another_provider_without_its_own_key_hides_pictures(window):
    window.config = replace(window.config, vision_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")

    window.refresh_vision_access()

    assert window.vision_api_key is None
    window.picture_button.setVisible.assert_called_with(False)
    window.attach_image(PNG)
    window.chat_input.text.return_value = "看"
    window.send_message()
    window.thread.start.assert_not_called()


def test_another_provider_with_its_own_key_uses_that_key(window):
    window.config = replace(window.config, vision_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    window.own_key["value"] = "sk-dashscope"

    window.refresh_vision_access()

    assert window.vision_api_key == "sk-dashscope"
    window.picture_button.setVisible.assert_called_with(True)
