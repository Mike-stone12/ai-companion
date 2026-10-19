"""Speech from an OpenAI-compatible /audio/speech endpoint, with bounded waits."""

from __future__ import annotations

import json
import tempfile
import urllib.error
import urllib.request

from companion.core.tts_provider import CustomVoice

# Like Edge TTS: a sentence is short, so these bounds are generous for a healthy service.
SPEECH_TIMEOUT_S = 20
MAX_ERROR_CHARS = 200


def speech_request(voice: CustomVoice, text: str, speed: float) -> urllib.request.Request:
    payload = {"model": voice.model, "input": text, "voice": voice.voice, "response_format": "mp3", "speed": speed}
    headers = {"Content-Type": "application/json"}
    # A keyless local server gets no Authorization header.
    if voice.api_key:
        headers["Authorization"] = f"Bearer {voice.api_key}"
    return urllib.request.Request(
        f"{voice.base_url}/audio/speech",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )


def synthesize_to_file(voice: CustomVoice, text: str, speed: float = 1.0, timeout: float = SPEECH_TIMEOUT_S) -> str:
    """Write the MP3 to a temporary file and return its path; errors never include the key."""
    try:
        with urllib.request.urlopen(speech_request(voice, text, speed), timeout=timeout) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:MAX_ERROR_CHARS].decode("utf-8", "replace")
        if voice.api_key:
            detail = detail.replace(voice.api_key, "[redacted]")
        raise RuntimeError(f"Voice service returned HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Voice service unreachable ({type(exc).__name__})") from None
    if not audio:
        raise RuntimeError("Voice service returned no audio")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as handle:
        handle.write(audio)
    return handle.name
