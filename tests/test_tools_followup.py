import json
import logging
from dataclasses import FrozenInstanceError

import pytest

from companion.core.tools.followup import (
    ToolCall,
    assistant_tool_call_message,
    execute_tool_call,
    tool_result_messages,
)
from companion.core.tools.registry import ToolRegistry


@pytest.fixture
def registry():
    registry = ToolRegistry()

    @registry.tool
    def echo(value: str = "default"):
        return value

    return registry


def test_tool_call_is_frozen():
    call = ToolCall("one", "echo", "{}")
    with pytest.raises(FrozenInstanceError):
        call.name = "changed"


@pytest.mark.parametrize("content", [None, "", "Checking both tools."])
def test_assistant_message_shape_and_order(content):
    calls = [ToolCall("one", "echo", '{"value": "first"}'), ToolCall("two", "other", "{}")]
    expected = {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"id": "one", "type": "function", "function": {"name": "echo", "arguments": '{"value": "first"}'}},
            {"id": "two", "type": "function", "function": {"name": "other", "arguments": "{}"}},
        ],
    }
    assert assistant_tool_call_message(iter(calls), content) == expected
    assert assistant_tool_call_message(calls)["content"] is None


def test_successful_call(registry):
    assert execute_tool_call(registry, ToolCall("one", "echo", '{"value": "hello"}')) == "hello"


@pytest.mark.parametrize("value", [{"text": "你好"}, [1, "你好"], None, True, 42])
def test_non_string_result_is_serialized(registry, value):
    @registry.tool
    def structured():
        return value

    assert execute_tool_call(registry, ToolCall("one", "structured", "{}")) == json.dumps(value, ensure_ascii=False)


def test_empty_arguments_use_defaults(registry):
    assert execute_tool_call(registry, ToolCall("one", "echo", "")) == "default"


@pytest.mark.parametrize("arguments", ["{broken", " ", "[" * 2000 + "]" * 2000])
def test_invalid_json(registry, arguments):
    result = execute_tool_call(registry, ToolCall("one", "echo", arguments))
    assert "json" in json.loads(result)["error"].lower()


@pytest.mark.parametrize("arguments", ["[]", '"text"', "null", "1", "true"])
def test_non_object_arguments(registry, arguments):
    result = execute_tool_call(registry, ToolCall("one", "echo", arguments))
    assert "object" in json.loads(result)["error"].lower()


def test_unknown_tool(registry):
    result = execute_tool_call(registry, ToolCall("one", "missing", "{}"))
    assert "unknown" in json.loads(result)["error"].lower()


def test_empty_arguments_still_validate_required_parameters(registry):
    @registry.tool
    def required(value: str):
        return value

    result = execute_tool_call(registry, ToolCall("one", "required", ""))
    assert "missing" in json.loads(result)["error"].lower()


def test_tool_exception_is_logged_without_argument_values(registry, caplog):
    @registry.tool
    def failing(secret: str):
        raise RuntimeError(secret)

    with caplog.at_level(logging.WARNING, logger="companion.core.tools.followup"):
        result = execute_tool_call(registry, ToolCall("one", "failing", '{"secret": "private-value"}'))
    assert json.loads(result)["error"]
    assert "private-value" not in result + caplog.text
    assert any(record.name == "companion.core.tools.followup" and record.levelno == logging.WARNING
               for record in caplog.records)


def test_result_messages_preserve_ids_order_and_continue_after_error(registry):
    calls = [
        ToolCall("first", "echo", '{"value": "one"}'),
        ToolCall("second", "missing", "{}"),
        ToolCall("third", "echo", '{"value": "three"}'),
    ]
    messages = tool_result_messages(registry, iter(calls))
    assert messages == [
        {"role": "tool", "tool_call_id": "first", "content": "one"},
        {"role": "tool", "tool_call_id": "second", "content": messages[1]["content"]},
        {"role": "tool", "tool_call_id": "third", "content": "three"},
    ]
    assert "unknown" in json.loads(messages[1]["content"])["error"].lower()
