from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from companion.paths import MODELS_DIR, VENDOR_DIR


DEFAULT_MODEL = "whale-girl"
DEFAULT_WINDOW_SIZE = (430, 720)
MODEL_PROFILE_FILE = "companion.json"


@dataclass(slots=True)
class ModelProfile:
    path: Path
    motions: dict[str, list[str]]
    window_size: tuple[int, int] = DEFAULT_WINDOW_SIZE


def read_profile_settings(model_dir: Path) -> dict:
    settings_path = model_dir / MODEL_PROFILE_FILE
    if not settings_path.exists():
        return {}
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[resources] Ignoring unreadable {settings_path}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def parse_window_size(raw: object) -> tuple[int, int]:
    if isinstance(raw, dict):
        width, height = raw.get("width"), raw.get("height")
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return (width, height)
    return DEFAULT_WINDOW_SIZE


def parse_motions(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    motions: dict[str, list[str]] = {}
    for role, groups in raw.items():
        if isinstance(groups, list):
            motions[str(role)] = [group for group in groups if isinstance(group, str)]
    return motions


def load_model_profile(target: Path) -> ModelProfile | None:
    model_dir = target.parent if target.is_file() else target
    settings = read_profile_settings(model_dir)

    if target.is_file():
        model_file: Path | None = target
    elif isinstance(settings.get("model"), str):
        model_file = model_dir / settings["model"]
    else:
        model_file = next(iter(sorted(model_dir.glob("*.model3.json"))), None)

    if model_file is None or not model_file.is_file():
        return None
    return ModelProfile(
        path=model_file.resolve(),
        motions=parse_motions(settings.get("motions")),
        window_size=parse_window_size(settings.get("window")),
    )


def discover_model_profile(configured: str = "", models_dir: Path = MODELS_DIR) -> ModelProfile | None:
    if configured:
        for target in (models_dir / configured, Path(configured).expanduser()):
            if target.exists():
                profile = load_model_profile(target)
                if profile is not None:
                    return profile
        print(f"[resources] LIVE2D_MODEL not found, falling back to default: {configured}")

    if not models_dir.is_dir():
        print(f"[resources] Models directory not found: {models_dir}")
        return None

    default_dir = models_dir / DEFAULT_MODEL
    candidates = [default_dir] + sorted(p for p in models_dir.iterdir() if p.is_dir() and p != default_dir)
    for candidate in candidates:
        if candidate.is_dir():
            profile = load_model_profile(candidate)
            if profile is not None:
                return profile

    print(f"[resources] No model found under: {models_dir}")
    return None


def discover_vendor_dir() -> Path | None:
    configured = os.getenv("LIVE2D_VENDOR_DIR", "").strip()
    if configured:
        explicit = Path(configured).expanduser()
        if explicit.exists():
            return explicit.resolve()
        print(f"[resources] Configured LIVE2D_VENDOR_DIR does not exist: {explicit}")

    if VENDOR_DIR.exists():
        return VENDOR_DIR.resolve()

    print(f"[resources] Vendor directory not found: {VENDOR_DIR}")
    return None
