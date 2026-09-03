from __future__ import annotations

import pytest

from live_translator.audio import IterableAudioSource, Pcm16FrameBuffer
from live_translator.models import CHUNK_BYTES, AudioChunk


def make_chunk(chunk_id: int) -> AudioChunk:
    return AudioChunk(
        chunk_id=chunk_id,
        pcm_bytes=bytes([chunk_id % 255]) * CHUNK_BYTES,
        captured_at_ms=chunk_id * 100,
    )


def test_frame_buffer_emits_fixed_frames_and_keeps_remainder() -> None:
    buffer = Pcm16FrameBuffer()
    first = b"\x01\x00" * 1_000
    second = b"\x02\x00" * 2_200

    assert buffer.push(first, captured_at_ms=500) == []
    chunks = buffer.push(second, captured_at_ms=562)

    assert len(chunks) == 2
    assert [chunk.chunk_id for chunk in chunks] == [0, 1]
    assert [chunk.captured_at_ms for chunk in chunks] == [500, 600]
    assert all(len(chunk.pcm_bytes) == CHUNK_BYTES for chunk in chunks)
    assert buffer.pending_bytes == 0


def test_frame_buffer_rejects_half_sample() -> None:
    with pytest.raises(ValueError, match="complete samples"):
        Pcm16FrameBuffer().push(b"\x00", captured_at_ms=0)


def test_frame_buffer_pads_the_final_partial_frame() -> None:
    buffer = Pcm16FrameBuffer()
    partial = b"\x01\x00" * 320

    assert buffer.push(partial, captured_at_ms=700) == []
    chunks = buffer.finish()

    assert len(chunks) == 1
    assert chunks[0].chunk_id == 0
    assert chunks[0].captured_at_ms == 700
    assert chunks[0].pcm_bytes[: len(partial)] == partial
    assert chunks[0].pcm_bytes[len(partial) :] == b"\x00" * (CHUNK_BYTES - len(partial))
    assert buffer.pending_bytes == 0


def test_iterable_audio_source_has_explicit_lifecycle() -> None:
    source = IterableAudioSource([make_chunk(0)])
    source.start()

    assert source.read_chunk() == make_chunk(0)
    assert source.read_chunk() is None

    source.stop()
    with pytest.raises(RuntimeError, match="not running"):
        source.read_chunk()
