import os
import sys
from collections.abc import Mapping
from pathlib import Path

from companion.env import load_local_env

APP_NAME = "AICompanion"
APP_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = APP_DIR / ".env"

# Load the project .env before anything reads the environment, so settings such as
# COMPANION_DATA_DIR below can come from it. Variables already set in the shell win.
load_local_env(ENV_PATH)


def user_data_dir(
    platform: str = sys.platform,
    env: Mapping[str, str] = os.environ,
    home: Path | None = None,
) -> Path:
    override = env.get("COMPANION_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    home = home or Path.home()
    if platform == "darwin":
        return home / "Library" / "Application Support" / APP_NAME
    if platform.startswith("win"):
        appdata = env.get("APPDATA")
        return (Path(appdata) if appdata else home / "AppData" / "Roaming") / APP_NAME
    xdg_data_home = env.get("XDG_DATA_HOME")
    return (Path(xdg_data_home) if xdg_data_home else home / ".local" / "share") / "ai-companion"


HTML_PATH = APP_DIR / "live2d_renderer.html"
MODELS_DIR = APP_DIR / "models"
VENDOR_DIR = APP_DIR / "vendor"

# User data lives outside the project so a packaged, read-only app can still write it.
DATA_DIR = user_data_dir()
MEMORY_PATH = DATA_DIR / "memory.json"
HISTORY_PATH = DATA_DIR / "history.json"
CONFIG_PATH = DATA_DIR / "config.json"
LOG_DIR = DATA_DIR / "logs"

LEGACY_MEMORY_PATH = APP_DIR / "memory.json"
