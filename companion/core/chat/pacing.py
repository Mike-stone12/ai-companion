"""Pace a reply like texting: a few short messages, each after a typing pause.

The model writes each chat message on its own line. ``MessageSplitter`` turns the
stream into complete messages as line breaks arrive; ``typing_delay`` says how long
"typing…" shows before a message appears, and ``reply_delay`` how long a busy or
sleeping companion takes to pick up. Randomness is injected for tests.
"""

from __future__ import annotations

import random

MAX_MESSAGES = 4
SECONDS_PER_CHAR = 0.06
MIN_TYPING = 0.6
MAX_TYPING = 4.0
JITTER = 0.2
MAX_REPLY_DELAY = 30.0
# The first message must not wait for a line break the model may never send: it goes out
# at its first complete sentence, or at a comma once it is this long. 10 matches where the
# unpaced speech path (SentenceSplitter.first_soft_limit) starts speaking, so first speech
# is no later with pacing on.
FIRST_FLUSH_CHARS = 10
SENTENCE_ENDS = "。！？!?…~"
CLOSING_MARKS = "”’\"'」』）)】"
CLAUSE_MARKS = "，,；;、"
REPLY_DELAYS = {"busy": (4.0, 15.0), "asleep": (3.0, 8.0)}

PACING_INSTRUCTION = (
    "Reply the way people text: one to four short chat messages, each on its own line, usually one or two "
    "sentences each. Use a single message when that is natural. The emotion tag goes only at the very start."
)


class MessageSplitter:
    """Collect streamed text into chat messages, one per non-blank line, at most MAX_MESSAGES."""

    def __init__(self) -> None:
        self.buffer = ""
        self.emitted = 0

    def feed(self, text: str) -> list[str]:
        self.buffer += text
        messages = []
        # The last allowed message takes every remaining line, so stop splitting before it.
        while self.emitted + len(messages) < MAX_MESSAGES - 1 and "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                messages.append(line.strip())
        if not messages and not self.emitted and "\n" not in self.buffer:
            cut = self._first_cut()
            if cut:
                messages.append(self.buffer[:cut].strip())
                self.buffer = self.buffer[cut:]
        self.emitted += len(messages)
        return messages

    def _first_cut(self) -> int:
        """Where an unbroken first line can already be sent: after a complete sentence or a long clause."""
        text = self.buffer
        for index, char in enumerate(text):
            is_period = char == "." and index + 1 < len(text) and text[index + 1] == " "
            if char not in SENTENCE_ENDS and not is_period:
                continue
            end = index + 1
            while end < len(text) and (text[end] in SENTENCE_ENDS or text[end] in CLOSING_MARKS):
                end += 1
            # A sentence is complete once something follows its marks (more marks may still come).
            if end < len(text) and text[:end].strip():
                return end
            return 0
        if len(text.strip()) >= FIRST_FLUSH_CHARS:
            cut = max(text.rfind(mark) for mark in CLAUSE_MARKS) + 1
            if cut > 4:
                return cut
        return 0

    def finish(self) -> list[str]:
        rest = " ".join(line.strip() for line in self.buffer.splitlines() if line.strip())
        self.buffer = ""
        if not rest:
            return []
        self.emitted += 1
        return [rest]


def split_for_display(text: str) -> list[str]:
    """The same split for a finished reply, e.g. when restoring history."""
    splitter = MessageSplitter()
    return splitter.feed(text) + splitter.finish()


def typing_delay(text: str, rng: random.Random, *, slow: float = 1.0) -> float:
    """Seconds of "typing…" before a message of this length appears."""
    seconds = len(text) * SECONDS_PER_CHAR * rng.uniform(1 - JITTER, 1 + JITTER) * slow
    return min(max(seconds, MIN_TYPING), MAX_TYPING)


def reply_delay(availability: str, rng: random.Random) -> float:
    """Extra seconds before the first message while busy or asleep (never left unanswered)."""
    bounds = REPLY_DELAYS.get(availability)
    if bounds is None:
        return 0.0
    return min(rng.uniform(*bounds), MAX_REPLY_DELAY)
