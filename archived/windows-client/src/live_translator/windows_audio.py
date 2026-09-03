from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import import_module
from queue import Empty, Full, Queue
from sys import platform
from typing import Protocol, cast

import numpy as np
import numpy.typing as npt
import soxr  # pyright: ignore[reportMissingTypeStubs]

from .audio import AudioSourceError, AudioSourceStats, Pcm16FrameBuffer
from .diagnostics import get_logger
from .models import SAMPLE_RATE, AudioChunk

_LOGGER = get_logger("windows_audio")
_WORKER_STOP_TIMEOUT_SECONDS = 2.0


class WindowsAudioError(AudioSourceError):
    pass


class _AudioStream(Protocol):
    def start_stream(self) -> None: ...

    def stop_stream(self) -> None: ...

    def close(self) -> None: ...


class _AudioCallback(Protocol):
    def __call__(
        self,
        in_data: bytes | None,
        _frame_count: int,
        _time_info: Mapping[str, float],
        _status_flags: int,
    ) -> tuple[None, int]: ...


class _PyAudioManager(Protocol):
    def get_default_wasapi_loopback(self) -> dict[str, object]: ...

    def get_device_info_by_index(self, device_index: int) -> dict[str, object]: ...

    def get_loopback_device_info_generator(self) -> Iterator[dict[str, object]]: ...

    def open(self, **kwargs: object) -> _AudioStream: ...

    def terminate(self) -> None: ...


class _PyAudioModule(Protocol):
    def PyAudio(self) -> _PyAudioManager: ...


@dataclass(frozen=True, slots=True)
class LoopbackDevice:
    index: int
    name: str
    sample_rate: int
    channels: int
    is_default: bool = False


def list_loopback_devices() -> list[LoopbackDevice]:
    manager = _new_manager()
    try:
        default_index = _device_from_mapping(
            manager.get_default_wasapi_loopback(),
            is_default=True,
        ).index
        devices = [
            _device_from_mapping(info, is_default=_required_int(info, "index") == default_index)
            for info in manager.get_loopback_device_info_generator()
        ]
    except OSError as exc:
        raise WindowsAudioError("WASAPI loopback is unavailable.") from exc
    finally:
        try:
            manager.terminate()
        except Exception:
            _LOGGER.exception("Could not terminate the audio device enumerator.")
    return devices


@dataclass(slots=True)
class StreamingPcmNormalizer:
    input_sample_rate: int
    input_channels: int
    _frame_buffer: Pcm16FrameBuffer = field(default_factory=Pcm16FrameBuffer, init=False)
    _resampler: soxr.ResampleStream | None = field(default=None, init=False)
    _last_capture_ms: int | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.input_sample_rate < 8_000:
            raise ValueError("input_sample_rate is too low")
        if self.input_channels < 1:
            raise ValueError("input_channels must be positive")
        if self.input_sample_rate != SAMPLE_RATE:
            self._resampler = soxr.ResampleStream(
                self.input_sample_rate,
                SAMPLE_RATE,
                1,
                dtype="float32",
                quality="HQ",
            )

    def push(self, raw_pcm16: bytes, *, captured_at_ms: int) -> list[AudioChunk]:
        self._last_capture_ms = captured_at_ms
        mono = self._decode_mono(raw_pcm16)
        normalized = self._resample(mono, last=False)
        return self._encode_chunks(normalized, captured_at_ms=captured_at_ms)

    def finish(self) -> list[AudioChunk]:
        chunks: list[AudioChunk] = []
        if self._resampler is not None:
            empty = np.empty(0, dtype=np.float32)
            normalized = self._resample(empty, last=True)
            chunks.extend(
                self._encode_chunks(
                    normalized,
                    captured_at_ms=self._last_capture_ms or 0,
                )
            )
        chunks.extend(self._frame_buffer.finish())
        return chunks

    def _decode_mono(self, raw_pcm16: bytes) -> npt.NDArray[np.float32]:
        sample_width = 2 * self.input_channels
        if len(raw_pcm16) % sample_width:
            raise WindowsAudioError("Loopback audio contains an incomplete frame.")
        samples = np.frombuffer(raw_pcm16, dtype="<i2")
        frames = samples.reshape(-1, self.input_channels)
        return frames.astype(np.float32).mean(axis=1) / 32_768.0

    def _resample(
        self,
        mono: npt.NDArray[np.float32],
        *,
        last: bool,
    ) -> npt.NDArray[np.float32]:
        if self._resampler is None:
            return mono
        output = self._resampler.resample_chunk(mono, last=last)
        return cast(npt.NDArray[np.float32], output)

    def _encode_chunks(
        self,
        normalized: npt.NDArray[np.float32],
        *,
        captured_at_ms: int,
    ) -> list[AudioChunk]:
        if not normalized.size:
            return []
        clipped = np.clip(normalized, -1.0, 32_767.0 / 32_768.0)
        pcm16 = cast(npt.NDArray[np.int16], (clipped * 32_768.0).astype("<i2"))
        return self._frame_buffer.push(pcm16.tobytes(), captured_at_ms=captured_at_ms)


