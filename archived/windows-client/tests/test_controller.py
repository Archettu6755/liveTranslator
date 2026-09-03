from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

import pytest

from live_translator.asr import FakeAsrClient
from live_translator.audio import AudioSourceStats, IterableAudioSource
from live_translator.controller import SessionController, SessionError
from live_translator.models import (
    CHUNK_BYTES,
    AudioChunk,
    TranslationRequest,
    TranslationResult,
)
from live_translator.subtitle import MemorySubtitleSink
from live_translator.translator import TranslationError


def make_chunk(chunk_id: int) -> AudioChunk:
    return AudioChunk(
        chunk_id=chunk_id,
        pcm_bytes=b"\x00" * CHUNK_BYTES,
        captured_at_ms=chunk_id * 100,
    )


@dataclass(slots=True)
class RecordingTranslator:
    translations: dict[str, str]
    requests: list[TranslationRequest] = field(default_factory=lambda: [])
    closed: bool = False

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        self.requests.append(request)
        return TranslationResult(
            source_text=request.source_text,
            translated_text=self.translations[request.source_text],
        )

    async def close(self) -> None:
        self.closed = True


@dataclass(slots=True)
class FailingTranslator:
    seen: list[str] = field(default_factory=lambda: [])

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        self.seen.append(request.source_text)
        raise TranslationError("Translation is unavailable.")

    async def close(self) -> None:
        return


@dataclass(slots=True)
class BlockedFirstTranslator:
    translations: dict[str, str]
    audio_gate: threading.Event
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    seen: list[str] = field(default_factory=lambda: [])

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        self.seen.append(request.source_text)
        if len(self.seen) == 1:
            self.started.set()
            self.audio_gate.set()
            await self.release.wait()
        return TranslationResult(
            source_text=request.source_text,
            translated_text=self.translations[request.source_text],
        )

    async def close(self) -> None:
        return


@dataclass(slots=True)
class UnexpectedOnceTranslator:
    seen: list[str] = field(default_factory=lambda: [])

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        self.seen.append(request.source_text)
        if len(self.seen) == 1:
            raise RuntimeError("provider internals")
        return TranslationResult(
            source_text=request.source_text,
            translated_text="第二条",
        )

    async def close(self) -> None:
        return


@dataclass(slots=True)
class CloseFailingTranslator(RecordingTranslator):
    close_attempted: bool = False

    async def close(self) -> None:
        self.close_attempted = True
        raise RuntimeError("translator close failed")


@dataclass(slots=True)
class CloseFailingAsr(FakeAsrClient):
    close_attempted: bool = False

    async def close(self) -> None:
        self.close_attempted = True
        raise RuntimeError("ASR close failed")


@dataclass(slots=True)
class GatedAudioSource:
    chunks: list[AudioChunk]
    gate: threading.Event
    _index: int = field(default=0, init=False)
    _started: bool = field(default=False, init=False)

    def start(self) -> None:
        self._started = True

    def read_chunk(self) -> AudioChunk | None:
        if not self._started:
            raise RuntimeError("audio source is not started")
        if self._index == 1 and not self.gate.wait(timeout=2):
            raise RuntimeError("translator did not start")
        if self._index >= len(self.chunks):
            return None
        chunk = self.chunks[self._index]
        self._index += 1
        return chunk

    def stop(self) -> None:
        self._started = False
        self.gate.set()

    def snapshot_stats(self) -> AudioSourceStats:
        return AudioSourceStats()


@dataclass(slots=True)
class DroppingAudioSource:
    chunks: list[AudioChunk]
    _index: int = field(default=0, init=False)
    _running: bool = field(default=False, init=False)

    def start(self) -> None:
        self._running = True

    def read_chunk(self) -> AudioChunk | None:
        if not self._running:
            return None
        if self._index >= len(self.chunks):
            return None
        chunk = self.chunks[self._index]
        self._index += 1
        return chunk

    def stop(self) -> None:
        self._running = False

    def snapshot_stats(self) -> AudioSourceStats:
        return AudioSourceStats(
            input_overflow_events=3,
            dropped_input_blocks=1,
            dropped_output_chunks=2,
        )


