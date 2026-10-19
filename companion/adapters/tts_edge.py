from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from companion.core.config import AppConfig
from companion.core.text import contains_cjk

try:
    import edge_tts
except ImportError:
    edge_tts = None

# edge-tts defaults to 10 s to connect and 60 s per read, per sentence; on a bad network a
# multi-sentence reply could keep the window busy for minutes. A sentence is short, so these
# bounds are generous for a healthy connection.
TTS_CONNECT_TIMEOUT_S = 5
TTS_RECEIVE_TIMEOUT_S = 15
TTS_TOTAL_TIMEOUT_S = 20


def is_available() -> bool:
    return edge_tts is not None


NEUTRAL_PROSODY = ("+0%", "+0Hz")


def choose_tts_voice(config: AppConfig, text: str) -> str:
    if contains_cjk(text):
        return config.voice_zh
    return config.voice_en


def choose_tts_prosody(config: AppConfig, text: str) -> tuple[str, str]:
    """(rate, pitch) for this sentence: the configured offsets for Chinese, neutral for English.

    Malformed values (e.g. from the environment, which bypasses the settings schema)
    fall back to neutral rather than failing every sentence.
    """
    from companion.core.settings_schema import valid_prosody

    if not contains_cjk(text):
        return NEUTRAL_PROSODY
    if not (valid_prosody("TTS_RATE", config.tts_rate) and valid_prosody("TTS_PITCH", config.tts_pitch)):
        return NEUTRAL_PROSODY
    return config.tts_rate, config.tts_pitch


async def synthesize_to_file(
    text: str, voice: str, timeout: float = TTS_TOTAL_TIMEOUT_S, *, rate: str = "+0%", pitch: str = "+0Hz",
) -> str:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed. Run pip install edge-tts.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
        output_path = temp_file.name

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        connect_timeout=TTS_CONNECT_TIMEOUT_S,
        receive_timeout=TTS_RECEIVE_TIMEOUT_S,
    )
    try:
        await asyncio.wait_for(communicate.save(output_path), timeout)
    except TimeoutError as exc:
        Path(output_path).unlink(missing_ok=True)
        raise RuntimeError(f"Speech synthesis timed out after {timeout:g} s") from exc
    except BaseException:
        Path(output_path).unlink(missing_ok=True)
        raise
    return output_path