@dataclass(slots=True)
class WasapiLoopbackSource:
    device_index: int | None = None
    raw_queue_size: int = 64
    output_queue_size: int = 32
    _manager: _PyAudioManager | None = field(default=None, init=False)
    _stream: _AudioStream | None = field(default=None, init=False)
    _raw_queue: Queue[tuple[bytes, int]] = field(init=False)
    _output_queue: Queue[AudioChunk] = field(init=False)
    _worker: threading.Thread | None = field(default=None, init=False)
    _running: threading.Event = field(default_factory=threading.Event, init=False)
    _last_error: Exception | None = field(default=None, init=False)
    _input_overflow_events: int = field(default=0, init=False)
    _dropped_raw_blocks: int = field(default=0, init=False)
    _dropped_output_chunks: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.raw_queue_size < 2:
            raise ValueError("raw_queue_size must be at least 2")
        if self.output_queue_size < 2:
            raise ValueError("output_queue_size must be at least 2")
        self._raw_queue = Queue(maxsize=self.raw_queue_size)
        self._output_queue = Queue(maxsize=self.output_queue_size)

    def start(self) -> None:
        if self._running.is_set():
            raise WindowsAudioError("WASAPI loopback is already running.")
        if self._worker is not None and self._worker.is_alive():
            raise WindowsAudioError("The previous audio worker is still stopping.")
        self._worker = None

        _drain_queue(self._raw_queue)
        _drain_queue(self._output_queue)
        self._input_overflow_events = 0
        self._dropped_raw_blocks = 0
        self._dropped_output_chunks = 0

        manager = _new_manager()
        stream: _AudioStream | None = None
        worker: threading.Thread | None = None
        worker_started = False
        try:
            device_info = (
                manager.get_default_wasapi_loopback()
                if self.device_index is None
                else manager.get_device_info_by_index(self.device_index)
            )
            device = _device_from_mapping(device_info, is_default=self.device_index is None)
            normalizer = StreamingPcmNormalizer(
                input_sample_rate=device.sample_rate,
                input_channels=device.channels,
            )
            callback = self._make_callback()
            stream = manager.open(
                format=_pyaudio_constant("paInt16"),
                channels=device.channels,
                rate=device.sample_rate,
                frames_per_buffer=max(1, device.sample_rate // 50),
                input=True,
                input_device_index=device.index,
                stream_callback=callback,
                start=False,
            )
            self._manager = manager
            self._stream = stream
            self._last_error = None
            self._running.set()
            worker = threading.Thread(
                target=self._normalizer_loop,
                args=(normalizer,),
                name="wasapi-normalizer",
                daemon=True,
            )
            self._worker = worker
            worker.start()
            worker_started = True
            stream.start_stream()
        except Exception as exc:
            _LOGGER.exception("Could not start WASAPI loopback capture.")
            self._running.clear()
            self._manager = None
            self._stream = None
            self._worker = None
            if stream is not None:
                with suppress(Exception):
                    stream.stop_stream()
                with suppress(Exception):
                    stream.close()
            if worker_started and worker is not None:
                worker.join(timeout=_WORKER_STOP_TIMEOUT_SECONDS)
                if worker.is_alive():
                    self._worker = worker
                    _LOGGER.error("Audio normalization worker remained alive after start failed.")
            with suppress(Exception):
                manager.terminate()
            raise WindowsAudioError("Could not open WASAPI loopback.") from exc

    def read_chunk(self) -> AudioChunk | None:
        while self._running.is_set() or not self._output_queue.empty():
            if self._last_error is not None:
                raise WindowsAudioError("Loopback audio processing failed.") from self._last_error
            try:
                return self._output_queue.get(timeout=0.25)
            except Empty:
                continue
        if self._last_error is not None:
            raise WindowsAudioError("Loopback audio processing failed.") from self._last_error
        return None

    def stop(self) -> None:
        self._running.clear()
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                _LOGGER.exception("Could not stop the WASAPI loopback stream cleanly.")
            try:
                stream.close()
            except Exception:
                _LOGGER.exception("Could not close the WASAPI loopback stream cleanly.")

        worker = self._worker
        worker_error: WindowsAudioError | None = None
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=_WORKER_STOP_TIMEOUT_SECONDS)
            if worker.is_alive():
                _LOGGER.error("Audio normalization worker did not stop before the deadline.")
                worker_error = WindowsAudioError(
                    "Audio processing did not stop before the deadline."
                )
            else:
                self._worker = None

        manager = self._manager
        self._manager = None
        if manager is not None:
            try:
                manager.terminate()
            except Exception:
                _LOGGER.exception("Could not terminate the WASAPI audio manager cleanly.")
        if worker_error is not None:
            raise worker_error

    @property
    def dropped_raw_blocks(self) -> int:
        return self._dropped_raw_blocks

    @property
    def dropped_output_chunks(self) -> int:
        return self._dropped_output_chunks

    def snapshot_stats(self) -> AudioSourceStats:
        return AudioSourceStats(
            input_overflow_events=self._input_overflow_events,
            dropped_input_blocks=self._dropped_raw_blocks,
            dropped_output_chunks=self._dropped_output_chunks,
        )

    def _make_callback(self) -> _AudioCallback:
        continue_flag = _pyaudio_constant("paContinue")
        abort_flag = _pyaudio_constant("paAbort")
        input_overflow_flag = _pyaudio_constant("paInputOverflow")

        def callback(
            in_data: bytes | None,
            _frame_count: int,
            _time_info: Mapping[str, float],
            _status_flags: int,
        ) -> tuple[None, int]:
            if not self._running.is_set():
                return None, abort_flag
            if _status_flags & input_overflow_flag:
                self._input_overflow_events += 1
            if in_data:
                item = (bytes(in_data), int(time.monotonic() * 1_000))
                if not _put_latest(self._raw_queue, item):
                    self._dropped_raw_blocks += 1
            return None, continue_flag

        return callback

    def _normalizer_loop(self, normalizer: StreamingPcmNormalizer) -> None:
        try:
            while self._running.is_set() or not self._raw_queue.empty():
                try:
                    raw, captured_at_ms = self._raw_queue.get(timeout=0.1)
                except Empty:
                    continue
                for chunk in normalizer.push(raw, captured_at_ms=captured_at_ms):
                    if not _put_latest(self._output_queue, chunk):
                        self._dropped_output_chunks += 1
            for chunk in normalizer.finish():
                if not _put_latest(self._output_queue, chunk):
                    self._dropped_output_chunks += 1
        except Exception as exc:
            _LOGGER.exception("Audio normalization worker failed.")
            self._last_error = exc
            self._running.clear()


