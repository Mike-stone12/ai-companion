"""Merge flat OpenAI-style streamed tool-call fragments without dependencies."""

from collections.abc import Iterable


def merge_tool_call_deltas(fragments: Iterable[object]) -> list[dict]:
    """Return complete wire-format calls sorted by their integer index.

    Missing or non-integer indexes (including booleans) use zero. Non-dict
    entries and malformed function objects are ignored; only string IDs,
    names, and arguments are used. The first non-empty ID, name, and type
    win, so repeated full names are never appended. Type defaults to
    ``function`` and missing IDs become ``call_{index}``. Nameless calls
    are dropped, and the input is never mutated.

    Arguments are concatenated verbatim without JSON parsing. Empty arguments
    remain empty because followup.execute_tool_call already accepts them as
    an empty object. The returned dicts match followup's assistant message
    shape; execution uses its ToolCall dataclass with the same ID/name/arguments.
    """
    calls: dict[int, dict] = {}
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        index = fragment.get("index", 0)
        if not isinstance(index, int) or isinstance(index, bool):
            index = 0
        call = calls.setdefault(index, {"id": "", "type": "", "name": "", "arguments": []})
        for field in ("id", "type"):
            value = fragment.get(field)
            if not call[field] and isinstance(value, str) and value:
                call[field] = value
        function = fragment.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not call["name"] and isinstance(name, str) and name:
            call["name"] = name
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            call["arguments"].append(arguments)

    return [
        {
            "id": call["id"] or f"call_{index}",
            "type": call["type"] or "function",
            "function": {"name": call["name"], "arguments": "".join(call["arguments"])},
        }
        for index, call in sorted(calls.items())
        if call["name"]
    ]
