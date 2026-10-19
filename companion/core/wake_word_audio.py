"""Sample alignment for streaming 16-bit PCM, independent of Qt and devices."""


class Pcm16ChunkBuffer:
    """Retain at most one byte so every emitted chunk contains whole samples."""

    def __init__(self) -> None:
        self._pending = b""

    def feed(self, chunk: bytes) -> bytes:
        data = self._pending + chunk
        end = len(data) - len(data) % 2
        self._pending = data[end:]
        return data[:end]

    def reset(self) -> None:
        """Discard an incomplete sample when a listening session ends."""
        self._pending = b""
