import builtins
import importlib.util
import json
import logging
import sys
from types import ModuleType

import pytest

from companion.adapters import wake_word_vosk
from companion.adapters.wake_word_vosk import VoskWakeWordRecognizer, WakeWordRecognizerUnavailable
from companion.core.wake_word_controller import WakeWordController


@pytest.fixture
def fake_vosk(monkeypatch):
    module = ModuleType("vosk")
    module.models = []
    module.recognizers = []

    class Model:
        def __init__(self, path):
            self.path = path
            module.models.append(self)

    class KaldiRecognizer:
        def __init__(self, model, sample_rate, grammar):
            self.args = (model, sample_rate, grammar)
            self.results = []
            self.pcm_chunks = []
            self.result_calls = []
            self.reset_calls = 0
            module.recognizers.append(self)

        def AcceptWaveform(self, pcm):
            self.pcm_chunks.append(pcm)
            self.final, self.raw = self.results.pop(0)
            return self.final

        def Result(self):
            assert self.final
            self.result_calls.append("final")
            return self.raw

        def PartialResult(self):
            assert not self.final
            self.result_calls.append("partial")
            return self.raw

        def Reset(self):
            self.reset_calls += 1

    module.Model = Model
    module.KaldiRecognizer = KaldiRecognizer
    monkeypatch.setitem(sys.modules, "vosk", module)
    return module


@pytest.mark.parametrize("sample_rate", [None, 8000])
def test_model_and_normalized_grammar(fake_vosk, tmp_path, sample_rate):
    kwargs = {} if sample_rate is None else {"sample_rate": sample_rate}
    adapter = VoskWakeWordRecognizer(tmp_path, [" Hey Whale ", "\tHELLO Whale\n", "小鲸"], **kwargs)
    model, rate, grammar = fake_vosk.recognizers[0].args
    assert model is fake_vosk.models[0]
    assert model.path == str(tmp_path)
    assert rate == (16000 if sample_rate is None else sample_rate)
    assert json.loads(grammar) == ["hey whale", "hello whale", "小鲸", "[unk]"]
    assert adapter.is_final is False


def test_partial_and_final_results(fake_vosk, tmp_path, caplog):
    adapter = VoskWakeWordRecognizer(tmp_path, ["hey whale"])
    recognizer = fake_vosk.recognizers[0]
    recognizer.results = [(False, '{"partial": "hey"}'), (True, '{"text": " hey whale "}')]
    pcm = b"\x00\x00\xff\x7f"
    with caplog.at_level(logging.DEBUG, logger=wake_word_vosk.__name__):
        assert adapter.feed(pcm) == "hey"
        assert adapter.is_final is False
        assert adapter.feed(pcm) == "hey whale"
        assert adapter.is_final is True
    assert recognizer.pcm_chunks == [pcm, pcm]
    assert recognizer.result_calls == ["partial", "final"]
    assert all(record.levelno <= logging.DEBUG for record in caplog.records)


@pytest.mark.parametrize("final", [False, True])
@pytest.mark.parametrize("text", ["", " \t", "[unk]", " [unk] [unk] ", None, 42])
def test_empty_or_unknown_results(fake_vosk, tmp_path, final, text):
    adapter = VoskWakeWordRecognizer(tmp_path, ["hey whale"])
    fake_vosk.recognizers[0].results = [(final, json.dumps({"text" if final else "partial": text}))]
    assert adapter.feed(b"\x00\x00") is None
    assert adapter.is_final is final


@pytest.mark.parametrize("final", [False, True])
def test_malformed_json_is_debug_logged(fake_vosk, tmp_path, caplog, final):
    adapter = VoskWakeWordRecognizer(tmp_path, ["hey whale"])
    fake_vosk.recognizers[0].results = [(final, '{"text": "private transcript')]
    with caplog.at_level(logging.DEBUG, logger=wake_word_vosk.__name__):
        assert adapter.feed(b"\x00\x00") is None
    assert adapter.is_final is final
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.DEBUG
    assert "malformed JSON" in caplog.text
    assert "private transcript" not in caplog.text


@pytest.mark.parametrize("raw", ["{}", "[]", "null", '"hey whale"'])
def test_missing_text_or_invalid_shape(fake_vosk, tmp_path, raw):
    adapter = VoskWakeWordRecognizer(tmp_path, ["hey whale"])
    fake_vosk.recognizers[0].results = [(True, raw)]
    assert adapter.feed(b"\x00\x00") is None


@pytest.mark.parametrize("has_reset", [False, True])
def test_reset(fake_vosk, tmp_path, monkeypatch, has_reset):
    adapter = VoskWakeWordRecognizer(tmp_path, ["hey whale"])
    recognizer = fake_vosk.recognizers[0]
    recognizer.results = [(True, '{"text": "hey whale"}')]
    adapter.feed(b"\x00\x00")
    if not has_reset:
        monkeypatch.delattr(fake_vosk.KaldiRecognizer, "Reset")
    adapter.reset()
    assert recognizer.reset_calls == int(has_reset)
    assert adapter.is_final is False


def test_missing_model_directory(fake_vosk, tmp_path):
    with pytest.raises(WakeWordRecognizerUnavailable, match="model directory does not exist"):
        VoskWakeWordRecognizer(tmp_path / "missing", ["hey whale"])
    assert fake_vosk.models == []


def test_missing_vosk(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "vosk", None)
    with pytest.raises(WakeWordRecognizerUnavailable, match="Vosk.*not installed"):
        VoskWakeWordRecognizer(tmp_path, ["hey whale"])


def test_import_does_not_load_vosk_or_qt(monkeypatch):
    monkeypatch.setitem(sys.modules, "vosk", None)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert not name.startswith(("vosk", "PyQt", "PySide"))
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    spec = importlib.util.spec_from_file_location("isolated_wake_word_vosk", wake_word_vosk.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.VoskWakeWordRecognizer is not None


def test_adapter_output_through_controller_matcher(fake_vosk, tmp_path):
    wakes = []
    phrases = ["Hey, Whale!"]
    controller = WakeWordController(phrases, wakes.append, cooldown_seconds=0)
    controller.start()
    adapter = VoskWakeWordRecognizer(tmp_path, phrases)
    fake_vosk.recognizers[0].results = [
        (False, '{"partial": "hey whale"}'),
        (False, '{"partial": "hey whale"}'),
        (True, '{"text": ""}'),
        (True, '{"text": "hey whale"}'),
    ]
    hits = []
    for _ in range(4):
        text = adapter.feed(b"\x00\x00")
        hits.append(controller.feed_transcript(text or "", final=adapter.is_final))
    assert hits == [True, False, False, True]
    assert wakes == ["Hey, Whale!", "Hey, Whale!"]
