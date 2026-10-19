"""Small app-facing adapter for a session's existing proactive engine."""

from collections.abc import Callable
from datetime import datetime, timedelta

from companion.core.tools.reminders import ReminderStore

from .composer import compose_message
from .engine import ProactiveContext, ProactiveEngine, ProactiveResult
from .policy import PolicyConfig, ProactivePolicy
from .triggers import GreetingTrigger, IdleTrigger, ReminderTrigger


class ProactiveSession:
    def __init__(self, reminders: ReminderStore, now: datetime):
        self.last_user_activity: datetime | None = None
        self.idle = IdleTrigger(timedelta(minutes=30), now)
        # Due reminders take priority; proposal/deduplication semantics remain
        # those of the engine (no queue or retry of rejected proposals).
        self.engine = ProactiveEngine(
            [ReminderTrigger(reminders), GreetingTrigger(), self.idle],
            ProactivePolicy(PolicyConfig()), compose_message,
        )

    def record_activity(self, now: datetime) -> None:
        self.last_user_activity = now
        self.idle.record_interaction(now)

    def tick(self, now: datetime, *, busy: bool, input_has_text: bool) -> ProactiveResult | None:
        return self.engine.tick(now, ProactiveContext(
            last_user_activity=self.last_user_activity, busy=busy or input_has_text,
        ))


def proactive_request(
    context: Callable[[], list[dict[str, str]]], result: ProactiveResult,
) -> Callable[[], list[dict[str, str]]]:
    """Append transient instructions on the worker, leaving saved turns untouched."""
    instructions = [dict(message) for message in result.messages]
    return lambda: [*context(), *instructions]
