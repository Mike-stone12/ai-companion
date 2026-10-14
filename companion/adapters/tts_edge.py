from __future__ import annotations

import tempfile

from companion.core.config import AppConfig
from companion.core.text import contains_cjk

try:
    import edge_tts
except ImportError:
    edge_tts = None


def is_available() -> bool:
    return edge_tts is not None


def choose_tts_voice(config: AppConfig, text: str) -> str:
    if contains_cjk(text):
        return config.voice_zh
    return config.voice_en


async def synthesize_to_file(text: str, voice: str) -> str:
    if edge_tts is None:
        raise RuntimeError("edge-tts is not installed. Run pip install edge-tts.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
        output_path = temp_file.name

    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(output_path)
    return output_path
