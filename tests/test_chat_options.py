import io
import json

import pytest

import main
from main import AppConfig, OpenAICompatibleClient, chat_request_options


def make_config(base_url, chat_thinking=False):
    config = AppConfig()
    config.api_key = "key"
    config.base_url = base_url
    config.chat_thinking = chat_thinking
    return config


@pytest.mark.parametrize("base_url", ["https://api.deepseek.com/v1", "https://api.moonshot.ai/v1"])
def test_chat_disables_thinking_by_default_where_supported(base_url):
    assert chat_request_options(make_config(base_url)) == {"thinking": {"type": "disabled"}}


def test_chat_thinking_can_be_turned_back_on():
    assert chat_request_options(make_config("https://api.deepseek.com/v1", chat_thinking=True)) == {}


def test_providers_without_toggle_get_no_extra_options():
    assert chat_request_options(make_config("https://api.openai.com/v1")) == {}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_chat_request_omits_temperature_and_sends_thinking_toggle(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout):
        sent.update(json.loads(request.data))
        return FakeResponse(json.dumps({"choices": [{"message": {"content": "你好呀?"}}]}).encode())

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    reply = OpenAICompatibleClient(make_config("https://api.moonshot.ai/v1")).chat([{"role": "user", "content": "hi"}])
    assert reply == "你好呀?"
    assert sent["thinking"] == {"type": "disabled"}
    # Moonshot only accepts temperature 0.6 with thinking off and 1 with it on.
    assert "temperature" not in sent


def test_chat_thinking_env_flag(monkeypatch):
    monkeypatch.setenv("CHAT_THINKING", "1")
    assert main.env_flag("CHAT_THINKING", default=False) is True
    monkeypatch.setenv("CHAT_THINKING", "0")
    assert main.env_flag("CHAT_THINKING", default=True) is False
    monkeypatch.delenv("CHAT_THINKING")
    assert main.env_flag("CHAT_THINKING", default=False) is False