def _new_manager() -> _PyAudioManager:
    try:
        return _pyaudio_module().PyAudio()
    except (ImportError, OSError) as exc:
        raise WindowsAudioError("Could not initialize Windows audio.") from exc


def _pyaudio_constant(name: str) -> int:
    value = cast(object, getattr(_pyaudio_module(), name, None))
    if isinstance(value, bool) or not isinstance(value, int):
        raise WindowsAudioError(f"PyAudio constant {name} is unavailable.")
    return value


@lru_cache(maxsize=1)
def _pyaudio_module() -> _PyAudioModule:
    if platform != "win32":
        raise WindowsAudioError("WASAPI loopback requires Windows.")
    try:
        module = import_module("pyaudiowpatch")
    except ImportError as exc:
        raise WindowsAudioError("PyAudioWPatch is not installed.") from exc
    return cast(_PyAudioModule, module)


def _device_from_mapping(info: Mapping[str, object], *, is_default: bool) -> LoopbackDevice:
    channels = _required_int(info, "maxInputChannels")
    if channels < 1:
        raise WindowsAudioError("Selected loopback device has no input channels.")
    return LoopbackDevice(
        index=_required_int(info, "index"),
        name=_required_str(info, "name"),
        sample_rate=round(_required_number(info, "defaultSampleRate")),
        channels=channels,
        is_default=is_default,
    )


def _required_int(info: Mapping[str, object], key: str) -> int:
    value = info.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise WindowsAudioError(f"Audio device field {key} is invalid.")
    return value


def _required_number(info: Mapping[str, object], key: str) -> float:
    value = info.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WindowsAudioError(f"Audio device field {key} is invalid.")
    return float(value)


def _required_str(info: Mapping[str, object], key: str) -> str:
    value = info.get(key)
    if not isinstance(value, str) or not value:
        raise WindowsAudioError(f"Audio device field {key} is invalid.")
    return value


def _put_latest[T](queue: Queue[T], item: T) -> bool:
    try:
        queue.put_nowait(item)
        return True
    except Full:
        with suppress(Empty):
            queue.get_nowait()
        queue.put_nowait(item)
        return False


def _drain_queue[T](queue: Queue[T]) -> None:
    while True:
        try:
            queue.get_nowait()
        except Empty:
            return
