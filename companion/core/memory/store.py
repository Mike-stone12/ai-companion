from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clip_memory_text(text: str, limit: int = 48) -> str:
    compact = re.sub(r"\s+", " ", text.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


class MemoryStore:
    def __init__(self, path: Path, limit: int = 24) -> None:
        self.path = path
        self.limit = limit
        self.items: list[dict[str, str]] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.items = []
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to read memory file %s: %s", self.path, exc)
            self.items = []
            return

        if not isinstance(data, list):
            self.items = []
            return

        cleaned: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary", "")).strip()
            if not summary:
                continue
            cleaned.append(
                {
                    "summary": clip_memory_text(summary),
                    "category": str(item.get("category", "memory") or "memory"),
                    "source": str(item.get("source", "") or ""),
                    "updated_at": str(item.get("updated_at", "") or utc_now_iso()),
                }
            )
        self.items = cleaned[-self.limit :]

    def save(self) -> None:
        self.path.write_text(json.dumps(self.items[-self.limit :], ensure_ascii=False, indent=2), encoding="utf-8")

    def render_context(self, max_items: int = 8) -> str:
        if not self.items:
            return ""

        recent = sorted(self.items, key=lambda item: item.get("updated_at", ""), reverse=True)[:max_items]
        lines = [f"- [{item.get('category', 'memory')}] {item['summary']}" for item in recent]
        return "长期记忆（已压缩）:\n" + "\n".join(lines)

    def upsert_many(self, memories: list[dict[str, str]]) -> int:
        added = 0
        for item in memories:
            summary = clip_memory_text(str(item.get("summary", "")).strip())
            if not summary:
                continue

            category = str(item.get("category", "memory") or "memory")
            source = str(item.get("source", "") or "")
            existing = next((entry for entry in self.items if entry.get("summary") == summary), None)
            if existing is not None:
                existing["category"] = category
                existing["source"] = source
                existing["updated_at"] = utc_now_iso()
                continue

            self.items.append(
                {
                    "summary": summary,
                    "category": category,
                    "source": source,
                    "updated_at": utc_now_iso(),
                }
            )
            added += 1

        self.items = sorted(self.items, key=lambda item: item.get("updated_at", ""), reverse=True)[: self.limit]
        if memories:
            self.save()
        return added
