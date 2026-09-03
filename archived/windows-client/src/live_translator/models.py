from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
CHUNK_MS = 100
CHUNK_BYTES = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES * CHUNK_MS // 1_000
ENCODING = "pcm_s16le"
SOURCE_LANGUAGE = "ja"
TARGET_LANGUAGE = "zh-CN"


@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    encoding: Literal["pcm_s16le"] = ENCODING
    chunk_ms: int = CHUNK_MS

    def __post_init__(self) -> None:
        if self.sample_rate != SAMPLE_RATE:
            raise ValueError(f"sample_rate must be {SAMPLE_RATE}")
        if self.channels != CHANNELS:
            raise ValueError(f"channels must be {CHANNELS}")
        if self.encoding != ENCODING:
            raise ValueError(f"encoding must be {ENCODING}")
        if self.chunk_ms != CHUNK_MS:
            raise ValueError(f"chunk_ms must be {CHUNK_MS}")

    @property
    def chunk_bytes(self) -> int:
        return CHUNK_BYTES


@dataclass(frozen=True, slots=True)
class AudioChunk:
    chunk_id: int
    pcm_bytes: bytes
    captured_at_ms: int

    def __post_init__(self) -> None:
        if self.chunk_id < 0:
            raise ValueError("chunk_id must be non-negative")
        if self.captured_at_ms < 0:
            raise ValueError("captured_at_ms must be non-negative")
        if len(self.pcm_bytes) != CHUNK_BYTES:
            raise ValueError(f"pcm_bytes must contain exactly {CHUNK_BYTES} bytes")


@dataclass(frozen=True, slots=True)
class StartStream:
    session_id: str
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    encoding: Literal["pcm_s16le"] = ENCODING
    language: Literal["ja"] = SOURCE_LANGUAGE

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        AudioFormat(
            sample_rate=self.sample_rate,
            channels=self.channels,
            encoding=self.encoding,
        )
        if self.language != SOURCE_LANGUAGE:
            raise ValueError(f"language must be {SOURCE_LANGUAGE}")


@dataclass(frozen=True, slots=True)
class StreamReady:
    session_id: str
    type: Literal["stream.ready"] = "stream.ready"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")


@dataclass(frozen=True, slots=True)
class TranscriptFinal:
    session_id: str
    seq: int
    text: str
    audio_start_ms: int
    audio_end_ms: int
    decode_ms: int
    type: Literal["transcript.final"] = "transcript.final"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if self.seq < 1:
            raise ValueError("seq must be positive")
        if not self.text.strip():
            raise ValueError("text must not be empty")
        if self.audio_start_ms < 0:
            raise ValueError("audio_start_ms must be non-negative")
        if self.audio_end_ms < self.audio_start_ms:
            raise ValueError("audio_end_ms must not precede audio_start_ms")
        if self.decode_ms < 0:
            raise ValueError("decode_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class RuntimeOverloaded:
    session_id: str
    dropped_audio_ms: int
    type: Literal["runtime.overloaded"] = "runtime.overloaded"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if self.dropped_audio_ms < 0:
            raise ValueError("dropped_audio_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class StreamStopped:
    session_id: str
    type: Literal["stream.stopped"] = "stream.stopped"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")


@dataclass(frozen=True, slots=True)
class AsrError:
    session_id: str
    code: str
    message: str
    retryable: bool
    type: Literal["error"] = "error"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if not self.code.strip():
            raise ValueError("code must not be empty")
        if not self.message.strip():
            raise ValueError("message must not be empty")


type AsrEvent = StreamReady | TranscriptFinal | RuntimeOverloaded | StreamStopped | AsrError


@dataclass(frozen=True, slots=True)
class TranslationContext:
    source_text: str
    translated_text: str


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    source_text: str
    context: tuple[TranslationContext, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_text.strip():
            raise ValueError("source_text must not be empty")
        if len(self.context) > 2:
            raise ValueError("translation context is limited to two entries")


@dataclass(frozen=True, slots=True)
class TranslationResult:
    source_text: str
    translated_text: str

    def __post_init__(self) -> None:
        if not self.source_text.strip():
            raise ValueError("source_text must not be empty")
        if not self.translated_text.strip():
            raise ValueError("translated_text must not be empty")


type AppStatus = Literal[
    "idle",
    "connecting",
    "running",
    "stopping",
    "stopped",
    "degraded",
    "error",
]


type TranslationStatus = Literal["pending", "translated", "failed", "skipped"]

MAX_VISIBLE_SUBTITLES = 2


@dataclass(frozen=True, slots=True)
class SubtitleSegment:
    session_id: str
    seq: int
    source_text: str
    audio_start_ms: int
    audio_end_ms: int
    translated_text: str = ""
    translation_status: TranslationStatus = "pending"

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        if self.seq < 1:
            raise ValueError("seq must be positive")
        if not self.source_text.strip():
            raise ValueError("source_text must not be empty")
        if self.audio_start_ms < 0:
            raise ValueError("audio_start_ms must be non-negative")
        if self.audio_end_ms < self.audio_start_ms:
            raise ValueError("audio_end_ms must not precede audio_start_ms")
        if self.translation_status == "translated" and not self.translated_text.strip():
            raise ValueError("translated subtitles must contain translated_text")
        if self.translation_status != "translated" and self.translated_text:
            raise ValueError("only translated subtitles may contain translated_text")


@dataclass(frozen=True, slots=True)
class SubtitleState:
    segments: tuple[SubtitleSegment, ...] = ()
    status: AppStatus = "idle"
    message: str = ""

    def __post_init__(self) -> None:
        if len(self.segments) > MAX_VISIBLE_SUBTITLES:
            raise ValueError(f"at most {MAX_VISIBLE_SUBTITLES} subtitles may be visible")
        if not self.segments:
            return
        session_id = self.segments[0].session_id
        if any(segment.session_id != session_id for segment in self.segments):
            raise ValueError("visible subtitles must belong to one session")
        sequences = tuple(segment.seq for segment in self.segments)
        if sequences != tuple(sorted(set(sequences))):
            raise ValueError("visible subtitle sequences must be unique and increasing")

    @property
    def current_segment(self) -> SubtitleSegment | None:
        if not self.segments:
            return None
        return self.segments[-1]

    @property
    def source_text(self) -> str:
        segment = self.current_segment
        return "" if segment is None else segment.source_text

    @property
    def translated_text(self) -> str:
        segment = self.current_segment
        return "" if segment is None else segment.translated_text
