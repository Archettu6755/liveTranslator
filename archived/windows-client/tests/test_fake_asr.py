from __future__ import annotations

from live_translator.asr import FakeAsrClient
from live_translator.models import CHUNK_BYTES, AudioChunk, StartStream, TranscriptFinal


def make_chunk(chunk_id: int) -> AudioChunk:
    return AudioChunk(
        chunk_id=chunk_id,
        pcm_bytes=b"\x00" * CHUNK_BYTES,
        captured_at_ms=chunk_id * 100,
    )


async def test_fake_asr_emits_multiple_finals_before_stop() -> None:
    client = FakeAsrClient(
        transcripts=("一つ目です。", "二つ目です。"),
        chunks_per_final=1,
    )
    await client.connect()
    await client.start_stream(StartStream(session_id="session"))
    await client.send_audio(make_chunk(0))
    await client.send_audio(make_chunk(1))
    await client.stop_stream()

    events = [event async for event in client.events()]
    finals = [event for event in events if isinstance(event, TranscriptFinal)]

    assert [event.seq for event in finals] == [1, 2]
    assert [event.text for event in finals] == ["一つ目です。", "二つ目です。"]


async def test_fake_asr_flushes_remaining_final_on_stop() -> None:
    client = FakeAsrClient(transcripts=("停止時の文です。",), chunks_per_final=10)
    await client.connect()
    await client.start_stream(StartStream(session_id="session"))
    await client.send_audio(make_chunk(0))
    await client.stop_stream()

    events = [event async for event in client.events()]

    assert any(
        isinstance(event, TranscriptFinal) and event.text == "停止時の文です。" for event in events
    )
