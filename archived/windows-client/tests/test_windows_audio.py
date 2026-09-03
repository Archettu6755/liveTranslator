from __future__ import annotations

import threading
from collections.abc import Iterator

import numpy as np
import pytest

from live_translator import windows_audio
from live_translator.models import CHUNK_BYTES
from live_translator.windows_audio import (
    StreamingPcmNormalizer,
    WasapiLoopbackSource,
    WindowsAudioError,
)


class FailingStartStream:
    def __init__(self) -> None:
        self.stop_called = False
        self.close_called = False

    def start_stream(self) -> None:
        raise OSError("start failed")

    def stop_stream(self) -> None:
        self.stop_called = True

    def close(self) -> None:
        self.close_called = True


class RecordingAudioManager:
    def __init__(self) -> None:
        self.stream = FailingStartStream()
        self.terminated = False

    def get_default_wasapi_loopback(self) -> dict[str, object]:
        return {
            "index": 1,
            "name": "test loopback",
            "defaultSampleRate": 48_000,
            "maxInputChannels": 2,
        }

    def get_device_info_by_index(self, _device_index: int) -> dict[str, object]:
        return self.get_default_wasapi_loopback()

    def get_loopback_device_info_generator(self) -> Iterator[dict[str, object]]:
        yield self.get_default_wasapi_loopback()

    def open(self, **_kwargs: object) -> FailingStartStream:
        return self.stream

    def terminate(self) -> None:
        self.terminated = True


class TerminateFailingAudioManager(RecordingAudioManager):
    def terminate(self) -> None:
        self.terminated = True
        raise OSError("terminate failed")


def test_stereo_input_is_mixed_to_mono() -> None:
    frames = np.empty((1_600, 2), dtype="<i2")
    frames[:, 0] = 1_000
    frames[:, 1] = -1_000
    normalizer = StreamingPcmNormalizer(input_sample_rate=16_000, input_channels=2)

    chunks = normalizer.push(frames.tobytes(), captured_at_ms=200)

    assert len(chunks) == 1
    assert chunks[0].captured_at_ms == 200
    assert chunks[0].pcm_bytes == b"\x00" * CHUNK_BYTES


def test_48khz_stream_is_resampled_to_fixed_16khz_chunks() -> None:
    frames = np.zeros((48_000, 2), dtype="<i2")
    normalizer = StreamingPcmNormalizer(input_sample_rate=48_000, input_channels=2)

    chunks = normalizer.push(frames.tobytes(), captured_at_ms=1_000)
    chunks.extend(normalizer.finish())

    assert len(chunks) == 10
    assert [chunk.captured_at_ms for chunk in chunks] == [
        1_000 + index * 100 for index in range(10)
    ]
    assert all(len(chunk.pcm_bytes) == CHUNK_BYTES for chunk in chunks)


def test_16khz_stream_pads_a_short_tail_on_finish() -> None:
    frames = np.full((320, 1), 1_000, dtype="<i2")
    normalizer = StreamingPcmNormalizer(input_sample_rate=16_000, input_channels=1)

    assert normalizer.push(frames.tobytes(), captured_at_ms=2_000) == []
    chunks = normalizer.finish()

    assert len(chunks) == 1
    assert chunks[0].captured_at_ms == 2_000
    assert chunks[0].pcm_bytes[: frames.nbytes] == frames.tobytes()
    assert chunks[0].pcm_bytes[frames.nbytes :] == b"\x00" * (CHUNK_BYTES - frames.nbytes)


def test_start_failure_closes_stream_and_audio_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RecordingAudioManager()

    def fake_pyaudio_constant(_name: str) -> int:
        return 0

    monkeypatch.setattr(windows_audio, "_new_manager", lambda: manager)
    monkeypatch.setattr(windows_audio, "_pyaudio_constant", fake_pyaudio_constant)

    source = WasapiLoopbackSource()
    with pytest.raises(WindowsAudioError, match="Could not open"):
        source.start()

    assert manager.stream.stop_called
    assert manager.stream.close_called
    assert manager.terminated
    assert source.read_chunk() is None


def test_worker_start_failure_still_closes_stream_and_audio_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = RecordingAudioManager()

    def fail_to_start_thread(_thread: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    def fake_pyaudio_constant(_name: str) -> int:
        return 0

    monkeypatch.setattr(windows_audio, "_new_manager", lambda: manager)
    monkeypatch.setattr(windows_audio, "_pyaudio_constant", fake_pyaudio_constant)
    monkeypatch.setattr(threading.Thread, "start", fail_to_start_thread)

    source = WasapiLoopbackSource()
    with pytest.raises(WindowsAudioError, match="Could not open"):
        source.start()

    assert manager.stream.stop_called
    assert manager.stream.close_called
    assert manager.terminated
    assert source._worker is None  # pyright: ignore[reportPrivateUsage]


def test_device_enumeration_ignores_manager_terminate_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = TerminateFailingAudioManager()
    monkeypatch.setattr(windows_audio, "_new_manager", lambda: manager)

    devices = windows_audio.list_loopback_devices()

    assert [device.name for device in devices] == ["test loopback"]
    assert manager.terminated


def test_callback_reports_native_input_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constants = {
        "paContinue": 0,
        "paAbort": 1,
        "paInputOverflow": 2,
    }

    def fake_pyaudio_constant(name: str) -> int:
        return constants[name]

    monkeypatch.setattr(windows_audio, "_pyaudio_constant", fake_pyaudio_constant)
    source = WasapiLoopbackSource()
    source._running.set()  # pyright: ignore[reportPrivateUsage]
    callback = source._make_callback()  # pyright: ignore[reportPrivateUsage]

    result = callback(b"\x00\x00", 1, {}, 2)

    assert result == (None, 0)
    assert source.snapshot_stats().input_overflow_events == 1


def test_stop_reports_and_retains_a_worker_that_misses_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_worker = threading.Event()
    worker = threading.Thread(target=release_worker.wait)
    worker.start()
    source = WasapiLoopbackSource()
    source._worker = worker  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(windows_audio, "_WORKER_STOP_TIMEOUT_SECONDS", 0.01)

    try:
        with pytest.raises(WindowsAudioError, match="did not stop"):
            source.stop()
        assert source._worker is worker  # pyright: ignore[reportPrivateUsage]
    finally:
        release_worker.set()
        worker.join(timeout=1.0)
    source.stop()
    assert source._worker is None  # pyright: ignore[reportPrivateUsage]
