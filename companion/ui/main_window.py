from __future__ import annotations

import json
import logging
import random
import sys
from collections import deque
from collections.abc import Callable
from copy import copy
from dataclasses import replace
from datetime import timedelta
from functools import partial
from pathlib import Path

from PyQt6.QtCore import PYQT_VERSION_STR, QPoint, QRect, Qt, QThread, QTimer, QUrl, QUrlQuery, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from companion.adapters import tts_edge
from companion.adapters.active_app import foreground_app_name
from companion.app.workers import (
    AppraisalWorker,
    ChatStreamWorker,
    MemoryWorker,
    SummaryWorker,
    TranscriptionWorker,
    TTSWorker,
)
from companion.core.api_key import ApiKeyStore
from companion.core.chat.emotion import EMOTION_INSTRUCTION
from companion.core.chat.history import ConversationHistory, ConversationSummary, display_text
from companion.core.chat.summary import build_chat_messages, plan_summary_update
from companion.core.config import AppConfig
from companion.core.llm.client import OpenAICompatibleClient
from companion.core.llm.transcription import transcribe
from companion.core.memory.browser import MemoryBrowserModel
from companion.core.memory.gate import should_extract_memory
from companion.core.memory.semantic_recall import create_session_embedder
from companion.core.memory.store import MemoryStore
from companion.core.model_profile import (
    DEFAULT_WINDOW_SIZE,
    discover_model_profile,
    discover_vendor_dir,
)
from companion.core.persona import BuiltinPersonas, Persona, PersonaStore, effective_system_prompt
from companion.core.proactive.session import ProactiveSession, proactive_request
from companion.core.schedule import block_at, presence_label
from companion.core.settings_form import SettingsForm
from companion.core.state import (
    StateStore,
    active_reasons,
    apply_events,
    apply_reply_tag,
    enter_care_mode,
    idle_emotion,
    looks_distressed,
    record_user_message,
    render_state_context,
    should_appraise,
    state_summary_lines,
)
from companion.core.text import sanitize_reply_text, sanitize_tts_text
from companion.core.tools.builtin import build_builtin_registry
from companion.core.tools.reminders import ReminderStore, local_now
from companion.core.voice_input_actions import can_start_voice_input, deliver_voice_input_result
from companion.core.voice_input_controller import VoiceInputController, VoiceInputResult
from companion.core.wake_word_actions import wake_word_enabled
from companion.core.window_state import (
    OPACITY_STEPS,
    SCALE_STEPS,
    Rect,
    fits_on_screens,
    load_window_state,
    resized_rect,
    save_window_state,
    scaled_size,
)
from companion.paths import CONFIG_PATH, DATA_DIR, HISTORY_PATH, HTML_PATH, MEMORY_PATH, PERSONA_PATH, STATE_PATH
from companion.ui.avatar_bridge import AvatarBridge
from companion.ui.chat_panel import ChatPanel
from companion.ui.memory_dialog import MemoryDialog
from companion.ui.persona_dialog import PersonaDialog
from companion.ui.settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)


LIVE2D_LOADER_CANDIDATES = (
    "pixi-live2d-display.min.js",
    "pixi-live2d-display.js",
    "live2d.min.js",
    "cubism4.min.js",
    "live2dcubismframework.js",
)


MEMORY_QUEUE_LIMIT = 5
CONVERSATION_WINDOW = 11  # Individual messages, excluding system and memory context.
CHAT_PANEL_HEIGHT = 170  # at scale 1.0
MIN_CHAT_PANEL_HEIGHT = 110
# Safety net if playback stops making progress (e.g. the renderer crashed).
AUDIO_WATCHDOG_MS = 120_000
WAKE_CAPTURE_MS = 5_000


def to_file_url(path: Path | None, *, directory: bool = False) -> str:
    if path is None:
        return ""
    url = QUrl.fromLocalFile(str(path)).toString()
    if directory and not url.endswith("/"):
        url += "/"
    return url


