"""Small app-facing adapter for a session's existing proactive engine."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

from companion.core.tools.reminders import ReminderStore

from .active_app import ActiveAppTrigger
from .composer import compose_message
from .engine import ProactiveContext, ProactiveEngine, ProactiveResult
from .events import ACTIVE_APP, MOOD
from .policy import PolicyConfig, ProactivePolicy
from .triggers import (
    AwakeGate,
    FeelingProbe,
    GreetingTrigger,
    IdleTrigger,
    MoodGate,
    MoodTrigger,
    ReminderTrigger,
    Trigger,
)

MOOD_COOLDOWN = timedelta(hours=2)


def build_proactive_triggers(
    reminders: ReminderStore, idle: IdleTrigger, *, proactive_chat: bool, active_app_monitor: bool,
    awake: Callable[[datetime], bool] | None = None,
    feeling: FeelingProbe | None = None,
    last_activity: Callable[[], datetime | None] = lambda: None,
) -> tuple[list[Trigger], ActiveAppTrigger | None]:
    """Assemble session triggers without querying the OS or creating disabled monitors.

    With ``awake`` (from the daily schedule), everything except reminders waits
    while the companion is asleep. With ``feeling`` (the dominant feeling), it waits
    while annoyed or jealous, and reaches out on its own when missing the user or
    in a great mood.
    """
    if not proactive_chat:
        return [], None

    def gate(trigger: Trigger) -> Trigger:
        if feeling is not None:
            trigger = MoodGate(trigger, feeling)
        return AwakeGate(trigger, awake) if awake is not None else trigger

    triggers: list[Trigger] = [ReminderTrigger(reminders), gate(GreetingTrigger()), gate(idle)]
    active_app = ActiveAppTrigger() if active_app_monitor else None
    if active_app is not None:
        triggers.append(gate(active_app))
    if feeling is not None:
        triggers.append(gate(MoodTrigger(feeling, last_activity)))
    return triggers, active_app


class ProactiveSession:
    def __init__(
        self, reminders: ReminderStore, now: datetime, *,
        proactive_chat: bool = True, active_app_monitor: bool = False,
        awake: Callable[[datetime], bool] | None = None,
        feeling: FeelingProbe | None = None,
    ):
        self.last_user_activity: datetime | None = None
        self.idle = IdleTrigger(timedelta(minutes=30), now)
        triggers, self.active_app = build_proactive_triggers(
            reminders, self.idle, proactive_chat=proactive_chat, active_app_monitor=active_app_monitor,
            awake=awake, feeling=feeling, last_activity=lambda: self.last_user_activity,
        )
        policy = PolicyConfig()
        if self.active_app is not None:
            policy = replace(policy, enabled_kinds=policy.enabled_kinds | {ACTIVE_APP})
        if feeling is not None:
            policy = replace(
                policy, enabled_kinds=policy.enabled_kinds | {MOOD},
                cooldowns={**policy.cooldowns, MOOD: MOOD_COOLDOWN},
            )
        # Due reminders take priority; proposal/deduplication semantics remain
        # those of the engine (no queue or retry of rejected proposals).
        self.engine = ProactiveEngine(
            triggers, ProactivePolicy(policy), compose_message,
        )

    def record_activity(self, now: datetime) -> None:
        self.last_user_activity = now
        self.idle.record_interaction(now)

    def tick(self, now: datetime, *, busy: bool, input_has_text: bool) -> ProactiveResult | None:
        result = self.engine.tick(now, ProactiveContext(
            last_user_activity=self.last_user_activity, busy=busy or input_has_text,
        ))
        if result is not None and result.event.kind == MOOD:
            for trigger in self.engine._triggers:
                mark_sent = getattr(trigger, "mark_sent", None)
                if callable(mark_sent):
                    mark_sent(result.event.at)
        return result


def proactive_request(
    context: Callable[[], list[dict[str, str]]], result: ProactiveResult,
) -> Callable[[], list[dict[str, str]]]:
    """Append transient instructions on the worker, leaving saved turns untouched."""
    instructions = [dict(message) for message in result.messages]
    return lambda: [*context(), *instructions]
