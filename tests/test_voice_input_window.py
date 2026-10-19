"""Exercise real window callbacks with Qt stand-ins, without devices or network."""

import builtins
import io
import sys
import wave
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import Signal, load_class

from companion.core.config import AppConfig
from companion.core.voice_input_actions import can_start_voice_input, deliver_voice_input_result
from companion.core.voice_input_controller import VoiceInputController, VoiceInputResult


@pytest.fixture
def window(monkeypatch):
    client = Mock(return_value="hello from voice")
    worker_class = load_class("companion/app/workers.py", "TranscriptionWorker", transcribe=client)
    worker_class.moveToThread = Mock()
    worker_class.deleteLater = Mock()
    microphone = Mock(pcm_ready=Signal(), failed=Signal())
    microphone_factory = Mock(return_value=microphone)
    monkeypatch.setitem(sys.modules, "companion.adapters.microphone", SimpleNamespace(Microphone=microphone_factory))
    button = Mock(pressed=Signal(), released=Signal())
    thread = Mock(started=Signal(), finished=Signal())
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {"closeEvent": Mock()}),
        partial=partial, transcribe=client, VoiceInputController=VoiceInputController,
        can_start_voice_input=can_start_voice_input, deliver_voice_input_result=deliver_voice_input_result,
        QPushButton=Mock(return_value=button), QThread=Mock(return_value=thread),
        TranscriptionWorker=worker_class, Qt=SimpleNamespace(ConnectionType=SimpleNamespace(DirectConnection=1)),
    )
    instance = cls.__new__(cls)
    instance.config = AppConfig(voice_input=True, transcription_model="test-model")
    instance.voice_session = instance.microphone = instance.talk_button = None
    instance.transcription_thread = instance.transcription_worker = None
    instance.busy = instance.closing = False
    instance.chat_input = Mock()
    instance.send_button = Mock()
    instance.chat_panel = Mock()
    instance.set_status = Mock()
    instance.set_talking = Mock()
    instance.submit_message = Mock()
    instance.proactive_timer = None
    instance.summary_thread = None
    instance.save_window_state = Mock()
    instance.idle_timer = Mock()
    instance.audio_watchdog = Mock()
    instance.bridge = Mock()
    instance.tts_queue = []
    instance.discard_pending_clips = Mock()
    instance.hide = Mock()
    instance.close = Mock()
    return SimpleNamespace(
        ui=instance, microphone=microphone, factory=microphone_factory, button=button,
        thread=thread, client=client,
    )


@pytest.mark.parametrize("enabled,model", [(False, "test-model"), (True, ""), (True, "  ")])
def test_disabled_voice_never_imports_or_constructs_microphone(window, monkeypatch, enabled, model):
    original = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name != "companion.adapters.microphone"
        assert "QtMultimedia" not in name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    window.ui.config = AppConfig(voice_input=enabled, transcription_model=model)
    layout = Mock()
    window.ui.setup_voice_input(layout)
    layout.addWidget.assert_not_called()
    window.factory.assert_not_called()
    assert window.ui.talk_button is None


def start_recording(window):
    window.ui.setup_voice_input(Mock())
    window.button.pressed.emit()
    window.microphone.start.assert_called_once()
    assert window.ui.voice_session.state == "recording"


def test_press_release_flushes_audio_then_transcribes_and_submits(window):
    start_recording(window)
    window.button.pressed.emit()  # Repeated press must not reset the active capture.
    window.microphone.start.assert_called_once()
    pcm = b"\x01\x00" * 4800
    window.microphone.stop.side_effect = lambda: window.microphone.pcm_ready.emit(pcm)
    window.button.released.emit()
    window.client.assert_not_called()
    window.thread.started.emit()
    with wave.open(io.BytesIO(window.client.call_args.args[0]), "rb") as wav:
        assert wav.readframes(4800) == pcm
    window.ui.submit_message.assert_called_once_with("hello from voice")
    window.ui.chat_panel.add_notice.assert_not_called()
    window.thread.quit.assert_called_once()
    window.thread.finished.emit()
    assert window.ui.transcription_thread is None
    assert window.ui.transcription_worker is None


@pytest.mark.parametrize("outcome", ["empty", "error", "too_short"])
def test_failed_or_empty_transcription_shows_notice_and_allows_retry(window, outcome):
    start_recording(window)
    if outcome != "too_short":
        window.microphone.pcm_ready.emit(b"\0\0" * 4800)
    if outcome == "error":
        window.client.side_effect = RuntimeError("network error")
    else:
        window.client.return_value = "  "
    window.button.released.emit()
    window.thread.started.emit()
    window.thread.finished.emit()
    window.ui.submit_message.assert_not_called()
    window.ui.chat_panel.add_notice.assert_called_once()
    assert window.ui.busy is False
    assert window.ui.voice_session.state == "idle"


def test_press_during_reply_does_not_capture(window):
    window.ui.setup_voice_input(Mock())
    window.ui.busy = True
    window.button.pressed.emit()
    window.microphone.start.assert_not_called()
    window.button.released.emit()
    window.thread.start.assert_not_called()


def test_microphone_failure_cancels_recording(window):
    start_recording(window)
    window.microphone.failed.emit("No microphone")
    window.button.released.emit()
    assert window.ui.voice_session.state == "idle"
    assert window.ui.busy is False
    window.ui.chat_panel.add_notice.assert_called_once_with("No microphone")
    window.thread.start.assert_not_called()


def test_close_discards_active_capture(window):
    start_recording(window)
    window.ui.closeEvent(Mock())
    assert window.ui.voice_session.state == "idle"
    window.microphone.stop.assert_called_once()


def test_close_retains_running_thread_and_ignores_late_results(window):
    start_recording(window)
    window.microphone.pcm_ready.emit(b"\0\0" * 4800)
    window.button.released.emit()
    window.thread.wait.return_value = False
    event = Mock()
    window.ui.closeEvent(event)
    window.thread.quit.assert_called_once()
    window.thread.wait.assert_called_once_with(2000)
    event.ignore.assert_called_once()
    window.ui.on_voice_input_result(VoiceInputResult("ok", text="late"))
    window.ui.submit_message.assert_not_called()
    window.thread.started.emit()  # Cancellation before run also suppresses transcription.
    window.client.assert_not_called()
    window.thread.finished.emit()
    window.ui.close.assert_called_once()


def test_typed_input_and_voice_share_submission_path(window):
    window.ui.chat_input.text.return_value = " typed text "
    window.ui.send_message()
    window.ui.submit_message.assert_called_once_with("typed text")
