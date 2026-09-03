from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from math import isfinite
from typing import Literal, Protocol, cast

import httpx
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from .diagnostics import get_logger
from .models import (
    AsrError,
    AsrEvent,
    AudioChunk,
    RuntimeOverloaded,
    StartStream,
    StreamReady,
    StreamStopped,
    TranscriptFinal,
)
from .protocol import ProtocolError, encode_audio_chunk, encode_start_stream, encode_stop_stream
from .urls import require_loopback_url

_CLOSE_GRACE_SECONDS = 0.5
_LOGGER = get_logger("asr")


class AsrClientError(RuntimeError):
    pass


class AsrClient(Protocol):
    async def probe_ready(self) -> bool: ...

    async def connect(self) -> None: ...

    async def start_stream(self, request: StartStream) -> None: ...

    async def send_audio(self, chunk: AudioChunk) -> None: ...

    def events(self) -> AsyncIterator[AsrEvent]: ...

    async def stop_stream(self) -> None: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AsrClientConfig:
    ws_url: str = "ws://127.0.0.1:9000/v1/asr"
    ready_url: str = "http://127.0.0.1:9000/ready"
    connect_timeout_s: float = 5.0
    stop_timeout_s: float = 5.0

    def __post_init__(self) -> None:
        require_loopback_url(self.ws_url, schemes={"ws", "wss"}, field_name="ws_url")
        require_loopback_url(
            self.ready_url,
            schemes={"http", "https"},
            field_name="ready_url",
        )
        if not isfinite(self.connect_timeout_s) or self.connect_timeout_s <= 0:
            raise ValueError("connect_timeout_s must be positive")
        if not isfinite(self.stop_timeout_s) or self.stop_timeout_s <= 0:
            raise ValueError("stop_timeout_s must be positive")


type ClientState = Literal[
    "new",
    "connected",
    "starting",
    "streaming",
    "stopping",
    "stopped",
    "closed",
]


