"""A small, caller-located reminder store with atomic JSON persistence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from companion.core.settings_file import load_json, save_settings


def local_now() -> datetime:
    return datetime.now().astimezone()


def _aware(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.utcoffset() is None:
        raise ValueError("Expected a timezone-aware datetime")
    return parsed


def _text(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError("Reminder text must contain 1 to 200 characters")
    return value.strip()


@dataclass(frozen=True)
class Reminder:
    id: str
    text: str
    due_at: str
    created_at: str


class ReminderStore:
    """Store aware ISO timestamps; upcoming excludes times at or before now.

    Files are reloaded for each operation. Concurrent writers require external
    coordination; atomic replacement protects against partially written JSON.
    """

    def __init__(self, path: str | Path, clock: Callable[[], datetime] = local_now):
        self.path = Path(path)
        self.clock = clock

    def _read(self) -> list[Reminder]:
        reminders = []
        for row in load_json(self.path, list):
            try:
                reminder = Reminder(**row)
                if not isinstance(reminder.id, str) or not reminder.id:
                    continue
                _text(reminder.text)
                _aware(reminder.due_at)
                _aware(reminder.created_at)
            except (TypeError, ValueError):
                continue
            reminders.append(reminder)
        return reminders

    def add(self, text: str, due_at: str | datetime) -> Reminder:
        text = _text(text)
        due_time = _aware(due_at)
        now = _aware(self.clock())
        if due_time.astimezone(UTC) < now.astimezone(UTC):
            raise ValueError("Reminder time cannot be in the past")
        reminders = self._read()
        reminder = Reminder(uuid4().hex[:12], text, due_time.isoformat(), now.isoformat())
        save_settings(self.path, [asdict(item) for item in [*reminders, reminder]])
        return reminder

    def list(self, include_past: bool = False) -> list[Reminder]:
        now = _aware(self.clock())
        reminders = sorted(self._read(), key=lambda item: _aware(item.due_at))
        return [item for item in reminders if include_past or _aware(item.due_at) > now]

    def due(self, now: datetime | None = None) -> list[Reminder]:
        """Return all reminders due at or before now, without consuming them."""
        cutoff = _aware(self.clock() if now is None else now)
        return sorted(
            (item for item in self._read() if _aware(item.due_at) <= cutoff),
            key=lambda item: _aware(item.due_at),
        )
