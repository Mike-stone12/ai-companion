"""Versioned reminder snapshots, independent of UI and session scheduling.

Callers supply the user-data path (typically ``data_dir / 'reminders.json'``).
This format is separate from ReminderStore's existing unversioned list format.
Reminder has no delivery state field, so callers must supply known completed IDs
to exclude fired or delivered reminders. Overdue timestamps do not imply delivery.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from companion.core import settings_file

from .reminders import Reminder, _aware, _text

logger = logging.getLogger(__name__)


def serialize_reminders(reminders: Iterable[Reminder], *, completed_ids: Iterable[str] = ()) -> dict:
    """Preserve identity and ISO timestamp strings, including their UTC offsets."""
    completed = set(completed_ids)
    return {
        "version": 1,
        "reminders": [asdict(reminder) for reminder in reminders if reminder.id not in completed],
    }


def deserialize_reminders(data: object) -> list[Reminder]:
    """Validate a versioned snapshot, warning and skipping malformed entries.

    Due times are not compared with the clock: overdue reminders must survive
    loading so that a future caller can deliver them after a restart.
    """
    if (
        not isinstance(data, dict)
        or type(data.get("version")) is not int
        or data["version"] != 1
        or not isinstance(data.get("reminders"), list)
    ):
        logger.warning("Ignoring reminder data: expected version 1 and a reminders list")
        return []

    reminders = []
    for index, row in enumerate(data["reminders"]):
        try:
            if not isinstance(row, dict):
                raise ValueError("Expected a reminder object")
            reminder = Reminder(**row)
            if not isinstance(reminder.id, str) or not reminder.id:
                raise ValueError("Expected a nonempty reminder ID")
            _text(reminder.text)
            for timestamp in (reminder.due_at, reminder.created_at):
                if not isinstance(timestamp, str):
                    raise ValueError("Expected an ISO timestamp string")
                _aware(timestamp)
        except (TypeError, ValueError) as exc:
            logger.warning("Skipping malformed reminder at index %s: %s", index, exc)
            continue
        reminders.append(reminder)
    return reminders


def load_reminders(path: str | Path) -> list[Reminder]:
    """Read without modifying the file; missing or invalid content yields no reminders."""
    path = Path(path)
    try:
        if not path.exists():
            logger.warning("Reminder file does not exist: %s", path)
            return []
        data = settings_file.load_json(path, dict)
    except (OSError, RecursionError) as exc:
        logger.warning("Ignoring unreadable reminder file %s: %s", path, exc)
        return []
    return deserialize_reminders(data)


def save_reminders(
    path: str | Path, reminders: Iterable[Reminder], *, completed_ids: Iterable[str] = (),
) -> None:
    """Atomically save pending reminders, creating parents and propagating write failures.

    Supply IDs known to have fired or been delivered via ``completed_ids``.
    The caller owns delivery tracking; the existing model has no state field.
    """
    settings_file.save_settings(Path(path), serialize_reminders(reminders, completed_ids=completed_ids))
