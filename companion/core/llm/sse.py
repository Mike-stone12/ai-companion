"""Parse OpenAI-compatible server-sent event streams."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator

logger = logging.getLogger(__name__)


def iter_sse_data(lines: Iterable[bytes | str]) -> Iterator[str]:
    """Yield the data payload of each event; multi-line data fields are joined with newlines."""
    data_lines: list[str] = []
    for raw in lines:
        line = (raw.decode("utf-8") if isinstance(raw, bytes) else raw).rstrip("\r\n")
        if not line:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data_lines.append(value[1:] if value.startswith(" ") else value)
    if data_lines:
        yield "\n".join(data_lines)


def iter_content_deltas(lines: Iterable[bytes | str]) -> Iterator[str]:
    """Yield `choices[].delta.content` text until `[DONE]`; reasoning deltas are skipped."""
    for data in iter_sse_data(lines):
        if data.strip() == "[DONE]":
            return
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Skipping unparseable stream event")
            continue
        if not isinstance(event, dict):
            continue
        if "error" in event:
            error = event["error"]
            message = error.get("message", error) if isinstance(error, dict) else error
            raise RuntimeError(f"LLM stream error: {message}")
        for choice in event.get("choices") or []:
            content = (choice.get("delta") or {}).get("content")
            if content:
                yield content