@dataclass(slots=True)
class WebSocketAsrClient:
    config: AsrClientConfig = field(default_factory=AsrClientConfig)
    _connection: ClientConnection | None = field(default=None, init=False)
    _receiver_task: asyncio.Task[None] | None = field(default=None, init=False)
    _events: asyncio.Queue[AsrEvent | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=64),
        init=False,
    )
    _state: ClientState = field(default="new", init=False)
    _session_id: str | None = field(default=None, init=False)
    _last_seq: int = field(default=0, init=False)
    _ready_waiter: asyncio.Future[None] | None = field(default=None, init=False)
    _stopped_waiter: asyncio.Future[None] | None = field(default=None, init=False)
    _send_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _closing: bool = field(default=False, init=False)

    async def probe_ready(self) -> bool:
        timeout = httpx.Timeout(self.config.connect_timeout_s)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.get(self.config.ready_url)
                response.raise_for_status()
        except (httpx.HTTPError, ValueError):
            return False

        try:
            payload = cast(object, response.json())
        except ValueError:
            return False
        if not isinstance(payload, dict):
            return False
        ready_payload = cast(dict[str, object], payload)
        return ready_payload.get("status") == "ready"

    async def connect(self) -> None:
        if self._state != "new":
            raise AsrClientError(f"connect is invalid while client state is {self._state}")
        try:
            self._connection = await connect(
                self.config.ws_url,
                open_timeout=self.config.connect_timeout_s,
                close_timeout=1.0,
                max_size=64 * 1_024,
                proxy=None,
            )
        except Exception as exc:
            raise AsrClientError(
                f"Could not connect to ASR service at {self.config.ws_url}"
            ) from exc

        self._state = "connected"
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def start_stream(self, request: StartStream) -> None:
        if self._state != "connected":
            raise AsrClientError(f"start_stream is invalid while client state is {self._state}")

        self._session_id = request.session_id
        self._last_seq = 0
        self._state = "starting"
        waiter = asyncio.get_running_loop().create_future()
        self._ready_waiter = waiter
        try:
            await self._send(encode_start_stream(request))
            await asyncio.wait_for(
                asyncio.shield(waiter),
                timeout=self.config.connect_timeout_s,
            )
        except TimeoutError as exc:
            waiter.cancel()
            raise AsrClientError("ASR service did not acknowledge stream.start") from exc
        except asyncio.CancelledError:
            waiter.cancel()
            raise
        except Exception:
            waiter.cancel()
            raise

    async def send_audio(self, chunk: AudioChunk) -> None:
        if self._state != "streaming":
            raise AsrClientError(f"send_audio is invalid while client state is {self._state}")
        await self._send(encode_audio_chunk(chunk))

    async def stop_stream(self) -> None:
        if self._state == "stopped":
            return
        if self._state != "streaming" or self._session_id is None:
            raise AsrClientError(f"stop_stream is invalid while client state is {self._state}")

        self._state = "stopping"
        waiter = asyncio.get_running_loop().create_future()
        self._stopped_waiter = waiter
        try:
            await self._send(encode_stop_stream(self._session_id))
            await asyncio.wait_for(
                asyncio.shield(waiter),
                timeout=self.config.stop_timeout_s,
            )
        except TimeoutError as exc:
            waiter.cancel()
            raise AsrClientError("ASR service did not acknowledge stream.stop") from exc
        except asyncio.CancelledError:
            waiter.cancel()
            raise
        except Exception:
            waiter.cancel()
            raise

    async def events(self) -> AsyncIterator[AsrEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event
            if isinstance(event, StreamStopped):
                return

    async def close(self) -> None:
        if self._state == "closed":
            return
        self._closing = True
        receiver_task = self._receiver_task
        self._receiver_task = None
        if receiver_task is not None:
            if not receiver_task.done():
                receiver_task.cancel()
            with suppress(asyncio.CancelledError):
                await receiver_task
        else:
            self._put_event_nowait(None)

        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                await asyncio.wait_for(
                    connection.close(),
                    timeout=_CLOSE_GRACE_SECONDS,
                )
            except TimeoutError:
                connection.transport.abort()
            except Exception:
                connection.transport.abort()

        self._fail_waiters(AsrClientError("ASR client closed"))
        self._state = "closed"

    async def _send(self, message: str | bytes) -> None:
        connection = self._connection
        if connection is None:
            raise AsrClientError("ASR WebSocket is not connected")
        try:
            async with self._send_lock:
                await connection.send(message)
        except ConnectionClosed as exc:
            raise AsrClientError("ASR WebSocket closed while sending") from exc

    async def _receive_loop(self) -> None:
        connection = self._connection
        if connection is None:
            return

        ended_normally = False
        try:
            async for message in connection:
                if not isinstance(message, str):
                    await self._emit_protocol_failure(
                        "ASR service sent an unexpected binary message"
                    )
                    return
                try:
                    event = parse_server_event(message)
                except ProtocolError as exc:
                    await self._emit_protocol_failure(str(exc))
                    return
                if event.session_id != self._session_id:
                    continue
                if isinstance(event, TranscriptFinal):
                    if event.seq <= self._last_seq:
                        continue
                    self._last_seq = event.seq

                if isinstance(event, StreamReady):
                    self._state = "streaming"
                    _resolve_waiter(self._ready_waiter)
                elif isinstance(event, StreamStopped):
                    self._state = "stopped"
                    _resolve_waiter(self._stopped_waiter)
                    ended_normally = True
                elif isinstance(event, AsrError):
                    self._fail_waiters(AsrClientError(event.message))
                self._queue_received_event(event)
        except ConnectionClosed:
            pass
        finally:
            if not self._closing and not ended_normally:
                await self._emit_connection_failure()
            self._put_event_nowait(None)

    async def _emit_protocol_failure(self, message: str) -> None:
        event = AsrError(
            session_id=self._session_id or "unknown",
            code="invalid_server_message",
            message=message,
            retryable=False,
        )
        self._queue_received_event(event)
        self._fail_waiters(AsrClientError(message))

    async def _emit_connection_failure(self) -> None:
        event = AsrError(
            session_id=self._session_id or "unknown",
            code="connection_closed",
            message="ASR service connection closed unexpectedly.",
            retryable=True,
        )
        self._queue_received_event(event)
        self._fail_waiters(AsrClientError(event.message))

    def _queue_received_event(self, event: AsrEvent) -> None:
        try:
            self._events.put_nowait(event)
            return
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._events.get_nowait()

        if isinstance(event, (StreamReady, StreamStopped, AsrError)):
            replacement = event
        else:
            replacement = AsrError(
                session_id=event.session_id,
                code="client_event_queue_overflow",
                message="The client dropped ASR events because its event queue was full.",
                retryable=True,
            )
        self._events.put_nowait(replacement)
        _LOGGER.warning("ASR event queue overflowed; an event was discarded.")

    def _fail_waiters(self, error: AsrClientError) -> None:
        for waiter in (self._ready_waiter, self._stopped_waiter):
            if waiter is not None and not waiter.done():
                waiter.set_exception(error)

    def _put_event_nowait(self, event: AsrEvent | None) -> None:
        try:
            self._events.put_nowait(event)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._events.get_nowait()
            self._events.put_nowait(event)


def parse_server_event(raw: str) -> AsrEvent:
    from .protocol import parse_event

    return parse_event(raw)


def _resolve_waiter(waiter: asyncio.Future[None] | None) -> None:
    if waiter is not None and not waiter.done():
        waiter.set_result(None)


@dataclass(slots=True)
class FakeAsrClient:
    transcripts: tuple[str, ...] = ("これはテストです。",)
    chunks_per_final: int = 1
    _events: asyncio.Queue[AsrEvent | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=64),
        init=False,
    )
    _state: ClientState = field(default="new", init=False)
    _session_id: str | None = field(default=None, init=False)
    _chunk_count: int = field(default=0, init=False)
    _next_transcript: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.chunks_per_final < 1:
            raise ValueError("chunks_per_final must be positive")
        if any(not text.strip() for text in self.transcripts):
            raise ValueError("fake transcripts must not be empty")

    async def probe_ready(self) -> bool:
        return True

    async def connect(self) -> None:
        if self._state != "new":
            raise AsrClientError(f"connect is invalid while client state is {self._state}")
        self._state = "connected"

    async def start_stream(self, request: StartStream) -> None:
        if self._state != "connected":
            raise AsrClientError(f"start_stream is invalid while client state is {self._state}")
        self._session_id = request.session_id
        self._state = "streaming"
        await self._events.put(StreamReady(session_id=request.session_id))

    async def send_audio(self, chunk: AudioChunk) -> None:
        if self._state != "streaming" or self._session_id is None:
            raise AsrClientError(f"send_audio is invalid while client state is {self._state}")
        self._chunk_count += 1
        if self._chunk_count % self.chunks_per_final == 0:
            await self._emit_next_transcript()

    async def events(self) -> AsyncIterator[AsrEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event
            if isinstance(event, StreamStopped):
                return

    async def stop_stream(self) -> None:
        if self._state == "stopped":
            return
        if self._state != "streaming" or self._session_id is None:
            raise AsrClientError(f"stop_stream is invalid while client state is {self._state}")
        while self._next_transcript < len(self.transcripts):
            await self._emit_next_transcript()
        self._state = "stopped"
        await self._events.put(StreamStopped(session_id=self._session_id))

    async def close(self) -> None:
        if self._state == "closed":
            return
        self._state = "closed"
        self._put_event_nowait(None)

    async def emit_overloaded(self, dropped_audio_ms: int) -> None:
        if self._session_id is None:
            raise AsrClientError("stream has not started")
        await self._events.put(
            RuntimeOverloaded(
                session_id=self._session_id,
                dropped_audio_ms=dropped_audio_ms,
            )
        )

    async def _emit_next_transcript(self) -> None:
        if self._session_id is None or self._next_transcript >= len(self.transcripts):
            return
        index = self._next_transcript
        self._next_transcript += 1
        end_ms = max(self._chunk_count * 100, (index + 1) * 100)
        await self._events.put(
            TranscriptFinal(
                session_id=self._session_id,
                seq=index + 1,
                text=self.transcripts[index],
                audio_start_ms=max(0, end_ms - 100),
                audio_end_ms=end_ms,
                decode_ms=0,
            )
        )

    def _put_event_nowait(self, event: AsrEvent | None) -> None:
        try:
            self._events.put_nowait(event)
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._events.get_nowait()
            self._events.put_nowait(event)