@dataclass(slots=True)
class TailOnStopAudioSource:
    tail_chunks: list[AudioChunk]
    read_started: threading.Event = field(default_factory=threading.Event)
    stopped: threading.Event = field(default_factory=threading.Event)

    def start(self) -> None:
        return

    def read_chunk(self) -> AudioChunk | None:
        self.read_started.set()
        if not self.stopped.wait(timeout=2):
            raise RuntimeError("audio source was not stopped")
        if not self.tail_chunks:
            return None
        return self.tail_chunks.pop(0)

    def stop(self) -> None:
        self.stopped.set()

    def snapshot_stats(self) -> AudioSourceStats:
        return AudioSourceStats()


async def wait_for_source(controller: SessionController, source_text: str) -> None:
    for _ in range(100):
        if controller.state.source_text == source_text:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"subtitle did not advance to {source_text}")


async def test_controller_runs_two_finals_through_translation_and_subtitle() -> None:
    translator = RecordingTranslator({"一つ": "第一条", "二つ": "第二条"})
    sink = MemorySubtitleSink()
    controller = SessionController(
        audio_source=IterableAudioSource([make_chunk(0), make_chunk(1)]),
        asr_client=FakeAsrClient(
            transcripts=("一つ", "二つ"),
            chunks_per_final=1,
        ),
        translator=translator,
        subtitle_sink=sink,
    )

    state = await controller.run()

    assert state.status == "stopped"
    assert state.source_text == "二つ"
    assert state.translated_text == "第二条"
    assert [segment.seq for segment in state.segments] == [1, 2]
    assert all(segment.translation_status == "translated" for segment in state.segments)
    assert [request.source_text for request in translator.requests] == ["一つ", "二つ"]
    assert translator.requests[0].context == ()
    assert translator.requests[1].context[0].translated_text == "第一条"
    assert translator.closed
    assert any(item.source_text == "一つ" and not item.translated_text for item in sink.history)


async def test_translation_failure_keeps_receiving_asr_finals() -> None:
    translator = FailingTranslator()
    sink = MemorySubtitleSink()
    controller = SessionController(
        audio_source=IterableAudioSource([make_chunk(0), make_chunk(1)]),
        asr_client=FakeAsrClient(
            transcripts=("一つ", "二つ"),
            chunks_per_final=1,
        ),
        translator=translator,
        subtitle_sink=sink,
    )

    state = await controller.run()

    assert state.status == "stopped"
    assert translator.seen == ["一つ", "二つ"]
    assert any(
        item.source_text == "二つ"
        and item.translated_text == ""
        and item.message == "Translation is unavailable."
        for item in sink.history
    )


async def test_late_translation_updates_its_segment_without_reverting_current_text() -> None:
    audio_gate = threading.Event()
    translator = BlockedFirstTranslator(
        {"一つ": "第一条", "二つ": "第二条", "三つ": "第三条"},
        audio_gate=audio_gate,
    )
    sink = MemorySubtitleSink()
    controller = SessionController(
        audio_source=GatedAudioSource(
            [make_chunk(0), make_chunk(1), make_chunk(2)],
            gate=audio_gate,
        ),
        asr_client=FakeAsrClient(
            transcripts=("一つ", "二つ", "三つ"),
            chunks_per_final=1,
        ),
        translator=translator,
        subtitle_sink=sink,
    )
    run_task = asyncio.create_task(controller.run())
    await translator.started.wait()
    await wait_for_source(controller, "三つ")
    history_after_latest_final = len(sink.history)
    translator.release.set()
    await run_task

    states_after_latest_final = sink.history[history_after_latest_final:]
    assert controller.state.source_text == "三つ"
    assert [segment.seq for segment in controller.state.segments] == [2, 3]
    assert all(state.source_text == "三つ" for state in states_after_latest_final)
    assert translator.seen == ["一つ", "二つ", "三つ"]


