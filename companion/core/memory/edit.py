"""Display and edit in-memory MemoryStore entries without persistence."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from companion.core.memory.store import MemoryStore, clip_memory_text, utc_now_iso


@dataclass(frozen=True)
class MemoryRow:
    index: int
    summary: str
    timestamp: str
    category: str
    source: str


class DuplicateMemoryError(ValueError):
    """The edited summary exactly matches another entry's summary."""


def load_memory_entries(path: Path) -> list[dict[str, str]]:
    """Read complete stored entries without cleanup, clipping, or a store limit."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("summary"), str) for entry in entries
    ):
        raise ValueError("expected a JSON list of memory objects with string summaries")
    return entries


def save_memory_edits(
    path: Path, entries: list[dict[str, str]], *, store: MemoryStore | None = None,
) -> Path:
    """Back up the original file, then atomically save all validated entries.

    Bypass load's cleanup and the usual store limit to preserve raw metadata and
    stored indices. Restore an injected store's state if persistence fails.
    """
    if store is None:
        store = MemoryStore(path, limit=len(entries))
    backup = path.with_name("memory.json.bak")
    old_items, old_limit = store.items, store.limit
    try:
        shutil.copyfile(path, backup)
        store.items = entries
        store.limit = len(entries)
        store.save()
    except Exception:
        store.items, store.limit = old_items, old_limit
        raise
    store.limit = old_limit
    return backup


def filter_memory_rows(rows: list[MemoryRow], query: str) -> list[MemoryRow]:
    """Match summaries by case-insensitive substring, retaining display order."""
    return [row for row in rows if query.casefold() in row.summary.casefold()]


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
