import io
import wave
from dataclasses import FrozenInstanceError

import pytest

from companion.core.voice_input import AudioFormat, PushToTalkRecorder, RecordedClip, encode_wav


def read_pcm(clip):
    with wave.open(io.BytesIO(clip.wav), "rb") as reader:
        return reader.readframes(reader.getnframes())


@pytest.mark.parametrize("sample_rate", [8000, 16000, 44100])
@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("sample_width", [1, 2, 3, 4])
@pytest.mark.parametrize("frames", [0, 7])
def test_wav_round_trip(sample_rate, channels, sample_width, frames):
    pcm = bytes(range(channels * sample_width * frames))
    audio = encode_wav(pcm, sample_rate, channels, sample_width)
    assert isinstance(audio, bytes)
    with wave.open(io.BytesIO(audio), "rb") as reader:
        assert reader.getframerate() == sample_rate
        assert reader.getnchannels() == channels
        assert reader.getsampwidth() == sample_width
        assert reader.getnframes() == frames
        assert reader.readframes(frames) == pcm


INVALID_FORMATS = [
    {"sample_rate": 0}, {"sample_rate": -1},
    {"channels": 0}, {"channels": -1},
    {"sample_width": 0}, {"sample_width": -1}, {"sample_width": 5},
]


@pytest.mark.parametrize("options", INVALID_FORMATS)
def test_invalid_wav_format(options):
    kwargs = dict(sample_rate=16000)
    kwargs.update(options)
    with pytest.raises(ValueError):
        encode_wav(b"", **kwargs)


@pytest.mark.parametrize("pcm,channels,sample_width", [(b"x", 1, 2), (b"abc", 2, 2), (b"abcd", 2, 3)])
def test_wav_rejects_partial_frames(pcm, channels, sample_width):
    with pytest.raises(ValueError):
        encode_wav(pcm, 16000, channels, sample_width)


@pytest.mark.parametrize("options", INVALID_FORMATS)
def test_recorder_rejects_invalid_format(options):
    with pytest.raises(ValueError):
        PushToTalkRecorder(fmt=AudioFormat(**options))


@pytest.mark.parametrize("options", [
    {"min_seconds": -0.1}, {"max_seconds": 0}, {"max_seconds": -1},
    {"min_seconds": 2, "max_seconds": 1},
    {"min_seconds": float("nan")}, {"max_seconds": float("nan")},
    {"min_seconds": float("inf")}, {"max_seconds": float("inf")},
])
def test_recorder_rejects_invalid_limits(options):
    with pytest.raises(ValueError):
        PushToTalkRecorder(**options)


def test_format_defaults_and_bytes_per_second():
    fmt = AudioFormat()
    assert (fmt.sample_rate, fmt.channels, fmt.sample_width) == (16000, 1, 2)
    assert fmt.bytes_per_second == 32000
    assert AudioFormat(8000, 2, 3).bytes_per_second == 48000


def test_dataclasses_are_frozen():
    fmt = AudioFormat()
    clip = RecordedClip(wav=b"wav", duration_seconds=1.0, truncated=False)
    with pytest.raises(FrozenInstanceError):
        fmt.channels = 2
    with pytest.raises(FrozenInstanceError):
        clip.truncated = True


@pytest.mark.parametrize("frames", [0, 1, 4799])
def test_short_tap_returns_none(frames):
    recorder = PushToTalkRecorder()
    recorder.press()
    recorder.feed(b"\0\0" * frames)
    assert recorder.release() is None
    assert not recorder.is_recording


@pytest.mark.parametrize("frames", [4800, 8000])
def test_normal_clip_duration_and_release_twice(frames):
    recorder = PushToTalkRecorder()
    assert not recorder.is_recording
    assert recorder.release() is None
    recorder.press()
    assert recorder.is_recording
    pcm = b"\x01\x02" * frames
    assert recorder.feed(pcm) is True
    clip = recorder.release()
    assert isinstance(clip, RecordedClip)
    assert clip.duration_seconds == pytest.approx(frames / 16000)
    assert not clip.truncated
    assert read_pcm(clip) == pcm
    assert not recorder.is_recording
    assert recorder.release() is None


