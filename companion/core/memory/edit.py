"""Display and edit in-memory MemoryStore entries without persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from companion.core.memory.store import clip_memory_text, utc_now_iso


@dataclass(frozen=True)
class MemoryRow:
    index: int
    summary: str
    timestamp: str
    category: str
    source: str


class DuplicateMemoryError(ValueError):
    """The edited summary exactly matches another entry's summary."""


def memory_rows(entries: list[dict[str, str]]) -> list[MemoryRow]:
    """Return immutable display rows retaining indices into the supplied list.

    Use recall's descending updated_at string order, with stable ties. Missing
    or non-string timestamps sort as empty strings. Invalid timestamps display
    as blank; valid ISO timestamps display with a space between date and time,
    retaining their timezone offset when present.
    """
    rows = []
    for index, entry in enumerate(entries):
        timestamp = entry.get("updated_at", "")
        sort_key = timestamp if isinstance(timestamp, str) else ""
        try:
            display_timestamp = datetime.fromisoformat(sort_key).isoformat(sep=" ", timespec="seconds")
        except ValueError:
            display_timestamp = ""
        rows.append(
            (
                sort_key,
                MemoryRow(
                    index=index,
                    summary=entry.get("summary", ""),
                    timestamp=display_timestamp,
                    category=str(entry.get("category", "memory") or "memory"),
                    source=str(entry.get("source", "") or ""),
                ),
            )
        )
    return [row for _, row in sorted(rows, key=lambda item: item[0], reverse=True)]


def edit_memory(
    entries: list[dict[str, str]],
    index: int,
    new_summary: str,
    now: Callable[[], str] | None = None,
) -> list[dict[str, str]]:
    """Return copied entries with one normalized summary and timestamp updated.

    The optional clock follows apply_consolidation: it returns an ISO timestamp
    in the store's UTC format. It is called only for a successful change.
    An unchanged normalized summary preserves the timestamp. Invalid indices
    and empty summaries raise ValueError; exact duplicates of another entry
    raise DuplicateMemoryError. Every returned entry is a new dictionary, and
    list length, order, and all other fields are preserved.
    """
    if type(index) is not int or not 0 <= index < len(entries):
        raise ValueError("memory index is out of range")

    summary = clip_memory_text(str(new_summary).strip())
    if not summary:
        raise ValueError("memory summary must not be empty")

    if any(entry.get("summary") == summary for other_index, entry in enumerate(entries) if other_index != index):
        raise DuplicateMemoryError("another memory already has this summary")

    result = [dict(entry) for entry in entries]
    if summary == entries[index].get("summary"):
        return result

    result[index]["summary"] = summary
    result[index]["updated_at"] = (utc_now_iso if now is None else now)()
    return result
