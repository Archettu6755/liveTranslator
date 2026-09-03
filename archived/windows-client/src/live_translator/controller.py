from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field, replace
from uuid import uuid4

from .asr import AsrClient, AsrClientError
from .audio import AudioSource, AudioSourceError, AudioSourceStats
from .diagnostics import get_logger
from .models import (
    MAX_VISIBLE_SUBTITLES,
    AppStatus,
    AsrError,
    AsrEvent,
    RuntimeOverloaded,
    StartStream,
    StreamReady,
    StreamStopped,
    SubtitleSegment,
    SubtitleState,
    TranscriptFinal,
    TranslationContext,
    TranslationRequest,
    TranslationStatus,
)
from .subtitle import SubtitleSink
from .translator import TranslationError, TranslatorClient


class SessionError(RuntimeError):
    pass


_LOGGER = get_logger("controller")
_UNEXPECTED_SESSION_ERROR = "Session stopped because of an unexpected error."


@dataclass(slots=True)
class SessionController:
    audio_source: AudioSource
    asr_client: AsrClient
    translator: TranslatorClient
    subtitle_sink: SubtitleSink
    translation_queue_size: int = 2
    session_id: str = field(default_factory=lambda: uuid4().hex)
    state: SubtitleState = field(default_factory=SubtitleState, init=False)
    _stop_requested: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _translation_queue: asyncio.Queue[TranscriptFinal | None] = field(init=False)
    _context: deque[TranslationContext] = field(
        default_factory=lambda: deque(maxlen=2),
        init=False,
    )
    _running: bool = field(default=False, init=False)
    _last_seq: int = field(default=0, init=False)
    _last_audio_stats: AudioSourceStats = field(default_factory=AudioSourceStats, init=False)

    def __post_init__(self) -> None:
        if self.translation_queue_size < 1:
            raise ValueError("translation_queue_size must be positive")
        self._translation_queue = asyncio.Queue(maxsize=self.translation_queue_size)

    async def run(self) -> SubtitleState:
        if self._running:
            raise SessionError("session is already running")
        self._running = True
        self._stop_requested.clear()
        self._publish(status="connecting", message="Connecting to ASR service.")

        event_task: asyncio.Task[None] | None = None
        translation_task: asyncio.Task[None] | None = None
        audio_started = False
        try:
            if not await self.asr_client.probe_ready():
                raise SessionError("ASR service is not ready.")
            await self.asr_client.connect()
            await self.asr_client.start_stream(StartStream(session_id=self.session_id))

            translation_task = asyncio.create_task(self._translation_loop())
            event_task = asyncio.create_task(self._event_loop())
            self.audio_source.start()
            audio_started = True
            self._publish(status="running", message="")

            while not self._stop_requested.is_set():
                chunk = await asyncio.to_thread(self.audio_source.read_chunk)
                self._report_audio_drops()
                if chunk is None:
                    break
                await self.asr_client.send_audio(chunk)

            self._publish(status="stopping", message="")
            if audio_started:
                self.audio_source.stop()
                audio_started = False
            if self._stop_requested.is_set():
                await self._drain_audio_after_stop()
            await self.asr_client.stop_stream()
            await event_task
            await self._translation_queue.join()
            await self._translation_queue.put(None)
            await translation_task
            self._publish(status="stopped", message="")
            return self.state
        except Exception as exc:
            message = _user_message(exc)
            self._publish(status="error", message=message)
            if message == _UNEXPECTED_SESSION_ERROR:
                _LOGGER.exception("Session failed unexpectedly.")
                raise SessionError(message) from exc
            raise
        finally:
            if audio_started:
                with suppress(Exception):
                    self.audio_source.stop()
            if event_task is not None and not event_task.done():
                event_task.cancel()
                with suppress(asyncio.CancelledError):
                    await event_task
            if translation_task is not None and not translation_task.done():
                translation_task.cancel()
                with suppress(asyncio.CancelledError):
                    await translation_task
            close_results = await asyncio.gather(
                self.translator.close(),
                self.asr_client.close(),
                return_exceptions=True,
            )
            self._running = False
            close_errors = [result for result in close_results if isinstance(result, BaseException)]
            if close_errors:
                _LOGGER.error(
                    "Session cleanup failed (%s).",
                    type(close_errors[0]).__name__,
                )
                if self.state.status != "error":
                    self._publish(status="error", message="Session cleanup failed.")
                    raise SessionError("Session cleanup failed.") from close_errors[0]

    def request_stop(self) -> None:
        self._stop_requested.set()
        with suppress(Exception):
            self.audio_source.stop()

    async def _drain_audio_after_stop(self) -> None:
        while True:
            chunk = await asyncio.to_thread(self.audio_source.read_chunk)
            self._report_audio_drops()
            if chunk is None:
                return
            await self.asr_client.send_audio(chunk)

    async def _event_loop(self) -> None:
        async for event in self.asr_client.events():
            if event.session_id != self.session_id:
                continue
            await self._handle_event(event)
            if isinstance(event, StreamStopped):
                return

    async def _handle_event(self, event: AsrEvent) -> None:
        if isinstance(event, StreamReady):
            return
        if isinstance(event, TranscriptFinal):
            if event.session_id != self.session_id or event.seq <= self._last_seq:
                return
            self._last_seq = event.seq
            segment = SubtitleSegment(
                session_id=event.session_id,
                seq=event.seq,
                source_text=event.text,
                audio_start_ms=event.audio_start_ms,
                audio_end_ms=event.audio_end_ms,
            )
            self._publish(
                segments=(*self.state.segments, segment)[-MAX_VISIBLE_SUBTITLES:],
                status="running",
                message="",
            )
            self._enqueue_translation(event)
            return
        if isinstance(event, RuntimeOverloaded):
            self._publish(
                status="degraded",
                message=f"ASR dropped {event.dropped_audio_ms} ms of audio.",
            )
            return
        if isinstance(event, AsrError):
            self._publish(
                status="degraded" if event.retryable else "error",
                message=event.message,
            )
            if not event.retryable:
                self.request_stop()
            return
        return

    def _enqueue_translation(self, event: TranscriptFinal) -> None:
        if self._translation_queue.full():
            dropped_event: TranscriptFinal | None = None
            try:
                dropped_event = self._translation_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            else:
                self._translation_queue.task_done()
            if dropped_event is not None:
                self._update_segment(
                    dropped_event,
                    translation_status="skipped",
                )
            self._publish(
                status="degraded",
                message="Translation queue dropped an older subtitle.",
            )
        self._translation_queue.put_nowait(event)

    async def _translation_loop(self) -> None:
        while True:
            event = await self._translation_queue.get()
            if event is None:
                self._translation_queue.task_done()
                return
            try:
                if not self._segment_is_visible(event):
                    continue
                result = await self.translator.translate(
                    TranslationRequest(
                        source_text=event.text,
                        context=tuple(self._context),
                    )
                )
            except TranslationError as exc:
                self._update_segment(
                    event,
                    translation_status="failed",
                    status="degraded",
                    message=str(exc),
                )
            except Exception:
                _LOGGER.exception("Translation failed unexpectedly.")
                self._update_segment(
                    event,
                    translation_status="failed",
                    status="degraded",
                    message="Translation failed unexpectedly.",
                )
            else:
                if self._update_segment(
                    event,
                    translated_text=result.translated_text,
                    translation_status="translated",
                    status="running",
                    message="",
                ):
                    self._context.append(
                        TranslationContext(
                            source_text=event.text,
                            translated_text=result.translated_text,
                        )
                    )
            finally:
                self._translation_queue.task_done()

    def _report_audio_drops(self) -> None:
        stats = self.audio_source.snapshot_stats()
        if stats == self._last_audio_stats:
            return
        self._last_audio_stats = stats
        if not stats.has_drops:
            return
        self._publish(
            status="degraded",
            message=(
                f"Audio capture reported {stats.input_overflow_events} native overflow events, "
                "dropped "
                f"{stats.dropped_input_blocks} input blocks and "
                f"{stats.dropped_output_chunks} normalized chunks."
            ),
        )

    def _segment_is_visible(self, event: TranscriptFinal) -> bool:
        return any(
            segment.session_id == event.session_id and segment.seq == event.seq
            for segment in self.state.segments
        )

    def _update_segment(
        self,
        event: TranscriptFinal,
        *,
        translated_text: str = "",
        translation_status: TranslationStatus,
        status: AppStatus | None = None,
        message: str | None = None,
    ) -> bool:
        found = False
        segments: list[SubtitleSegment] = []
        for segment in self.state.segments:
            if segment.session_id == event.session_id and segment.seq == event.seq:
                found = True
                segments.append(
                    replace(
                        segment,
                        translated_text=translated_text,
                        translation_status=translation_status,
                    )
                )
            else:
                segments.append(segment)
        if found:
            self._publish(segments=tuple(segments), status=status, message=message)
        return found

    def _publish(
        self,
        *,
        segments: tuple[SubtitleSegment, ...] | None = None,
        status: AppStatus | None = None,
        message: str | None = None,
    ) -> None:
        next_state = SubtitleState(
            segments=self.state.segments if segments is None else segments,
            status=self.state.status if status is None else status,
            message=self.state.message if message is None else message,
        )
        self.state = next_state
        self.subtitle_sink.set_state(next_state)


def _user_message(error: Exception) -> str:
    if isinstance(error, (SessionError, AsrClientError, AudioSourceError, TranslationError)):
        return str(error)
    return _UNEXPECTED_SESSION_ERROR
