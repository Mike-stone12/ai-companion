"""Proactive event data, independent of scheduling and presentation."""

from dataclasses import dataclass, field
from datetime import datetime

IDLE = "idle"
GREETING = "greeting"
REMINDER = "reminder"


@dataclass(frozen=True)
class Event:
    kind: str
    at: datetime
    payload: dict = field(default_factory=dict)
