"""Proactive event data, independent of scheduling and presentation."""

from dataclasses import dataclass, field
from datetime import datetime

IDLE = "idle"
GREETING = "greeting"
REMINDER = "reminder"
ACTIVE_APP = "active_app"
# The companion reaches out because of how it feels (missing the user, wanting to share).
MOOD = "mood"


@dataclass(frozen=True)
class Event:
    kind: str
    at: datetime
    payload: dict = field(default_factory=dict)
