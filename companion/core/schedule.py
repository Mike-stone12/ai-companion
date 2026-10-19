"""The companion's daily routine: time blocks with an activity and how available it is.

The schedule is edited as text, one block per line::

    08:30-12:00 [busy] in class
    19:00-23:30 watching a drama
    00:30-07:30 [asleep] sleeping

A block may cross midnight. The optional kind is ``free`` (default), ``busy``,
``drowsy``, or ``asleep``. Times not covered by any block count as free with no
particular activity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time

KINDS = ("free", "busy", "drowsy", "asleep")
MAX_BLOCKS = 16
MAX_ACTIVITY_CHARS = 60
LINE_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s+(?:\[(\w+)\]\s*)?(.*)$")


@dataclass(frozen=True, slots=True)
class ScheduleBlock:
    start: time
    end: time
    activity: str
    kind: str = "free"

    def contains(self, moment: time) -> bool:
        if self.start <= self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end


def _time(hours: str, minutes: str) -> time:
    return time(int(hours), int(minutes))


def _activity(text: str) -> str:
    cleaned = "".join(char for char in text if char.isprintable())
    return " ".join(cleaned.split())[:MAX_ACTIVITY_CHARS].strip()


def _block(start: time, end: time, activity: object, kind: object) -> ScheduleBlock:
    if start == end:
        raise ValueError("start and end are the same")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not isinstance(activity, str):
        raise ValueError("activity must be text")
    activity = _activity(activity)
    if not activity:
        raise ValueError("activity is empty")
    return ScheduleBlock(start, end, activity, kind)


def parse_schedule(text: str) -> tuple[ScheduleBlock, ...]:
    """Parse the editable text; errors name the line (1-based, counting every line)."""
    blocks = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = LINE_RE.match(line)
        try:
            if match is None:
                raise ValueError("expected HH:MM-HH:MM [kind] activity")
            start = _time(match[1], match[2])
            end = _time(match[3], match[4])
            blocks.append(_block(start, end, match[6], (match[5] or "free").lower()))
        except ValueError as exc:
            raise ValueError(f"Daily routine line {number}: {exc}") from None
    if len(blocks) > MAX_BLOCKS:
        raise ValueError(f"Daily routine can have at most {MAX_BLOCKS} lines")
    return tuple(blocks)


def format_schedule(blocks: tuple[ScheduleBlock, ...]) -> str:
    lines = []
    for block in blocks:
        kind = "" if block.kind == "free" else f"[{block.kind}] "
        lines.append(f"{block.start:%H:%M}-{block.end:%H:%M} {kind}{block.activity}")
    return "\n".join(lines)


def schedule_to_list(blocks: tuple[ScheduleBlock, ...]) -> list[dict[str, str]]:
    return [
        {"start": f"{block.start:%H:%M}", "end": f"{block.end:%H:%M}", "activity": block.activity, "kind": block.kind}
        for block in blocks
    ]


def schedule_from_list(data: object) -> tuple[ScheduleBlock, ...]:
    """Validate untrusted JSON (persona files)."""
    if not isinstance(data, list) or len(data) > MAX_BLOCKS:
        raise ValueError(f"schedule must be a list of at most {MAX_BLOCKS} blocks")
    blocks = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("schedule blocks must be objects")
        try:
            start = time.fromisoformat(item.get("start", ""))
            end = time.fromisoformat(item.get("end", ""))
        except (TypeError, ValueError):
            raise ValueError("schedule times must be HH:MM") from None
        blocks.append(_block(start, end, item.get("activity"), item.get("kind", "free")))
    return tuple(blocks)


def block_at(blocks: tuple[ScheduleBlock, ...], now: datetime) -> ScheduleBlock | None:
    moment = now.time().replace(tzinfo=None)
    return next((block for block in blocks if block.contains(moment)), None)


def presence_label(block: ScheduleBlock | None) -> str:
    """Short plain text for the window's presence indicator."""
    if block is None:
        return "Online"
    if block.kind == "asleep":
        return "Asleep"
    return block.activity[:1].upper() + block.activity[1:]


# A day for the default childhood friend (青梅竹马): school, an evening at home, a late night.
DEFAULT_SCHEDULE = parse_schedule("""
07:30-08:30 getting ready and having breakfast
08:30-12:00 [busy] in class
12:00-13:00 having lunch with friends
13:00-17:30 [busy] in class and studying
17:30-19:00 heading home and having dinner
19:00-23:30 watching a drama or playing games
23:30-00:30 [drowsy] getting ready for bed
00:30-07:30 [asleep] sleeping
""")
