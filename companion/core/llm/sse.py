"""Parse OpenAI-compatible server-sent event streams."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Iterator

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


def iter_content_deltas(
    lines: Iterable[bytes | str],
    *,
    first_content_timeout: float | None = None,
    idle_timeout: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[str]:
    """Yield `choices[].delta.content` text until `[DONE]`; reasoning deltas are skipped."""
    for event in iter_chat_chunks(
        lines, first_content_timeout=first_content_timeout, idle_timeout=idle_timeout, clock=clock,
    ):
        for choice in event.get("choices") or []:
            content = (choice.get("delta") or {}).get("content")
            if content:
                yield content


def iter_chat_chunks(
    lines: Iterable[bytes | str],
    *,
    first_content_timeout: float | None = None,
    idle_timeout: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[dict]:
    """Yield OpenAI chunk dicts unchanged until `[DONE]`, including finish reasons.

    An overloaded server can hold the stream open with keep-alive comments and no content,
    which never trips the socket timeout. The deadlines bound the wait for the first piece of
    content and the gap between pieces; they are checked on every incoming line. Text and
    non-empty tool-call deltas count as content; reasoning and finish reasons alone do not.
    """
    started = clock()
    last_content: float | None = None

    def guarded() -> Iterator[bytes | str]:
        for raw in lines:
            now = clock()
            if last_content is None:
                if first_content_timeout is not None and now - started > first_content_timeout:
                    raise RuntimeError(f"模型服务繁忙：{first_content_timeout:g} 秒内没有返回内容，请稍后再试。")
            elif idle_timeout is not None and now - last_content > idle_timeout:
                raise RuntimeError(f"回复中断：{idle_timeout:g} 秒内没有收到新内容。")
            yield raw

    for data in iter_sse_data(guarded()):
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
            delta = choice.get("delta") or {}
            if delta.get("content") or delta.get("tool_calls"):
                last_content = clock()
        yield event
