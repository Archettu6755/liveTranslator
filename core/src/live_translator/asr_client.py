"""asyncio client for the asr.v1 WebSocket worker.

Lifecycle adapted from archived/windows-client/src/live_translator/asr.py (commit 3e91d93):
start/ready before audio, independent send/receive, session filtering, stop acknowledgement
with timeout, bounded event queue whose lifecycle events are never dropped silently.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from .asr_protocol import (
    AsrError,
    AudioFrame,
    AudioGap,
    ProtocolError,
    ServerMessage,
    SessionReady,
    SessionStart,
    SessionStop,
    SessionStopped,
    encode_audio_frame,
    encode_client,
    parse_server,
)
from .diagnostics import get_logger, register_secret
from .urls import require_loopback_url

_LOGGER = get_logger("asr_client")


class AsrClientError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AsrClientConfig:
    url: str
    token: str
    connect_timeout_s: float = 5.0
    stop_timeout_s: float = 5.0
    event_queue_size: int = 256

    def __post_init__(self) -> None:
        require_loopback_url(self.url, schemes={"ws"}, field_name="asr url")
        if len(self.token) < 16:
            raise ValueError("ASR token is too short")
        register_secret(self.token)


class AsrClient:
    def __init__(self, config: AsrClientConfig) -> None:
        self.config = config
        self._ws: ClientConnection | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[ServerMessage | None] = asyncio.Queue(config.event_queue_size)
        self._session_id: str | None = None
        self._last_seq = 0
        self._ready: asyncio.Future[str] | None = None
        self._stopped: asyncio.Future[None] | None = None
        self._send_lock = asyncio.Lock()
        self.dropped_events = 0

    async def start(self, session_id: str) -> str:
        """Connect and start a session; returns the backend name."""
        try:
            self._ws = await connect(
                self.config.url,
                additional_headers={"Authorization": f"Bearer {self.config.token}"},
                open_timeout=self.config.connect_timeout_s,
                max_size=64 * 1024,
                proxy=None,
            )
        except Exception as exc:
            raise AsrClientError("could not connect to the ASR worker") from exc
        self._session_id = session_id
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._receiver = asyncio.create_task(self._receive_loop())
        await self._send(encode_client(SessionStart(session_id)))
        try:
            return await asyncio.wait_for(asyncio.shield(self._ready), self.config.connect_timeout_s)
        except TimeoutError as exc:
            raise AsrClientError("ASR worker did not acknowledge session.start") from exc

    async def send_audio(self, frame: AudioFrame) -> None:
        await self._send(encode_audio_frame(frame))

    async def send_gap(self, start_sample: int, missing_samples: int) -> None:
        assert self._session_id is not None
        await self._send(encode_client(AudioGap(self._session_id, start_sample, missing_samples)))

    async def stop(self) -> None:
        """Request a drained stop; waits for session.stopped within the timeout."""
        if self._session_id is None or self._ws is None:
            return
        self._stopped = asyncio.get_running_loop().create_future()
        try:
            await self._send(encode_client(SessionStop(self._session_id)))
            await asyncio.wait_for(asyncio.shield(self._stopped), self.config.stop_timeout_s)
        except (TimeoutError, AsrClientError) as exc:
            raise AsrClientError("ASR worker did not acknowledge session.stop") from exc

    async def events(self) -> AsyncIterator[ServerMessage]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        if self._receiver is not None:
            self._receiver.cancel()
            with suppress(asyncio.CancelledError):
                await self._receiver
            self._receiver = None
        if self._ws is not None:
            with suppress(Exception):
                await asyncio.wait_for(self._ws.close(), 1.0)
            self._ws = None
        self._fail(AsrClientError("ASR client closed"))
        self._put(None)

    async def _send(self, message: str | bytes) -> None:
        ws = self._ws
        if ws is None:
            raise AsrClientError("ASR worker is not connected")
        try:
            async with self._send_lock:
                await ws.send(message)
        except ConnectionClosed as exc:
            raise AsrClientError("ASR connection closed while sending") from exc

    async def _receive_loop(self) -> None:
        assert self._ws is not None
        clean = False
        try:
            async for raw in self._ws:
                if not isinstance(raw, str):
                    self._protocol_failure("unexpected binary message from ASR worker")
                    return
                try:
                    seq, message = parse_server(raw)
                except ProtocolError as exc:
                    self._protocol_failure(str(exc))
                    return
                if message.session_id not in (self._session_id, "unknown"):
                    continue
                if seq is not None:
                    if seq <= self._last_seq:
                        continue
                    self._last_seq = seq
                if isinstance(message, SessionReady) and self._ready and not self._ready.done():
                    self._ready.set_result(message.backend)
                elif isinstance(message, SessionStopped):
                    if self._stopped and not self._stopped.done():
                        self._stopped.set_result(None)
                    clean = True
                elif isinstance(message, AsrError):
                    self._fail(AsrClientError(f"{message.code}: {message.message}"))
                self._put(message)
                if clean:
                    return
        except ConnectionClosed:
            pass
        finally:
            if not clean:
                lost = AsrError(self._session_id or "unknown", "connection_closed", "ASR worker connection closed unexpectedly.", True)
                self._fail(AsrClientError(lost.message))
                self._put(lost)
            self._put(None)

    def _protocol_failure(self, detail: str) -> None:
        error = AsrError(self._session_id or "unknown", "invalid_server_message", detail, False)
        self._fail(AsrClientError(detail))
        self._put(error)

    def _fail(self, error: AsrClientError) -> None:
        for waiter in (self._ready, self._stopped):
            if waiter is not None and not waiter.done():
                waiter.set_exception(error)
                waiter.exception()  # mark retrieved

    def _put(self, event: ServerMessage | None) -> None:
        try:
            self._events.put_nowait(event)
            return
        except asyncio.QueueFull:
            with suppress(asyncio.QueueEmpty):
                self._events.get_nowait()
            self.dropped_events += 1
            _LOGGER.warning("ASR event queue overflowed; the oldest event was discarded")
        self._events.put_nowait(event)
