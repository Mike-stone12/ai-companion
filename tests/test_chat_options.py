import io
import json
import runpy

import pytest

from companion.core import config
from companion.core.config import AppConfig
from companion.core.llm import client as llm_client
from companion.core.llm.client import OpenAICompatibleClient, chat_request_options


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

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)
    reply = OpenAICompatibleClient(make_config("https://api.moonshot.ai/v1")).chat([{"role": "user", "content": "hi"}])
    assert reply == "你好呀?"
    assert sent["thinking"] == {"type": "disabled"}
    # Moonshot only accepts temperature 0.6 with thinking off and 1 with it on.
    assert "temperature" not in sent


def test_chat_thinking_env_flag(monkeypatch):
    monkeypatch.setenv("CHAT_THINKING", "1")
    assert config.env_flag("CHAT_THINKING", default=False) is True
    monkeypatch.setenv("CHAT_THINKING", "0")
    assert config.env_flag("CHAT_THINKING", default=True) is False
    monkeypatch.delenv("CHAT_THINKING")
    assert config.env_flag("CHAT_THINKING", default=False) is False


@pytest.mark.parametrize("value, expected", [(None, True), ("0", False)])
def test_conversation_summary_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("CONVERSATION_SUMMARY", raising=False)
    else:
        monkeypatch.setenv("CONVERSATION_SUMMARY", value)
    # Evaluate import-time defaults without changing the shared config module.
    config_class = runpy.run_path(config.__file__)["AppConfig"]
    assert config_class().conversation_summary is expected


@pytest.mark.parametrize("value, expected", [(None, False), ("1", True), ("0", False)])
def test_chat_tools_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("CHAT_TOOLS", raising=False)
    else:
        monkeypatch.setenv("CHAT_TOOLS", value)
    config_class = runpy.run_path(config.__file__)["AppConfig"]
    assert config_class().chat_tools is expected


@pytest.mark.parametrize("value, expected", [(None, False), ("1", True), ("0", False)])
def test_proactive_chat_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("PROACTIVE_CHAT", raising=False)
    else:
        monkeypatch.setenv("PROACTIVE_CHAT", value)
    config_class = runpy.run_path(config.__file__)["AppConfig"]
    assert config_class().proactive_chat is expected


@pytest.mark.parametrize("value, expected", [(None, False), ("0", False), ("1", True), (" YES ", True)])
def test_memory_semantic_recall_setting(monkeypatch, value, expected):
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-model")
    if value is None:
        monkeypatch.delenv("MEMORY_SEMANTIC_RECALL", raising=False)
    else:
        monkeypatch.setenv("MEMORY_SEMANTIC_RECALL", value)
    config_class = runpy.run_path(config.__file__)["AppConfig"]
    assert config_class().memory_semantic_recall is expected


@pytest.mark.parametrize("model", [None, "", "  "])
def test_semantic_recall_without_model_is_disabled(monkeypatch, model):
    monkeypatch.setenv("MEMORY_SEMANTIC_RECALL", "1")
    if model is None:
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    else:
        monkeypatch.setenv("EMBEDDING_MODEL", model)
    config_class = runpy.run_path(config.__file__)["AppConfig"]
    assert config_class().embedding_model == ""
    assert config_class().memory_semantic_recall is False
