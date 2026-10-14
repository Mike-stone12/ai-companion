from __future__ import annotations

import json
import logging
import os
import sys
from collections import deque
from pathlib import Path

from PyQt6.QtCore import PYQT_VERSION_STR, QPoint, Qt, QThread, QTimer, QUrl, QUrlQuery
from PyQt6.QtGui import QColor
from PyQt6.QtWebChannel import QWebChannel
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

from companion.adapters import tts_edge
from companion.app.workers import ChatStreamWorker, MemoryWorker, TTSWorker
from companion.core.config import AppConfig
from companion.core.llm.client import OpenAICompatibleClient
from companion.core.memory.gate import should_extract_memory
from companion.core.memory.store import MemoryStore
from companion.core.model_profile import (
    DEFAULT_WINDOW_SIZE,
    discover_model_profile,
    discover_vendor_dir,
)
from companion.core.text import sanitize_reply_text, sanitize_tts_text
from companion.paths import HTML_PATH, MEMORY_PATH
from companion.ui.avatar_bridge import AvatarBridge

logger = logging.getLogger(__name__)


LIVE2D_LOADER_CANDIDATES = (
    "pixi-live2d-display.min.js",
    "pixi-live2d-display.js",
    "live2d.min.js",
    "cubism4.min.js",
    "live2dcubismframework.js",
)


MEMORY_QUEUE_LIMIT = 5
# Safety net if playback stops making progress (e.g. the renderer crashed).
AUDIO_WATCHDOG_MS = 120_000


def to_file_url(path: Path | None, *, directory: bool = False) -> str:
    if path is None:
        return ""
    url = QUrl.fromLocalFile(str(path)).toString()
    if directory and not url.endswith("/"):
        url += "/"
    return url


def print_resource_report(model_path: Path | None, vendor_dir: Path | None) -> None:
    logger.info("Qt: PyQt6 %s", PYQT_VERSION_STR)
    logger.info("HTML: %s", HTML_PATH)
    logger.info("Model: %s", model_path or "NOT FOUND")
    logger.info("Vendor: %s", vendor_dir or "NOT FOUND")

    if vendor_dir is None:
        return

    pixi_path = vendor_dir / "pixi.min.js"
    core_min_path = vendor_dir / "live2dcubismcore.min.js"
    core_path = vendor_dir / "live2dcubismcore.js"
    logger.debug("PIXI exists=%s path=%s", pixi_path.exists(), pixi_path)
    logger.debug("Cubism core min exists=%s path=%s", core_min_path.exists(), core_min_path)
    logger.debug("Cubism core exists=%s path=%s", core_path.exists(), core_path)

    for candidate in LIVE2D_LOADER_CANDIDATES:
        candidate_path = vendor_dir / candidate
        logger.debug("Loader exists=%s path=%s", candidate_path.exists(), candidate_path)

    legacy_loader = vendor_dir / "pixi-live2d-display.min.js"
    cubism4_bundle = vendor_dir / "cubism4.min.js"
    cubism2_runtime = vendor_dir / "live2d.min.js"
    if legacy_loader.exists() and not cubism4_bundle.exists() and not cubism2_runtime.exists():
        logger.warning(
            "vendor/pixi-live2d-display.min.js is the legacy browser bundle and needs live2d.min.js; "
            "the renderer will try vendor/cubism4.min.js or the pinned CDN copy instead."
        )


