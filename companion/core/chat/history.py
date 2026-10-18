"""Persisted conversation history, restored on the next start."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from companion.core.chat.emotion import EmotionTagParser
from companion.core.memory.store import utc_now_iso

logger = logging.getLogger(__name__)

ROLES = ("user", "assistant")
MAX_HISTORY_ENTRIES = 200


@dataclass(frozen=True)
class ConversationSummary:
    """Summary text and the covered prefix of valid history entries.

    summarized_count uses the individual-message cursor from summary.py's
    plan_summary_update. Text can also cover older turns no longer on disk.
    """

    text: str
    summarized_count: int


class ConversationHistory:
    """User and assistant turns as sent to the model (replies keep their emotion tag).

    Assign summary after a successful summary update, then call save(). On disk,
    an optional {"summary": {"text": ..., "summarized_count": ...}} entry follows
    the turns. It has no role, so legacy loaders skip it and retain every turn.
    Files without a summary keep the original list-of-turns format.
    """

    def __init__(self, path: Path, max_entries: int = MAX_HISTORY_ENTRIES) -> None:
        self.path = path
        self.max_entries = max_entries
        self.entries: list[dict[str, str]] = []
        self.summary: ConversationSummary | None = None
        self.load()

    def load(self) -> None:
        self.entries = []
        self.summary = None
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read conversation history %s: %s", self.path, exc)
            return
        if not isinstance(data, list):
            return
        summaries = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if "summary" in item and "role" not in item:
                summaries.append(item["summary"])
                continue
            role, content = item.get("role"), item.get("content")
            if role in ROLES and isinstance(content, str) and content:
                self.entries.append({"role": role, "content": content, "at": str(item.get("at") or "")})
        if summaries:
            record = summaries[0]
            if (
                len(summaries) == 1
                and isinstance(record, dict)
                and isinstance(record.get("text"), str)
                and type(record.get("summarized_count")) is int
                and 0 <= record["summarized_count"] <= len(self.entries)
            ):
                self.summary = ConversationSummary(record["text"], record["summarized_count"])
            else:
                logger.warning("Ignoring malformed conversation summary in %s", self.path)
        self._trim_entries()

    def _trim_entries(self) -> None:
        """Keep summary text while subtracting dropped turns from its cursor.

        Once all covered turns have been dropped, the cursor stays at zero:
        the summary still provides older context without skipping new turns.
        """
        previous_length = len(self.entries)
        self.entries = self.entries[-self.max_entries :]
        if self.summary is not None:
            dropped = previous_length - len(self.entries)
            covered = min(self.summary.summarized_count, previous_length)
            self.summary = ConversationSummary(self.summary.text, max(0, covered - dropped))

    def append(self, role: str, content: str) -> None:
        self.entries.append({"role": role, "content": content, "at": utc_now_iso()})
        self.save()

    def clear(self) -> None:
        self.entries = []
        self.summary = None
        self.save()

    def messages(self) -> list[dict[str, str]]:
        return [{"role": entry["role"], "content": entry["content"]} for entry in self.entries]

    def save(self) -> None:
        self._trim_entries()
        # Write to a temp file in the same directory and swap it in, so a crash mid-write
        # never leaves a truncated history behind.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = list(self.entries)
        if self.summary is not None:
            data.append({"summary": {
                "text": self.summary.text,
                "summarized_count": self.summary.summarized_count,
            }})
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".history-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temp_name, self.path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise


def display_text(entry: dict[str, str]) -> str:
    """Text to show for a stored turn: replies lose their leading emotion tag."""
    if entry.get("role") != "assistant":
        return entry.get("content", "")
    parser = EmotionTagParser()
    return (parser.feed(entry.get("content", "")) + parser.flush()).strip()
