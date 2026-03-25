from __future__ import annotations

import asyncio
import json
import os
import re
import site
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ENV_PATH = APP_DIR / ".env"


def load_local_env(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


load_local_env(ENV_PATH)


def bootstrap_windows_qt_dlls() -> list[Path]:
    if os.name != "nt":
        return []

    raw_candidates: list[Path] = [
        Path(sys.prefix),
        Path(sys.prefix) / "DLLs",
        Path(sys.prefix) / "Library" / "bin",
        Path(sys.prefix) / "Library" / "usr" / "bin",
        Path(sys.prefix) / "Scripts",
    ]

    try:
        raw_candidates.extend(Path(path) for path in site.getsitepackages())
    except Exception:
        pass

    try:
        raw_candidates.append(Path(site.getusersitepackages()))
    except Exception:
        pass

    raw_candidates.extend(Path(path) for path in sys.path if path)

    candidate_dirs: list[Path] = []
    seen: set[str] = set()
    for root in raw_candidates:
        for candidate in (
            root,
            root / "PyQt6" / "Qt6" / "bin",
            root / "PyQt6" / "Qt" / "bin",
            root / "PyQt6",
            root / "PyQt5" / "Qt5" / "bin",
            root / "PyQt5" / "Qt" / "bin",
            root / "PyQt5",
        ):
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            if candidate.exists():
                candidate_dirs.append(candidate)

    active_dirs: list[Path] = []
    for dll_dir in candidate_dirs:
        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(dll_dir))
            except OSError:
                continue
        active_dirs.append(dll_dir)

    return active_dirs


def diagnose_pyqt6_icu_mismatch() -> str | None:
    try:
        import lief
    except Exception:
        return None

    qt6_core = Path(sys.prefix) / "Lib" / "site-packages" / "PyQt6" / "Qt6" / "bin" / "Qt6Core.dll"
    icu_uc = Path(sys.prefix) / "Library" / "bin" / "icuuc.dll"
    if not qt6_core.exists() or not icu_uc.exists():
        return None

    try:
        qt_binary = lief.parse(str(qt6_core))
        icu_binary = lief.parse(str(icu_uc))
    except Exception:
        return None

    required_symbols: list[str] = []
    for imported in qt_binary.imports:
        if imported.name.lower() == "icuuc.dll":
            for entry in imported.entries:
                if entry.name:
                    required_symbols.append(entry.name)
            break

    if not required_symbols:
        return None

    exported_symbols = {entry.name for entry in icu_binary.exported_functions if entry.name}
    missing = [name for name in required_symbols if name not in exported_symbols]
    if not missing:
        return None

    preview = ", ".join(missing[:5])
    return (
        "[PyQt6 bootstrap] 检测到 ICU 运行时不兼容。\n"
        f"[PyQt6 bootstrap] Qt6Core.dll 需要这些未版本化符号: {preview}\n"
        f"[PyQt6 bootstrap] 但当前加载到的 ICU 是: {icu_uc}\n"
        "[PyQt6 bootstrap] 这是 pip 安装的 PyQt6-Qt6 与 Anaconda base 环境 ICU 冲突的典型现象。"
    )


ACTIVE_DLL_DIRS = bootstrap_windows_qt_dlls()
QT_API = ""
IS_QT6 = False
QAudioOutput = None
QMediaContent = None
WEBATTR_JAVASCRIPT = None
WEBATTR_LOCAL_FILE = None
WEBATTR_WEBGL = None
WEBATTR_REMOTE = None
WINDOW_FRAMELESS = None
WINDOW_TOPMOST = None
WINDOW_TOOL = None
ATTR_TRANSLUCENT = None
LEFT_BUTTON = None
PLAYBACK_STOPPED = None

