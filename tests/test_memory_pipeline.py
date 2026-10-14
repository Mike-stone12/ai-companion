import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

import main
from main import (
    AppConfig,
    OpenAICompatibleClient,
    extract_memories_with_llm,
    extraction_request_options,
    heuristic_memory_candidates,
    should_extract_memory,
)


class FakeClient:
    def __init__(self, reply=None, error=None, api_key="key", base_url="https://api.moonshot.ai/v1"):
        self.config = SimpleNamespace(api_key=api_key, base_url=base_url)
        self.reply = reply
        self.error = error
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.reply


# --- heuristics (fallback only) ---


@pytest.mark.parametrize(
    ("text", "summary"),
    [
        ("我叫小林", "用户名字：小林"),
        ("你可以叫我阿杰", "用户名字：阿杰"),
        ("我是一名大学生", "用户身份：一名大学生"),
        ("我喜欢吃寿司", "用户喜欢：吃寿司"),
        ("我住在杭州", "用户住在：杭州"),
    ],
)
def test_heuristics_capture_stable_facts(text, summary):
    assert summary in [item["summary"] for item in heuristic_memory_candidates(text)]


@pytest.mark.parametrize(
    "text",
    [
        "今天天气真不错我们聊点别的话题吧好不好",
        "我在想要不要出去走走",
        "我是说真的啦",
        "我是不是太累了",
        "明天再说吧",
    ],
)
def test_heuristics_ignore_chit_chat(text):
    assert heuristic_memory_candidates(text) == []


# --- gate ---


@pytest.mark.parametrize("text", ["我叫小林", "我下周三要去北京面试", "我最近在学吉他", "我打算明年换工作"])
def test_gate_passes_informative_messages(text):
    assert should_extract_memory(text)


@pytest.mark.parametrize(
    "text",
    ["哈哈好的", "今天好累啊真的好累好累啊", "我想你了", "我要睡觉了晚安", "你觉得这首歌怎么样呀"],
)
def test_gate_skips_chit_chat(text):
    assert not should_extract_memory(text)


# --- LLM extraction ---


def test_empty_llm_result_is_respected():
    client = FakeClient(reply='{"memories": []}')
    assert extract_memories_with_llm(client, "我喜欢吃寿司，今天天气不错", "好呀") == []


def test_llm_memories_are_parsed_clipped_and_capped():
    items = [{"summary": f"事实{i}" + "很长" * 20, "category": "plan"} for i in range(5)]
    client = FakeClient(reply=json.dumps({"memories": items}, ensure_ascii=False))
    memories = extract_memories_with_llm(client, "我叫小林", "你好小林")
    assert len(memories) == 3
    assert all(item["source"] == "llm" and len(item["summary"]) <= 28 for item in memories)


def test_bare_list_reply_is_accepted():
    client = FakeClient(reply='```json\n[{"summary": "用户叫小林", "category": "identity"}]\n```')
    assert extract_memories_with_llm(client, "我叫小林", "你好")[0]["summary"] == "用户叫小林"


def test_request_failure_falls_back_to_heuristics():
    client = FakeClient(error=RuntimeError("HTTP 500"))
    memories = extract_memories_with_llm(client, "我叫小林", "你好")
    assert [item["source"] for item in memories] == ["heuristic"]


def test_unparseable_reply_falls_back_to_heuristics():
    client = FakeClient(reply="抱歉我不能输出 JSON")
    memories = extract_memories_with_llm(client, "我叫小林", "你好")
    assert memories[0]["summary"] == "用户名字：小林"


def test_without_api_key_uses_heuristics_and_skips_request():
    client = FakeClient(reply='{"memories": []}', api_key="")
    assert extract_memories_with_llm(client, "我叫小林", "你好")[0]["source"] == "heuristic"
    assert client.calls == []


def test_extraction_uses_background_retry_delays():
    client = FakeClient(reply='{"memories": []}')
    extract_memories_with_llm(client, "我叫小林", "你好")
    assert client.calls[0]["retry_delays"] == main.MEMORY_RETRY_DELAYS


JSON_MODE = {"response_format": {"type": "json_object"}}
THINKING_OFF = {"thinking": {"type": "disabled"}}
LOW_TEMPERATURE = {"temperature": main.MEMORY_EXTRACTION_TEMPERATURE}


def test_moonshot_extraction_disables_thinking_without_temperature():
    assert extraction_request_options("https://api.moonshot.ai/v1") == {**JSON_MODE, **THINKING_OFF}


def test_deepseek_extraction_disables_thinking_with_low_temperature():
    assert extraction_request_options("https://api.deepseek.com/v1") == {**JSON_MODE, **THINKING_OFF, **LOW_TEMPERATURE}


def test_other_providers_get_json_mode_and_low_temperature():
    assert extraction_request_options("https://api.openai.com/v1") == {**JSON_MODE, **LOW_TEMPERATURE}


# --- client retries ---


def http_error(code, body):
    return urllib.error.HTTPError("https://x/chat/completions", code, "err", {}, io.BytesIO(body.encode()))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def ok_response(content):
    return FakeResponse(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def make_client():
    config = AppConfig()
    config.api_key = "key"
    return OpenAICompatibleClient(config)


def test_rate_limit_is_retried_with_given_delays(monkeypatch):
    responses = [http_error(429, '{"error":{"type":"rate_limit_reached_error"}}'), ok_response("你好")]
    sleeps = []

    def fake_urlopen(request, timeout):
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(main.time, "sleep", sleeps.append)
    assert make_client().complete([{"role": "user", "content": "hi"}], retry_delays=(10, 25)) == "你好"
    assert sleeps == [10]


def test_rate_limit_error_message_after_retries(monkeypatch):
    def fake_urlopen(request, timeout):
        raise http_error(429, '{"error":{"type":"rate_limit_reached_error"}}')

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(main.time, "sleep", lambda seconds: None)
    with pytest.raises(RuntimeError, match="限流"):
        make_client().complete([{"role": "user", "content": "hi"}], retry_delays=(1,))


def test_complete_sends_extra_options(monkeypatch):
    sent = {}

    def fake_urlopen(request, timeout):
        sent.update(json.loads(request.data))
        return ok_response("{}")

    monkeypatch.setattr(main.urllib.request, "urlopen", fake_urlopen)
    make_client().complete([{"role": "user", "content": "hi"}], extra={"response_format": {"type": "json_object"}})
    assert sent["response_format"] == {"type": "json_object"}
    assert "temperature" not in sent
