"""Emotion tags: the model opens each reply with e.g. [happy], which drives the avatar's face."""

from __future__ import annotations

import re

EMOTIONS = ("happy", "sad", "angry", "surprised", "shy", "confused", "awkward", "neutral")
EMOTION_INSTRUCTION = (
    "Begin every reply with exactly one emotion tag that matches how you feel, chosen from: "
    + " ".join(f"[{emotion}]" for emotion in EMOTIONS)
    + ". Put nothing before the tag, use it only at the very start, and never mention it."
)

OPENING_BRACKETS = "[【"
# A known emotion word in brackets anywhere in the text: models sometimes tag every sentence
# or every paced message even though the instruction asks for one tag at the very start.
ANY_TAG_RE = re.compile(r"\s*[\[【]\s*(" + "|".join(EMOTIONS) + r")\s*[\]】]\s*", re.IGNORECASE)
LEADING_TAG_RE = re.compile(r"^\s*[\[【]\s*(" + "|".join(EMOTIONS) + r")\s*[\]】]\s*", re.IGNORECASE)


def split_leading_tag(text: str) -> tuple[str | None, str]:
    """(emotion, rest) for one paced message; unknown bracketed words are not tags."""
    match = LEADING_TAG_RE.match(text)
    if not match:
        return None, text
    return match.group(1).lower(), text[match.end():]


def strip_emotion_tags(text: str, *, keep_leading: bool = True) -> str:
    """Remove emotion tags, optionally keeping one at the very start (history needs it)."""
    lead = ""
    if keep_leading:
        match = LEADING_TAG_RE.match(text)
        if match:
            lead, text = text[:match.end()], text[match.end():]
    return lead + ANY_TAG_RE.sub(" ", text).strip() if lead else ANY_TAG_RE.sub(" ", text).strip()
TAG_RE = re.compile(r"\s*[\[【]\s*([A-Za-z_-]{1,16})\s*[\]】]\s*")
PARTIAL_TAG_RE = re.compile(r"\s*[\[【]\s*[A-Za-z_-]*\s*")
MAX_TAG_PREFIX = 24


class EmotionTagParser:
    """Strip a leading emotion tag from a streamed reply.

    Text is held back only while the start of the stream could still be a tag, so replies
    without one (or starting with "[1]" or "[注意]") reach the screen immediately.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.resolved = False
        self.emotion: str | None = None

    def feed(self, text: str) -> str:
        if self.resolved:
            return text
        self.buffer += text
        stripped = self.buffer.lstrip()
        if not stripped:
            return ""
        if stripped[0] not in OPENING_BRACKETS:
            return self._release()

        match = TAG_RE.match(self.buffer)
        if match:
            name = match.group(1).lower()
            self.emotion = name if name in EMOTIONS else "neutral"
            self.resolved = True
            rest = self.buffer[match.end() :]
            self.buffer = ""
            return rest

        could_still_be_tag = PARTIAL_TAG_RE.fullmatch(self.buffer) and len(self.buffer) <= MAX_TAG_PREFIX
        return "" if could_still_be_tag else self._release()

    def flush(self) -> str:
        return "" if self.resolved else self._release()

    def _release(self) -> str:
        self.resolved = True
        text, self.buffer = self.buffer, ""
        return text
