"""Choose who speaks for the companion: Edge TTS (default) or a custom-voice provider.

``openai`` is any OpenAI-compatible ``/audio/speech`` endpoint (cloud services with
fixed or designed voices, or a local server). The custom voice is used for every
sentence; if it fails, the app falls back to Edge TTS for that sentence and says so
once. Voices must be AI-generated or properly licensed, never a cloned real person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from companion.core.api_key import service_api_key

PROVIDERS = ("edge", "openai")
RATE_RE = re.compile(r"[+-]\d{1,2}%")


@dataclass(frozen=True, slots=True)
class CustomVoice:
    provider: str
    base_url: str
    model: str
    voice: str
    api_key: str


NEEDS_OWN_KEY = "the voice service is not your chat provider and has no key of its own (Settings… > Voice key)"


def custom_voice(
    provider: str, base_url: str, model: str, voice: str, chat_base_url: str, chat_api_key: str, own_key: str,
) -> tuple[CustomVoice | None, str]:
    """The configured custom voice and "", or (None, reason) to speak with Edge TTS.

    Incomplete settings quietly mean Edge (empty reason). The key follows
    service_api_key: the voice service's own key (keychain or TTS_API_KEY); else the
    chat key only on the chat provider's host; a loopback server gets no key; any other
    host without its own key is refused, so the chat key never reaches a third party.
    """
    provider = provider.strip().lower()
    if provider != "openai" or not model.strip() or not voice.strip():
        return None, ""
    url = (base_url.strip() or chat_base_url).rstrip("/")
    key = service_api_key(url, chat_base_url, own_key, chat_api_key)
    if key is None:
        return None, NEEDS_OWN_KEY
    return CustomVoice(provider, url, model.strip(), voice.strip(), key), ""


def rate_to_speed(rate: str) -> float:
    """Edge's "+6%" becomes OpenAI's speed 1.06 (clamped to 0.5–2.0); anything else is 1.0."""
    if not RATE_RE.fullmatch(rate):
        return 1.0
    return min(max(1 + int(rate.rstrip("%")) / 100, 0.5), 2.0)
