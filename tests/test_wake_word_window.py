"""Run desktop wake callbacks with Qt stand-ins, without audio devices or Vosk."""

import builtins
import logging
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import Signal
from test_voice_input_window import window as window


@pytest.fixture
def wake_window(window, monkeypatch):
    ui = window.ui
    ui.setup_voice_input(Mock())
    ui.config.wake_word = True
    ui.config.wake_word_phrases = ("hey whale",)
    ui.config.wake_word_model_dir = "model"
    microphone = Mock(pcm_ready=Signal(), failed=Signal())
    worker = Mock(started=Signal(), finished=Signal(), error=Signal(), wakeDetected=Signal())
    thread = Mock(started=Signal(), finished=Signal())
    monkeypatch.setitem(sys.modules, "companion.adapters.microphone", SimpleNamespace(
        Microphone=Mock(return_value=microphone),
    ))
    monkeypatch.setitem(sys.modules, "companion.app.wake_word_worker", SimpleNamespace(
        WakeWordWorker=Mock(return_value=worker),
    ))
    namespace = ui.setup_wake_word.__globals__
    transcription_thread_factory = namespace["QThread"]
    namespace["QThread"] = Mock(return_value=thread)
    ui.setup_wake_word()
    namespace["QThread"] = transcription_thread_factory
    return SimpleNamespace(ui=ui, voice=window, microphone=microphone, worker=worker, thread=thread)


@pytest.mark.parametrize("settings", [
    {"wake_word": False}, {"wake_word_phrases": ()}, {"wake_word_phrases": (" \t",)},
    {"wake_word_model_dir": ""}, {"wake_word_model_dir": " \t"},
    {"voice_input": False}, {"transcription_model": ""}, {"transcription_model": " \t"},
])
def test_disabled_wake_creates_and_imports_nothing(window, monkeypatch, settings):
    ui = window.ui
    ui.config.wake_word = True
    ui.config.wake_word_phrases = ("hey whale",)
    ui.config.wake_word_model_dir = "model"
    for name, value in settings.items():
        setattr(ui.config, name, value)
    original = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert name not in {"companion.adapters.microphone", "companion.app.wake_word_worker", "vosk"}
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    ui.setup_wake_word()
    assert ui.wake_worker is ui.wake_microphone is ui.wake_indicator is None
    namespace = ui.setup_wake_word.__globals__
    for name in ("QThread", "QTimer", "QLabel"):
        namespace[name].assert_not_called()


def test_capture_waits_for_worker_readiness_and_indicator_tracks_microphone(wake_window):
    w = wake_window
    w.microphone.start.assert_not_called()
    w.ui.wake_indicator.show.assert_not_called()
    w.thread.started.emit()
    w.worker.start.assert_called_once()
    w.worker.started.emit()
    w.microphone.start.assert_called_once()
    w.worker.reset.assert_called_once()
    w.ui.wake_indicator.show.assert_called_once()
    w.microphone.pcm_ready.emit(b"\0\0")
    w.worker.feed.assert_called_once_with(b"\0\0")
    w.worker.finished.emit()
    assert not w.ui.wake_listening
    w.ui.wake_indicator.hide.assert_called()
    w.microphone.stop.assert_called_once()
    w.thread.quit.assert_called_once()


def test_wake_auto_stops_transcribes_sends_and_resumes_after_reply(wake_window):
    w = wake_window
    w.worker.started.emit()
    w.worker.wakeDetected.emit("hey whale")
    assert w.ui.voice_session.state == "recording"
    assert not w.ui.wake_listening
    w.microphone.stop.assert_called_once()
    w.voice.microphone.start.assert_called_once()
    w.ui.chat_panel.add_notice.assert_called_once_with("Listening…")
    w.ui.wake_capture_timer.start.assert_called_once_with(5000)
    w.voice.microphone.pcm_ready.emit(b"\0\0" * 4800)
    w.ui.wake_capture_timer.timeout.emit()
    w.voice.microphone.stop.assert_called_once()
    w.ui.submit_message.side_effect = lambda _: setattr(w.ui, "busy", True)
    w.voice.thread.started.emit()
    w.ui.submit_message.assert_called_once_with("hello from voice")
    w.voice.thread.finished.emit()
    assert not w.ui.wake_listening  # Reply still owns the turn.
    w.ui.finish_interaction()
    assert w.ui.wake_listening
    assert w.microphone.start.call_count == 2


