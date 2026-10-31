"""Core process entry for the desktop host: JSON Lines over stdio (contracts/host-core-v1).

stdout carries protocol lines only; diagnostics go to stderr (redacted). The core is the single
owner of segmentation, scheduling and cue versions. Translation HTTP is executed by the host
(Electron main, which holds the API key); the ``core_mock`` executor answers locally for offline
use. Audio PCM never crosses this channel.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import sys
import threading
import time
import uuid
from contextlib import suppress
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, BinaryIO

from . import __version__
from .asr_client import AsrClient, AsrClientConfig, AsrClientError
from .asr_protocol import AsrError, RuntimeOverloaded, SessionStopped, samples_to_ms
from .config import CoreConfig
from .demo import SCENARIOS, DemoRunner
from .diagnostics import configure_stderr_logging, get_logger, register_secret
from .engine import SubtitleEngine
from .host_protocol import CommandError, validate_command
from .mock_translation import mock_reply
from .models import AsrSnapshot, CaptureGap, SpeechActivity, TranslationRequest
from .source_organizer import StableSourceOrganizer
from .translation import TranslationMode

PROTOCOL = "host-core.v1"
MAX_LINE_BYTES = 1024 * 1024
TICK_S = 0.1
HEARTBEAT_MS = 1000
_LOGGER = get_logger("host")


@dataclass(slots=True)
class SourceStatus:
    kind: str = ""
    label: str = ""
    capturing: bool = False
    asr_connected: bool = False
    asr_backend: str | None = None
    speech_active: bool = False
    frames_dropped: int = 0
    gap_ms: int = 0
    asr_overloaded_ms: int = 0
    error: str | None = None


class Host:
    def __init__(self, output: BinaryIO, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._output = output
        self._write_lock = threading.Lock()
        self._monotonic = monotonic
        self._base = monotonic()
        self.engine = SubtitleEngine(CoreConfig())
        self.mode = "idle"  # idle | live | demo
        self.executor = "core_mock"  # core_mock | host
        self.status = SourceStatus()
        self._demo: DemoRunner | None = None
        self._live: LiveSession | None = None
        self._last_emit_version = -1
        self._last_emit_ms = 0
        self._stopping = False
        self._shutdown = asyncio.Event()
        self._closing = False
        self._stop_task: asyncio.Task[None] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._seq = 0

    # -- plumbing -----------------------------------------------------------------------

    def now_ms(self) -> int:
        return int((self._monotonic() - self._base) * 1000)

    def emit(self, message: dict[str, Any]) -> None:
        self._seq += 1
        message = {**message, "protocol": PROTOCOL, "seq": self._seq}
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        with self._write_lock:
            self._output.write(line)
            self._output.flush()

    async def run(self, lines: asyncio.Queue[bytes | None]) -> None:
        ticker = asyncio.create_task(self._ticker())
        shutdown = asyncio.create_task(self._shutdown.wait())
        reading: asyncio.Task[bytes | None] | None = None
        try:
            while not self._shutdown.is_set():
                reading = asyncio.create_task(lines.get())
                done, _ = await asyncio.wait({reading, shutdown}, return_when=asyncio.FIRST_COMPLETED)
                if shutdown in done:
                    break
                raw = reading.result()
                if raw is None:
                    break
                await self._dispatch_line(raw)
        finally:
            for task in (reading, shutdown):
                if task is not None:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            if self._shutdown_task is not None:
                await self._shutdown_task
            elif self._stop_task is not None:
                await self._stop_task
            else:
                await self._stop_activity()
            ticker.cancel()
            with suppress(asyncio.CancelledError):
                await ticker

    async def _dispatch_line(self, raw: bytes) -> None:
        command_id = None
        try:
            if len(raw) > MAX_LINE_BYTES:
                raise CommandError("command exceeds the size limit")
            value = json.loads(raw.decode("utf-8"))
            if isinstance(value, dict) and isinstance(value.get("command_id"), str) and len(value["command_id"]) <= 80:
                command_id = value["command_id"]
            message = validate_command(value)
            await self.handle(message)
            if command_id:
                self.emit({"type": "command.accepted", "command_id": command_id})
        except (CommandError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.emit({"type": "error", "command_id": command_id, "code": "invalid_command", "message": str(exc)})
        except Exception:  # noqa: BLE001 - never let one command kill the core
            _LOGGER.exception("command failed")
            self.emit({"type": "error", "command_id": command_id, "code": "internal_error", "message": "core command failed"})

    # -- commands -----------------------------------------------------------------------

    async def handle(self, msg: dict[str, Any]) -> None:
        kind = msg["type"]
        if self._closing and kind not in {"translation.result", "session.stop", "shutdown"}:
            raise CommandError("core is shutting down")
        if kind == "hello":
            if msg.get("protocol") != PROTOCOL:
                raise CommandError("unsupported protocol")
            self.emit(
                {
                    "type": "core.ready",
                    "command_id": msg.get("command_id"),
                    "protocol": PROTOCOL,
                    "version": __version__,
                    "platform": sys.platform,
                    "scenarios": [
                        {"name": s.name, "title": s.title, "description": s.description}
                        for s in SCENARIOS.values()
                    ],
                }
            )
        elif kind == "config.update":
            self._config_update(msg)
        elif kind == "sources.list":
            await self._sources_list(_req_str(msg, "request_id"))
        elif kind == "session.start":
            await self._session_start(msg)
        elif kind == "session.stop":
            if self._stop_task is not None and not self._stop_task.done():
                raise CommandError("stop is already in progress")
            self._stop_task = asyncio.create_task(self._stop_command(msg.get("command_id")))
        elif kind == "demo.start":
            await self._demo_start(_req_str(msg, "scenario"))
        elif kind == "translation.result":
            self._translation_result(msg)
        elif kind == "shutdown":
            if not self._closing:
                self._closing = True
                self._shutdown_task = asyncio.create_task(self._finish_shutdown())
        else:
            raise CommandError(f"unknown command: {kind}")

    def _config_update(self, msg: dict[str, Any]) -> None:
        if self.mode != "idle":
            raise CommandError("settings can only change while idle")
        translation = msg.get("translation", {})
        if not isinstance(translation, dict):
            raise CommandError("translation must be an object")
        if translation.keys() - {"executor", "mode"}:
            raise CommandError("unsupported translation settings")
        executor = translation.get("executor", self.executor)
        mode = translation.get("mode", self.engine.mode.value)
        if not isinstance(executor, str) or not isinstance(mode, str) or executor not in {"core_mock", "host"} or mode not in {"structured", "plain"}:
            raise CommandError("invalid translation settings")
        glossary = msg.get("glossary", self.engine.glossary)
        if not isinstance(glossary, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and len(k) <= 64 and len(v) <= 64
            for k, v in glossary.items()
        ) or len(glossary) > 200:
            raise CommandError("glossary must map short strings to strings")
        self.executor = executor
        self.engine.mode = TranslationMode(mode)
        self.engine.glossary = dict(glossary)

    async def _sources_list(self, request_id: str) -> None:
        result: dict[str, Any] = {"type": "sources.result", "request_id": request_id}
        if sys.platform != "win32":
            result.update(applications=[], devices=[], error="audio capture requires Windows")
        else:
            try:
                from .audio import sessions

                apps, devices = await asyncio.to_thread(
                    lambda: (sessions.list_application_candidates(), sessions.list_output_devices())
                )
                result.update(
                    applications=[a.to_dict() for a in apps],
                    devices=[d.to_dict() for d in devices],
                    error=None,
                )
            except Exception as exc:  # noqa: BLE001
                result.update(applications=[], devices=[], error=f"source discovery failed: {exc}")
        self.emit(result)

    async def _session_start(self, msg: dict[str, Any]) -> None:
        if self.mode != "idle" or self.engine.state != "idle":
            raise CommandError("a session or demo is already running")
        source = msg.get("source")
        asr = msg.get("asr")
        if not isinstance(source, dict) or not isinstance(asr, dict):
            raise CommandError("source and asr are required")
        if source.keys() - {"kind", "label", "root_pid", "device_id"} or asr.keys() != {"url", "token"}:
            raise CommandError("unsupported source or ASR fields")
        kind = source.get("kind")
        label = source.get("label", "")
        if not isinstance(label, str) or len(label) > 120:
            raise CommandError("invalid source label")
        if kind == "application":
            if "device_id" in source:
                raise CommandError("device_id is not valid for an application")
            pid = source.get("root_pid")
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                raise CommandError("root_pid must be a positive integer")
            target = ("application", pid, None, label)
        elif kind == "output_device":
            if "root_pid" in source:
                raise CommandError("root_pid is not valid for an output device")
            device_id = source.get("device_id")
            if device_id is not None and not isinstance(device_id, str):
                raise CommandError("device_id must be a string")
            target = ("output_device", None, device_id, label)
        else:
            raise CommandError("source.kind must be application or output_device")
        url, token = asr.get("url"), asr.get("token")
        if not isinstance(url, str) or not isinstance(token, str):
            raise CommandError("asr.url and asr.token are required")
        register_secret(token)
        try:
            client_config = AsrClientConfig(url=url, token=token)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        session_id = uuid.uuid4().hex[:12]
        self.status = SourceStatus(kind=target[0], label=label)
        self.mode = "live"
        self.engine.start_session(session_id, self.now_ms())
        self._live = LiveSession(self, session_id, target, client_config)
        self._emit_snapshot(force=True)
        await self._live.start()
        if not self.status.capturing:
            await self._stop_activity()

    async def _demo_start(self, name: str) -> None:
        if name not in SCENARIOS:
            raise CommandError(f"unknown scenario: {name}")
        if self.mode != "idle" or self.engine.state != "idle":
            raise CommandError("a session or demo is already running")
        session_id = f"demo-{uuid.uuid4().hex[:8]}"
        self.mode = "demo"
        self.status = SourceStatus(kind="demo", label=SCENARIOS[name].title)
        now = self.now_ms()
        self.engine.start_session(session_id, now)
        self._demo = DemoRunner(SCENARIOS[name], self.engine, session_id, now)
        self._emit_snapshot(force=True)

    def _translation_result(self, msg: dict[str, Any]) -> None:
        request_id = _req_str(msg, "request_id")
        content, error = msg.get("content"), msg.get("error")
        if content is not None and not isinstance(content, str):
            raise CommandError("content must be a string")
        if error is not None and not isinstance(error, str):
            raise CommandError("error must be a string")
        if (content is None) == (error is None):
            raise CommandError("exactly one of content or error is required")
        if content is not None and len(content) > 16_000:
            raise CommandError("translation content is too large")
        if error is not None and len(error) > 200:
            raise CommandError("translation error is too large")
        if "session_id" in msg and msg["session_id"] != self.engine.session_id:
            return
        request = self.engine.scheduler.request_by_id(request_id)
        if request is not None and "source_revision" in msg and msg["source_revision"] != request.source_revision:
            return
        self.engine.translation_reply(request_id, self.now_ms(), content=content, error=error)
        self._flush_requests()

    # -- activity -----------------------------------------------------------------------

    async def _stop_command(self, command_id: str | None) -> None:
        await self._stop_activity()
        self.emit({"type": "session.stopped", "command_id": command_id, "session_id": self.engine.session_id})

    async def _finish_shutdown(self) -> None:
        if self._stop_task is not None:
            await self._stop_task
        else:
            await self._stop_activity()
        self.emit({"type": "core.exiting"})
        self._shutdown.set()

    async def _stop_activity(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        try:
            now = self.now_ms()
            if self._live is not None:
                live, self._live = self._live, None
                await live.stop()
            if self._demo is not None:
                self._demo.finish(now)
            self.engine.stop_session(self.now_ms())
            self._flush_requests()
            # Drain: wait for final translations within the finalize budget.
            deadline = self.now_ms() + self.engine.config.scheduler.finalize_timeout_ms + 500
            while self.engine.state == "stopping" and self.now_ms() < deadline:
                await asyncio.sleep(TICK_S)
            if self.engine.state != "idle":
                self.engine.tick(deadline + self.engine.config.scheduler.request_timeout_ms)
            self._demo = None
            self.mode = "idle"
            self.status.capturing = False
            self.status.asr_connected = False
            self._emit_snapshot(force=True)
        finally:
            self._stopping = False

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            if self._shutdown.is_set():
                return
            now = self.now_ms()
            if self._demo is not None:
                # The runner ticks the engine and answers its own requests (same engine path).
                self._demo.advance(now)
                if self._demo.done(now) and not self._stopping:
                    self._stop_task = asyncio.create_task(self._stop_command(None))
            else:
                self.engine.tick(now)
                self._flush_requests()
            self._emit_snapshot()

    def _flush_requests(self) -> None:
        if self._demo is not None:
            return  # requests stay queued for the demo runner to collect
        for request in self.engine.drain_requests():
            if self.executor == "core_mock":
                asyncio.get_running_loop().call_later(0.35, self._answer_mock, request)
            else:
                self.emit(
                    {
                        "type": "translate.request",
                        "request_id": request.request_id,
                        "session_id": request.session_id,
                        "segment_id": request.segment_id,
                        "source_revision": request.source_revision,
                        "final": request.final,
                        "attempt": request.attempt,
                        "messages": list(request.messages),
                    }
                )

    def _answer_mock(self, request: TranslationRequest) -> None:
        content = mock_reply(request, mode=self.engine.mode)
        self.engine.translation_reply(request.request_id, self.now_ms(), content=content)
        self._flush_requests()

    def _emit_snapshot(self, force: bool = False) -> None:
        now = self.now_ms()
        version = self.engine.version + self.engine.board.version
        if not force and version == self._last_emit_version and now - self._last_emit_ms < HEARTBEAT_MS:
            return
        self._last_emit_version = version
        self._last_emit_ms = now
        snap = self.engine.snapshot(now)
        snap.update(
            type="snapshot",
            mode=self.mode,
            version=version,
            now_ms=now,
            executor=self.executor,
            translation_mode=self.engine.mode.value,
            source={
                "kind": self.status.kind,
                "label": self.status.label,
                "capturing": self.status.capturing,
                "asr_connected": self.status.asr_connected,
                "asr_backend": self.status.asr_backend,
                "speech_active": self.status.speech_active,
                "frames_dropped": self.status.frames_dropped,
                "gap_ms": self.status.gap_ms,
                "asr_overloaded_ms": self.status.asr_overloaded_ms,
                "error": self.status.error,
            },
        )
        self.emit(snap)


class LiveSession:
    """Capture -> ASR worker -> organizer -> engine for one session."""

    def __init__(
        self,
        host: Host,
        session_id: str,
        target: tuple[str, int | None, str | None, str],
        client_config: AsrClientConfig,
    ) -> None:
        self.host = host
        self.session_id = session_id
        self.target = target
        self.client = AsrClient(client_config)
        self.organizer = StableSourceOrganizer(session_id, host.engine.config.organizer)
        self.capture: Any = None
        self._tasks: list[asyncio.Task[None]] = []
        self._closing = False

    async def start(self) -> None:
        status = self.host.status
        _LOGGER.info("starting ASR connection")
        try:
            backend = await self.client.start(self.session_id)
            _LOGGER.info("ASR connection ready")
            status.asr_connected = True
            status.asr_backend = backend
        except AsrClientError as exc:
            status.error = f"ASR 服务不可用：{exc}"
            await self.client.close()
            return
        self._tasks.append(asyncio.create_task(self._read_events()))
        if sys.platform != "win32":
            status.error = "音频采集仅支持 Windows"
            return
        from .audio.capture import CaptureError, CaptureTarget, LoopbackCapture

        kind, pid, device_id, label = self.target
        self.capture = LoopbackCapture(CaptureTarget(kind, root_pid=pid, device_id=device_id, label=label))
        _LOGGER.info("starting selected audio capture")
        try:
            await asyncio.to_thread(self.capture.start)
        except CaptureError as exc:
            # No silent fallback to a wider capture scope (A1).
            status.error = f"无法采集所选来源：{exc}"
            self.capture = None
            return
        status.capturing = True
        _LOGGER.info("audio capture ready")
        self._tasks.append(asyncio.create_task(self._pump_audio()))

    async def _pump_audio(self) -> None:
        capture = self.capture
        status = self.host.status
        loop = asyncio.get_running_loop()
        next_sample = 0
        while True:
            try:
                kind, item = await loop.run_in_executor(None, _queue_get, capture.output)
            except _Empty:
                status.frames_dropped = capture.stats.frames_dropped
                if self._closing:
                    return
                continue
            try:
                status.frames_dropped = capture.stats.frames_dropped
                if kind == "frame":
                    if item.start_sample > next_sample:
                        await self._report_gap(next_sample, item.start_sample - next_sample)
                    await self.client.send_audio(item)
                    next_sample = item.start_sample + item.samples
                elif kind == "gap":
                    end_sample = item.start_sample + item.missing_samples
                    if end_sample > next_sample:
                        await self._report_gap(next_sample, end_sample - next_sample)
                        next_sample = end_sample
                elif kind == "error":
                    status.error = f"来源已断开：{item}"
                    status.capturing = False
                elif kind == "end":
                    if type(item) is int and item > next_sample:
                        await self._report_gap(next_sample, item - next_sample)
                    status.capturing = False
                    return
            except AsrClientError as exc:
                status.error = f"ASR 连接中断：{exc}"
                status.asr_connected = False
                return

    async def _report_gap(self, start_sample: int, missing_samples: int) -> None:
        self.host.status.gap_ms += samples_to_ms(missing_samples)
        self._organize(self.organizer.push_gap(CaptureGap(
            self.session_id, samples_to_ms(start_sample), samples_to_ms(missing_samples),
        )))
        await self.client.send_gap(start_sample, missing_samples)

    async def _read_events(self) -> None:
        status = self.host.status
        async for event in self.client.events():
            if isinstance(event, AsrSnapshot):
                self._organize(self.organizer.push_snapshot(event))
            elif isinstance(event, SpeechActivity):
                status.speech_active = event.active
                self._organize(self.organizer.push_activity(event))
            elif isinstance(event, RuntimeOverloaded):
                status.asr_overloaded_ms += event.dropped_audio_ms
                self._organize(
                    self.organizer.push_gap(CaptureGap(self.session_id, None, event.dropped_audio_ms, "asr_overloaded"))
                )
            elif isinstance(event, AsrError):
                if not self._closing or event.code != "connection_closed":
                    status.error = f"ASR 错误（{event.code}）：{event.message}"
                if event.code == "connection_closed":
                    status.asr_connected = False
            elif isinstance(event, SessionStopped):
                return

    def _organize(self, updates: list[Any]) -> None:
        now = self.host.now_ms()
        for update in updates:
            self.host.engine.source_update(update, now)
        self.host._flush_requests()

    async def stop(self) -> None:
        """Stop capture, let the ASR drain its tail, then flush the organizer."""
        self._closing = True
        if self.capture is not None:
            await asyncio.to_thread(self.capture.stop)
        if self._tasks:
            pump = self._tasks[1] if len(self._tasks) > 1 else None
            if pump is not None:
                try:
                    await asyncio.wait_for(pump, 3.0)
                except (TimeoutError, asyncio.CancelledError):
                    pump.cancel()
        if self.host.status.asr_connected:
            try:
                await self.client.stop()
            except AsrClientError as exc:
                self.host.status.error = f"ASR 未确认停止：{exc}"
        for task in self._tasks:
            if not task.done():
                try:
                    await asyncio.wait_for(task, 1.0)
                except (TimeoutError, asyncio.CancelledError):
                    task.cancel()
        self._organize(self.organizer.stop())
        await self.client.close()


class _Empty(Exception):
    pass


def _queue_get(q: Any) -> tuple[str, Any]:
    import queue as _q

    try:
        return q.get(timeout=0.2)
    except _q.Empty as exc:
        raise _Empty from exc


def _req_str(msg: dict[str, Any], key: str) -> str:
    value = msg.get(key)
    if not isinstance(value, str) or not value or len(value) > 200:
        raise CommandError(f"{key} must be a non-empty string")
    return value


def _stdin_reader(loop: asyncio.AbstractEventLoop, lines: asyncio.Queue[bytes | None], stopped: threading.Event) -> None:
    descriptor = sys.stdin.fileno()
    pending = b""
    oversized = False

    def enqueue(value: bytes | None) -> bool:
        try:
            future = asyncio.run_coroutine_threadsafe(lines.put(value), loop)
            while not stopped.is_set():
                try:
                    future.result(timeout=0.1)
                    return True
                except concurrent.futures.TimeoutError:
                    continue
            future.cancel()
        except (RuntimeError, concurrent.futures.CancelledError):
            pass
        return False

    while not stopped.is_set():
        try:
            raw = os.read(descriptor, 64 * 1024)
        except BlockingIOError:
            stopped.wait(0.01)
            continue
        if not raw:
            if oversized:
                enqueue(b'{"type":"__oversized__"}')
            elif pending.strip():
                enqueue(pending)
            enqueue(None)
            return
        pending += raw
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if oversized or len(line) + 1 > MAX_LINE_BYTES:
                if not enqueue(b'{"type":"__oversized__"}'):
                    return
            elif line.strip() and not enqueue(line):
                return
            oversized = False
        if len(pending) > MAX_LINE_BYTES or oversized:
            oversized = True
            pending = b""


async def _amain() -> None:
    if sys.platform == "win32":
        # Load native audio dependencies before starting blocking stdin IO on Windows.
        from .audio import framer  # noqa: F401
    loop = asyncio.get_running_loop()
    lines: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=128)
    os.set_blocking(sys.stdin.fileno(), False)
    stopped = threading.Event()
    reader = threading.Thread(target=_stdin_reader, args=(loop, lines, stopped), name="stdin-reader", daemon=True)
    reader.start()
    host = Host(sys.stdout.buffer)
    try:
        await host.run(lines)
    finally:
        stopped.set()
        await asyncio.to_thread(reader.join, 1.0)


def main() -> int:
    configure_stderr_logging()
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass
    except OSError:
        print("The host requires a readable pipe on stdin.", file=sys.stderr)
        return 2
    return 0
