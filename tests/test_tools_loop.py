import json
from copy import deepcopy

import pytest

from companion.core.tools.loop import run_tool_rounds
from companion.core.tools.registry import ToolRegistry


def chunk(delta=None, finish_reason=None):
    return {"choices": [{"delta": delta or {}, "finish_reason": finish_reason}]}


def call_fragment(name="echo", arguments="{}", *, index=0, call_id="one"):
    return {"index": index, "id": call_id, "function": {"name": name, "arguments": arguments}}


def scripted_stream(rounds, requests):
    scripts = iter(rounds)

    def stream_round(messages, tools):
        requests.append((deepcopy(messages), deepcopy(tools)))
        return iter(next(scripts))

    return stream_round


@pytest.fixture
def registry():
    registry = ToolRegistry()
    calls = []

    @registry.tool
    def echo(value: str = "default"):
        calls.append(value)
        return value

    return registry, calls


def test_plain_text_streams_each_delta_as_it_arrives(registry):
    registry, calls = registry
    messages = [{"role": "user", "content": "Hello"}]
    received = []

    def stream_round(working_messages, tools):
        assert working_messages == messages
        assert working_messages is not messages
        assert tools == registry.schemas()
        yield {}
        yield {"choices": []}
        yield {"choices": None}
        yield chunk({"role": "assistant", "content": None})
        for index, text in enumerate(["Hi", "", " there"]):
            yield chunk({"content": text})
            assert received == ["Hi", "", " there"][:index + 1]
        yield chunk(finish_reason="stop")

    result = run_tool_rounds(messages, registry, stream_round, on_text=received.append)

    assert result.final_text == "Hi there"
    assert result.added_messages == [{"role": "assistant", "content": "Hi there"}]
    assert result.rounds == 1
    assert not result.stopped_by_max_rounds
    assert calls == []


def test_fragmented_call_then_final_reply(registry):
    registry, calls = registry
    messages = [{"role": "user", "content": "Echo hello"}]
    requests = []
    received = []
    stream = scripted_stream([
        [
            chunk({"content": "Checking.", "tool_calls": [call_fragment(arguments='{"val')]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'ue": "hel'}}]}),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'lo"}'}}]}),
            chunk(finish_reason="tool_calls"),
        ],
        [chunk({"content": "All "}), chunk({"content": "done."}), chunk(finish_reason="stop")],
    ], requests)

    result = run_tool_rounds(messages, registry, stream, on_text=received.append)

    followup = [
        {
            "role": "assistant", "content": "Checking.",
            "tool_calls": [{
                "id": "one", "type": "function",
                "function": {"name": "echo", "arguments": '{"value": "hello"}'},
            }],
        },
        {"role": "tool", "tool_call_id": "one", "content": "hello"},
    ]
    assert calls == ["hello"]
    assert requests == [(messages, registry.schemas()), (messages + followup, registry.schemas())]
    assert received == ["Checking.", "All ", "done."]
    assert result.final_text == "All done."
    assert result.added_messages == followup + [{"role": "assistant", "content": "All done."}]
    assert result.rounds == 2
    assert not result.stopped_by_max_rounds


def test_two_parallel_calls_keep_ids_and_merge_independently(registry):
    registry, calls = registry
    requests = []
    stream = scripted_stream([
        [
            chunk({"tool_calls": [
                call_fragment(arguments='{"value":', index=1, call_id="two"),
                call_fragment(arguments='{"value":', index=0, call_id="one"),
            ]}),
            chunk({"tool_calls": [
                {"index": 0, "function": {"arguments": '"first"}'}},
                {"index": 1, "function": {"arguments": '"second"}'}},
            ]}, "tool_calls"),
        ],
        [chunk({"content": "Finished"})],
    ], requests)

    result = run_tool_rounds([], registry, stream)

    assert calls == ["first", "second"]
    assert requests[1][0][0]["content"] is None
    assert [call["id"] for call in requests[1][0][0]["tool_calls"]] == ["one", "two"]
    assert requests[1][0][1:] == [
        {"role": "tool", "tool_call_id": "one", "content": "first"},
        {"role": "tool", "tool_call_id": "two", "content": "second"},
    ]
    assert result.added_messages[:-1] == requests[1][0]
    assert result.final_text == "Finished"
    assert result.rounds == 2


@pytest.mark.parametrize("max_rounds", [1, 3])
def test_limit_stops_before_executing_last_round_calls(registry, max_rounds):
    registry, calls = registry
    requests = []

    def stream_round(messages, tools):
        requests.append(deepcopy(messages))
        return [chunk({"content": "Again", "tool_calls": [call_fragment()]}, "tool_calls")]

    result = run_tool_rounds([], registry, stream_round, max_rounds=max_rounds)

    assert len(requests) == result.rounds == max_rounds
    assert calls == ["default"] * (max_rounds - 1)
    assert result.stopped_by_max_rounds
    assert result.final_text == "Again"
    assert len(result.added_messages) == 2 * max_rounds - 1
    assert result.added_messages[-1]["tool_calls"][0]["function"]["name"] == "echo"
    assert result.added_messages[-1]["role"] == "assistant"


def test_plain_reply_on_last_allowed_round_is_not_limit_stop(registry):
    registry, calls = registry
    requests = []
    stream = scripted_stream([
        [chunk({"tool_calls": [call_fragment()]})],
        [chunk({"content": "Done"})],
    ], requests)

    result = run_tool_rounds([], registry, stream, max_rounds=2)

    assert result.rounds == 2
    assert not result.stopped_by_max_rounds
    assert result.final_text == "Done"
    assert calls == ["default"]


@pytest.mark.parametrize("name, error", [
    ("missing", "Unknown tool"),
    ("failing", "Tool execution failed (RuntimeError)"),
])
def test_tool_errors_are_sent_to_next_round(registry, name, error):
    registry, _ = registry

    @registry.tool
    def failing():
        raise RuntimeError("private details")

    requests = []
    stream = scripted_stream([
        [chunk({"tool_calls": [call_fragment(name)]})],
        [chunk({"content": "Could not complete the tool."})],
    ], requests)

    result = run_tool_rounds([], registry, stream)

    tool_message = requests[1][0][1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "one"
    assert json.loads(tool_message["content"]) == {"error": error}
    assert result.final_text == "Could not complete the tool."
    assert not result.stopped_by_max_rounds


def test_caller_messages_are_unchanged(registry):
    registry, _ = registry
    messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
    original = deepcopy(messages)
    requests = []
    stream = scripted_stream([
        [chunk({"tool_calls": [call_fragment()]})],
        [chunk({"content": "Done"})],
    ], requests)

    result = run_tool_rounds(messages, registry, stream)

    assert messages == original
    assert len(requests[1][0]) == len(original) + 2
    assert len(result.added_messages) == 3


def test_empty_stream_returns_empty_assistant_text(registry):
    registry, _ = registry
    result = run_tool_rounds([], registry, lambda messages, tools: iter([]))
    assert result.final_text == ""
    assert result.added_messages == [{"role": "assistant", "content": ""}]
    assert result.rounds == 1
    assert not result.stopped_by_max_rounds


@pytest.mark.parametrize("max_rounds, error", [
    (0, ValueError), (-1, ValueError), (1.5, TypeError), (True, TypeError),
])
def test_invalid_round_limit_is_rejected_before_streaming(registry, max_rounds, error):
    registry, _ = registry

    def stream_round(messages, tools):
        pytest.fail("Invalid limits must not start a stream")

    with pytest.raises(error, match="max_rounds"):
        run_tool_rounds([], registry, stream_round, max_rounds=max_rounds)
