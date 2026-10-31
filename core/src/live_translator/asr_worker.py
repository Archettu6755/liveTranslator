"""Standalone ASR worker: authenticated loopback WebSocket server speaking asr.v1.

Model inference is behind the ``AsrBackend`` interface. This build ships:
- ``scripted``: drives preset Japanese text from *real* incoming audio using an energy VAD, so
  capture -> ASR -> subtitles can be exercised without a model. It recognizes nothing.
- ``qwen``: placeholder slot for Qwen3-ASR; it reports ``model_not_configured`` until a runtime
  is configured (model setup is out of scope for this build).

The worker never holds translation keys. It binds 127.0.0.1 only and requires a bearer token
from the LIVE_TRANSLATOR_ASR_TOKEN environment variable.
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Protocol

import numpy as np
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from .asr_protocol import (
    MAX_AUDIO_FRAME_BYTES,
    AsrError,
    AudioGap,
    ProtocolError,
    RuntimeOverloaded,
    SessionReady,
    SessionStart,
    SessionStop,
    SessionStopped,
    decode_audio_frame,
    encode_activity,
    encode_server,
    parse_client,
    samples_to_ms,
)
from .diagnostics import get_logger
from .models import AsrSnapshot, SpeechActivity

TOKEN_ENV = "LIVE_TRANSLATOR_ASR_TOKEN"
_LOGGER = get_logger("asr_worker")


# -- backend interface ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowText:
    window_id: int
    text: str
    final: bool


class BackendNotConfigured(RuntimeError):
    pass


class BackendSession(Protocol):
    def feed(self, pcm: np.ndarray, end_ms: int, speech: bool, silence_ms: int) -> list[WindowText]: ...

    def finish(self, end_ms: int) -> list[WindowText]: ...


class AsrBackend(Protocol):
    name: str

    def open_session(self) -> BackendSession: ...


DEFAULT_SCRIPT = (
    "みなさんこんばんは。今日は雑談をします。",
    "昨日コンビニに行ったら、推しのグッズがありました。でも買わなかった。",
    "スパチャありがとうございます。本当に嬉しい。",
    "ちょっと待って、マイクの調子がおかしいかも。",
    "じゃあ始めましょう。次は歌を歌います。",
)


@dataclass(slots=True)
class ScriptedSession:
    """Reveals script text proportionally to detected speech; silence ends the window."""

    script: Sequence[str]
    chars_per_second: float = 7.0
    window_end_silence_ms: int = 700
    window_max_ms: int = 20_000
    _line: int = 0
    _offset: int = 0
    _window_id: int = 1
    _window_text: str = ""
    _window_speech_ms: float = 0.0
    _window_start_ms: int | None = None
    _credit: float = 0.0

    def feed(self, pcm: np.ndarray, end_ms: int, speech: bool, silence_ms: int) -> list[WindowText]:
        out: list[WindowText] = []
        duration_ms = len(pcm) * 1000 / 16_000
        if speech:
            if self._window_start_ms is None:
                self._window_start_ms = end_ms
            self._window_speech_ms += duration_ms
            self._credit += duration_ms / 1000 * self.chars_per_second
            revealed = ""
            while self._credit >= 1.0:
                line = self.script[self._line % len(self.script)]
                if self._offset >= len(line):
                    self._line += 1
                    self._offset = 0
                    continue
                revealed += line[self._offset]
                self._offset += 1
                self._credit -= 1.0
            if revealed:
                self._window_text += revealed
                out.append(WindowText(self._window_id, self._window_text, False))
        too_long = (
            self._window_start_ms is not None and end_ms - self._window_start_ms >= self.window_max_ms
        )
        if self._window_text and (silence_ms >= self.window_end_silence_ms or too_long):
            out.append(self._close_window())
        return out

    def finish(self, end_ms: int) -> list[WindowText]:
        return [self._close_window()] if self._window_text else []

    def _close_window(self) -> WindowText:
        final = WindowText(self._window_id, self._window_text, True)
        self._window_id += 1
        self._window_text = ""
        self._window_speech_ms = 0.0
        self._window_start_ms = None
        self._credit = 0.0
        return final


@dataclass(slots=True)
class ScriptedBackend:
    script: Sequence[str] = DEFAULT_SCRIPT
    name: str = "scripted"

    def open_session(self) -> BackendSession:
        return ScriptedSession(self.script)


@dataclass(slots=True)
class QwenBackend:
    """Slot for Qwen3-ASR streaming. Intentionally not implemented in this build."""

    model_path: str | None = None
    name: str = "qwen"

    def open_session(self) -> BackendSession:
        raise BackendNotConfigured(
            "Qwen3-ASR runtime is not configured on this machine; use the scripted backend "
            "or configure a model runtime first."
        )


# -- voice activity ---------------------------------------------------------------------


@dataclass(slots=True)
class EnergyVad:
    """Simple RMS gate on the audio timeline. Silence is not a recognition failure (U5)."""

    threshold_dbfs: float = -45.0
    hangover_ms: int = 200
    silence_ms: int = 0
    active: bool = False
    _since_voice_ms: int = 10_000

    def update(self, pcm: np.ndarray) -> bool:
        duration = len(pcm) * 1000 // 16_000
        if len(pcm) == 0:
            return self.active
        rms = float(np.sqrt(np.mean(np.square(pcm.astype(np.float32) / 32768.0))))
        level = 20 * np.log10(max(rms, 1e-9))
        if level >= self.threshold_dbfs:
            self._since_voice_ms = 0
        else:
            self._since_voice_ms += duration
        self.active = self._since_voice_ms <= self.hangover_ms
        self.silence_ms = 0 if self.active else self._since_voice_ms
        return self.active


# -- server -----------------------------------------------------------------------------


@dataclass(slots=True)
class _Connection:
    websocket: ServerConnection
    backend: AsrBackend
    queue_limit: int = 50
    session_id: str | None = None
    session: BackendSession | None = None
    vad: EnergyVad = field(default_factory=EnergyVad)
    seq: int = 0
    audio_end_ms: int = 0
    last_activity_ms: int = -1_000
    last_active: bool | None = None
    queue: asyncio.Queue[object] = field(default_factory=lambda: asyncio.Queue(maxsize=50))
    dropped_ms: int = 0

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


async def _send(conn: _Connection, text: str) -> None:
    await conn.websocket.send(text)


async def _process(conn: _Connection) -> None:
    """Consumes queued audio off the receive path so slow inference never blocks it."""
    while True:
        item = await conn.queue.get()
        if item is None:
            return
        if isinstance(item, SessionStop):
            assert conn.session is not None and conn.session_id is not None
            for window in conn.session.finish(conn.audio_end_ms):
                await _send_window(conn, window)
            await _send(conn, encode_server(SessionStopped(conn.session_id, conn.next_seq())))
            return
        assert isinstance(item, tuple)
        start_sample, pcm = item
        end_ms = samples_to_ms(start_sample + len(pcm))
        conn.audio_end_ms = max(conn.audio_end_ms, end_ms)
        speech = conn.vad.update(pcm)
        assert conn.session is not None and conn.session_id is not None
        windows = await asyncio.to_thread(conn.session.feed, pcm, end_ms, speech, conn.vad.silence_ms)
        for window in windows:
            await _send_window(conn, window)
        if speech != conn.last_active or end_ms - conn.last_activity_ms >= 200:
            conn.last_active = speech
            conn.last_activity_ms = end_ms
            activity = SpeechActivity(conn.session_id, end_ms, speech, conn.vad.silence_ms)
            await _send(conn, encode_activity(activity, conn.next_seq()))
        if conn.dropped_ms:
            dropped, conn.dropped_ms = conn.dropped_ms, 0
            await _send(conn, encode_server(RuntimeOverloaded(conn.session_id, conn.next_seq(), dropped)))


async def _send_window(conn: _Connection, window: WindowText) -> None:
    assert conn.session_id is not None
    snapshot = AsrSnapshot(
        session_id=conn.session_id,
        seq=conn.next_seq(),
        window_id=window.window_id,
        text=window.text,
        audio_end_ms=conn.audio_end_ms,
        window_final=window.final,
    )
    await _send(conn, encode_server(snapshot))


async def _error(conn: _Connection, code: str, message: str, retryable: bool = False) -> None:
    await _send(conn, encode_server(AsrError(conn.session_id or "unknown", code, message, retryable)))


async def handle_connection(websocket: ServerConnection, backend: AsrBackend) -> None:
    conn = _Connection(websocket, backend)
    worker: asyncio.Task[None] | None = None
    try:
        async for message in websocket:
            if isinstance(message, bytes):
                if conn.session is None:
                    await _error(conn, "no_session", "audio received before session.start")
                    continue
                try:
                    frame = decode_audio_frame(message)
                except ProtocolError as exc:
                    await _error(conn, "invalid_audio", str(exc))
                    continue
                pcm = np.frombuffer(frame.pcm, dtype="<i2")
                try:
                    conn.queue.put_nowait((frame.start_sample, pcm))
                except asyncio.QueueFull:
                    conn.dropped_ms += samples_to_ms(len(pcm))
                continue
            try:
                parsed = parse_client(message)
            except ProtocolError as exc:
                await _error(conn, "invalid_message", str(exc))
                continue
            if isinstance(parsed, SessionStart):
                if conn.session is not None:
                    await _error(conn, "session_active", "a session is already running")
                    continue
                try:
                    conn.session = backend.open_session()
                except BackendNotConfigured as exc:
                    conn.session_id = parsed.session_id
                    await _error(conn, "model_not_configured", str(exc))
                    continue
                conn.session_id = parsed.session_id
                worker = asyncio.create_task(_process(conn))
                await _send(conn, encode_server(SessionReady(parsed.session_id, backend.name)))
            elif isinstance(parsed, AudioGap):
                _LOGGER.info("client reported an audio gap of %d samples", parsed.missing_samples)
            elif isinstance(parsed, SessionStop):
                if conn.session is None or parsed.session_id != conn.session_id:
                    await _error(conn, "no_session", "stop for an unknown session")
                    continue
                await conn.queue.put(parsed)  # drained in order after queued audio
                if worker is not None:
                    await worker
                    worker = None
                conn.session = None
    except ConnectionClosed:
        pass
    finally:
        if worker is not None:
            worker.cancel()


def _auth_checker(token: str):  # type: ignore[no-untyped-def]
    expected = f"Bearer {token}".encode()

    def process_request(connection: ServerConnection, request: Request) -> Response | None:
        supplied = request.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(supplied, expected):
            return Response(HTTPStatus.UNAUTHORIZED, "Unauthorized", Headers(), b"unauthorized\n")
        if request.path != "/v1/asr":
            return Response(HTTPStatus.NOT_FOUND, "Not Found", Headers(), b"not found\n")
        return None

    return process_request


async def run_server(backend: AsrBackend, token: str, port: int = 0, ready_file=sys.stdout) -> None:  # type: ignore[no-untyped-def]
    async def handler(websocket: ServerConnection) -> None:
        await handle_connection(websocket, backend)

    async with serve(
        handler,
        "127.0.0.1",
        port,
        process_request=_auth_checker(token),
        max_size=MAX_AUDIO_FRAME_BYTES,
        close_timeout=1.0,
    ) as server:
        bound = next(iter(server.sockets)).getsockname()[1]
        ready_file.write(json.dumps({"type": "asr.listening", "port": bound, "backend": backend.name}) + "\n")
        ready_file.flush()
        await server.serve_forever()


def make_backend(name: str) -> AsrBackend:
    if name == "scripted":
        return ScriptedBackend()
    if name == "qwen":
        return QwenBackend(model_path=os.environ.get("LIVE_TRANSLATOR_QWEN_MODEL"))
    raise ValueError(f"unknown backend: {name}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="live_translator asr-worker")
    parser.add_argument("--backend", choices=["scripted", "qwen"], default="scripted")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    token = os.environ.get(TOKEN_ENV, "")
    if len(token) < 16:
        print(f"{TOKEN_ENV} must be set to a random token (>=16 chars)", file=sys.stderr)
        return 2
    try:
        asyncio.run(run_server(make_backend(args.backend), token, args.port))
    except KeyboardInterrupt:
        pass
    return 0