async def test_full_translation_queue_drops_the_oldest_pending_segment() -> None:
    audio_gate = threading.Event()
    translator = BlockedFirstTranslator(
        {
            "一つ": "第一条",
            "二つ": "第二条",
            "三つ": "第三条",
            "四つ": "第四条",
        },
        audio_gate=audio_gate,
    )
    sink = MemorySubtitleSink()
    controller = SessionController(
        audio_source=GatedAudioSource(
            [make_chunk(0), make_chunk(1), make_chunk(2), make_chunk(3)],
            gate=audio_gate,
        ),
        asr_client=FakeAsrClient(
            transcripts=("一つ", "二つ", "三つ", "四つ"),
            chunks_per_final=1,
        ),
        translator=translator,
        subtitle_sink=sink,
        translation_queue_size=2,
    )

    run_task = asyncio.create_task(controller.run())
    await translator.started.wait()
    await wait_for_source(controller, "四つ")
    translator.release.set()
    await run_task

    assert translator.seen == ["一つ", "三つ", "四つ"]
    assert any(
        state.status == "degraded"
        and state.message == "Translation queue dropped an older subtitle."
        for state in sink.history
    )


async def test_unexpected_translation_failure_does_not_stop_later_finals() -> None:
    translator = UnexpectedOnceTranslator()
    sink = MemorySubtitleSink()
    controller = SessionController(
        audio_source=IterableAudioSource([make_chunk(0), make_chunk(1)]),
        asr_client=FakeAsrClient(
            transcripts=("一つ", "二つ"),
            chunks_per_final=1,
        ),
        translator=translator,
        subtitle_sink=sink,
    )

    state = await controller.run()

    assert state.status == "stopped"
    assert translator.seen == ["一つ", "二つ"]
    assert state.translated_text == "第二条"
    assert any(item.message == "Translation failed unexpectedly." for item in sink.history)


async def test_cleanup_attempts_both_clients_when_each_close_fails() -> None:
    translator = CloseFailingTranslator({"一つ": "第一条"})
    asr = CloseFailingAsr(transcripts=("一つ",), chunks_per_final=1)
    controller = SessionController(
        audio_source=IterableAudioSource([make_chunk(0)]),
        asr_client=asr,
        translator=translator,
        subtitle_sink=MemorySubtitleSink(),
    )

    with pytest.raises(SessionError, match="cleanup failed"):
        await controller.run()

    assert translator.close_attempted
    assert asr.close_attempted


async def test_audio_queue_drops_are_visible_in_session_state_history() -> None:
    sink = MemorySubtitleSink()
    controller = SessionController(
        audio_source=DroppingAudioSource([make_chunk(0)]),
        asr_client=FakeAsrClient(transcripts=("一つ",), chunks_per_final=1),
        translator=RecordingTranslator({"一つ": "第一条"}),
        subtitle_sink=sink,
    )

    await controller.run()

    assert any(
        state.status == "degraded"
        and state.message
        == (
            "Audio capture reported 3 native overflow events, "
            "dropped 1 input blocks and 2 normalized chunks."
        )
        for state in sink.history
    )


async def test_stop_drains_normalized_audio_before_stopping_asr() -> None:
    source = TailOnStopAudioSource([make_chunk(0), make_chunk(1), make_chunk(2)])
    controller = SessionController(
        audio_source=source,
        asr_client=FakeAsrClient(
            transcripts=("一つ", "二つ", "三つ"),
            chunks_per_final=1,
        ),
        translator=RecordingTranslator({"一つ": "第一条", "二つ": "第二条", "三つ": "第三条"}),
        subtitle_sink=MemorySubtitleSink(),
    )

    run_task = asyncio.create_task(controller.run())
    assert await asyncio.to_thread(source.read_started.wait, 1.0)
    controller.request_stop()
    state = await asyncio.wait_for(run_task, timeout=2.0)

    assert state.source_text == "三つ"
    assert [segment.seq for segment in state.segments] == [2, 3]
