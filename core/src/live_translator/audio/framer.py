"""PCM framing on a 16 kHz sample timeline with explicit gaps (PRODUCT_DISCUSSION.md T1).

Redesign of archived/windows-client/src/live_translator/audio.py (Pcm16FrameBuffer): instead of
callback time and zero-padded tails, every frame carries its start sample on the output
timeline, discontinuities advance the timeline as a gap, and the last frame keeps its true
length.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import soxr

from ..asr_protocol import SAMPLE_RATE, AudioFrame

FRAME_SAMPLES = SAMPLE_RATE // 10  # 100 ms


@dataclass(frozen=True, slots=True)
class Gap:
    start_sample: int
    missing_samples: int


@dataclass(slots=True)
class Framer:
    """Converts interleaved int16 input at any rate/channel count into 100 ms frames."""

    input_rate: int
    channels: int
    _resampler: object | None = field(default=None, init=False)
    _buffer: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int16), init=False)
    _next_sample: int = field(default=0, init=False)  # output timeline position of _buffer[0]
    input_frames: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.input_rate <= 0 or self.channels <= 0:
            raise ValueError("invalid input format")
        if self.input_rate != SAMPLE_RATE:
            self._resampler = soxr.ResampleStream(self.input_rate, SAMPLE_RATE, 1, dtype="float32")

    @property
    def timeline_samples(self) -> int:
        return self._next_sample + len(self._buffer)

    def push(self, interleaved: np.ndarray) -> list[AudioFrame]:
        if interleaved.size % self.channels:
            raise ValueError("input must contain whole frames")
        self.input_frames += interleaved.size // self.channels
        mono = interleaved.reshape(-1, self.channels).astype(np.float32).mean(axis=1) / 32768.0
        if self._resampler is not None:
            mono = self._resampler.resample_chunk(mono)  # type: ignore[attr-defined]
        pcm = np.clip(np.round(mono * 32768.0), -32768, 32767).astype(np.int16)
        self._buffer = np.concatenate([self._buffer, pcm])
        return self._drain(final=False)

    def gap(self, missing_input_frames: int) -> tuple[list[AudioFrame], Gap | None]:
        """Flush what we have, then advance the timeline by the missing duration."""
        self._flush_resampler()
        frames = self._drain(final=True)
        missing = missing_input_frames * SAMPLE_RATE // self.input_rate
        if missing <= 0:
            return frames, None
        gap = Gap(self._next_sample, missing)
        self._next_sample += missing
        if self._resampler is not None:
            self._resampler = soxr.ResampleStream(self.input_rate, SAMPLE_RATE, 1, dtype="float32")
        return frames, gap

    def finish(self) -> list[AudioFrame]:
        self._flush_resampler()
        return self._drain(final=True)

    def _flush_resampler(self) -> None:
        if self._resampler is None:
            return
        tail = self._resampler.resample_chunk(np.zeros(0, dtype=np.float32), last=True)  # type: ignore[attr-defined]
        pcm = np.clip(np.round(tail * 32768.0), -32768, 32767).astype(np.int16)
        self._buffer = np.concatenate([self._buffer, pcm])

    def _drain(self, *, final: bool) -> list[AudioFrame]:
        frames: list[AudioFrame] = []
        while len(self._buffer) >= FRAME_SAMPLES or (final and len(self._buffer)):
            take = min(FRAME_SAMPLES, len(self._buffer))
            chunk, self._buffer = self._buffer[:take], self._buffer[take:]
            frames.append(AudioFrame(self._next_sample, chunk.astype("<i2").tobytes()))
            self._next_sample += take
        return frames
