from __future__ import annotations

import re

EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # pictographs, emoticons, flags, skin tones
    "☀-➿"  # misc symbols and dingbats (incl. ★☆❤)
    "⭐⭕"
    "️‍⃣"  # variation selector, ZWJ, keycap joiners
    "]+"
)


def contains_cjk(text: str) -> bool:
    for char in text:
        codepoint = ord(char)
        if 0x3400 <= codepoint <= 0x9FFF or 0xF900 <= codepoint <= 0xFAFF:
            return True
    return False


def sanitize_reply_text(text: str) -> str:
    from companion.core.chat.emotion import strip_emotion_tags

    cleaned = strip_emotion_tags(text.strip())
    cleaned = re.sub(r"```(?:[a-zA-Z0-9_+-]+)?", "", cleaned)
    cleaned = cleaned.replace("```", "")
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = cleaned.replace("*", "")
    cleaned = EMOJI_RE.sub("", cleaned)
    # Collapse spaces but keep one line break per message: history restores them as bubbles.
    lines = (re.sub(r"[^\S\n]+", " ", line).strip() for line in cleaned.split("\n"))
    return "\n".join(line for line in lines if line)


# Asides like （轻轻晃了晃脑袋） or (笑) are stage directions: shown on screen, never spoken.
# Asides with Latin text or digits, such as (比如 Python) or （大约3公里）, carry content and stay.
STAGE_DIRECTION_RE = re.compile(r"[（(][^（）()A-Za-z0-9\n]{1,30}[）)]")


def sanitize_tts_text(text: str) -> str:
    from companion.core.chat.emotion import strip_emotion_tags

    # A stray "[neutral]" would otherwise be read out as the word "neutral".
    cleaned = EMOJI_RE.sub("", strip_emotion_tags(text.strip(), keep_leading=False))
    cleaned = STAGE_DIRECTION_RE.sub("", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"[*_~#>\-\[\]\(\)]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


SENTENCE_TERMINATORS = "。！？!?；;…\n"
CLOSING_MARKS = "”’」』）)】\"'"
SOFT_BREAKS = "，,、：:"


class SentenceSplitter:
    """Cut streamed text into speakable sentences as soon as each one is complete.

    Fragments shorter than ``min_chars`` (like "嗯。") are merged into the next sentence, and a
    clause that runs past ``soft_limit`` characters without a terminator is cut at its last
    comma so speech can start before the model finishes a long sentence. Until the first piece
    is out, the lower ``first_soft_limit`` applies: that piece gates when the companion starts
    speaking, so it is cut at the first comma after a few words.
    """

    def __init__(self, min_chars: int = 4, soft_limit: int = 40, first_soft_limit: int = 10) -> None:
        self.min_chars = min_chars
        self.soft_limit = soft_limit
        self.first_soft_limit = first_soft_limit
        self.buffer = ""
        self.emitted_any = False

    def feed(self, text: str) -> list[str]:
        self.buffer += text
        sentences: list[str] = []
        scan_from = 0
        while (end := self._find_end(scan_from)) is not None:
            candidate = self.buffer[:end].strip()
            if len(candidate) < self.min_chars:
                scan_from = end
                continue
            sentences.append(candidate)
            self.buffer = self.buffer[end:]
            scan_from = 0

        soft_limit = self.soft_limit if (self.emitted_any or sentences) else self.first_soft_limit
        tail = self.buffer.rstrip()
        ends_in_terminator = bool(tail) and (tail[-1] in SENTENCE_TERMINATORS or tail[-1] in CLOSING_MARKS)
        if len(tail.lstrip()) >= soft_limit and not ends_in_terminator:
            cut = max(self.buffer.rfind(mark) for mark in SOFT_BREAKS) + 1
            if len(self.buffer[:cut].strip()) >= self.min_chars:
                sentences.append(self.buffer[:cut].strip())
                self.buffer = self.buffer[cut:]
        self.emitted_any = self.emitted_any or bool(sentences)
        return sentences

    def flush(self) -> list[str]:
        tail = self.buffer.strip()
        self.buffer = ""
        return [tail] if tail else []

    def _find_end(self, start: int) -> int | None:
        text = self.buffer
        for index in range(start, len(text)):
            char = text[index]
            is_period = char == "." and index + 1 < len(text) and text[index + 1].isspace()
            if char not in SENTENCE_TERMINATORS and not is_period:
                continue
            end = index + 1
            while end < len(text) and (text[end] in SENTENCE_TERMINATORS or text[end] in CLOSING_MARKS):
                end += 1
            # A terminator at the very end may still be followed by more marks or a closing quote.
            return end if end < len(text) else None
        return None
