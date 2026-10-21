"""When the chat shows in "chat on hover" mode, where only the avatar stays on screen otherwise.

The window asks on a timer: the chat shows while the pointer is over the window or the user
is engaged (typing, a reply or picture in flight), lingers for ``hide_delay`` seconds after
that so a slip of the pointer does not flicker it, and a new message from the companion
shows it for ``message_hold`` seconds so a reply is never missed.
"""

from __future__ import annotations

from dataclasses import dataclass

HIDE_DELAY = 1.5
MESSAGE_HOLD = 8.0


@dataclass(slots=True)
class RevealPolicy:
    hide_delay: float = HIDE_DELAY
    message_hold: float = MESSAGE_HOLD
    _until: float = float("-inf")

    def visible(self, now: float, *, hovered: bool, engaged: bool) -> bool:
        if hovered or engaged:
            self._until = max(self._until, now + self.hide_delay)
            return True
        return now < self._until

    def note_message(self, now: float) -> None:
        self._until = max(self._until, now + self.message_hold)

    def reset(self) -> None:
        self._until = float("-inf")
