from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from .models import CHUNK_BYTES, CHUNK_MS, AudioChunk


class AudioSourceError(RuntimeError):
    pass


class AudioSource(Protocol):
    def start(self) -> None: ...

    def read_chunk(self) -> AudioChunk | None: ...

    def stop(self) -> None: ...

    def snapshot_stats(self) -> AudioSourceStats: ...


@dataclass(frozen=True, slots=True)
class AudioSourceStats:
    input_overflow_events: int = 0
    dropped_input_blocks: int = 0
    dropped_output_chunks: int = 0

    def __post_init__(self) -> None:
        if (
            self.input_overflow_events < 0
            or self.dropped_input_blocks < 0
            or self.dropped_output_chunks < 0
        ):
            raise ValueError("audio drop counters must be non-negative")

    @property
    def has_drops(self) -> bool:
        return (
            self.input_overflow_events > 0
            or self.dropped_input_blocks > 0
            or self.dropped_output_chunks > 0
        )


@dataclass(slots=True)
class Pcm16FrameBuffer:
    _buffer: bytearray = field(default_factory=bytearray, init=False)
    _next_chunk_id: int = field(default=0, init=False)
    _next_captured_at_ms: int | None = field(default=None, init=False)

    def push(self, pcm_bytes: bytes, *, captured_at_ms: int) -> list[AudioChunk]:
        if captured_at_ms < 0:
            raise ValueError("captured_at_ms must be non-negative")
        if len(pcm_bytes) % 2:
            raise ValueError("PCM16 input must contain complete samples")
        if self._next_captured_at_ms is None:
            self._next_captured_at_ms = captured_at_ms
        self._buffer.extend(pcm_bytes)

        chunks: list[AudioChunk] = []
        while len(self._buffer) >= CHUNK_BYTES:
            chunk_bytes = bytes(self._buffer[:CHUNK_BYTES])
            del self._buffer[:CHUNK_BYTES]
            chunk = AudioChunk(
                chunk_id=self._next_chunk_id,
                pcm_bytes=chunk_bytes,
                captured_at_ms=self._next_captured_at_ms,
            )
            chunks.append(chunk)
            self._next_chunk_id += 1
            self._next_captured_at_ms += CHUNK_MS

        if not self._buffer:
            self._next_captured_at_ms = None
        return chunks

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)

    def clear(self) -> None:
        self._buffer.clear()
        self._next_captured_at_ms = None

    def finish(self) -> list[AudioChunk]:
        if not self._buffer or self._next_captured_at_ms is None:
            return []
        padded = bytes(self._buffer) + b"\x00" * (CHUNK_BYTES - len(self._buffer))
        chunk = AudioChunk(
            chunk_id=self._next_chunk_id,
            pcm_bytes=padded,
            captured_at_ms=self._next_captured_at_ms,
        )
        self._buffer.clear()
        self._next_chunk_id += 1
        self._next_captured_at_ms = None
        return [chunk]


@dataclass(slots=True)
class IterableAudioSource:
    chunks: Iterable[AudioChunk]
    _iterator: Iterator[AudioChunk] | None = field(default=None, init=False)
    _running: bool = field(default=False, init=False)

    def start(self) -> None:
        if self._running:
            raise RuntimeError("audio source is already running")
        self._iterator = iter(self.chunks)
        self._running = True

    def read_chunk(self) -> AudioChunk | None:
        if not self._running or self._iterator is None:
            raise RuntimeError("audio source is not running")
        iterator = self._iterator
        try:
            return next(iterator)
        except StopIteration:
            return None

    def stop(self) -> None:
        self._running = False
        self._iterator = None

    def snapshot_stats(self) -> AudioSourceStats:
        return AudioSourceStats()
