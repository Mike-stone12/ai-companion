"""Choose who speaks for the companion: Edge TTS (default) or a custom-voice provider.

``openai`` is any OpenAI-compatible ``/audio/speech`` endpoint (cloud services with
fixed or designed voices, or a local server). The custom voice is used for every
sentence; if it fails, the app falls back to Edge TTS for that sentence and says so
once. Voices must be AI-generated or properly licensed, never a cloned real person.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

PROVIDERS = ("edge", "openai")
RATE_RE = re.compile(r"[+-]\d{1,2}%")


@dataclass(frozen=True, slots=True)
class CustomVoice:
    provider: str
    base_url: str
    model: str
    voice: str
    api_key: str


def custom_voice(
    provider: str, base_url: str, model: str, voice: str, chat_base_url: str, chat_api_key: str,
    environ: Mapping[str, str] | None = None,
) -> CustomVoice | None:
    """The configured custom voice, or None for Edge TTS (also when it is incomplete).

    A separate TTS_API_KEY (environment or .env only, never config.json) is used when
    the voice service is not the chat provider; otherwise the chat key.
    """
    provider = provider.strip().lower()
    if provider != "openai" or not model.strip() or not voice.strip():
        return None
    environ = os.environ if environ is None else environ
    key = environ.get("TTS_API_KEY", "").strip() or chat_api_key
    return CustomVoice(provider, (base_url.strip() or chat_base_url).rstrip("/"), model.strip(), voice.strip(), key)


def rate_to_speed(rate: str) -> float:
    """Edge's "+6%" becomes OpenAI's speed 1.06 (clamped to 0.5–2.0); anything else is 1.0."""
    if not RATE_RE.fullmatch(rate):
        return 1.0
    return min(max(1 + int(rate.rstrip("%")) / 100, 0.5), 2.0)
