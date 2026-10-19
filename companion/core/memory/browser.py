"""A GUI-independent browser and staged editor for stored memories."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from companion.core.memory.edit import (
    MemoryRow,
    edit_memory,
    filter_memory_rows,
    load_memory_entries,
    memory_rows,
    save_memory_edits,
)
from companion.core.memory.store import MemoryStore


@dataclass(frozen=True, slots=True)
class EditPreview:
    index: int
    old_summary: str
    new_summary: str


class MemoryBrowserModel:
    """Stage summary edits using stable 1-based indices into stored order.

    Rows and filtering describe saved entries until save succeeds. Previews
    describe pending edits; validation includes other pending summaries. Invalid
    edits raise ValueError, remove earlier pending edits for that index, and
    block saving until corrected or discarded. I/O errors propagate and retain
    pending edits. Supply either a data directory or an already loaded store.
    With an injected store, rows and indices reflect its loaded (normalized and
    limited) items. Saving refuses to overwrite subsequent store changes.
    """

    def __init__(
        self, data_dir: Path | None = None, *, store: MemoryStore | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        if (data_dir is None) == (store is None):
            raise ValueError("provide either a data directory or a store")
        self._store = store
        self._now = now
        if store is not None:
            self.path = store.path
            self._entries = [dict(entry) for entry in store.items]
            self._baseline = [dict(entry) for entry in store.items]
        else:
            self.path = Path(data_dir) / "memory.json"
            try:
                self._entries = load_memory_entries(self.path)
            except FileNotFoundError:
                self._entries = []
        self._pending: dict[int, str] = {}
        self._errors: dict[int, str] = {}

    @property
    def rows(self) -> list[MemoryRow]:
        """Return immutable rows newest first, with CLI-compatible 1-based indices."""
        return [replace(row, index=row.index + 1) for row in memory_rows(self._entries)]

    def filter(self, query: str) -> list[MemoryRow]:
        return filter_memory_rows(self.rows, query)

    @property
    def errors(self) -> dict[int, str]:
        return self._errors.copy()

    @property
    def has_pending_changes(self) -> bool:
        return bool(self._pending)

    def _pending_entries(self) -> list[dict[str, str]]:
        entries = [dict(entry) for entry in self._entries]
        for index, summary in self._pending.items():
            entries[index - 1]["summary"] = summary
        return entries

    def stage_edit(self, index: int, new_text: str) -> EditPreview:
        """Return the saved and normalized summaries, or raise a validation error.

        Staging never writes or reads the clock. A normalized no-op removes any
        earlier pending edit for the same index.
        """
        offset = index - 1 if type(index) is int else index
        try:
            edited = edit_memory(self._pending_entries(), offset, new_text, now=lambda: "")
        except ValueError as exc:
            self._pending.pop(index, None)
            self._errors[index] = str(exc)
            raise
        self._errors.pop(index, None)
        old = self._entries[offset]["summary"]
        new = edited[offset]["summary"]
        if new == old:
            self._pending.pop(index, None)
        else:
            self._pending[index] = new
        return EditPreview(index, old, new)

    def discard(self) -> None:
        """Clear pending edits and validation errors without writing."""
        self._pending.clear()
        self._errors.clear()

    def save(self) -> str:
        """Validate the entire batch before backing up and atomically saving it.

        Compare each edit with its saved summary while checking duplicates
        against the final batch. This also permits reuse of a summary vacated
        by another pending edit, independent of staging order.
        """
        if self._errors:
            raise ValueError("Cannot save memories while validation errors exist")
        if not self._pending:
            return "No changes to save."
        if self._store is not None and [dict(entry) for entry in self._store.items] != self._baseline:
            raise ValueError("Memories changed since they were loaded; reload before saving")
        entries = self._pending_entries()
        for index, summary in self._pending.items():
            # Restore only the target's original value for change detection;
            # all other summaries reflect the final batch for duplicate checks.
            entries[index - 1] = dict(self._entries[index - 1])
            entries = edit_memory(entries, index - 1, summary, now=self._now)
        backup = save_memory_edits(self.path, entries, store=self._store)
        count = len(self._pending)
        self._entries = [dict(entry) for entry in entries]
        self._baseline = [dict(entry) for entry in entries]
        self.discard()
        noun = "memory" if count == 1 else "memories"
        return f"Saved {count} {noun}. Backup: {backup}"