def test_feed_outside_recording_is_ignored():
    recorder = PushToTalkRecorder(min_seconds=0)
    assert recorder.feed(b"ignored") is True
    assert recorder.release() is None
    recorder.press()
    clip = recorder.release()
    assert read_pcm(clip) == b""
    assert clip.duration_seconds == 0
    assert recorder.feed(b"ignored again") is True
    assert recorder.release() is None


@pytest.mark.parametrize("extra", [b"", b"extra bytes"])
def test_max_duration_caps_audio(extra):
    recorder = PushToTalkRecorder(AudioFormat(10, 2, 2), min_seconds=0, max_seconds=0.5)
    recorder.press()
    pcm = bytes(range(20))
    assert recorder.feed(pcm[:4]) is True
    assert recorder.feed(pcm[4:] + extra) is False
    assert recorder.feed(b"more") is False
    assert recorder.feed(b"") is False
    clip = recorder.release()
    assert read_pcm(clip) == pcm
    assert clip.duration_seconds == 0.5
    assert clip.truncated


def test_partial_frames_are_preserved_across_chunks():
    recorder = PushToTalkRecorder(AudioFormat(10, 2, 2), min_seconds=0)
    recorder.press()
    for chunk in (b"a", b"bc", b"de", b"fgh", b"i"):
        assert recorder.feed(chunk) is True
    clip = recorder.release()
    assert read_pcm(clip) == b"abcdefgh"
    assert clip.duration_seconds == 0.2
    assert not clip.truncated


def test_cap_rounds_down_to_whole_frames():
    recorder = PushToTalkRecorder(AudioFormat(10, 2, 2), min_seconds=0, max_seconds=0.25)
    recorder.press()
    assert recorder.feed(b"abc") is True
    assert recorder.feed(b"defghij") is False
    clip = recorder.release()
    assert read_pcm(clip) == b"abcdefgh"
    assert clip.duration_seconds == 0.2
    assert clip.truncated


def test_cap_shorter_than_one_frame():
    recorder = PushToTalkRecorder(AudioFormat(10), min_seconds=0, max_seconds=0.01)
    recorder.press()
    assert recorder.feed(b"ab") is False
    clip = recorder.release()
    assert read_pcm(clip) == b""
    assert clip.duration_seconds == 0
    assert clip.truncated


@pytest.mark.parametrize("old_audio", [b"abc", b"abcdextra"])
def test_press_restarts_and_resets_partial_frames_and_truncation(old_audio):
    recorder = PushToTalkRecorder(AudioFormat(10), min_seconds=0, max_seconds=0.2)
    recorder.press()
    recorder.feed(old_audio)
    recorder.press()
    assert recorder.feed(b"xy") is True
    clip = recorder.release()
    assert read_pcm(clip) == b"xy"
    assert clip.duration_seconds == 0.1
    assert not clip.truncated


def test_cancel_discards_audio_and_partial_frame():
    recorder = PushToTalkRecorder(min_seconds=0)
    recorder.cancel()
    recorder.press()
    recorder.feed(b"abc")
    recorder.cancel()
    assert not recorder.is_recording
    assert recorder.release() is None
    assert recorder.feed(b"ignored") is True
    recorder.press()
    recorder.feed(b"xy")
    assert read_pcm(recorder.release()) == b"xy"


def test_equal_minimum_and_maximum_is_allowed():
    recorder = PushToTalkRecorder(AudioFormat(10), min_seconds=0.2, max_seconds=0.2)
    recorder.press()
    assert recorder.feed(b"abcd") is False
    clip = recorder.release()
    assert clip.duration_seconds == 0.2
    assert clip.truncated
