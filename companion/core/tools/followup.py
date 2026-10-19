"""Build follow-up conversation messages from complete function tool calls."""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from .registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str


def assistant_tool_call_message(tool_calls: Iterable[ToolCall], content: str | None = None) -> dict:
    """Preserve the assistant's content and ordered, raw function arguments."""
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in tool_calls
        ],
    }


def execute_tool_call(registry: ToolRegistry, call: ToolCall) -> str:
    """Invoke a complete call, returning tool content or a JSON error object."""
    try:
        arguments = json.loads(call.arguments if call.arguments != "" else "{}")
    except (ValueError, TypeError, RecursionError):
        return json.dumps({"error": "Invalid JSON arguments"})
    if not isinstance(arguments, dict):
        return json.dumps({"error": "Arguments must be a JSON object"})

    try:
        result = registry.execute(call.name, arguments)
        if not result.ok:
            # The registry wraps exceptions as failed results. Log failures
            # without argument values, arbitrary exception text, or tracebacks.
            logger.warning("Tool call failed")
            return json.dumps({"error": result.content}, ensure_ascii=False)
        # The registry already serializes non-string tool return values.
        return result.content if isinstance(result.content, str) else json.dumps(result.content, ensure_ascii=False)
    except Exception:
        logger.warning("Tool execution failed")
        return json.dumps({"error": "Tool execution failed"})


def tool_result_messages(registry: ToolRegistry, tool_calls: Iterable[ToolCall]) -> list[dict]:
    """Execute calls in order and associate each result with its call ID."""
    return [
        {"role": "tool", "tool_call_id": call.id, "content": execute_tool_call(registry, call)}
        for call in tool_calls
    ]
