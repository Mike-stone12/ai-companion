"""Worker control flow with Qt stand-ins; no Qt, Vosk, or microphone required."""

import sys
import weakref
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import load_class

from companion.adapters.wake_word_vosk import VoskWakeWordRecognizer
from companion.core.config import AppConfig
from companion.core.wake_word_audio import Pcm16ChunkBuffer
from companion.core.wake_word_controller import WakeWordController


@pytest.fixture
def make_worker():
    def make(factory=None, **settings):
        main, background = object(), object()
        threads = SimpleNamespace(current=background, owner=background, main=main)
        config = AppConfig(**{
            "wake_word": True,
            "wake_word_phrases": ("Hey Whale",),
            "wake_word_model_dir": "test-model",
            **settings,
        })
        factory = factory if factory is not None else Mock()
        cls = load_class(
            "companion/app/wake_word_worker.py", "WakeWordWorker",
            pyqtSlot=lambda *args: lambda method: method,
            QThread=SimpleNamespace(currentThread=lambda: threads.current),
            QCoreApplication=SimpleNamespace(instance=lambda: SimpleNamespace(thread=lambda: threads.main)),
            VoskWakeWordRecognizer=factory,
            WakeWordController=lambda *args: WakeWordController(*args, cooldown_seconds=0),
            Pcm16ChunkBuffer=Pcm16ChunkBuffer,
        )
        cls.thread = lambda self: threads.owner
        return cls(config), factory, config, threads

    return make


def test_model_is_deferred_and_settings_are_snapshotted(make_worker):
    worker, factory, config, _ = make_worker()
    factory.assert_not_called()
    worker.feed(b"\x00\x00")
    config.wake_word = False
    config.wake_word_phrases = ("changed",)
    config.wake_word_model_dir = "changed"
    worker.start()
    worker.start()
    factory.assert_called_once_with("test-model", ("Hey Whale",), sample_rate=16000)
    assert worker.started.values == [()]
    assert not worker.error.values
    worker.stop()
    worker.stop()
    assert worker.finished.values == [()]
    assert worker._recognizer is worker._controller is None
    worker.feed(b"\x00\x00")
    factory.return_value.feed.assert_not_called()


@pytest.mark.parametrize("settings", [
    {"wake_word": False}, {"wake_word_phrases": ()},
    {"wake_word_phrases": ("  ",)}, {"wake_word_model_dir": "  "},
])
def test_unusable_settings_finish_without_loading_vosk(make_worker, settings):
    worker, factory, _, _ = make_worker(**settings)
    worker.start()
    worker.stop()
    factory.assert_not_called()
    assert worker.finished.values == [()]
    assert not worker.started.values
    assert not worker.error.values


def test_aligned_pcm_and_partial_final_results_reach_real_controller(make_worker):
    worker, factory, _, _ = make_worker()
    recognizer = factory.return_value
    results = iter([(False, "hey whale"), (False, "hey whale"), (True, None), (True, "hey whale")])

    def recognize(pcm):
        recognizer.is_final, text = next(results)
        return text

    recognizer.feed.side_effect = recognize
    worker.start()
    worker.feed(b"\x01")
    worker.feed(b"")
    recognizer.feed.assert_not_called()
    for chunk in (b"\x02\x03", b"\x04", b"\x05\x06", b"\x07\x08"):
        worker.feed(chunk)
    assert [call.args[0] for call in recognizer.feed.call_args_list] == [
        b"\x01\x02", b"\x03\x04", b"\x05\x06", b"\x07\x08",
    ]
    assert worker.wakeDetected.values == [("Hey Whale",), ("Hey Whale",)]
    assert not worker.error.values


@pytest.mark.parametrize("reason", ["missing_package", "missing_directory", "invalid_model"])
def test_real_adapter_startup_errors_signal_and_finish(make_worker, tmp_path, monkeypatch, reason):
    model_dir = tmp_path
    if reason == "missing_directory":
        model_dir = tmp_path / "missing"
    monkeypatch.setitem(sys.modules, "vosk", None)
    if reason == "invalid_model":
        monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(Model=Mock(side_effect=RuntimeError("Invalid model"))))
    worker, _, _, _ = make_worker(VoskWakeWordRecognizer, wake_word_model_dir=str(model_dir))
    events = []
    worker.error.connect(lambda message: events.append("error"))
    worker.finished.connect(lambda: events.append("finished"))
    worker.start()
    worker.feed(b"\x00\x00")
    worker.stop()
    assert events == ["error", "finished"]
    message, = worker.error.values[0]
    expected = {
        "missing_package": "not installed", "missing_directory": "does not exist", "invalid_model": "Invalid model",
    }
    assert expected[reason] in message
    assert not worker.started.values
    assert worker._recognizer is worker._controller is None


def test_feed_error_releases_session_and_can_restart(make_worker):
    worker, factory, _, _ = make_worker()
    factory.return_value.feed.side_effect = RuntimeError()
    worker.start()
    worker.feed(b"\x00\x00")
    assert worker.error.values == [("RuntimeError",)]
    assert worker.finished.values == [()]
    assert worker._recognizer is worker._controller is None
    factory.return_value.feed.side_effect = None
    worker.start()
    assert factory.call_count == 2
    worker.stop()
    assert worker.finished.values == [(), ()]


def test_stop_releases_recognizer_and_resets_buffer_and_matcher(make_worker):
    class Recognizer:
        is_final = False

        def __init__(self, *args, **kwargs):
            self.chunks = []

        def feed(self, pcm):
            self.chunks.append(pcm)
            return "hey whale"

    worker, _, _, _ = make_worker(Recognizer)
    worker.start()
    worker.feed(b"\x01\x02\xff")
    reference = weakref.ref(worker._recognizer)
    worker.stop()
    assert reference() is None
    worker.start()
    worker.feed(b"\x03\x04")
    assert worker._recognizer.chunks == [b"\x03\x04"]
    assert worker.wakeDetected.values == [("Hey Whale",), ("Hey Whale",)]


@pytest.mark.parametrize("wrong_thread", ["main", "other"])
def test_start_refuses_recognition_outside_own_background_thread(make_worker, wrong_thread):
    worker, factory, _, threads = make_worker()
    if wrong_thread == "main":
        threads.current = threads.owner = threads.main
    else:
        threads.current = object()
    worker.start()
    factory.assert_not_called()
    assert "background QThread" in worker.error.values[0][0]
    assert worker.finished.values == [()]


def test_direct_feed_on_ui_thread_never_runs_recognition(make_worker):
    worker, factory, _, threads = make_worker()
    worker.start()
    threads.current = threads.main
    worker.feed(b"\x00\x00")
    factory.return_value.feed.assert_not_called()
    assert "background QThread" in worker.error.values[0][0]
    assert worker.finished.values == [()]


def test_reset_discards_partial_utterance_and_buffer_without_reloading_model(make_worker):
    worker, factory, _, _ = make_worker()
    factory.return_value.feed.return_value = "hey whale"
    factory.return_value.is_final = False
    worker.start()
    worker.feed(b"\x01\x02\xff")
    worker.reset()
    worker.feed(b"\x03\x04")
    factory.assert_called_once()
    factory.return_value.reset.assert_called_once()
    factory.return_value.feed.assert_called_with(b"\x03\x04")
    assert worker.wakeDetected.values == [("Hey Whale",), ("Hey Whale",)]
    assert not worker.finished.values
