from copy import deepcopy

import pytest

from companion.core.tools.followup import ToolCall, assistant_tool_call_message, execute_tool_call
from companion.core.tools.registry import ToolRegistry
from companion.core.tools.stream_merge import merge_tool_call_deltas


@pytest.fixture
def registry():
    registry = ToolRegistry()

    @registry.tool
    def echo(value: str = "default"):
        return value

    return registry


def test_single_call_split_with_id_and_name_only_in_first_fragment():
    fragments = [
        {"index": 0, "id": "one", "type": "function", "function": {"name": "echo", "arguments": '{"val'}},
        {"index": 0, "function": {"arguments": 'ue": "hel'}},
        {"index": 0, "function": {"arguments": 'lo"}'}},
    ]
    original = deepcopy(fragments)
    assert merge_tool_call_deltas(iter(fragments)) == [
        {"id": "one", "type": "function", "function": {"name": "echo", "arguments": '{"value": "hello"}'}}
    ]
    assert fragments == original


def test_interleaved_calls_are_sorted_by_index():
    fragments = [
        {"index": 7, "id": "second", "function": {"name": "echo", "arguments": '{"value":'}},
        {"index": 2, "id": "first", "function": {"name": "other", "arguments": "["}},
        {"index": 7, "function": {"arguments": '"two"}'}},
        {"index": 2, "function": {"arguments": "]"}},
    ]
    assert merge_tool_call_deltas(fragments) == [
        {"id": "first", "type": "function", "function": {"name": "other", "arguments": "[]"}},
        {"id": "second", "type": "function", "function": {"name": "echo", "arguments": '{"value":"two"}'}},
    ]


def test_missing_index_uses_zero():
    assert merge_tool_call_deltas([
        {"function": {"name": "echo", "arguments": "a"}},
        {"index": 0, "function": {"arguments": "b"}},
    ]) == [{"id": "call_0", "type": "function", "function": {"name": "echo", "arguments": "ab"}}]


@pytest.mark.parametrize("index", [None, "2", 2.0, [], {}, True, False])
def test_non_integer_index_uses_zero(index):
    assert merge_tool_call_deltas([
        {"index": index, "function": {"name": "echo", "arguments": "a"}},
        {"index": 0, "function": {"arguments": "b"}},
    ]) == [{"id": "call_0", "type": "function", "function": {"name": "echo", "arguments": "ab"}}]


def test_empty_input():
    assert merge_tool_call_deltas([]) == []


def test_malformed_entries_and_fields_are_ignored():
    assert merge_tool_call_deltas([
        None, 1, "fragment", [],
        {}, {"function": None}, {"function": []}, {"function": "echo"},
        {"id": 12, "type": [], "function": {"name": False, "arguments": {}}},
        {"function": {"name": "echo", "arguments": "a"}},
        {"id": [], "function": {"name": {}, "arguments": 42}},
        {"function": {"arguments": "b"}},
    ]) == [{"id": "call_0", "type": "function", "function": {"name": "echo", "arguments": "ab"}}]


def test_nameless_calls_are_dropped():
    assert merge_tool_call_deltas([
        {"index": 1, "id": "one", "function": {"arguments": "{}"}},
        {"index": 2, "function": {"name": ""}},
        {"index": 3, "function": {"name": None}},
    ]) == []


def test_first_nonempty_id_and_name_win():
    assert merge_tool_call_deltas([
        {"id": "", "function": {"name": "", "arguments": "a"}},
        {"id": "one", "function": {"name": "echo", "arguments": "b"}},
        {"id": "two", "function": {"name": "echo", "arguments": "c"}},
        {"function": {"name": "other", "arguments": "d"}},
    ]) == [{"id": "one", "type": "function", "function": {"name": "echo", "arguments": "abcd"}}]


def test_arguments_are_concatenated_verbatim_even_when_invalid_json():
    parts = [' \n{"value":', ' "hi\\n', '\t世界"', " trailing garbage "]
    merged = merge_tool_call_deltas(
        {"function": {"name": "echo", "arguments": part}} for part in parts
    )
    assert merged[0]["function"]["arguments"] == "".join(parts)


def test_empty_arguments_and_deterministic_fallback_id():
    fragments = [{"index": -2, "function": {"name": "echo"}}]
    expected = [{"id": "call_-2", "type": "function", "function": {"name": "echo", "arguments": ""}}]
    assert merge_tool_call_deltas(fragments) == expected
    assert merge_tool_call_deltas(fragments) == expected


@pytest.mark.parametrize("parts, expected", [(['{"value":', '"hello"}'], "hello"), ([""], "default")])
def test_merged_call_executes_through_followup(registry, parts, expected):
    merged = merge_tool_call_deltas(
        {"id": "one", "function": {"name": "echo", "arguments": part}} for part in parts
    )
    # The executor accepts ToolCall; the assistant message uses the wire dict shape.
    call = ToolCall(id=merged[0]["id"], **merged[0]["function"])
    assert assistant_tool_call_message([call])["tool_calls"] == merged
    assert execute_tool_call(registry, call) == expected