try:
    from PyQt6.QtCore import QObject, QPoint, QThread, QTimer, QUrl, QUrlQuery, Qt, pyqtSignal, pyqtSlot
    from PyQt6.QtGui import QColor
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import (
        QApplication,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    QT_API = "PyQt6"
    IS_QT6 = True
    WEBATTR_JAVASCRIPT = QWebEngineSettings.WebAttribute.JavascriptEnabled
    WEBATTR_LOCAL_FILE = QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls
    WEBATTR_WEBGL = QWebEngineSettings.WebAttribute.WebGLEnabled
    WEBATTR_REMOTE = QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls
    WINDOW_FRAMELESS = Qt.WindowType.FramelessWindowHint
    WINDOW_TOPMOST = Qt.WindowType.WindowStaysOnTopHint
    WINDOW_TOOL = Qt.WindowType.Tool
    ATTR_TRANSLUCENT = Qt.WidgetAttribute.WA_TranslucentBackground
    LEFT_BUTTON = Qt.MouseButton.LeftButton
    PLAYBACK_STOPPED = QMediaPlayer.PlaybackState.StoppedState
except ImportError as pyqt6_exc:
    print("[PyQt6 bootstrap] Failed to import PyQt6 modules.")
    print(f"[PyQt6 bootstrap] ImportError: {pyqt6_exc}")
    if ACTIVE_DLL_DIRS:
        print("[PyQt6 bootstrap] DLL directories added:")
        for dll_dir in ACTIVE_DLL_DIRS:
            print(f"  - {dll_dir}")
    diagnosis = diagnose_pyqt6_icu_mismatch()
    if diagnosis:
        print(diagnosis)
    print("[PyQt6 bootstrap] 将尝试回退到当前环境中可用的 PyQt5。")

    try:
        from PyQt5.QtCore import QObject, QPoint, QThread, QTimer, QUrl, QUrlQuery, Qt, pyqtSignal, pyqtSlot
        from PyQt5.QtGui import QColor
        from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
        from PyQt5.QtWebEngineWidgets import QWebEngineSettings, QWebEngineView
        from PyQt5.QtWidgets import (
            QApplication,
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
            QWidget,
        )

        QT_API = "PyQt5"
        IS_QT6 = False
        WEBATTR_JAVASCRIPT = QWebEngineSettings.JavascriptEnabled
        WEBATTR_LOCAL_FILE = QWebEngineSettings.LocalContentCanAccessFileUrls
        WEBATTR_WEBGL = QWebEngineSettings.WebGLEnabled
        WEBATTR_REMOTE = QWebEngineSettings.LocalContentCanAccessRemoteUrls
        WINDOW_FRAMELESS = Qt.FramelessWindowHint
        WINDOW_TOPMOST = Qt.WindowStaysOnTopHint
        WINDOW_TOOL = Qt.Tool
        ATTR_TRANSLUCENT = Qt.WA_TranslucentBackground
        LEFT_BUTTON = Qt.LeftButton
        PLAYBACK_STOPPED = QMediaPlayer.StoppedState
        print("[Qt fallback] 已成功回退到 PyQt5 + PyQtWebEngine。")
    except ImportError:
        print("[Qt fallback] PyQt5 也不可用，程序无法继续启动。")
        raise pyqt6_exc

try:
    import edge_tts
except ImportError:
    edge_tts = None


HTML_PATH = APP_DIR / "live2d_renderer.html"
EXTRACTED_MODEL_DIR = APP_DIR / "1"
MODELS_DIR = APP_DIR / "models"
VENDOR_DIR = APP_DIR / "vendor"
MEMORY_PATH = APP_DIR / "memory.json"
MODEL_SEARCH_DIRS = (EXTRACTED_MODEL_DIR, MODELS_DIR)
MODEL_PATTERNS = ("*.model3.json", "*.model3", "*.model.json", "*.model")
LIVE2D_LOADER_CANDIDATES = (
    "pixi-live2d-display.min.js",
    "pixi-live2d-display.js",
    "live2d.min.js",
    "cubism4.min.js",
    "live2dcubismframework.js",
)


@dataclass(slots=True)
class AppConfig:
    base_url: str = os.getenv("OPENAI_BASE_URL") or os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
    api_key: str = os.getenv("OPENAI_API_KEY") or os.getenv("MOONSHOT_API_KEY", "")
    model: str = os.getenv("OPENAI_MODEL") or os.getenv("MOONSHOT_MODEL", "kimi-k2.5")
    voice: str = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
    voice_zh: str = os.getenv("EDGE_TTS_VOICE_ZH", os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural"))
    voice_en: str = os.getenv("EDGE_TTS_VOICE_EN", "en-US-AriaNeural")
    system_prompt: str = os.getenv(
        "COMPANION_SYSTEM_PROMPT",
        "You are a friendly Live2D desktop companion. Reply briefly, warmly, and in spoken language.",
    )
    request_timeout: int = int(os.getenv("OPENAI_TIMEOUT", "60"))
    request_retries: int = int(os.getenv("OPENAI_RETRIES", "2"))
    memory_enabled: bool = os.getenv("MEMORY_ENABLED", "1").strip() not in {"0", "false", "False"}
    memory_limit: int = int(os.getenv("MEMORY_LIMIT", "24"))


EMOJI_REPLACEMENTS = {
    "?": "",
    "?": "",
    "??": "",
    "??": "",
    "??": "",
    "??": "",
    "??": "",
    "??": "",
    "?": "",
    "??": "",
    "??": "",
}


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
    cleaned = cleaned.replace("?", "")
    cleaned = re.sub(r"[★☆????????????????]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def sanitize_tts_text(text: str) -> str:
    cleaned = text.strip()
    for source, target in EMOJI_REPLACEMENTS.items():
        cleaned = cleaned.replace(source, target)

    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"[*_~#>\-\[\]\(\)]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def choose_tts_voice(config: AppConfig, text: str) -> str:
    if contains_cjk(text):
        return config.voice_zh
    return config.voice_en



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clip_memory_text(text: str, limit: int = 48) -> str:
    compact = re.sub(r"\s+", " ", text.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


class MemoryStore:
    def __init__(self, path: Path, limit: int = 24) -> None:
        self.path = path
        self.limit = limit
        self.items: list[dict[str, str]] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.items = []
            return

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"[memory] Failed to read memory file: {self.path} error={exc}")
            self.items = []
            return

        if not isinstance(data, list):
            self.items = []
            return

        cleaned: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary", "")).strip()
            if not summary:
                continue
            cleaned.append(
                {
                    "summary": clip_memory_text(summary),
                    "category": str(item.get("category", "memory") or "memory"),
                    "source": str(item.get("source", "") or ""),
                    "updated_at": str(item.get("updated_at", "") or utc_now_iso()),
                }
            )
        self.items = cleaned[-self.limit :]

    def save(self) -> None:
        self.path.write_text(json.dumps(self.items[-self.limit :], ensure_ascii=False, indent=2), encoding="utf-8")

    def render_context(self, max_items: int = 8) -> str:
        if not self.items:
            return ""

        recent = sorted(self.items, key=lambda item: item.get("updated_at", ""), reverse=True)[:max_items]
        lines = [f"- [{item.get('category', 'memory')}] {item['summary']}" for item in recent]
        return "长期记忆（已压缩）:\n" + "\n".join(lines)

    def upsert_many(self, memories: list[dict[str, str]]) -> int:
        added = 0
        for item in memories:
            summary = clip_memory_text(str(item.get("summary", "")).strip())
            if not summary:
                continue

            category = str(item.get("category", "memory") or "memory")
            source = str(item.get("source", "") or "")
            existing = next((entry for entry in self.items if entry.get("summary") == summary), None)
            if existing is not None:
                existing["category"] = category
                existing["source"] = source
                existing["updated_at"] = utc_now_iso()
                continue

            self.items.append(
                {
                    "summary": summary,
                    "category": category,
                    "source": source,
                    "updated_at": utc_now_iso(),
                }
            )
            added += 1

        self.items = sorted(self.items, key=lambda item: item.get("updated_at", ""), reverse=True)[: self.limit]
        if memories:
            self.save()
        return added


MEMORY_TRIGGER_RE = re.compile(
    r"(我叫|你可以叫我|我是|我住在|我在|我喜欢|我不喜欢|我讨厌|我想|我要|我打算|我准备|明天|今天|最近|下周|周末|生日|工作|上班|上学|考试|面试|搬家|旅行|男朋友|女朋友|对象|老公|老婆|妈妈|爸爸|姐姐|哥哥|弟弟|妹妹|室友|同事|朋友)"
)


def heuristic_memory_candidates(user_text: str) -> list[dict[str, str]]:
    patterns = [
        (r"(?:我叫|你可以叫我)([^，。！!？?\s]{1,12})", "identity", "用户名字：{value}"),
        (r"我是([^，。！!？?]{1,20})", "identity", "用户身份：{value}"),
        (r"我喜欢([^，。！!？?]{1,24})", "preference", "用户喜欢：{value}"),
        (r"我不喜欢([^，。！!？?]{1,24})", "preference", "用户不喜欢：{value}"),
        (r"我讨厌([^，。！!？?]{1,24})", "preference", "用户讨厌：{value}"),
        (r"我在([^，。！!？?]{1,24})", "status", "用户目前在：{value}"),
        (r"我住在([^，。！!？?]{1,24})", "profile", "用户住在：{value}"),
        (r"(?:明天|今天|最近|下周|周末)([^。！!？?]{1,36})", "event", "用户近期事件：{value}"),
    ]

    candidates: list[dict[str, str]] = []
    for pattern, category, template in patterns:
        match = re.search(pattern, user_text)
        if not match:
            continue
        value = clip_memory_text(match.group(1).strip(" ，。！!？?"), 28)
        if not value:
            continue
        candidates.append({"summary": template.format(value=value), "category": category, "source": "heuristic"})

    if not candidates and len(user_text) >= 14 and contains_cjk(user_text):
        candidates.append(
            {
                "summary": "近期提到：" + clip_memory_text(user_text, 32),
                "category": "event",
                "source": "heuristic",
            }
        )

    return candidates[:3]


def should_extract_memory(user_text: str) -> bool:
    stripped = user_text.strip()
    if heuristic_memory_candidates(stripped):
        return True

    if len(stripped) < 6:
        return False

    if len(stripped) >= 16 and MEMORY_TRIGGER_RE.search(stripped):
        return True

    return False


def discover_model_path() -> Path | None:
    configured = os.getenv("LIVE2D_MODEL", "").strip()
    if configured:
        explicit = Path(configured).expanduser()
        if explicit.exists():
            return explicit.resolve()
        print(f"[resources] Configured LIVE2D_MODEL does not exist: {explicit}")

    for root in MODEL_SEARCH_DIRS:
        if not root.exists():
            continue
        for pattern in MODEL_PATTERNS:
            matches = sorted(root.rglob(pattern))
            if matches:
                return matches[0].resolve()

    print(f"[resources] No model file found under: {MODEL_SEARCH_DIRS}")
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


def to_file_url(path: Path | None, *, directory: bool = False) -> str:
    if path is None:
        return ""
    url = QUrl.fromLocalFile(str(path)).toString()
    if directory and not url.endswith("/"):
        url += "/"
    return url


def print_resource_report(model_path: Path | None, vendor_dir: Path | None) -> None:
    print(f"[resources] Qt API: {QT_API}")
    print(f"[resources] HTML: {HTML_PATH}")
    print(f"[resources] Model: {model_path or 'NOT FOUND'}")
    print(f"[resources] Vendor: {vendor_dir or 'NOT FOUND'}")

    if vendor_dir is None:
        return

    pixi_path = vendor_dir / "pixi.min.js"
    core_min_path = vendor_dir / "live2dcubismcore.min.js"
    core_path = vendor_dir / "live2dcubismcore.js"
    print(f"[resources] PIXI exists={pixi_path.exists()} path={pixi_path}")
    print(f"[resources] Cubism core min exists={core_min_path.exists()} path={core_min_path}")
    print(f"[resources] Cubism core exists={core_path.exists()} path={core_path}")

    for candidate in LIVE2D_LOADER_CANDIDATES:
        candidate_path = vendor_dir / candidate
        print(f"[resources] Loader exists={candidate_path.exists()} path={candidate_path}")

    legacy_loader = vendor_dir / "pixi-live2d-display.min.js"
    cubism4_bundle = vendor_dir / "cubism4.min.js"
    cubism2_runtime = vendor_dir / "live2d.min.js"
    if legacy_loader.exists() and not cubism4_bundle.exists() and not cubism2_runtime.exists():
        print("[resources] Warning: 当前本地 pixi-live2d-display.min.js 是旧浏览器 bundle，单独使用会要求 live2d.min.js。渲染器将优先尝试 vendor/cubism4.min.js 或 CDN 的 Cubism4 bundle。")


def event_global_point(event) -> QPoint:
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


def set_media_source(player: QMediaPlayer, audio_path: str) -> None:
    url = QUrl.fromLocalFile(audio_path)
    if IS_QT6:
        player.setSource(url)
    else:
        player.setMedia(QMediaContent(url))


def run_app(app: QApplication) -> int:
    if hasattr(app, "exec"):
        return app.exec()
    return app.exec_()


class OpenAICompatibleClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def chat(self, messages: list[dict[str, str]]) -> str:
        if not self.config.api_key:
            return (
                "Demo mode is active. Set OPENAI_API_KEY, OPENAI_BASE_URL, and OPENAI_MODEL "
                "to enable live responses."
            )

        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 1,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }

        attempt_count = max(1, self.config.request_retries + 1)
        data = None
        for attempt in range(1, attempt_count + 1):
            request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
            print(f"[llm] Requesting {endpoint} model={self.config.model} attempt={attempt}/{attempt_count}")
            try:
                with urllib.request.urlopen(request, timeout=self.config.request_timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                details = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 401 or "invalid_authentication_error" in details:
                    raise RuntimeError(
                        "Kimi API 鉴权失败：当前 OPENAI_API_KEY 无效、已过期，或不属于 Moonshot 官方平台。"
                    ) from exc
                if exc.code == 404 and "model" in details.lower():
                    raise RuntimeError(
                        f"Kimi 模型不可用：当前配置的模型名是 {self.config.model}。"
                    ) from exc
                if exc.code == 429 or "engine_overloaded_error" in details:
                    if attempt < attempt_count:
                        delay_seconds = min(4, attempt)
                        print(f"[llm] Model busy, retrying in {delay_seconds}s.")
                        time.sleep(delay_seconds)
                        continue
                    raise RuntimeError("Kimi 最新模型当前繁忙，请稍后重试。") from exc
                raise RuntimeError(f"LLM request failed: HTTP {exc.code} {details}") from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

        if data is None:
            raise RuntimeError("LLM response was empty after retries.")

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LLM response did not include any choices.")

        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            ]
            content = "\n".join(part for part in text_parts if part).strip()

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM response content was empty.")

        return sanitize_reply_text(content.strip())

def strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned


def extract_memories_with_llm(client: OpenAICompatibleClient, user_text: str, assistant_text: str) -> list[dict[str, str]]:
    if not client.config.api_key:
        return heuristic_memory_candidates(user_text)

    endpoint = client.config.base_url.rstrip("/") + "/chat/completions"
    prompt_messages = [
        {
            "role": "system",
            "content": (
                "你是桌面陪伴助手的记忆提取器。"
                "只提取适合长期记忆的重要信息，例如用户身份、重要人物特征、稳定偏好、待办计划、关键事件。"
                "忽略寒暄、即时情绪和泛泛回答。"
                "输出必须是 JSON 数组，每项格式为 {\"summary\": string, \"category\": string}。"
                "summary 要压缩、具体、中文、20字以内。最多输出 3 条。没有重要信息就输出 []。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_message": user_text,
                    "assistant_reply": assistant_text,
                },
                ensure_ascii=False,
            ),
        },
    ]

    payload = {
        "model": client.config.model,
        "messages": prompt_messages,
        "temperature": 1,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {client.config.api_key}",
    }

    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=client.config.request_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"[memory] LLM extraction failed, falling back to heuristics: {exc}")
        return heuristic_memory_candidates(user_text)

    choices = data.get("choices") or []
    if not choices:
        return heuristic_memory_candidates(user_text)

    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        content = "\n".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
        )

    try:
        parsed = json.loads(strip_json_fence(str(content)))
    except json.JSONDecodeError:
        print(f"[memory] Could not parse extraction JSON: {content}")
        return heuristic_memory_candidates(user_text)

    if not isinstance(parsed, list):
        return heuristic_memory_candidates(user_text)

    memories: list[dict[str, str]] = []
    for item in parsed[:3]:
        if not isinstance(item, dict):
            continue
        summary = clip_memory_text(str(item.get("summary", "")).strip(), 28)
        if not summary:
            continue
        memories.append(
            {
                "summary": summary,
                "category": str(item.get("category", "memory") or "memory"),
                "source": "llm",
            }
        )

    if memories:
        return memories
    return heuristic_memory_candidates(user_text)



class ChatWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, client: OpenAICompatibleClient, messages: list[dict[str, str]]) -> None:
        super().__init__()
        self.client = client
        self.messages = messages

    @pyqtSlot()
    def run(self) -> None:
        try:
            reply = self.client.chat(self.messages)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit(reply)


class TTSWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, text: str, voice: str) -> None:
        super().__init__()
        self.text = text
        self.voice = voice

    async def _synthesize(self) -> str:
        if edge_tts is None:
            raise RuntimeError("edge-tts is not installed. Run pip install edge-tts.")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_file:
            output_path = temp_file.name

        communicate = edge_tts.Communicate(text=self.text, voice=self.voice)
        await communicate.save(output_path)
        return output_path

    @pyqtSlot()
    def run(self) -> None:
        try:
            audio_path = asyncio.run(self._synthesize())
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit(audio_path)


class MemoryWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, client: OpenAICompatibleClient, user_text: str, assistant_text: str) -> None:
        super().__init__()
        self.client = client
        self.user_text = user_text
        self.assistant_text = assistant_text

    @pyqtSlot()
    def run(self) -> None:
        try:
            memories = extract_memories_with_llm(self.client, self.user_text, self.assistant_text)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            return
        self.finished.emit(memories)


class CompanionWindow(QWidget):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.client = OpenAICompatibleClient(config)
        self.model_path = discover_model_path()
        self.vendor_dir = discover_vendor_dir()
        self.memory_store = MemoryStore(MEMORY_PATH, config.memory_limit)
        self.messages: list[dict[str, str]] = [{"role": "system", "content": config.system_prompt}]

        print_resource_report(self.model_path, self.vendor_dir)

        self.drag_offset: QPoint | None = None
        self.chat_thread: QThread | None = None
        self.chat_worker: ChatWorker | None = None
        self.tts_thread: QThread | None = None
        self.tts_worker: TTSWorker | None = None
        self.memory_thread: QThread | None = None
        self.memory_worker: MemoryWorker | None = None
        self.audio_file_path: str | None = None
        self.audio_active = False
        self.pending_user_text = ""
        self.page_ready = False
        self.busy = False

        if IS_QT6:
            self.audio_output = QAudioOutput(self)
            self.audio_output.setVolume(0.90)
            self.player = QMediaPlayer(self)
            self.player.setAudioOutput(self.audio_output)
            self.player.playbackStateChanged.connect(self.on_playback_state_changed)
            self.player.errorOccurred.connect(self.on_audio_error)
        else:
            self.audio_output = None
            self.player = QMediaPlayer(self)
            self.player.setVolume(90)
            self.player.stateChanged.connect(self.on_playback_state_changed)
            self.player.error.connect(self.on_audio_error)

        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(9000)
        self.idle_timer.timeout.connect(self.play_random_motion)

        self.setup_window()
        self.build_ui()
        self.load_live2d_scene()
        self.position_near_taskbar()

    def setup_window(self) -> None:
        flags = WINDOW_FRAMELESS | WINDOW_TOPMOST | WINDOW_TOOL
        self.setWindowFlags(flags)
        self.setAttribute(ATTR_TRANSLUCENT, True)
        self.setObjectName("root")
        self.resize(430, 720)

    def build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self.top_bar = QFrame()
        self.top_bar.setObjectName("topBar")
        self.top_bar.mousePressEvent = self.handle_drag_press
        self.top_bar.mouseMoveEvent = self.handle_drag_move
        self.top_bar.mouseReleaseEvent = self.handle_drag_release

        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(12, 8, 8, 8)
        top_layout.setSpacing(8)

        drag_label = QLabel("Drag me")
        drag_label.setObjectName("dragLabel")
        top_layout.addWidget(drag_label)
        top_layout.addStretch(1)

        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("statusLabel")
        top_layout.addWidget(self.status_label)

        close_button = QPushButton("x")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(self.close)
        top_layout.addWidget(close_button)
        root_layout.addWidget(self.top_bar)

        self.web_view = QWebEngineView()
        self.web_view.setAttribute(ATTR_TRANSLUCENT, True)
        self.web_view.setStyleSheet("background: transparent; border: 0;")
        if hasattr(self.web_view.page(), "setBackgroundColor"):
            self.web_view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        settings = self.web_view.settings()
        settings.setAttribute(WEBATTR_JAVASCRIPT, True)
        settings.setAttribute(WEBATTR_LOCAL_FILE, True)
        if WEBATTR_REMOTE is not None:
            settings.setAttribute(WEBATTR_REMOTE, True)
        settings.setAttribute(WEBATTR_WEBGL, True)
        self.web_view.loadFinished.connect(self.on_page_loaded)
        root_layout.addWidget(self.web_view, 1)

        self.reply_label = QLabel("Type a message to wake your companion.")
        self.reply_label.setWordWrap(True)
        self.reply_label.setObjectName("replyLabel")
        root_layout.addWidget(self.reply_label)

        controls = QFrame()
        controls.setObjectName("controls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(10, 10, 10, 10)
        controls_layout.setSpacing(8)

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Say something...")
        self.chat_input.returnPressed.connect(self.send_message)
        controls_layout.addWidget(self.chat_input, 1)

        send_button = QPushButton("Send")
        send_button.clicked.connect(self.send_message)
        controls_layout.addWidget(send_button)
        self.send_button = send_button

        root_layout.addWidget(controls)

        self.setStyleSheet(
            """
            QWidget#root {
                background: transparent;
                color: #f6f7fb;
                font-family: "Segoe UI";
            }
            QFrame#topBar, QFrame#controls, QLabel#replyLabel {
                background-color: rgba(15, 18, 28, 170);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 18px;
            }
            QLabel#dragLabel {
                color: rgba(255, 255, 255, 0.88);
                font-weight: 600;
            }
            QLabel#statusLabel {
                color: #b7f3cf;
                font-size: 12px;
                padding: 2px 10px;
                background-color: rgba(76, 175, 80, 40);
                border-radius: 10px;
            }
            QLabel#replyLabel {
                padding: 12px 14px;
                color: rgba(255, 255, 255, 0.94);
            }
            QLineEdit {
                min-height: 40px;
                padding: 0 14px;
                border-radius: 14px;
                background-color: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.16);
                color: white;
            }
            QPushButton {
                min-height: 40px;
                padding: 0 16px;
                border-radius: 14px;
                border: 0;
                background-color: rgba(97, 189, 255, 0.92);
                color: #08131f;
                font-weight: 700;
            }
            QPushButton#closeButton {
                min-width: 30px;
                min-height: 30px;
                padding: 0;
                border-radius: 15px;
                background-color: rgba(255, 99, 132, 0.92);
                color: white;
            }
            QPushButton:disabled {
                background-color: rgba(255, 255, 255, 0.28);
                color: rgba(255, 255, 255, 0.65);
            }
            """
        )

    def load_live2d_scene(self) -> None:
        print(f"[resources] Loading HTML from: {HTML_PATH}")
        url = QUrl.fromLocalFile(str(HTML_PATH))
        query = QUrlQuery()
        query.addQueryItem("model", to_file_url(self.model_path))
        query.addQueryItem("vendor", to_file_url(self.vendor_dir, directory=True))
        url.setQuery(query)
        self.web_view.setUrl(url)

    def position_near_taskbar(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        geometry = screen.geometry()
        target_x = available.right() - self.width() - 18
        target_y = geometry.bottom() - self.height() + 8
        self.move(max(geometry.left(), target_x), max(geometry.top(), target_y))

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def handle_drag_press(self, event) -> None:  # type: ignore[override]
        if event.button() == LEFT_BUTTON:
            self.drag_offset = event_global_point(event) - self.frameGeometry().topLeft()
            event.accept()

    def handle_drag_move(self, event) -> None:  # type: ignore[override]
        if self.drag_offset is None or not (event.buttons() & LEFT_BUTTON):
            return
        self.move(event_global_point(event) - self.drag_offset)
        event.accept()

    def handle_drag_release(self, event) -> None:  # type: ignore[override]
        self.drag_offset = None
        event.accept()

    def on_page_loaded(self, ok: bool) -> None:
        self.page_ready = ok
        if ok:
            self.set_status("Ready")
            self.idle_timer.start()
            self.play_random_motion()
            if self.model_path is None:
                self.reply_label.setText("No .model3.json or .model3 file was found under the models folder.")
        else:
            self.reply_label.setText("The Live2D renderer page could not be loaded. Check console output for path details.")

    def run_js(self, script: str) -> None:
        if not self.page_ready:
            return
        self.web_view.page().runJavaScript(script)

    def set_talking(self, talking: bool) -> None:
        state = "true" if talking else "false"
        self.run_js(f"window.Live2DController?.setTalking?.({state});")

    def play_random_motion(self) -> None:
        if self.busy:
            return
        self.run_js("window.Live2DController?.playRandomMotion?.();")

    def conversation_window(self) -> list[dict[str, str]]:
        history = self.messages[:] if len(self.messages) <= 12 else [self.messages[0], *self.messages[-11:]]
        memory_context = self.memory_store.render_context()
        if memory_context:
            return [history[0], {"role": "system", "content": memory_context}, *history[1:]]
        return history

    def send_message(self) -> None:
        user_text = self.chat_input.text().strip()
        if not user_text or self.busy:
            return

        self.busy = True
        self.chat_input.clear()
        self.chat_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.set_status("Thinking")
        self.reply_label.setText(f"You: {user_text}")
        self.pending_user_text = user_text
        self.messages.append({"role": "user", "content": user_text})
        self.set_talking(True)
        self.start_chat_worker(self.conversation_window())

    def start_chat_worker(self, payload: list[dict[str, str]]) -> None:
        self.chat_thread = QThread(self)
        self.chat_worker = ChatWorker(self.client, payload)
        self.chat_worker.moveToThread(self.chat_thread)

        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.finished.connect(self.on_chat_reply)
        self.chat_worker.error.connect(self.on_chat_error)
        self.chat_worker.finished.connect(self.chat_worker.deleteLater)
        self.chat_worker.error.connect(self.chat_worker.deleteLater)
        self.chat_worker.finished.connect(self.chat_thread.quit)
        self.chat_worker.error.connect(self.chat_thread.quit)
        self.chat_thread.finished.connect(self.chat_thread.deleteLater)
        self.chat_thread.start()

    def start_memory_worker(self, user_text: str, assistant_text: str) -> None:
        if not self.config.memory_enabled or not user_text.strip() or not assistant_text.strip():
            return
        if not should_extract_memory(user_text):
            print("[memory] Skipped extraction for low-signal message.")
            return

        if self.memory_thread is not None:
            try:
                if self.memory_thread.isRunning():
                    return
            except RuntimeError:
                self.memory_thread = None
                self.memory_worker = None

        self.memory_thread = QThread(self)
        self.memory_worker = MemoryWorker(self.client, user_text, assistant_text)
        self.memory_worker.moveToThread(self.memory_thread)

        self.memory_thread.started.connect(self.memory_worker.run)
        self.memory_worker.finished.connect(self.on_memory_ready)
        self.memory_worker.error.connect(self.on_memory_error)
        self.memory_worker.finished.connect(self.memory_worker.deleteLater)
        self.memory_worker.error.connect(self.memory_worker.deleteLater)
        self.memory_worker.finished.connect(self.memory_thread.quit)
        self.memory_worker.error.connect(self.memory_thread.quit)
        self.memory_thread.finished.connect(self.on_memory_thread_finished)
        self.memory_thread.finished.connect(self.memory_thread.deleteLater)
        self.memory_thread.start()

    def start_tts_worker(self, text: str) -> None:
        if edge_tts is None:
            self.finish_interaction()
            self.set_status("Ready")
            return

        tts_text = sanitize_tts_text(text)
        if not tts_text:
            self.finish_interaction()
            self.set_status("Ready")
            return

        voice = choose_tts_voice(self.config, tts_text)
        print(f"[tts] voice={voice} text={tts_text}")

        self.tts_thread = QThread(self)
        self.tts_worker = TTSWorker(tts_text, voice)
        self.tts_worker.moveToThread(self.tts_thread)

        self.tts_thread.started.connect(self.tts_worker.run)
        self.tts_worker.finished.connect(self.on_tts_ready)
        self.tts_worker.error.connect(self.on_tts_error)
        self.tts_worker.finished.connect(self.tts_worker.deleteLater)
        self.tts_worker.error.connect(self.tts_worker.deleteLater)
        self.tts_worker.finished.connect(self.tts_thread.quit)
        self.tts_worker.error.connect(self.tts_thread.quit)
        self.tts_thread.finished.connect(self.tts_thread.deleteLater)
        self.tts_thread.start()

    def on_chat_reply(self, reply: str) -> None:
        self.messages.append({"role": "assistant", "content": reply})
        self.reply_label.setText(f"Companion: {reply}")
        self.start_memory_worker(self.pending_user_text, reply)
        self.pending_user_text = ""
        self.set_status("Speaking")
        self.start_tts_worker(reply)

    def on_chat_error(self, error_text: str) -> None:
        self.reply_label.setText(error_text)
        self.set_status("Error")
        self.finish_interaction()

    def on_tts_ready(self, audio_path: str) -> None:
        self.audio_file_path = audio_path
        self.audio_active = True
        set_media_source(self.player, audio_path)
        self.player.play()

    def on_tts_error(self, error_text: str) -> None:
        self.reply_label.setText(f"{self.reply_label.text()}\n\n[TTS] {error_text}")
        self.set_status("Ready")
        self.finish_interaction()

    def on_memory_thread_finished(self) -> None:
        self.memory_thread = None
        self.memory_worker = None

    def on_memory_ready(self, memories: list[dict[str, str]]) -> None:
        added = self.memory_store.upsert_many(memories)
        if added:
            print(f"[memory] Stored {added} new memories in {MEMORY_PATH}")

    def on_memory_error(self, error_text: str) -> None:
        print(f"[memory] Worker error: {error_text}")

    def on_audio_error(self, *args) -> None:
        error_text = ""
        if IS_QT6:
            if len(args) >= 2:
                error_text = str(args[1])
        else:
            if hasattr(self.player, "errorString"):
                error_text = self.player.errorString()
            elif args:
                error_text = str(args[0])

        if error_text:
            self.reply_label.setText(f"{self.reply_label.text()}\n\n[Audio] {error_text}")
        self.finish_audio_playback()

    def on_playback_state_changed(self, state) -> None:
        if self.audio_active and state == PLAYBACK_STOPPED:
            self.finish_audio_playback()

    def finish_audio_playback(self) -> None:
        self.audio_active = False
        self.pending_user_text = ""
        self.set_status("Idle")
        self.finish_interaction()
        if self.audio_file_path:
            try:
                Path(self.audio_file_path).unlink(missing_ok=True)
            except OSError:
                pass
            self.audio_file_path = None

    def finish_interaction(self) -> None:
        self.busy = False
        self.chat_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.chat_input.setFocus()
        self.set_talking(False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.idle_timer.stop()
        self.player.stop()
        if self.audio_file_path:
            try:
                Path(self.audio_file_path).unlink(missing_ok=True)
            except OSError:
                pass
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = CompanionWindow(AppConfig())
    window.show()
    return run_app(app)


if __name__ == "__main__":
    raise SystemExit(main())

























