import io
import wave
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from companion.core.config import AppConfig
from companion.core.voice_input import AudioFormat, PushToTalkRecorder
from companion.core.voice_input_controller import VoiceInputController, VoiceInputResult

PCM = b"\x01\x02" * 4800  # Exactly the recorder's default minimum: 0.3 seconds.


def make_controller(transcribe=None, **kwargs):
    config = AppConfig(voice_input=True, transcription_model=" test-model ")
    return VoiceInputController(config, transcribe=transcribe, **kwargs)


def read_pcm(wav):
    with wave.open(io.BytesIO(wav), "rb") as reader:
        return reader.readframes(reader.getnframes())


def test_idle_and_successful_turn_can_be_repeated():
    received = []

    def transcribe(wav):
        assert controller.state == "transcribing"
        received.append(read_pcm(wav))
        return "  hello world\n"

    controller = make_controller(transcribe)
    assert controller.state == "idle"
    assert controller.stop() == VoiceInputResult("idle")
    assert controller.feed(b"ignored") is True
    for _ in range(2):
        assert controller.start() == VoiceInputResult("recording")
        assert controller.state == "recording"
        assert controller.feed(PCM[:1]) is True
        assert controller.feed(PCM[1:]) is True
        assert controller.stop() == VoiceInputResult("ok", text="hello world")
        assert controller.state == "idle"
        assert controller.stop() == VoiceInputResult("idle")
    assert received == [PCM, PCM]


@pytest.mark.parametrize("enabled,model", [(False, "model"), (False, ""), (True, ""), (True, " \t\n")])
def test_disabled_start_is_a_noop(enabled, model):
    transcribe = Mock(return_value="unused")
    recorder = PushToTalkRecorder()
    config = AppConfig(voice_input=enabled, transcription_model=model)
    controller = VoiceInputController(config, transcribe, recorder=recorder)
    result = controller.start()
    assert result.status == "disabled"
    assert result.text == ""
    assert controller.state == "idle"
    assert not recorder.is_recording
    controller.feed(PCM)
    assert controller.stop() == VoiceInputResult("idle")
    transcribe.assert_not_called()
    config.voice_input = True
    config.transcription_model = "model"
    assert controller.start().status == "recording"


@pytest.mark.parametrize("frames", [0, 1, 4799])
def test_too_short_does_not_transcribe(frames):
    transcribe = Mock(return_value="unused")
    controller = make_controller(transcribe)
    controller.start()
    controller.feed(b"\0\0" * frames)
    assert controller.stop() == VoiceInputResult("too_short")
    assert controller.state == "idle"
    transcribe.assert_not_called()
    assert controller.start().status == "recording"


@pytest.mark.parametrize("text", ["", " \t\n"])
def test_empty_transcript_has_no_text(text):
    transcribe = Mock(return_value=text)
    controller = make_controller(transcribe)
    controller.start()
    controller.feed(PCM)
    assert controller.stop() == VoiceInputResult("empty_transcript")
    assert controller.state == "idle"
    transcribe.assert_called_once()


def test_transcription_error_returns_to_idle_and_allows_retry():
    transcribe = Mock(side_effect=[RuntimeError("transcription failed"), "recovered"])
    controller = make_controller(transcribe)
    controller.start()
    controller.feed(PCM)
    assert controller.stop() == VoiceInputResult("error", message="transcription failed")
    assert controller.state == "idle"
    controller.start()
    controller.feed(PCM)
    assert controller.stop() == VoiceInputResult("ok", text="recovered")


def test_default_has_no_transcriber():
    controller = make_controller()
    controller.start()
    controller.feed(PCM)
    result = controller.stop()
    assert result.status == "error"
    assert result.message
    assert result.text == ""
    assert controller.state == "idle"


def test_cancel_discards_recording_and_partial_frame():
    transcribe = Mock(return_value="fresh")
    controller = make_controller(transcribe)
    assert controller.cancel() == VoiceInputResult("idle")
    controller.start()
    controller.feed(PCM + b"x")
    assert controller.cancel() == VoiceInputResult("idle")
    assert controller.state == "idle"
    assert controller.stop() == VoiceInputResult("idle")
    transcribe.assert_not_called()
    controller.start()
    controller.feed(PCM)
    assert controller.stop().text == "fresh"
    assert read_pcm(transcribe.call_args.args[0]) == PCM


def test_double_start_preserves_recording():
    transcribe = Mock(return_value="hello")
    controller = make_controller(transcribe)
    controller.start()
    controller.feed(PCM[:4800])
    assert controller.start() == VoiceInputResult("recording")
    controller.feed(PCM[4800:])
    assert controller.stop().status == "ok"
    assert read_pcm(transcribe.call_args.args[0]) == PCM


@pytest.mark.parametrize("cancel", [False, True])
def test_busy_transcription_ignores_start_stop_and_feed(cancel):
    entered = Event()
    finish = Event()

    def transcribe(wav):
        entered.set()
        assert finish.wait(5)
        return "hello"

    controller = make_controller(transcribe)
    controller.start()
    controller.feed(PCM)
    with ThreadPoolExecutor(max_workers=1) as worker:
        pending = worker.submit(controller.stop)
        try:
            assert entered.wait(5)
            assert controller.state == "transcribing"
            assert controller.start() == VoiceInputResult("transcribing")
            assert controller.stop() == VoiceInputResult("transcribing")
            assert controller.feed(PCM) is True
            if cancel:
                # The synchronous call cannot be interrupted; discard its eventual result.
                assert controller.cancel() == VoiceInputResult("transcribing")
                assert controller.start() == VoiceInputResult("transcribing")
        finally:
            finish.set()
        expected = VoiceInputResult("idle") if cancel else VoiceInputResult("ok", text="hello")
        assert pending.result(timeout=5) == expected
    assert controller.state == "idle"
    assert controller.start().status == "recording"
    assert controller.stop().status == "too_short"


def test_recorder_custom_limits_are_reused():
    transcribe = Mock(return_value="bounded")
    recorder = PushToTalkRecorder(AudioFormat(10), min_seconds=0.5, max_seconds=1)
    controller = make_controller(transcribe, recorder=recorder)
    controller.start()
    controller.feed(b"ab" * 4)
    assert controller.stop().status == "too_short"
    transcribe.assert_not_called()
    controller.start()
    assert controller.feed(b"ab" * 20) is False
    assert controller.feed(b"more") is False
    assert controller.stop().status == "ok"
    assert read_pcm(transcribe.call_args.args[0]) == b"ab" * 10


def test_default_maximum_duration_is_bounded():
    transcribe = Mock(return_value="bounded")
    controller = make_controller(transcribe)
    controller.start()
    assert controller.feed(b"ab" * (16000 * 61)) is False
    assert controller.stop().status == "ok"
    assert read_pcm(transcribe.call_args.args[0]) == b"ab" * (16000 * 60)
