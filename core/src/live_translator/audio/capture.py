"""Windows loopback capture threads: application (process tree) or output-device mix.

The capture thread only reads buffers, frames them and hands them to a bounded queue; it never
waits on ASR, HTTP or UI (AGENTS.md section 4). Drops and discontinuities are counted and turned
into timeline gaps. Application capture never falls back to device capture on failure (A1).
"""

from __future__ import annotations

import ctypes
import queue
import threading
from dataclasses import dataclass, field

import comtypes
import numpy as np

from ..diagnostics import get_logger
from . import win_com as wc
from .framer import Framer, Gap

_LOGGER = get_logger("capture")
CAPTURE_RATE = 48_000
CAPTURE_CHANNELS = 2
BUFFER_HNS = 2_000_000  # 200 ms


class CaptureError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    kind: str  # "application" | "output_device"
    root_pid: int | None = None
    device_id: str | None = None
    label: str = ""


@dataclass(slots=True)
class CaptureStats:
    frames_queued: int = 0
    frames_dropped: int = 0
    discontinuities: int = 0
    gap_samples: int = 0


class _CompletionHandler(comtypes.COMObject):
    _com_interfaces_ = [wc.IActivateAudioInterfaceCompletionHandler, wc.IAgileObject]

    def __init__(self) -> None:
        super().__init__()
        self.done = threading.Event()

    def ActivateCompleted(self, operation) -> int:  # type: ignore[no-untyped-def]  # noqa: N802
        self.done.set()
        return 0


def _activate_process_loopback(root_pid: int) -> wc.IAudioClient:
    params = wc.AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = wc.AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = root_pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = wc.PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
    prop = wc.PROPVARIANT()
    prop.vt = wc.VT_BLOB
    prop.value.blob.cbSize = ctypes.sizeof(params)
    prop.value.blob.pBlobData = ctypes.cast(ctypes.pointer(params), ctypes.c_void_p)

    handler = _CompletionHandler()
    handler_ptr = handler.QueryInterface(wc.IActivateAudioInterfaceCompletionHandler)
    operation = ctypes.POINTER(wc.IActivateAudioInterfaceAsyncOperation)()
    wc.ActivateAudioInterfaceAsync(
        wc.VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        ctypes.byref(wc.IAudioClient._iid_),
        ctypes.byref(prop),
        handler_ptr,
        ctypes.byref(operation),
    )
    if not handler.done.wait(5.0):
        raise CaptureError("process loopback activation timed out")
    hr, unknown = operation.GetActivateResult()
    if hr < 0 or not unknown:
        raise CaptureError(f"process loopback activation failed (0x{hr & 0xFFFFFFFF:08X})")
    return unknown.QueryInterface(wc.IAudioClient)


def _activate_device(device_id: str | None) -> wc.IAudioClient:
    enumerator = wc.create_enumerator()
    device = (
        enumerator.GetDevice(device_id)
        if device_id
        else enumerator.GetDefaultAudioEndpoint(wc.eRender, wc.eConsole)
    )
    return wc.activate(device, wc.IAudioClient)


@dataclass(slots=True)
class LoopbackCapture:
    """One capture session. ``frames`` yields ("frame", AudioFrame) / ("gap", Gap) / ("error", str)."""

    target: CaptureTarget
    max_queue: int = 100
    output: queue.Queue[tuple[str, object]] = field(init=False)
    stats: CaptureStats = field(default_factory=CaptureStats)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _started: threading.Event = field(default_factory=threading.Event)
    _start_error: str | None = None

    def __post_init__(self) -> None:
        self.output = queue.Queue(self.max_queue)

    def start(self, timeout_s: float = 6.0) -> None:
        self._thread = threading.Thread(target=self._run, name="loopback-capture", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout_s):
            self.stop()
            raise CaptureError("audio capture did not start in time")
        if self._start_error:
            raise CaptureError(self._start_error)

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
            self._thread = None

    def _put(self, item: tuple[str, object], *, lifecycle: bool = False) -> None:
        try:
            self.output.put_nowait(item)
            if item[0] == "frame":
                self.stats.frames_queued += 1
        except queue.Full:
            if lifecycle:
                try:
                    dropped = self.output.get_nowait()
                    if dropped[0] == "frame":
                        self.stats.frames_dropped += 1
                except queue.Empty:
                    pass
                self.output.put_nowait(item)
            else:
                self.stats.frames_dropped += 1

    def _run(self) -> None:
        wc.co_initialize_mta()
        event = None
        client = None
        try:
            if self.target.kind == "application":
                if not self.target.root_pid:
                    raise CaptureError("no application selected")
                client = _activate_process_loopback(self.target.root_pid)
            else:
                client = _activate_device(self.target.device_id)
            fmt = wc.pcm16_format(CAPTURE_RATE, CAPTURE_CHANNELS)
            flags = (
                wc.AUDCLNT_STREAMFLAGS_LOOPBACK
                | wc.AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                | wc.AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
                | wc.AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY
            )
            client.Initialize(wc.AUDCLNT_SHAREMODE_SHARED, flags, BUFFER_HNS, 0, ctypes.byref(fmt), None)
            event = wc.CreateEventW(None, False, False, None)
            client.SetEventHandle(event)
            capture = ctypes.cast(
                client.GetService(ctypes.byref(wc.IAudioCaptureClient._iid_)),
                ctypes.POINTER(wc.IAudioCaptureClient),
            )
            client.Start()
        except Exception as exc:  # noqa: BLE001 - surface any activation failure as a start error
            self._start_error = f"capture start failed: {exc}"
            self._started.set()
            if event:
                wc.CloseHandle(event)
            return
        self._started.set()

        framer = Framer(CAPTURE_RATE, CAPTURE_CHANNELS)
        expected_position: int | None = None
        try:
            while not self._stop.is_set():
                wc.WaitForSingleObject(event, 100)
                while True:
                    packet = capture.GetNextPacketSize()
                    if packet == 0:
                        break
                    data, frames, buf_flags, position, _qpc = capture.GetBuffer()
                    try:
                        if expected_position is not None and position > expected_position:
                            self._emit_gap(framer, position - expected_position)
                        elif buf_flags & wc.AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY and expected_position is not None:
                            self.stats.discontinuities += 1
                        if buf_flags & wc.AUDCLNT_BUFFERFLAGS_SILENT or not data:
                            samples = np.zeros(frames * CAPTURE_CHANNELS, dtype=np.int16)
                        else:
                            raw = ctypes.string_at(data, frames * CAPTURE_CHANNELS * 2)
                            samples = np.frombuffer(raw, dtype="<i2").copy()
                    finally:
                        capture.ReleaseBuffer(frames)
                    expected_position = position + frames
                    for frame in framer.push(samples):
                        self._put(("frame", frame))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("capture loop ended: %s", exc)
            self._put(("error", f"audio capture stopped: {exc}"), lifecycle=True)
        finally:
            for frame in framer.finish():
                self._put(("frame", frame))
            try:
                client.Stop()
            except Exception:  # noqa: BLE001
                pass
            wc.CloseHandle(event)
            self._put(("end", framer.timeline_samples), lifecycle=True)

    def _emit_gap(self, framer: Framer, missing_frames: int) -> None:
        self.stats.discontinuities += 1
        frames, gap = framer.gap(missing_frames)
        for frame in frames:
            self._put(("frame", frame))
        if isinstance(gap, Gap):
            self.stats.gap_samples += gap.missing_samples
            self._put(("gap", gap), lifecycle=True)
