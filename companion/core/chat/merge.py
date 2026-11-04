"""Wait for a burst of user messages, then answer them together.

People text in bursts: "在吗", "我跟你说，", "今天被老板骂了". Answering each line as it lands
reads like a bot; a person waits until the other side seems done. ``MessageMerger`` holds
the burst and says how long to stay quiet after the latest message: briefly after a
finished sentence, longer after something that trails off (a comma, "然后", a bare "在吗"),
and never more than ``MAX_WAIT`` from the first message, so a long burst still gets an
answer. Times are plain floats (seconds, monotonic) so tests need no clock.
"""

from __future__ import annotations

from collections.abc import Iterable

QUIET_CLOSED = 0.8
QUIET_PLAIN = 1.5
QUIET_OPEN = 3.0
MAX_WAIT = 6.0

SENTENCE_ENDS = "。！？!?.~～"
OPEN_ENDS = "，,；;、：:—-"
OPEN_WORDS = (
    "然后", "而且", "还有", "就是", "但是", "不过", "因为", "所以", "结果", "我跟你说", "跟你说",
    "话说", "等一下", "等等", "对了", "我想", "那个",
)
OPEN_WORDS_EN = ("and", "but", "so", "because", "then", "also", "i mean", "wait", "like")
# A message this short with no sentence end ("在吗", "诶", "hi") is usually an opener.
OPENER_CHARS = 3


def looks_unfinished(text: str) -> bool:
    """Whether the sender probably has more to say."""
    text = text.strip()
    if not text:
        return False
    if text.endswith(("…", "...", "。。")):
        return True
    if text[-1] in OPEN_ENDS:
        return True
    if text[-1] in SENTENCE_ENDS:
        return False
    if len(text) <= OPENER_CHARS:
        return True
    lowered = text.lower()
    if lowered.endswith(OPEN_WORDS):
        return True
    return any(lowered == word or lowered.endswith(f" {word}") for word in OPEN_WORDS_EN)


def quiet_after(text: str) -> float:
    """Seconds to wait for another message after this one."""
    if looks_unfinished(text):
        return QUIET_OPEN
    if text.strip()[-1:] in SENTENCE_ENDS:
        return QUIET_CLOSED
    return QUIET_PLAIN


def merged_text(messages: Iterable[str]) -> str:
    """One text for the burst, as memory extraction and appraisal see it."""
    return "\n".join(message.strip() for message in messages if message.strip())


class MessageMerger:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._messages: list[str] = []
        self._first_at = 0.0
        self._last_at = 0.0

    def __bool__(self) -> bool:
        return bool(self._messages)

    @property
    def pending(self) -> tuple[str, ...]:
        return tuple(self._messages)

    def add(self, text: str, now: float) -> None:
        text = text.strip()
        if not text:
            return
        if not self._messages:
            self._first_at = now
        self._messages.append(text)
        self._last_at = now

    def wait(self, now: float) -> float | None:
        """Seconds until the burst should be answered; 0 when due, None when empty."""
        if not self._messages:
            return None
        if not self.enabled:
            return 0.0
        quiet_until = self._last_at + quiet_after(self._messages[-1])
        due = min(quiet_until, self._first_at + MAX_WAIT)
        return max(0.0, due - now)

    def take(self) -> list[str]:
        messages, self._messages = self._messages, []
        return messages
