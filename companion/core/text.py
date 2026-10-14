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
    cleaned = text.strip()
    cleaned = re.sub(r"```(?:[a-zA-Z0-9_+-]+)?", "", cleaned)
    cleaned = cleaned.replace("```", "")
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = cleaned.replace("*", "")
    cleaned = EMOJI_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


# Asides like （轻轻晃了晃脑袋） or (笑) are stage directions: shown on screen, never spoken.
# Asides with Latin text or digits, such as (比如 Python) or （大约3公里）, carry content and stay.
STAGE_DIRECTION_RE = re.compile(r"[（(][^（）()A-Za-z0-9\n]{1,30}[）)]")


def sanitize_tts_text(text: str) -> str:
    cleaned = EMOJI_RE.sub("", text.strip())
    cleaned = STAGE_DIRECTION_RE.sub("", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"[*_~#>\-\[\]\(\)]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()
