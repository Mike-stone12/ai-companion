"""Run an injected chat stream through bounded, synchronous tool rounds."""

from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass

from .followup import ToolCall, assistant_tool_call_message, tool_result_messages
from .registry import ToolRegistry
from .stream_merge import merge_tool_call_deltas


@dataclass
class ToolLoopResult:
    final_text: str
    added_messages: list[dict]
    rounds: int
    stopped_by_max_rounds: bool


def run_tool_rounds(
    messages: list[dict],
    registry: ToolRegistry,
    stream_round: Callable[[list[dict], list[dict]], Iterable[dict]],
    on_text: Callable[[str], None] | None = None,
    max_rounds: int = 3,
) -> ToolLoopResult:
    """Stream replies, execute requested tools, and send their results back.

    ``max_rounds`` must be a positive integer and counts model requests,
    including the initial request. Calls requested on the last allowed round
    are recorded but never executed. A normal reply on that round is not a
    limit stop.

    ``added_messages`` contains every assistant message and executed tool
    result in order, excluding the input messages. On a limit stop its last
    assistant message has unanswered tool calls. ``final_text`` contains only
    the last round's content; ``on_text`` receives strings from every round
    immediately, including empty strings.

    Input messages are deep-copied. Tool errors become result messages through
    the follow-up helpers; stream and callback exceptions propagate to callers.
    """
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool):
        raise TypeError("max_rounds must be a positive integer")
    if max_rounds < 1:
        raise ValueError("max_rounds must be a positive integer")

    working_messages = deepcopy(messages)
    added_messages = []
    for round_number in range(1, max_rounds + 1):
        text_parts = []
        fragments = []
        for chunk in stream_round(working_messages, registry.schemas()):
            choices = chunk.get("choices")
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if isinstance(content, str):
                text_parts.append(content)
                if on_text is not None:
                    on_text(content)
            fragments.extend(delta.get("tool_calls") or [])

        final_text = "".join(text_parts)
        calls = [
            ToolCall(id=call["id"], **call["function"])
            for call in merge_tool_call_deltas(fragments)
        ]
        if not calls:
            added_messages.append({"role": "assistant", "content": final_text})
            return ToolLoopResult(final_text, added_messages, round_number, False)

        assistant_message = assistant_tool_call_message(calls, content=final_text or None)
        added_messages.append(assistant_message)
        if round_number == max_rounds:
            return ToolLoopResult(final_text, added_messages, round_number, True)

        results = tool_result_messages(registry, calls)
        added_messages.extend(results)
        working_messages.extend([assistant_message, *results])
