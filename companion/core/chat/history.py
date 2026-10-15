"""Persisted conversation history, restored on the next start."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from companion.core.chat.emotion import EmotionTagParser
from companion.core.memory.store import utc_now_iso

logger = logging.getLogger(__name__)

ROLES = ("user", "assistant")
MAX_HISTORY_ENTRIES = 200


class ConversationHistory:
    """User and assistant turns as sent to the model (replies keep their emotion tag)."""

    def __init__(self, path: Path, max_entries: int = MAX_HISTORY_ENTRIES) -> None:
        self.path = path
        self.max_entries = max_entries
        self.entries: list[dict[str, str]] = []
        self.load()

    def load(self) -> None:
        self.entries = []
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to read conversation history %s: %s", self.path, exc)
            return
        if not isinstance(data, list):
            return
        for item in data:
            if not isinstance(item, dict):
                continue
            role, content = item.get("role"), item.get("content")
            if role in ROLES and isinstance(content, str) and content:
                self.entries.append({"role": role, "content": content, "at": str(item.get("at") or "")})
        self.entries = self.entries[-self.max_entries :]

    def append(self, role: str, content: str) -> None:
        self.entries.append({"role": role, "content": content, "at": utc_now_iso()})
        self.entries = self.entries[-self.max_entries :]
        self.save()

    def clear(self) -> None:
        self.entries = []
        self.save()

    def messages(self) -> list[dict[str, str]]:
        return [{"role": entry["role"], "content": entry["content"]} for entry in self.entries]

    def save(self) -> None:
        # Write to a temp file in the same directory and swap it in, so a crash mid-write
        # never leaves a truncated history behind.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.entries, ensure_ascii=False, indent=2)
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
