from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = APP_DIR / ".env"
HTML_PATH = APP_DIR / "live2d_renderer.html"
MODELS_DIR = APP_DIR / "models"
VENDOR_DIR = APP_DIR / "vendor"
MEMORY_PATH = APP_DIR / "memory.json"
LOG_DIR = APP_DIR / "logs"
