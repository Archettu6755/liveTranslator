"""ASR v1 WebSocket protocol (contracts/asr-v1.schema.json).

Replaces the archived final-only contract: the server sends revisable window snapshots, audio
frames carry their sample position, gaps are explicit, and speech activity is reported on the
audio timeline. Validation style adapted from archived/windows-client/src/live_translator/
protocol.py (commit 3e91d93).
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from .models import AsrSnapshot, SpeechActivity

PROTOCOL = "asr.v1"
SAMPLE_RATE = 16_000
CHANNELS = 1
ENCODING = "pcm_s16le"
MAX_TEXT_MESSAGE_CHARS = 64 * 1_024
MAX_AUDIO_FRAME_BYTES = 64 * 1_024
_HEADER = struct.Struct("<Q")


class ProtocolError(ValueError):
    pass


# -- client -> server ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionStart:
    session_id: str
    language: str = "ja"


@dataclass(frozen=True, slots=True)
class AudioGap:
    session_id: str
    start_sample: int
    missing_samples: int


@dataclass(frozen=True, slots=True)
class SessionStop:
    session_id: str


@dataclass(frozen=True, slots=True)
class AudioFrame:
    start_sample: int
    pcm: bytes

    @property
    def samples(self) -> int:
        return len(self.pcm) // 2


ClientMessage = SessionStart | AudioGap | SessionStop


# -- server -> client ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionReady:
    session_id: str
    backend: str


@dataclass(frozen=True, slots=True)
class RuntimeOverloaded:
    session_id: str
    seq: int
    dropped_audio_ms: int


@dataclass(frozen=True, slots=True)
class AsrError:
    session_id: str
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class SessionStopped:
    session_id: str
    seq: int


ServerMessage = (
    SessionReady | AsrSnapshot | SpeechActivity | RuntimeOverloaded | AsrError | SessionStopped
)


def samples_to_ms(samples: int) -> int:
    return samples * 1000 // SAMPLE_RATE


def ms_to_samples(ms: int) -> int:
    return ms * SAMPLE_RATE // 1000


# -- encoding ---------------------------------------------------------------------------


def encode_audio_frame(frame: AudioFrame) -> bytes:
    if frame.start_sample < 0 or len(frame.pcm) % 2:
        raise ProtocolError("audio frame must have a non-negative start and whole samples")
    data = _HEADER.pack(frame.start_sample) + frame.pcm
    if len(data) > MAX_AUDIO_FRAME_BYTES:
        raise ProtocolError("audio frame exceeds the size limit")
    return data


def decode_audio_frame(data: bytes) -> AudioFrame:
    if len(data) < _HEADER.size or len(data) > MAX_AUDIO_FRAME_BYTES:
        raise ProtocolError("audio frame has an invalid size")
    if (len(data) - _HEADER.size) % 2:
        raise ProtocolError("audio frame must contain whole samples")
    (start,) = _HEADER.unpack_from(data)
    return AudioFrame(start_sample=start, pcm=bytes(data[_HEADER.size :]))


def encode_client(message: ClientMessage) -> str:
    if isinstance(message, SessionStart):
        return _dump(
            {
                "type": "session.start",
                "protocol": PROTOCOL,
                "session_id": message.session_id,
                "sample_rate": SAMPLE_RATE,
                "channels": CHANNELS,
                "encoding": ENCODING,
                "language": message.language,
            }
        )
    if isinstance(message, AudioGap):
        return _dump(
            {
                "type": "audio.gap",
                "session_id": message.session_id,
                "start_sample": message.start_sample,
                "missing_samples": message.missing_samples,
            }
        )
    return _dump({"type": "session.stop", "session_id": message.session_id})


def encode_server(message: ServerMessage) -> str:
    if isinstance(message, SessionReady):
        return _dump(
            {"type": "session.ready", "session_id": message.session_id, "backend": message.backend}
        )
    if isinstance(message, AsrSnapshot):
        return _dump(
            {
                "type": "transcript.snapshot",
                "session_id": message.session_id,
                "seq": message.seq,
                "window_id": message.window_id,
                "text": message.text,
                "audio_end_ms": message.audio_end_ms,
                "window_final": message.window_final,
            }
        )
    if isinstance(message, SpeechActivity):
        raise ProtocolError("speech activity needs a seq; use encode_activity")
    if isinstance(message, RuntimeOverloaded):
        return _dump(
            {
                "type": "runtime.overloaded",
                "session_id": message.session_id,
                "seq": message.seq,
                "dropped_audio_ms": message.dropped_audio_ms,
            }
        )
    if isinstance(message, AsrError):
        return _dump(
            {
                "type": "error",
                "session_id": message.session_id,
                "code": message.code,
                "message": message.message,
                "retryable": message.retryable,
            }
        )
    return _dump({"type": "session.stopped", "session_id": message.session_id, "seq": message.seq})


def encode_activity(activity: SpeechActivity, seq: int) -> str:
    return _dump(
        {
            "type": "speech.activity",
            "session_id": activity.session_id,
            "seq": seq,
            "audio_end_ms": activity.audio_end_ms,
            "active": activity.active,
            "silence_ms": activity.silence_ms,
        }
    )


# -- parsing ----------------------------------------------------------------------------


def parse_client(raw: str) -> ClientMessage:
    data = _load(raw)
    kind = _str(data, "type")
    session_id = _str(data, "session_id")
    if kind == "session.start":
        _exact(data, {"type", "protocol", "session_id", "sample_rate", "channels", "encoding", "language"})
        if data["protocol"] != PROTOCOL:
            raise ProtocolError("unsupported protocol version")
        if type(data["sample_rate"]) is not int or type(data["channels"]) is not int or (data["sample_rate"], data["channels"], data["encoding"]) != (SAMPLE_RATE, CHANNELS, ENCODING):
            raise ProtocolError("only 16 kHz mono pcm_s16le audio is supported")
        if data["language"] != "ja":
            raise ProtocolError("only Japanese transcription is supported")
        return SessionStart(session_id=session_id, language=_str(data, "language"))
    if kind == "audio.gap":
        _exact(data, {"type", "session_id", "start_sample", "missing_samples"})
        return AudioGap(session_id, _nonneg(data, "start_sample"), _nonneg(data, "missing_samples"))
    if kind == "session.stop":
        _exact(data, {"type", "session_id"})
        return SessionStop(session_id)
    raise ProtocolError(f"unsupported client message: {kind}")


def parse_server(raw: str) -> tuple[int | None, ServerMessage]:
    """Return (seq, message); seq is None for session.ready and error."""
    data = _load(raw)
    kind = _str(data, "type")
    session_id = _str(data, "session_id")
    if kind == "session.ready":
        _exact(data, {"type", "session_id", "backend"})
        return None, SessionReady(session_id, _str(data, "backend"))
    if kind == "transcript.snapshot":
        _exact(data, {"type", "session_id", "seq", "window_id", "text", "audio_end_ms", "window_final"})
        text = data["text"]
        if not isinstance(text, str):
            raise ProtocolError("text must be a string")
        seq = _nonneg(data, "seq")
        return seq, AsrSnapshot(
            session_id=session_id,
            seq=seq,
            window_id=_nonneg(data, "window_id"),
            text=text,
            audio_end_ms=_nonneg(data, "audio_end_ms"),
            window_final=_bool(data, "window_final"),
        )
    if kind == "speech.activity":
        _exact(data, {"type", "session_id", "seq", "audio_end_ms", "active", "silence_ms"})
        return _nonneg(data, "seq"), SpeechActivity(
            session_id,
            _nonneg(data, "audio_end_ms"),
            _bool(data, "active"),
            _nonneg(data, "silence_ms"),
        )
    if kind == "runtime.overloaded":
        _exact(data, {"type", "session_id", "seq", "dropped_audio_ms"})
        seq = _nonneg(data, "seq")
        return seq, RuntimeOverloaded(session_id, seq, _nonneg(data, "dropped_audio_ms"))
    if kind == "error":
        _exact(data, {"type", "session_id", "code", "message", "retryable"})
        return None, AsrError(session_id, _str(data, "code"), _str(data, "message"), _bool(data, "retryable"))
    if kind == "session.stopped":
        _exact(data, {"type", "session_id", "seq"})
        seq = _nonneg(data, "seq")
        return seq, SessionStopped(session_id, seq)
    raise ProtocolError(f"unsupported server message: {kind}")


def _dump(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load(raw: str) -> dict[str, object]:
    if len(raw) > MAX_TEXT_MESSAGE_CHARS:
        raise ProtocolError("message exceeds the size limit")
    try:
        value = cast(object, json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ProtocolError("message is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("message must be a JSON object")
    return cast(dict[str, object], value)


def _str(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"{key} must be a non-empty string")
    return value


def _nonneg(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolError(f"{key} must be a non-negative integer")
    return value


def _bool(data: Mapping[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ProtocolError(f"{key} must be a boolean")
    return value


def _exact(data: Mapping[str, object], expected: set[str]) -> None:
    missing = expected - set(data)
    extra = set(data) - expected
    if missing or extra:
        raise ProtocolError(f"fields mismatch (missing={sorted(missing)}, extra={sorted(extra)})")