@pytest.mark.parametrize("busy_state", [
    {"busy": True}, {"stream_done": False}, {"tts_thread": object()},
    {"tts_queue": ["speaking"]}, {"pending_clips": {"url": "clip"}},
    {"transcription_thread": object()}, {"closing": True},
    {"input": "unsent text"}, {"input": " "}, {"recording": True},
])
def test_busy_detections_do_not_start_or_extend_capture(wake_window, busy_state):
    w = wake_window
    w.worker.started.emit()
    for name, value in busy_state.items():
        if name == "input":
            w.ui.chat_input.text.return_value = value
        elif name == "recording":
            w.ui.voice_session.start()
        else:
            setattr(w.ui, name, value)
    w.worker.wakeDetected.emit("hey whale")
    w.voice.microphone.start.assert_not_called()
    w.ui.wake_capture_timer.start.assert_not_called()
    w.ui.chat_panel.add_notice.assert_not_called()


@pytest.mark.parametrize("status", ["empty", "error", "too_short"])
def test_wake_transcription_failures_use_existing_notices_and_resume(wake_window, status):
    w = wake_window
    w.worker.started.emit()
    w.worker.wakeDetected.emit("hey whale")
    w.ui.chat_panel.add_notice.reset_mock()
    if status != "too_short":
        w.voice.microphone.pcm_ready.emit(b"\0\0" * 4800)
    w.voice.client.return_value = ""
    if status == "error":
        w.voice.client.side_effect = RuntimeError("failed")
    w.ui.wake_capture_timer.timeout.emit()
    w.voice.thread.started.emit()
    w.voice.thread.finished.emit()
    w.ui.submit_message.assert_not_called()
    w.ui.chat_panel.add_notice.assert_called_once()
    assert w.ui.wake_listening


@pytest.mark.parametrize("source", ["worker", "microphone"])
def test_failure_warns_once_disables_wake_and_preserves_push_to_talk(wake_window, caplog, source):
    w = wake_window
    if source == "microphone":
        w.worker.started.emit()
        signal = w.microphone.failed
    else:
        signal = w.worker.error
    with caplog.at_level(logging.WARNING):
        signal.emit("Unavailable")
        signal.emit("Repeated error")
    assert len(caplog.records) == 1
    assert "Wake word disabled" in caplog.text
    assert not w.ui.wake_listening
    w.ui.resume_wake_word()
    assert not w.ui.wake_listening
    w.ui.start_voice_input()
    assert w.ui.voice_session.state == "recording"


def test_close_bounds_wait_and_retains_owner_until_worker_finishes(wake_window):
    w = wake_window
    w.worker.started.emit()
    w.thread.wait.return_value = False
    event = Mock()
    w.ui.closeEvent(event)
    w.worker.stop.assert_called_once()
    w.thread.wait.assert_called_once_with(2000)
    w.ui.wake_capture_timer.stop.assert_called_once()
    event.ignore.assert_called_once()
    w.ui.hide.assert_called_once()
    w.worker.wakeDetected.emit("late")
    w.voice.microphone.start.assert_not_called()
    w.thread.finished.emit()
    assert w.ui.wake_thread is w.ui.wake_worker is None
    w.ui.close.assert_called_once()


def test_voice_device_failure_cancels_auto_stop_before_next_manual_capture(wake_window):
    w = wake_window
    w.worker.started.emit()
    w.worker.wakeDetected.emit("hey whale")
    w.voice.microphone.failed.emit("Cannot capture")
    w.ui.wake_capture_timer.stop.assert_called_once()
    assert w.ui.voice_session.state == "idle"
    assert w.ui.wake_listening


def test_close_cancels_capture_before_waiting_for_listener(wake_window):
    w = wake_window
    w.worker.started.emit()
    w.worker.wakeDetected.emit("hey whale")

    def wait(_timeout):
        assert w.ui.voice_session.state == "idle"
        w.voice.microphone.stop.assert_called_once()
        assert not w.ui.wake_listening
        return False

    w.thread.wait.side_effect = wait
    w.ui.closeEvent(Mock())
    w.ui.wake_capture_timer.stop.assert_called_once()


def test_listener_ready_after_close_never_opens_microphone(wake_window):
    w = wake_window
    w.ui.closing = True
    w.worker.started.emit()
    w.microphone.start.assert_not_called()
    w.worker.stop.assert_called_once()