def rect_tuple(rect: QRect) -> Rect:
    return rect.x(), rect.y(), rect.width(), rect.height()


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
    wake_stop_requested = pyqtSignal()
    wake_reset_requested = pyqtSignal()

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.client = OpenAICompatibleClient(config)
        # Tools and proactive triggers share a store; only CHAT_TOOLS enables persistence.
        reminders = None
        if config.chat_tools or config.proactive_chat:
            reminders = ReminderStore(data_dir=DATA_DIR if config.chat_tools else None)
        self.tool_registry = build_builtin_registry(reminders) if config.chat_tools else None
        self.model_profile = discover_model_profile(config.live2d_model)
        self.model_path = self.model_profile.path if self.model_profile else None
        self.vendor_dir = discover_vendor_dir()
        self.base_size = self.model_profile.window_size if self.model_profile else DEFAULT_WINDOW_SIZE
        self.window_state = load_window_state(CONFIG_PATH)
        self.memory_store = MemoryStore(MEMORY_PATH, config.memory_limit)
        self.memory_embedder = create_session_embedder(config)
        self.history = ConversationHistory(HISTORY_PATH)
        self.personas = BuiltinPersonas()
        self.persona_store = PersonaStore(PERSONA_PATH, self.personas)
        self.persona = self.persona_store.active(self.personas)
        self.messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_message()}, *self.history.messages(),
        ]
        # The companion's own mood and last contact (companion/core/state); None when turned off.
        self.state_store = StateStore(STATE_PATH) if config.companion_state else None
        self.companion_state = self.state_store.load(local_now()) if self.state_store else None
        self.idle_face: str | None = None
        self.emotion_rng = random.Random()
        self.appraisal_thread: QThread | None = None
        self.appraisal_worker: AppraisalWorker | None = None

        print_resource_report(self.model_path, self.vendor_dir)

        self.drag_offset: QPoint | None = None
        self.chat_thread: QThread | None = None
        self.chat_worker: ChatStreamWorker | None = None
        self.tts_thread: QThread | None = None
        self.tts_worker: TTSWorker | None = None
        self.memory_thread: QThread | None = None
        self.memory_worker: MemoryWorker | None = None
        self.summary_thread: QThread | None = None
        self.summary_worker: SummaryWorker | None = None
        self.summary_snapshot: tuple[int, int, ConversationSummary | None] | None = None
        self.memory_jobs: deque[tuple[str, str]] = deque(maxlen=MEMORY_QUEUE_LIMIT)
        self.tts_queue: deque[str] = deque()
        self.pending_clips: dict[str, str] = {}
        self.reply_parts: list[str] = []
        self.reply_notes: list[str] = []
        self.reply_emotion: str | None = None
        self.stream_done = True
        self.speak_reply = False
        self.speech_started = False
        self.finish_status = "Idle"
        self.pending_user_text = ""
        self.renderer_ready = False
        self.busy = False
        self.closing = False
        self.voice_session: VoiceInputController | None = None
        self.microphone = None
        self.talk_button = None
        self.transcription_thread: QThread | None = None
        self.transcription_worker: TranscriptionWorker | None = None
        self.wake_thread: QThread | None = None
        self.wake_worker = None
        self.wake_microphone = None
        self.wake_indicator = None
        self.wake_capture_timer = None
        self.wake_ready = False
        self.wake_listening = False
        self.wake_failed = False

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

        # The mood fades with time, so the idle face is rechecked even when nobody talks.
        self.mood_timer = QTimer(self)
        self.mood_timer.setInterval(60_000)
        self.mood_timer.timeout.connect(self.refresh_idle_emotion)
        self.mood_timer.timeout.connect(self.refresh_presence)
        if self.companion_state is not None or config.daily_schedule:
            self.mood_timer.start()

        self.setup_window()
        self.build_ui()
        self.load_live2d_scene()
        self.restore_position()
        self.refresh_presence()
        self.setup_proactive(reminders)
        self.setup_wake_word()

    def setup_wake_word(self) -> None:
        if not wake_word_enabled(self.config):
            return
        from companion.adapters.microphone import Microphone
        from companion.app.wake_word_worker import WakeWordWorker

        self.wake_indicator = QLabel("Wake word on")
        self.wake_indicator.setTextFormat(Qt.TextFormat.PlainText)
        self.wake_indicator.setStyleSheet("color: #b7f3cf; font-size: 11px;")
        self.wake_indicator.hide()
        self.top_bar.layout().insertWidget(1, self.wake_indicator)
        self.wake_capture_timer = QTimer(self)
        self.wake_capture_timer.setSingleShot(True)
        self.wake_capture_timer.timeout.connect(self.stop_voice_input)
        self.wake_microphone = Microphone(self)
        self.wake_microphone.failed.connect(self.on_wake_error)
        self.wake_thread = QThread(self)
        self.wake_worker = WakeWordWorker(self.config)
        self.wake_worker.moveToThread(self.wake_thread)
        queued = Qt.ConnectionType.QueuedConnection
        self.wake_thread.started.connect(self.wake_worker.start, queued)
        self.wake_microphone.pcm_ready.connect(self.wake_worker.feed, queued)
        self.wake_stop_requested.connect(self.wake_worker.stop, queued)
        self.wake_reset_requested.connect(self.wake_worker.reset, queued)
        self.wake_worker.started.connect(self.on_wake_started)
        self.wake_worker.wakeDetected.connect(self.on_wake_detected)
        self.wake_worker.error.connect(self.on_wake_error)
        self.wake_worker.finished.connect(self.on_wake_finished)
        # Direct quit also works while closeEvent is waiting on the UI thread.
        self.wake_worker.finished.connect(self.wake_thread.quit, Qt.ConnectionType.DirectConnection)
        self.wake_thread.finished.connect(self.wake_worker.deleteLater)
        self.wake_thread.finished.connect(self.on_wake_thread_finished)
        self.wake_thread.finished.connect(self.wake_thread.deleteLater)
        self.wake_thread.start()

    def on_wake_started(self) -> None:
        if self.closing or self.wake_failed:
            self.wake_stop_requested.emit()
            return
        self.wake_ready = True
        self.resume_wake_word()

    def pause_wake_word(self) -> None:
        if self.wake_microphone is None:
            return
        self.wake_listening = False
        self.wake_indicator.hide()
        self.wake_microphone.stop()

    def resume_wake_word(self) -> None:
        if not self.wake_ready or self.wake_failed or self.closing or self.wake_listening:
            return
        if (
            self.busy or not self.stream_done or self.tts_thread is not None
            or self.tts_queue or self.pending_clips or self.transcription_thread is not None
            or self.voice_session.state != "idle"
        ):
            return
        # Discard partial utterances from before capture/playback before feeding new PCM.
        self.wake_reset_requested.emit()
        if self.wake_microphone.start() and not self.wake_failed:
            self.wake_listening = True
            self.wake_indicator.show()

    def on_wake_detected(self, _phrase: str) -> None:
        if not self.wake_listening or self.closing or self.wake_failed:
            return
        if (
            self.busy or not self.stream_done or self.tts_thread is not None
            or self.tts_queue or self.pending_clips or self.transcription_thread is not None
            or self.voice_session.state != "idle" or self.chat_input.text()
        ):
            return
        self.start_voice_input()
        if self.voice_session.state == "recording":
            self.chat_panel.add_notice("Listening…")
            self.wake_capture_timer.start(WAKE_CAPTURE_MS)

    def on_wake_error(self, message: str) -> None:
        if self.wake_failed:
            return
        self.wake_failed = True
        logger.warning("Wake word disabled for this session: %s", message)
        self.on_wake_finished()
        self.wake_stop_requested.emit()

    def on_wake_finished(self) -> None:
        self.wake_ready = False
        self.pause_wake_word()

    def on_wake_thread_finished(self) -> None:
        self.on_wake_finished()
        self.wake_thread = None
        self.wake_worker = None
        if self.closing:
            self.close()

    def setup_proactive(self, reminders: ReminderStore | None) -> None:
        self.proactive = None
        self.proactive_timer = None
        if self.config.proactive_chat:
            self.proactive = ProactiveSession(
                reminders, local_now(), proactive_chat=self.config.proactive_chat,
                active_app_monitor=self.config.active_app_monitor,
                # Asleep per the daily routine: only reminders may wake the companion up.
                awake=self.is_awake if self.config.daily_schedule else None,
            )
            self.proactive_timer = QTimer(self)
            self.proactive_timer.setInterval(30_000)
            self.proactive_timer.timeout.connect(self.on_proactive_tick)
            self.proactive_timer.start()

    def on_proactive_tick(self) -> None:
        if self.proactive is None:
            return
        now = local_now()
        if self.proactive.active_app is not None:
            try:
                app_name = foreground_app_name()
            except Exception:
                logger.debug("Foreground application query failed; skipping sample", exc_info=True)
            else:
                if app_name is None:
                    logger.debug("Foreground application unavailable; skipping sample")
                else:
                    self.proactive.active_app.record_sample(app_name, now)
        busy = bool(
            self.busy or not self.stream_done or self.tts_thread is not None
            or self.tts_queue or self.pending_clips
        )
        result = self.proactive.tick(now, busy=busy, input_has_text=bool(self.chat_input.text()))
        if result is None or busy:
            return
        self.busy = True
        self.pause_wake_word()
        self.chat_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.set_status("Thinking")
        self.pending_user_text = ""
        self.reset_reply_state()
        self.start_chat_worker(proactive_request(self.conversation_window(defer=True), result))

    def setup_window(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("root")
        self.resize(*scaled_size(self.base_size, self.window_state.scale))
        self.setWindowOpacity(self.window_state.opacity)

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

        # What the companion is up to, from its daily routine (hidden when that is off).
        self.presence_label = QLabel("")
        self.presence_label.setObjectName("presenceLabel")
        self.presence_label.setTextFormat(Qt.TextFormat.PlainText)
        top_layout.addWidget(self.presence_label)
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
        # Chromium would otherwise pop its own Back/Reload/Inspect menu over the avatar. The view
        # does not pass context-menu events up to its parent, so hook its signal instead.
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(
            lambda pos: self.show_context_menu(self.web_view.mapToGlobal(pos))
        )
        root_layout.addWidget(self.web_view, 1)

        self.chat_panel = ChatPanel()
        self.chat_panel.setFixedHeight(self.chat_panel_height())
        root_layout.addWidget(self.chat_panel)
        if self.history.entries:
            self.chat_panel.load([(entry["role"], display_text(entry)) for entry in self.history.entries])
        else:
            self.chat_panel.add_notice("Type a message to wake your companion.")

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
        self.setup_voice_input(controls_layout)

        root_layout.addWidget(controls)

        self.setStyleSheet(
            """
            QWidget#root {
                background: transparent;
                color: #f6f7fb;
                font-family: "Segoe UI";
            }
            QFrame#topBar, QFrame#controls {
                background-color: rgba(15, 18, 28, 170);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 18px;
            }
            QScrollArea#chatPanel, QWidget#chatContainer {
                background: transparent;
            }
            QLabel#userBubble, QLabel#assistantBubble {
                padding: 7px 11px;
                border-radius: 12px;
            }
            QLabel#userBubble {
                background-color: rgba(97, 189, 255, 0.92);
                color: #08131f;
            }
            QLabel#assistantBubble {
                background-color: rgba(15, 18, 28, 200);
                border: 1px solid rgba(255, 255, 255, 28);
                color: rgba(255, 255, 255, 0.94);
            }
            QLabel#noticeBubble {
                padding: 3px 9px;
                border-radius: 8px;
                background-color: rgba(0, 0, 0, 0.35);
                color: rgba(255, 255, 255, 0.7);
                font-size: 11px;
            }
            QLabel#dragLabel {
                color: rgba(255, 255, 255, 0.88);
                font-weight: 600;
            }
            QLabel#presenceLabel {
                color: rgba(255, 255, 255, 0.7);
                font-size: 11px;
            }
            QLabel#statusLabel {
                color: #b7f3cf;
                font-size: 12px;
                padding: 2px 10px;
                background-color: rgba(76, 175, 80, 40);
                border-radius: 10px;
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
            QMenu {
                background-color: rgb(22, 26, 38);
                border: 1px solid rgba(255, 255, 255, 40);
                padding: 6px;
                color: #f6f7fb;
            }
            QMenu::item {
                padding: 6px 28px 6px 12px;
                border-radius: 6px;
            }
            QMenu::item:selected {
                background-color: rgba(97, 189, 255, 90);
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 30);
                margin: 4px 6px;
            }
            """
        )

    def setup_voice_input(self, layout: QHBoxLayout) -> None:
        if not self.config.voice_input_usable:
            return
        # Keep QtMultimedia and audio-device construction behind the opt-in gate.
        from companion.adapters.microphone import Microphone

        self.voice_session = VoiceInputController(
            self.config,
            partial(
                transcribe, base_url=self.config.base_url, api_key=self.config.api_key,
                model=self.config.transcription_model.strip(),
            ),
        )
        self.microphone = Microphone(self)
        self.microphone.pcm_ready.connect(self.voice_session.feed)
        self.microphone.failed.connect(self.on_microphone_failed)
        self.talk_button = QPushButton("Hold to talk")
        self.talk_button.pressed.connect(self.start_voice_input)
        self.talk_button.released.connect(self.stop_voice_input)
        layout.addWidget(self.talk_button)

    def start_voice_input(self) -> None:
        if self.voice_session is None or not can_start_voice_input(
            busy=self.busy, worker_active=self.transcription_thread is not None, closing=self.closing,
        ):
            return
        self.voice_session.start()
        if self.voice_session.state != "recording":
            return
        # Reserve this turn so typed input and proactive replies cannot race transcription.
        self.busy = True
        self.pause_wake_word()
        self.chat_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.set_status("Listening")
        self.microphone.start()

    def stop_voice_input(self) -> None:
        if self.wake_capture_timer is not None:
            self.wake_capture_timer.stop()
        if self.voice_session is None or self.voice_session.state != "recording":
            return
        # stop() delivers the last buffered PCM synchronously before finalizing the clip.
        self.microphone.stop()
        if self.voice_session.state != "recording":
            return  # A final microphone read failure cancelled the recording.
        self.talk_button.setEnabled(False)
        self.set_status("Transcribing")
        self.transcription_thread = QThread(self)
        self.transcription_worker = TranscriptionWorker(None, self.config, session=self.voice_session)
        self.transcription_worker.moveToThread(self.transcription_thread)
        self.transcription_thread.started.connect(self.transcription_worker.run)
        self.transcription_worker.session_finished.connect(self.on_voice_input_result)
        self.transcription_worker.session_finished.connect(self.transcription_worker.deleteLater)
        # quit() is thread-safe; direct delivery also lets the bounded close wait finish.
        self.transcription_worker.session_finished.connect(
            self.transcription_thread.quit, Qt.ConnectionType.DirectConnection,
        )
        self.transcription_thread.finished.connect(self.on_transcription_thread_finished)
        self.transcription_thread.finished.connect(self.transcription_thread.deleteLater)
        self.transcription_thread.start()

    def on_microphone_failed(self, message: str) -> None:
        if self.voice_session is None or self.voice_session.state != "recording":
            return
        self.voice_session.cancel()
        if self.wake_capture_timer is not None:
            self.wake_capture_timer.stop()
        if self.closing:
            return
        self.chat_panel.add_notice(message)
        self.set_status("Idle")
        self.finish_interaction()

    def on_voice_input_result(self, result: VoiceInputResult) -> None:
        if self.closing:
            return
        self.set_status("Idle")
        self.finish_interaction()
        deliver_voice_input_result(result, self.submit_message, self.chat_panel.add_notice)

    def on_transcription_thread_finished(self) -> None:
        self.transcription_thread = None
        self.transcription_worker = None
        if self.closing:
            self.close()
        else:
            self.talk_button.setEnabled(True)
            self.resume_wake_word()

    def load_live2d_scene(self) -> None:
        logger.debug("Loading HTML from: %s", HTML_PATH)
        url = QUrl.fromLocalFile(str(HTML_PATH))
        query = QUrlQuery()
        query.addQueryItem("model", to_file_url(self.model_path))
        query.addQueryItem("vendor", to_file_url(self.vendor_dir, directory=True))
        if self.model_profile and self.model_profile.motions:
            query.addQueryItem("motions", json.dumps(self.model_profile.motions, ensure_ascii=False))
        if self.model_profile and self.model_profile.expressions:
            query.addQueryItem("expressions", json.dumps(self.model_profile.expressions, ensure_ascii=False))
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

    # --- placement: position, size, opacity (persisted under "window" in config.json) ---

    def screen_rects(self) -> list[Rect]:
        return [rect_tuple(screen.availableGeometry()) for screen in QApplication.screens()]

    def restore_position(self) -> None:
        state = self.window_state
        if state.has_position:
            if fits_on_screens((state.x, state.y, self.width(), self.height()), self.screen_rects()):
                self.move(state.x, state.y)
                return
            logger.info("Saved window position (%d, %d) is off every screen, using the default", state.x, state.y)
        self.position_near_taskbar()

    def save_window_state(self) -> None:
        self.window_state.x, self.window_state.y = self.pos().x(), self.pos().y()
        save_window_state(CONFIG_PATH, self.window_state)

    def chat_panel_height(self) -> int:
        return max(MIN_CHAT_PANEL_HEIGHT, round(CHAT_PANEL_HEIGHT * self.window_state.scale))

    def set_scale(self, scale: float) -> None:
        self.window_state.scale = scale
        screen = self.screen() or QApplication.primaryScreen()
        screen_rect = rect_tuple(screen.geometry()) if screen else rect_tuple(self.geometry())
        target = resized_rect(rect_tuple(self.geometry()), scaled_size(self.base_size, scale), screen_rect)
        self.chat_panel.setFixedHeight(self.chat_panel_height())
        self.setGeometry(*target)  # the renderer refits the model on its resize event
        self.save_window_state()

    def set_opacity(self, opacity: float) -> None:
        self.window_state.opacity = opacity
        self.setWindowOpacity(opacity)
        self.save_window_state()

    def reset_position(self) -> None:
        self.position_near_taskbar()
        self.save_window_state()

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        self.show_context_menu(event.globalPos())
        event.accept()

    def show_context_menu(self, global_pos: QPoint) -> QMenu:
        menu = QMenu(self)
        menu.aboutToHide.connect(menu.deleteLater)
        self.add_choices(menu.addMenu("Size"), SCALE_STEPS, self.window_state.scale, self.set_scale)
        self.add_choices(menu.addMenu("Opacity"), OPACITY_STEPS, self.window_state.opacity, self.set_opacity)
        menu.addSeparator()
        menu.addAction("Reset position", self.reset_position)
        menu.addAction("Persona…", self.show_persona_dialog)
        menu.addAction("Companion state…", self.show_state)
        menu.addAction("Settings…", self.show_settings)
        menu.addAction("Memories…", self.show_memories)
        menu.addSeparator()
        menu.addAction("Quit", self.close)
        menu.popup(global_pos)
        return menu

    def show_settings(self) -> None:
        api_keys = ApiKeyStore()
        dialog = SettingsDialog(SettingsForm(CONFIG_PATH), self, api_keys=api_keys)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.chat_panel.add_notice("Settings saved. Changes apply on the next start.")
        if dialog.api_key_changed:
            # The chat client reads config.api_key on every request.
            self.config.api_key = api_keys.resolve().value
            self.chat_panel.add_notice("API key updated." if self.config.api_key else "No API key is set now.")
        dialog.deleteLater()

    def system_message(self) -> str:
        return f"{effective_system_prompt(self.config.system_prompt, self.persona)}\n\n{EMOTION_INSTRUCTION}"

    def needs_persona_setup(self) -> bool:
        return not self.config.system_prompt and not self.persona_store.exists()

    def apply_persona(self, persona: Persona) -> None:
        self.persona_store.save(persona)
        self.persona = persona
        # Proactive turns and summaries read messages[0], so they follow the new persona too.
        self.messages[0] = {"role": "system", "content": self.system_message()}
        if self.config.system_prompt:
            self.chat_panel.add_notice("Persona saved, but COMPANION_SYSTEM_PROMPT is set and overrides it.")
        if hasattr(self, "presence_label"):
            self.refresh_presence()

    def show_persona_dialog(self, first_run: bool = False) -> None:
        dialog = PersonaDialog(self.personas, self.persona, self, first_run=first_run)
        try:
            if dialog.exec() == PersonaDialog.DialogCode.Accepted:
                self.apply_persona(dialog.persona())
            elif first_run:
                # "Keep default" is an answer too; do not ask again on the next start.
                self.apply_persona(self.persona)
        except OSError as exc:
            self.chat_panel.add_notice(f"Could not save the persona: {exc}")
        dialog.deleteLater()

    def current_block(self):
        if not self.config.daily_schedule:
            return None
        return block_at(self.persona.schedule, local_now())

    def is_awake(self, now) -> bool:
        block = block_at(self.persona.schedule, now)
        return block is None or block.kind != "asleep"

    def scheduled(self, state):
        """The state with what the routine says the companion is doing right now."""
        block = self.current_block()
        if block is None:
            return replace(state, activity="", availability="")
        return replace(state, activity=block.activity, availability=block.kind)

    def refresh_presence(self) -> None:
        enabled = self.config.daily_schedule
        self.presence_label.setVisible(enabled)
        if enabled:
            self.presence_label.setText(f"● {presence_label(self.current_block())}")

    def mood_half_life(self) -> timedelta:
        return timedelta(minutes=max(self.config.mood_half_life_minutes, 5))

    def state_context(self) -> str:
        state = getattr(self, "companion_state", None)
        if state is None:
            return ""
        return render_state_context(self.scheduled(state), local_now(), self.persona.traits, self.mood_half_life())

    def update_state(self, state) -> None:
        self.companion_state = state
        try:
            self.state_store.save(state)
        except OSError as exc:
            logger.warning("Could not save the companion state: %s", type(exc).__name__)
        self.refresh_idle_emotion()

    def record_user_activity(self) -> None:
        state = getattr(self, "companion_state", None)
        if state is not None:
            self.update_state(record_user_message(state, local_now(), self.persona.traits, self.mood_half_life()))

    def record_reply_mood(self) -> None:
        state = getattr(self, "companion_state", None)
        if state is not None:
            traits, base = self.persona.traits, self.mood_half_life()
            self.update_state(apply_reply_tag(state, self.reply_emotion, local_now(), traits, base))

    def refresh_idle_emotion(self) -> None:
        state = getattr(self, "companion_state", None)
        if state is None or not self.renderer_ready:
            return
        face = idle_emotion(state, local_now(), self.persona.traits, self.mood_half_life())
        if face != self.idle_face:
            self.idle_face = face
            self.bridge.setIdleEmotion.emit(face or "")

    def precheck_distress(self, user_text: str) -> None:
        """Zero-cost keyword check before the reply: the answer to an upsetting message is caring."""
        state = getattr(self, "companion_state", None)
        if state is not None and looks_distressed(user_text):
            self.update_state(enter_care_mode(state, local_now()))

    def start_appraisal_worker(self, user_text: str, assistant_text: str) -> None:
        """Judge an emotional turn in the background; small talk never gets this far."""
        state = getattr(self, "companion_state", None)
        if state is None or not self.config.emotion_appraisal or not self.config.api_key:
            return
        if not should_appraise(user_text):
            return
        if self.appraisal_thread is not None:
            logger.debug("Emotion appraisal still running; skipping this turn")
            return
        grievances = active_reasons(state, local_now(), self.persona.traits, self.mood_half_life())
        self.appraisal_thread = QThread(self)
        self.appraisal_worker = AppraisalWorker(self.client, user_text, assistant_text, grievances)
        self.appraisal_worker.moveToThread(self.appraisal_thread)
        self.appraisal_thread.started.connect(self.appraisal_worker.run)
        self.appraisal_worker.finished.connect(self.on_appraisal_ready)
        self.appraisal_worker.finished.connect(self.appraisal_worker.deleteLater)
        self.appraisal_worker.finished.connect(self.appraisal_thread.quit)
        self.appraisal_thread.finished.connect(self.on_appraisal_thread_finished)
        self.appraisal_thread.finished.connect(self.appraisal_thread.deleteLater)
        self.appraisal_thread.start()

    def on_appraisal_ready(self, appraisal) -> None:
        state = getattr(self, "companion_state", None)
        if appraisal is None or state is None or self.closing:
            return
        logger.info(
            "Emotion appraisal: %s, distress=%.2f",
            ", ".join(f"{event.type}:{event.intensity:.2f}" for event in appraisal.events) or "none",
            appraisal.user_distress,
        )
        self.update_state(apply_events(
            state, appraisal.events, local_now(), self.persona.traits, self.mood_half_life(),
            user_distress=appraisal.user_distress, rng=self.emotion_rng,
        ))

    def on_appraisal_thread_finished(self) -> None:
        self.appraisal_thread = None
        self.appraisal_worker = None

    def state_viewer_text(self) -> str:
        if self.companion_state is None:
            return "The companion's mood is turned off (COMPANION_STATE in Settings)."
        state = self.scheduled(self.companion_state)
        return "\n".join(state_summary_lines(state, local_now(), self.persona.traits, self.mood_half_life()))

    def show_state(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Companion state")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(self.state_viewer_text())
        box.exec()
        box.deleteLater()

    def show_memories(self) -> None:
        # Saving through the live store keeps subsequent recall and writes in sync.
        dialog = MemoryDialog(MemoryBrowserModel(store=self.memory_store), self)
        dialog.exec()
        dialog.deleteLater()

    @staticmethod
    def add_choices(menu: QMenu, steps: tuple[float, ...], current: float, apply) -> None:
        group = QActionGroup(menu)
        group.setExclusive(True)
        for step in steps:
            action = QAction(f"{round(step * 100)}%", menu)
            action.setCheckable(True)
            action.setChecked(abs(step - current) < 0.001)
            action.triggered.connect(lambda _checked=False, value=step: apply(value))
            group.addAction(action)
            menu.addAction(action)

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
        if self.drag_offset is not None:
            self.drag_offset = None
            self.save_window_state()
        event.accept()

    def on_page_loaded(self, ok: bool) -> None:
        if not ok:
            self.chat_panel.add_notice(
                "The Live2D renderer page could not be loaded. Check console output for path details."
            )
        elif self.model_path is None:
            self.chat_panel.add_notice("No .model3.json or .model3 file was found under the models folder.")

    def on_renderer_ready(self) -> None:
        logger.info("Renderer connected over QWebChannel")
        self.renderer_ready = True
        self.set_status("Ready")
        self.idle_timer.start()
        self.play_random_motion()
        self.idle_face = None
        self.refresh_idle_emotion()

    def set_talking(self, talking: bool) -> None:
        if self.renderer_ready:
            self.bridge.setTalking.emit(talking)

    def play_random_motion(self) -> None:
        if self.renderer_ready and not self.busy:
            self.bridge.playRandomMotion.emit()

    def conversation_window(
        self, user_text: str = "", *, defer: bool = False,
    ) -> list[dict[str, str]] | Callable[[], list[dict[str, str]]]:
        summary = self.history.summary if self.config.conversation_summary else None
        system_prompt = self.messages[0]["content"]
        turns = [dict(message) for message in self.messages[1:][-CONVERSATION_WINDOW:]]
        # Read before this message updates the last-contact time, so a long silence shows.
        state_context = self.state_context()
        relevant_recall = self.config.memory_relevant_recall
        embed = self.memory_embedder
        memory_store = self.memory_store
        if defer:
            # Background extraction can update the live store while chat recall is running.
            memory_store = copy(memory_store)
            memory_store.items = [dict(item) for item in memory_store.items]

        def build_context() -> list[dict[str, str]]:
            return build_chat_messages(
                system_prompt, turns,
                memory_context=memory_store.render_context(
                    query=user_text, relevant_recall=relevant_recall, embed=embed,
                ),
                summary=summary.text if summary else None,
                state_context=state_context,
            )

        return build_context if defer else build_context()

    def send_message(self) -> None:
        self.submit_message(self.chat_input.text().strip())

    def submit_message(self, user_text: str) -> None:
        if not user_text or self.busy:
            return

        if self.proactive is not None:
            self.proactive.record_activity(local_now())
        self.busy = True
        self.pause_wake_word()
        self.chat_input.clear()
        self.chat_input.setEnabled(False)
        self.send_button.setEnabled(False)
        self.set_status("Thinking")
        self.chat_panel.add_user(user_text)
        self.pending_user_text = user_text
        self.messages.append({"role": "user", "content": user_text})
        self.history.append("user", user_text)
        self.reset_reply_state()
        self.precheck_distress(user_text)
        self.start_chat_worker(self.conversation_window(user_text, defer=True))
        self.record_user_activity()

    def reset_reply_state(self) -> None:
        self.reply_parts = []
        self.reply_notes = []
        self.reply_emotion = None
        self.chat_panel.end_reply()
        self.stream_done = False
        self.speak_reply = tts_edge.is_available() and self.renderer_ready
        self.speech_started = False
        self.finish_status = "Idle"
        self.tts_queue.clear()

    def start_chat_worker(self, payload: list[dict[str, str]] | Callable[[], list[dict[str, str]]]) -> None:
        self.chat_thread = QThread(self)
        self.chat_worker = ChatStreamWorker(self.client, payload, registry=self.tool_registry)
        self.chat_worker.moveToThread(self.chat_thread)

        self.chat_thread.started.connect(self.chat_worker.run)
        self.chat_worker.emotion.connect(self.on_reply_emotion)
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

    def start_summary_worker(self) -> None:
        if not self.config.conversation_summary or not self.config.api_key or self.summary_thread is not None:
            return
        turns = self.history.messages()
        summary = self.history.summary
        if plan_summary_update(turns, CONVERSATION_WINDOW, summary.summarized_count if summary else 0) is None:
            return
        # self.messages is append-only; history.entries is capped on every save.
        self.summary_snapshot = (len(self.messages), len(turns), summary)
        self.summary_thread = QThread(self)
        self.summary_worker = SummaryWorker(self.client, turns, summary, CONVERSATION_WINDOW)
        self.summary_worker.moveToThread(self.summary_thread)
        self.summary_thread.started.connect(self.summary_worker.run)
        self.summary_worker.finished.connect(self.on_summary_ready)
        self.summary_worker.finished.connect(self.summary_worker.deleteLater)
        self.summary_worker.finished.connect(self.summary_thread.quit)
        self.summary_thread.finished.connect(self.on_summary_thread_finished)
        self.summary_thread.finished.connect(self.summary_thread.deleteLater)
        self.summary_thread.start()

    def on_summary_ready(self, summary: ConversationSummary | None) -> None:
        if self.summary_snapshot is None or not self.config.conversation_summary:
            return
        message_count, history_count, previous = self.summary_snapshot
        if summary is None or summary is previous:
            return
        appended = len(self.messages) - message_count
        dropped = max(0, history_count + appended - len(self.history.entries))
        previous = self.history.summary
        self.history.summary = ConversationSummary(summary.text, max(0, summary.summarized_count - dropped))
        try:
            self.history.save()
        except Exception:
            self.history.summary = previous
            logger.info("Conversation summary save failed")

    def on_summary_thread_finished(self) -> None:
        self.summary_thread = None
        self.summary_worker = None
        self.summary_snapshot = None

    def render_reply(self) -> None:
        reply = sanitize_reply_text("".join(self.reply_parts))
        notes = "".join(f"\n\n{note}" for note in self.reply_notes)
        self.chat_panel.update_reply(f"{reply}{notes}")

    def add_reply_note(self, note: str) -> None:
        if note not in self.reply_notes:
            self.reply_notes.append(note)
            self.render_reply()

    def on_reply_emotion(self, emotion: str) -> None:
        logger.debug("Reply emotion: %s", emotion)
        self.reply_emotion = emotion
        if self.renderer_ready:
            self.bridge.setEmotion.emit(emotion)

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
            self.record_reply(reply)
            self.record_reply_mood()
            if self.pending_user_text:
                self.start_memory_worker(self.pending_user_text, reply)
                if getattr(self, "companion_state", None) is not None:
                    self.start_appraisal_worker(self.pending_user_text, reply)
        self.render_reply()
        self.pending_user_text = ""
        self.stream_done = True
        self.maybe_finish_reply()

    def on_reply_error(self, error_text: str) -> None:
        logger.error("Chat request failed: %s", error_text)
        partial = sanitize_reply_text("".join(self.reply_parts))
        if partial:
            self.record_reply(partial)
            self.add_reply_note(f"[Interrupted] {error_text}")
        else:
            self.chat_panel.add_notice(error_text)
            self.finish_status = "Error"
        self.pending_user_text = ""
        self.stream_done = True
        self.maybe_finish_reply()

    # The tag stays in the history sent back to the model: without it the model copies its own
    # untagged earlier replies and stops tagging after a turn or two (2/8 vs 8/8 in testing).
    def history_text(self, reply: str) -> str:
        return f"[{self.reply_emotion}] {reply}" if self.reply_emotion else reply

    def record_reply(self, reply: str) -> None:
        content = self.history_text(reply)
        self.messages.append({"role": "assistant", "content": content})
        self.history.append("assistant", content)
        try:
            self.start_summary_worker()
        except Exception:
            logger.info("Conversation summary worker could not start")
            self.summary_thread = None
            self.summary_worker = None
            self.summary_snapshot = None

    def run_next_tts(self) -> None:
        if self.tts_thread is not None or not self.tts_queue:
            return
        text = self.tts_queue.popleft()
        voice = tts_edge.choose_tts_voice(self.config, text)
        rate, pitch = tts_edge.choose_tts_prosody(self.config, text)
        logger.debug("TTS voice=%s rate=%s pitch=%s text=%s", voice, rate, pitch, text)

        self.tts_thread = QThread(self)
        self.tts_worker = TTSWorker(text, voice, rate, pitch)
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
        logger.warning("TTS failed, not speaking the rest of this reply: %s", error_text)
        self.add_reply_note(f"[TTS] {error_text}")
        # Failures come from the network and repeat; retrying every remaining sentence would
        # stack one timeout per sentence. Clips already queued still play.
        self.speak_reply = False
        self.tts_queue.clear()

    def on_memory_thread_finished(self) -> None:
        self.memory_thread = None
        self.memory_worker = None
        self.run_next_memory_job()

    def on_memory_ready(self, memories: list[dict[str, str]]) -> None:
        if self.config.memory_consolidation:
            self.memory_store.load()
            return
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
        # Close the bubble only now: TTS and audio notes can arrive after the text stream ends
        # and must land in this reply's bubble, not open a new one.
        self.chat_panel.end_reply()
        self.set_status(self.finish_status)
        self.finish_interaction()

    def finish_interaction(self) -> None:
        self.busy = False
        self.chat_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.chat_input.setFocus()
        self.set_talking(False)
        self.resume_wake_word()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closing = True
        if self.wake_capture_timer is not None:
            self.wake_capture_timer.stop()
        self.pause_wake_word()
        if self.voice_session is not None:
            self.voice_session.cancel()
            self.microphone.stop()
        if self.wake_thread is not None and self.wake_thread.isRunning():
            self.wake_stop_requested.emit()
            if not self.wake_thread.wait(2000):
                # Model loading may still be running; retain its owner until finished.
                event.ignore()
                self.hide()
                return
        if self.transcription_thread is not None and self.transcription_thread.isRunning():
            self.transcription_thread.quit()
            if not self.transcription_thread.wait(2000):
                # Keep the thread owner alive until the bounded network operation returns.
                # finished retries close; cancellation suppresses any late transcript.
                event.ignore()
                self.hide()
                return
        if self.proactive_timer is not None:
            self.proactive_timer.stop()
        self.proactive = None
        appraisal_thread = getattr(self, "appraisal_thread", None)
        if appraisal_thread is not None and appraisal_thread.isRunning():
            # Results after closing are ignored; give the request a bounded moment to finish.
            appraisal_thread.quit()
            appraisal_thread.wait(2000)
        # Ignore queued summary results once teardown begins.
        self.summary_snapshot = None
        if self.summary_thread is not None and self.summary_thread.isRunning():
            self.summary_thread.quit()
            self.summary_thread.wait(2000)
        self.save_window_state()
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
    resolved = ApiKeyStore().resolve()
    logger.info("API key source: %s", resolved.source)
    window = CompanionWindow(AppConfig(api_key=resolved.value))
    window.show()
    if window.needs_persona_setup():
        QTimer.singleShot(600, partial(window.show_persona_dialog, first_run=True))
    return app.exec()
