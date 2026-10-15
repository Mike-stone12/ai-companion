from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def load_settings(path: Path) -> dict:
    """Read a JSON settings file; a missing, unreadable, or non-object file counts as empty."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring unreadable settings file %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("Ignoring settings file %s: expected a JSON object", path)
        return {}
    return data


def save_settings(path: Path, settings: dict) -> None:
    """Write the whole settings object atomically, so a crash mid-write cannot truncate it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)


def update_section(path: Path, section: str, values: dict) -> None:
    """Replace one top-level section of the settings file, keeping every other key as it is."""
    settings = load_settings(path)
    settings[section] = values
    save_settings(path, settings)
