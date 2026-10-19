"""Exercise adapter logic with Qt stand-ins, without importing Qt or using hardware."""

import ast
import io
import logging
import wave
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from companion.core.config import AppConfig
from companion.core.llm.transcription import TranscriptionError, transcribe
from companion.core.voice_input import AudioFormat, PushToTalkRecorder


class Signal:
    def __init__(self, *_):
        self.slots = []
        self.values = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot):
        if slot not in self.slots:
            raise TypeError("Not connected")
        self.slots.remove(slot)

    def emit(self, *args):
        self.values.append(args)
        for slot in list(self.slots):
            slot(*args)


def load_class(relative_path, name, **dependencies):
    # Like the existing app tests, compile the real class with fake Qt names.
    # This checks Python control flow, not Qt bindings or thread scheduling.
    path = Path(__file__).resolve().parents[1] / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    namespace = {
        "QObject": type("QObject", (), {"__init__": lambda self, parent=None: None}),
        "pyqtSignal": Signal,
        "pyqtSlot": lambda: lambda method: method,
        "logger": logging.getLogger(__name__),
        **dependencies,
    }
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    module = ast.fix_missing_locations(ast.Module(body=[future, cls], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]


@pytest.fixture
def microphone():
    errors = Enum("Error", "NoError OpenError IOError")
    input_device = Mock()
    input_device.isNull.return_value = False
    input_device.isFormatSupported.return_value = True
    stream = Mock(readyRead=Signal())
    stream.readAll.return_value = b""
    source = Mock(stateChanged=Signal())
    source.start.return_value = stream
    source.error.return_value = errors.NoError
    source_factory = Mock(return_value=source)
    media = Mock()
    media.defaultAudioInput.return_value = input_device
    format_factory = Mock(SampleFormat=SimpleNamespace(Int16="int16"))
    cls = load_class(
        "companion/adapters/microphone.py", "Microphone", AudioFormat=AudioFormat,
        QMediaDevices=media, QAudioFormat=format_factory, QAudioSource=source_factory,
        QAudio=SimpleNamespace(Error=errors),
    )
    return SimpleNamespace(
        capture=cls(), input=input_device, stream=stream, source=source,
        source_factory=source_factory, format_factory=format_factory, errors=errors,
    )


@pytest.mark.parametrize("reason", ["missing", "unsupported", "backend_exception"])
def test_unavailable_microphone_reports_error_without_starting(microphone, reason):
    m = microphone
    if reason == "missing":
        m.input.isNull.return_value = True
    elif reason == "unsupported":
        m.input.isFormatSupported.return_value = False
    else:
        m.input.isFormatSupported.side_effect = RuntimeError("backend failure")
    assert m.capture.start() is False
    message, = m.capture.failed.values[0]
    assert {"missing": "No audio input", "unsupported": "16000 Hz mono 16-bit", "backend_exception": "initialize"}[
        reason
    ] in message
    m.source_factory.assert_not_called()
    m.capture.stop()


def test_pcm_matches_recorder_including_final_and_partial_chunks(microphone):
    m = microphone
    recorder = PushToTalkRecorder(min_seconds=0)
    recorder.press()
    m.capture.pcm_ready.connect(recorder.feed)
    assert m.capture.start() is True
    fmt = m.format_factory.return_value
    fmt.setSampleRate.assert_called_once_with(AudioFormat().sample_rate)
    fmt.setChannelCount.assert_called_once_with(1)
    fmt.setSampleFormat.assert_called_once_with("int16")
    m.input.isFormatSupported.assert_called_once_with(fmt)
    assert m.capture.start() is True
    m.source_factory.assert_called_once_with(m.input, fmt, m.capture)
    m.stream.readAll.return_value = b"\x01"
    m.stream.readyRead.emit()
    m.stream.readAll.return_value = b"\x02\x03\x04"
    m.capture.stop()
    with wave.open(io.BytesIO(recorder.release().wav), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert wav.readframes(2) == b"\x01\x02\x03\x04"
    m.capture.stop()
    m.source.stop.assert_called_once()
    m.source.deleteLater.assert_called_once()
    assert not m.stream.readyRead.slots
    assert not m.source.stateChanged.slots
    assert not m.capture.failed.values
    assert m.capture.start() is True
    m.capture.stop()


@pytest.mark.parametrize("reason", ["no_stream", "open_error", "start_exception", "runtime_error", "read_error"])
def test_capture_errors_release_source_and_allow_retry(microphone, reason):
    m = microphone
    if reason == "no_stream":
        m.source.start.return_value = None
    elif reason == "open_error":
        m.source.error.return_value = m.errors.OpenError
    elif reason == "start_exception":
        m.source.start.side_effect = RuntimeError("backend failure")
    if reason in {"runtime_error", "read_error"}:
        assert m.capture.start() is True
        if reason == "runtime_error":
            m.source.error.return_value = m.errors.IOError
            m.source.stateChanged.emit("stopped")
        else:
            m.stream.readAll.side_effect = RuntimeError("read failed")
            m.stream.readyRead.emit()
    else:
        assert m.capture.start() is False
    assert len(m.capture.failed.values) == 1
    m.source.stop.assert_called_once()
    m.source.deleteLater.assert_called_once()
    m.capture.stop()
    m.source.start.side_effect = None
    m.source.start.return_value = m.stream
    m.source.error.return_value = m.errors.NoError
    m.stream.readAll.side_effect = None
    assert m.capture.start() is True
    m.capture.stop()


def test_final_read_failure_still_releases_microphone(microphone):
    m = microphone
    assert m.capture.start() is True
    m.stream.readAll.side_effect = RuntimeError("read failed")
    m.capture.stop()
    assert m.capture.failed.values == [("Could not read the final microphone audio.",)]
    m.source.stop.assert_called_once()
    m.source.deleteLater.assert_called_once()


def make_worker(client):
    cls = load_class("companion/app/workers.py", "TranscriptionWorker", transcribe=client)
    config = AppConfig(base_url="https://example.test/v1", api_key="fake-key", transcription_model="test-model")
    wav = b"RIFF test audio"
    worker = cls(wav, config)
    config.transcription_model = "changed-model"
    return worker, wav


def test_worker_defers_request_and_emits_text_from_config_snapshot():
    client = Mock(return_value="hello")
    worker, wav = make_worker(client)
    client.assert_not_called()
    worker.run()
    client.assert_called_once_with(
        wav, base_url="https://example.test/v1", api_key="fake-key", model="test-model",
    )
    assert worker.finished.values == [("hello",)]
    assert not worker.failed.values


@pytest.mark.parametrize("error", [TranscriptionError("Network timeout"), RuntimeError()])
def test_worker_emits_only_failure_and_does_not_log_error_contents(error, caplog):
    worker, _ = make_worker(Mock(side_effect=error))
    with caplog.at_level(logging.INFO):
        worker.run()
    assert worker.failed.values == [(str(error) or type(error).__name__,)]
    assert not worker.finished.values
    assert [record.message for record in caplog.records] == ["Transcription worker failed"]


def test_worker_preserves_real_client_default_timeout(monkeypatch):
    opener = Mock(side_effect=TimeoutError)
    monkeypatch.setattr("urllib.request.urlopen", opener)
    worker, _ = make_worker(transcribe)
    worker.run()
    assert opener.call_args.kwargs == {"timeout": 30.0}
    assert worker.failed.values == [("Transcription request failed: network error or timeout",)]
    assert not worker.finished.values
