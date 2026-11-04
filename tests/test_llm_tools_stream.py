import io
import json

import pytest

from companion.core.config import AppConfig
from companion.core.llm import client as llm_client
from companion.core.llm.client import OpenAICompatibleClient
from companion.core.tools.loop import run_tool_rounds
from companion.core.tools.registry import ToolRegistry
from companion.core.tools.stream_merge import merge_tool_call_deltas

MESSAGES = [{"role": "user", "content": "Say hello"}]
TOOLS = [{"type": "function", "function": {"name": "greet", "parameters": {"type": "object"}}}]
FRAGMENTS = [
    {"index": 0, "id": "call_greet", "type": "function",
     "function": {"name": "greet", "arguments": '{"name":'}},
    {"index": 0, "function": {"arguments": '"Ada'}},
    {"index": 0, "function": {"arguments": '"}'}},
]


def chunk(delta=None, finish_reason=None):
    return {"choices": [{"delta": delta or {}, "finish_reason": finish_reason}]}


def sse_lines(events):
    for event in events:
        yield f"data: {json.dumps(event)}\n".encode()
        yield b"\n"
    yield b"data: [DONE]\n"
    yield b"\n"


def tool_round():
    return [*(chunk({"tool_calls": [fragment]}) for fragment in FRAGMENTS),
            chunk(finish_reason="tool_calls")]


@pytest.fixture
def client():
    config = AppConfig()
    config.api_key = "key"
    config.base_url = "https://api.deepseek.com/v1"
    config.chat_thinking = False
    return OpenAICompatibleClient(config)


def fake_transport(monkeypatch, *rounds):
    responses = iter(rounds)
    bodies = []

    def urlopen(request, timeout):
        bodies.append(request.data)
        return io.BytesIO(b"".join(sse_lines(next(responses))))

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", urlopen)
    return bodies


@pytest.mark.parametrize("options", [{}, {"tools": None}, {"tools": []},
                                     {"tools": None, "tool_choice": "auto"},
                                     {"tools": [], "tool_choice": "auto"}])
def test_no_tools_preserves_request_bytes_and_text(monkeypatch, client, options):
    events = [chunk({"reasoning_content": "thinking"}), chunk({"content": "[happy] Hello"}),
              chunk(finish_reason="stop")]
    bodies = fake_transport(monkeypatch, events)
    assert list(client.stream_chat(MESSAGES, **options)) == ["[happy] Hello"]
    assert bodies == [json.dumps({
        "model": client.config.model, "messages": MESSAGES, "stream": True,
        "thinking": {"type": "disabled"},
    }).encode("utf-8")]


@pytest.mark.parametrize("choice", [None, "auto", {"type": "function", "function": {"name": "greet"}}])
def test_tools_and_optional_choice_are_sent(monkeypatch, client, choice):
    bodies = fake_transport(monkeypatch, [chunk(finish_reason="stop")])
    list(client.stream_chat(MESSAGES, tools=TOOLS, tool_choice=choice))
    body = json.loads(bodies[0])
    assert body["tools"] == TOOLS
    if choice is None:
        assert "tool_choice" not in body
    else:
        assert body["tool_choice"] == choice


def test_tool_fragments_and_finish_reason_preserved_and_merge(monkeypatch, client):
    events = tool_round()
    fake_transport(monkeypatch, events)
    received = list(client.stream_chat(MESSAGES, tools=TOOLS))
    assert received == events
    fragments = [fragment for event in received
                 for fragment in event["choices"][0]["delta"].get("tool_calls", [])]
    assert fragments == FRAGMENTS
    calls = merge_tool_call_deltas(fragments)
    assert calls == [{"id": "call_greet", "type": "function",
                      "function": {"name": "greet", "arguments": '{"name":"Ada"}'}}]
    assert json.loads(calls[0]["function"]["arguments"]) == {"name": "Ada"}
    assert received[-1]["choices"][0]["finish_reason"] == "tool_calls"


def test_mixed_text_and_tool_calls_preserve_order(monkeypatch, client):
    events = [chunk({"content": "[happy] I'll check."}), *tool_round()]
    fake_transport(monkeypatch, events)
    assert list(client.stream_chat(MESSAGES, tools=TOOLS)) == events


def test_chunk_adapter_keeps_chunk_shape_with_empty_tools(monkeypatch, client):
    events = [chunk({"content": "Hello"}), chunk(finish_reason="stop")]
    bodies = fake_transport(monkeypatch, events)
    assert list(client.stream_chat_chunks(MESSAGES, [])) == events
    assert "tools" not in json.loads(bodies[0])


class TimedResponse:
    def __init__(self, clock, events, gap):
        self.clock = clock
        self.events = events
        self.gap = gap

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def __iter__(self):
        for line in sse_lines(self.events):
            if line.startswith(b"data:"):
                self.clock[0] += self.gap
            yield line


def timed_transport(monkeypatch, events, gap):
    now = [0.0]
    # Patch the parser boundary to supply a deterministic clock without real waits.
    parser = llm_client.iter_chat_chunks
    monkeypatch.setattr(llm_client, "iter_chat_chunks",
                        lambda lines, **kw: parser(lines, clock=lambda: now[0], **kw))
    monkeypatch.setattr(llm_client.urllib.request, "urlopen",
                        lambda request, timeout: TimedResponse(now, events, gap))


def test_tool_only_stream_counts_as_content_for_both_deadlines(monkeypatch, client):
    # 60 seconds total exceeds both deadlines, but each tool fragment arrives in time.
    events = tool_round()
    timed_transport(monkeypatch, events, gap=12)
    assert list(client.stream_chat(MESSAGES, tools=TOOLS)) == events


def test_tool_stream_still_enforces_idle_deadline(monkeypatch, client):
    events = tool_round()
    timed_transport(monkeypatch, events, gap=16)
    monkeypatch.setattr(llm_client, "STREAM_IDLE_TIMEOUT_S", 15)
    stream = client.stream_chat(MESSAGES, tools=TOOLS)
    assert next(stream) == events[0]
    with pytest.raises(RuntimeError, match="15"):
        next(stream)


def test_tool_stream_propagates_sse_error(monkeypatch, client):
    fake_transport(monkeypatch, [{"error": {"message": "overloaded"}}])
    with pytest.raises(RuntimeError, match="overloaded"):
        list(client.stream_chat(MESSAGES, tools=TOOLS))


def test_orchestrator_runs_tool_and_text_rounds_through_client(monkeypatch, client):
    registry = ToolRegistry()
    executed = []

    @registry.tool
    def greet(name: str) -> str:
        executed.append(name)
        return f"Hello, {name}!"

    bodies = fake_transport(monkeypatch, tool_round(),
                            [chunk({"content": "Hello, "}), chunk({"content": "Ada!"}),
                             chunk(finish_reason="stop")])
    text = []
    result = run_tool_rounds(MESSAGES, registry, client.stream_chat_chunks, on_text=text.append)
    assert result.final_text == "Hello, Ada!"
    assert result.rounds == 2
    assert not result.stopped_by_max_rounds
    assert executed == ["Ada"]
    assert text == ["Hello, ", "Ada!"]
    assert result.added_messages[0]["tool_calls"][0]["id"] == "call_greet"
    assert result.added_messages[1] == {
        "role": "tool", "tool_call_id": "call_greet", "content": "Hello, Ada!",
    }
    first, second = map(json.loads, bodies)
    assert first["messages"] == MESSAGES
    assert second["messages"] == MESSAGES + result.added_messages[:2]
    assert first["tools"] == second["tools"] == registry.schemas()