class CompanionWindow(QWidget):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.client = OpenAICompatibleClient(config)
        self.model_profile = discover_model_profile(os.getenv("LIVE2D_MODEL", "").strip())
        self.model_path = self.model_profile.path if self.model_profile else None
        self.vendor_dir = discover_vendor_dir()
        self.memory_store = MemoryStore(MEMORY_PATH, config.memory_limit)
        self.messages: list[dict[str, str]] = [{"role": "system", "content": config.system_prompt}]

        print_resource_report(self.model_path, self.vendor_dir)

        self.drag_offset: QPoint | None = None
        self.chat_thread: QThread | None = None
        self.chat_worker: ChatStreamWorker | None = None
        self.tts_thread: QThread | None = None
        self.tts_worker: TTSWorker | None = None
        self.memory_thread: QThread | None = None
        self.memory_worker: MemoryWorker | None = None
        self.memory_jobs: deque[tuple[str, str]] = deque(maxlen=MEMORY_QUEUE_LIMIT)
        self.tts_queue: deque[str] = deque()
        self.pending_clips: dict[str, str] = {}
        self.reply_parts: list[str] = []
        self.reply_notes: list[str] = []
        self.stream_done = True
        self.speak_reply = False
        self.speech_started = False
        self.finish_status = "Idle"
        self.pending_user_text = ""
        self.renderer_ready = False
        self.busy = False

        self.bridge = AvatarBridge(self)
        self.bridge.ready.connect(self.on_renderer_ready)
        self.bridge.audioStarted.connect(self.on_audio_started)
        self.bridge.audioFinished.connect(self.on_audio_finished)
        self.bridge.audioFailed.connect(self.on_audio_error)

        self.audio_watchdog = QTimer(self)
        self.audio_watchdog.setSingleShot(True)
        self.audio_watchdog.timeout.connect(self.on_audio_watchdog)

        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(9000)
        self.idle_timer.timeout.connect(self.play_random_motion)

        self.setup_window()
        self.build_ui()
        self.load_live2d_scene()
        self.position_near_taskbar()

    def setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("root")
        self.resize(*(self.model_profile.window_size if self.model_profile else DEFAULT_WINDOW_SIZE))

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
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.web_view.setStyleSheet("background: transparent; border: 0;")
        self.web_view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        # Replies are spoken by the renderer without a click, so allow autoplay.
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.web_channel = QWebChannel(self.web_view.page())
        self.web_channel.registerObject("avatar", self.bridge)
        self.web_view.page().setWebChannel(self.web_channel)
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
        logger.debug("Loading HTML from: %s", HTML_PATH)
        url = QUrl.fromLocalFile(str(HTML_PATH))
        query = QUrlQuery()
        query.addQueryItem("model", to_file_url(self.model_path))
        query.addQueryItem("vendor", to_file_url(self.vendor_dir, directory=True))
        if self.model_profile and self.model_profile.motions:
            query.addQueryItem("motions", json.dumps(self.model_profile.motions, ensure_ascii=False))
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def handle_drag_move(self, event) -> None:  # type: ignore[override]
        if self.drag_offset is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        self.move(event.globalPosition().toPoint() - self.drag_offset)
        event.accept()

    def handle_drag_release(self, event) -> None:  # type: ignore[override]
        self.drag_offset = None
        event.accept()

    def on_page_loaded(self, ok: bool) -> None:
        if not ok:
            self.reply_label.setText(
                "The Live2D renderer page could not be loaded. Check console output for path details."
            )
        elif self.model_path is None:
            self.reply_label.setText("No .model3.json or .model3 file was found under the models folder.")

    def on_renderer_ready(self) -> None:
        logger.info("Renderer connected over QWebChannel")
        self.renderer_ready = True
        self.set_status("Ready")
        self.idle_timer.start()
        self.play_random_motion()

    def set_talking(self, talking: bool) -> None:
        if self.renderer_ready:
            self.bridge.setTalking.emit(talking)

    def play_random_motion(self) -> None:
        if self.renderer_ready and not self.busy:
            self.bridge.playRandomMotion.emit()

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
        self.reset_reply_state()
        self.start_chat_worker(self.conversation_window())

    def reset_reply_state(self) -> None:
        self.reply_parts = []
        self.reply_notes = []
        self.stream_done = False
        self.speak_reply = tts_edge.is_available() and self.renderer_ready
        self.speech_started = False
        self.finish_status = "Idle"
        self.tts_queue.clear()

    def start_chat_worker(self, payload: list[dict[str, str]]) -> None:
        self.chat_thread = QThread(self)
        self.chat_worker = ChatStreamWorker(self.client, payload)
        self.chat_worker.moveToThread(self.chat_thread)

        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.delta.connect(self.on_reply_delta)
        self.chat_worker.sentence.connect(self.on_reply_sentence)
        self.chat_worker.finished.connect(self.on_reply_finished)
        self.chat_worker.error.connect(self.on_reply_error)
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
            logger.debug("Skipped memory extraction for a low-signal message")
            return
        if len(self.memory_jobs) == self.memory_jobs.maxlen:
            logger.warning("Memory extraction queue full, dropping the oldest pending job")
        self.memory_jobs.append((user_text, assistant_text))
        self.run_next_memory_job()

    def run_next_memory_job(self) -> None:
        if self.memory_thread is not None or not self.memory_jobs:
            return
        user_text, assistant_text = self.memory_jobs.popleft()

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

    def render_reply(self) -> None:
        reply = sanitize_reply_text("".join(self.reply_parts))
        notes = "".join(f"\n\n{note}" for note in self.reply_notes)
        self.reply_label.setText(f"Companion: {reply}{notes}")

    def add_reply_note(self, note: str) -> None:
        if note not in self.reply_notes:
            self.reply_notes.append(note)
            self.render_reply()

    def on_reply_delta(self, text: str) -> None:
        if not self.reply_parts:
            self.set_status("Replying")
        self.reply_parts.append(text)
        self.render_reply()

    def on_reply_sentence(self, sentence: str) -> None:
        if not self.speak_reply:
            return
        spoken = sanitize_tts_text(sentence)
        if spoken:
            self.tts_queue.append(spoken)
            self.run_next_tts()

    def on_reply_finished(self, raw_reply: str) -> None:
        reply = sanitize_reply_text(raw_reply)
        if reply:
            self.messages.append({"role": "assistant", "content": reply})
            self.start_memory_worker(self.pending_user_text, reply)
        self.render_reply()
        self.pending_user_text = ""
        self.stream_done = True
        self.maybe_finish_reply()

    def on_reply_error(self, error_text: str) -> None:
        logger.error("Chat request failed: %s", error_text)
        partial = sanitize_reply_text("".join(self.reply_parts))
        if partial:
            self.messages.append({"role": "assistant", "content": partial})
            self.add_reply_note(f"[Interrupted] {error_text}")
        else:
            self.reply_label.setText(error_text)
            self.finish_status = "Error"
        self.pending_user_text = ""
        self.stream_done = True
        self.maybe_finish_reply()

    def run_next_tts(self) -> None:
        if self.tts_thread is not None or not self.tts_queue:
            return
        text = self.tts_queue.popleft()
        voice = tts_edge.choose_tts_voice(self.config, text)
        logger.debug("TTS voice=%s text=%s", voice, text)

        self.tts_thread = QThread(self)
        self.tts_worker = TTSWorker(text, voice)
        self.tts_worker.moveToThread(self.tts_thread)

        self.tts_thread.started.connect(self.tts_worker.run)
        self.tts_worker.finished.connect(self.on_tts_ready)
        self.tts_worker.error.connect(self.on_tts_error)
        self.tts_worker.finished.connect(self.tts_worker.deleteLater)
        self.tts_worker.error.connect(self.tts_worker.deleteLater)
        self.tts_worker.finished.connect(self.tts_thread.quit)
        self.tts_worker.error.connect(self.tts_thread.quit)
        self.tts_thread.finished.connect(self.on_tts_thread_finished)
        self.tts_thread.finished.connect(self.tts_thread.deleteLater)
        self.tts_thread.start()

    def on_tts_thread_finished(self) -> None:
        self.tts_thread = None
        self.tts_worker = None
        self.run_next_tts()
        self.maybe_finish_reply()

    def on_tts_ready(self, audio_path: str) -> None:
        if not self.speak_reply:
            delete_file(audio_path)
            return
        url = QUrl.fromLocalFile(audio_path).toString()
        self.pending_clips[url] = audio_path
        self.audio_watchdog.start(AUDIO_WATCHDOG_MS)
        self.bridge.playAudio.emit(url)

    def on_tts_error(self, error_text: str) -> None:
        logger.warning("TTS failed: %s", error_text)
        self.add_reply_note(f"[TTS] {error_text}")

    def on_memory_thread_finished(self) -> None:
        self.memory_thread = None
        self.memory_worker = None
        self.run_next_memory_job()

    def on_memory_ready(self, memories: list[dict[str, str]]) -> None:
        added = self.memory_store.upsert_many(memories)
        if added:
            logger.info("Stored %d new memories in %s", added, MEMORY_PATH)

    def on_memory_error(self, error_text: str) -> None:
        logger.error("Memory worker error: %s", error_text)

    def on_audio_started(self, url: str, duration: float) -> None:
        logger.debug("Audio started, duration=%.1fs", duration)
        if not self.speech_started:
            self.speech_started = True
            self.set_status("Speaking")
        self.audio_watchdog.start(AUDIO_WATCHDOG_MS)

    def on_audio_finished(self, url: str) -> None:
        self.release_clip(url)

    def on_audio_error(self, url: str, error_text: str) -> None:
        logger.warning("Audio playback failed: %s", error_text)
        if url in self.pending_clips:
            self.add_reply_note(f"[Audio] {error_text}")
        self.release_clip(url)

    def release_clip(self, url: str) -> None:
        path = self.pending_clips.pop(url, None)
        if path:
            delete_file(path)
        if self.pending_clips:
            self.audio_watchdog.start(AUDIO_WATCHDOG_MS)
        else:
            self.audio_watchdog.stop()
        self.maybe_finish_reply()

    def on_audio_watchdog(self) -> None:
        if not self.pending_clips:
            return
        logger.warning("Playback made no progress for %d s, dropping the rest of this reply", AUDIO_WATCHDOG_MS // 1000)
        self.bridge.stopAudio.emit()
        self.speak_reply = False
        self.tts_queue.clear()
        self.discard_pending_clips()
        self.maybe_finish_reply()

    def discard_pending_clips(self) -> None:
        for path in self.pending_clips.values():
            delete_file(path)
        self.pending_clips.clear()

    def maybe_finish_reply(self) -> None:
        if not self.busy or not self.stream_done:
            return
        if self.tts_queue or self.tts_thread is not None or self.pending_clips:
            return
        self.audio_watchdog.stop()
        self.set_status(self.finish_status)
        self.finish_interaction()

    def finish_interaction(self) -> None:
        self.busy = False
        self.chat_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.chat_input.setFocus()
        self.set_talking(False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.idle_timer.stop()
        self.audio_watchdog.stop()
        self.bridge.stopAudio.emit()
        self.speak_reply = False
        self.tts_queue.clear()
        self.discard_pending_clips()
        super().closeEvent(event)


def delete_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def main() -> int:
    app = QApplication(sys.argv)
    window = CompanionWindow(AppConfig())
    window.show()
    return app.exec()
