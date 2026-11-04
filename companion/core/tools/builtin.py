"""Built-in tools bound to explicit dependencies, without global state."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime

from .registry import ToolRegistry
from .reminders import ReminderStore, local_now


def build_builtin_registry(
    store: ReminderStore, clock: Callable[[], datetime] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    clock = local_now if clock is None else clock

    @registry.tool
    def get_time() -> str:
        """Get the current local date, time, and weekday."""
        return clock().astimezone().strftime("%Y-%m-%d %H:%M:%S %A %z")

    @registry.tool
    def set_reminder(text: str, when: str) -> str:
        """Set a reminder for a future date and time.

        Args:
            text: Reminder text, up to 200 characters.
            when: ISO 8601 datetime; omitted timezone means local time.
        """
        due_at = datetime.fromisoformat(when)
        if due_at.utcoffset() is None:
            due_at = due_at.astimezone()
        reminder = store.add(text, due_at)
        return f"Reminder {reminder.id} set for {reminder.due_at}: {reminder.text}"

    @registry.tool
    def list_reminders() -> list[dict]:
        """List upcoming reminders in due-time order."""
        return [asdict(reminder) for reminder in store.list()]

    return registry
