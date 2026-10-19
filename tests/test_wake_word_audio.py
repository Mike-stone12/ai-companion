from companion.core.wake_word_audio import Pcm16ChunkBuffer


def test_chunks_preserve_samples_across_odd_byte_boundaries():
    buffer = Pcm16ChunkBuffer()
    assert buffer.feed(b"\x01") == b""
    assert buffer.feed(b"") == b""
    assert buffer.feed(b"\x02\x03\x04\x05") == b"\x01\x02\x03\x04"
    assert buffer.feed(b"\x06\x07") == b"\x05\x06"
    assert buffer.feed(b"\x08") == b"\x07\x08"
    assert buffer.feed(b"\x09\x0a") == b"\x09\x0a"


def test_reset_discards_incomplete_sample_between_sessions():
    buffer = Pcm16ChunkBuffer()
    buffer.feed(b"\xff")
    buffer.reset()
    buffer.reset()
    assert buffer.feed(b"\x01\x02") == b"\x01\x02"
