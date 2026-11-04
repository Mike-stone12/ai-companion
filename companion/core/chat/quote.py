"""Quote replies: the user answers one earlier message, as in any chat app.

The model gets the quoted line inline with the user's turn, in the same bracketed style
as pictures (``[引用你说的：「…」]``), so it knows which of its messages is meant even after
the line has scrolled out of the conversation window. The bubble shows a short reply
marker instead. Quotes are clipped to one line so a long message cannot flood the prompt.
"""

from __future__ import annotations

import re

MAX_QUOTE_CHARS = 60
MARKER = "↪"
HERS = "你说的"
OWN = "我自己说的"
_PATTERN = re.compile(rf"^\[引用({HERS}|{OWN})：「(.*?)」\](?:\n(.*))?$", re.DOTALL)


def clip_quote(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= MAX_QUOTE_CHARS else line[:MAX_QUOTE_CHARS] + "…"


def quote_turn_text(quoted: str, *, own: bool, text: str) -> str:
    """The user's turn as the companion sees it."""
    header = f"[引用{OWN if own else HERS}：「{clip_quote(quoted)}」]"
    text = text.strip()
    return f"{header}\n{text}" if text else header


def split_quote(content: str) -> tuple[str, bool, str] | None:
    """(quoted line, quoting themselves, their text) for a stored quote turn, else None."""
    match = _PATTERN.match(content)
    if match is None:
        return None
    return match.group(2), match.group(1) == OWN, match.group(3) or ""


def quote_display(quoted: str, text: str) -> str:
    """What the user's own bubble shows."""
    marker = f"{MARKER} {clip_quote(quoted)}"
    return f"{marker}\n{text}" if text.strip() else marker
