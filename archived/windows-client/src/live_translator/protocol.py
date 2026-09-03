from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Never, cast

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

MAX_CONTROL_MESSAGE_CHARS = 64 * 1_024


class ProtocolError(ValueError):
    pass


def encode_start_stream(request: StartStream) -> str:
    return _encode(
        {
            "type": "stream.start",
            "session_id": request.session_id,
            "sample_rate": request.sample_rate,
            "channels": request.channels,
            "encoding": request.encoding,
            "language": request.language,
        }
    )


def encode_stop_stream(session_id: str) -> str:
    if not session_id.strip():
        raise ProtocolError("session_id must not be empty")
    return _encode({"type": "stream.stop", "session_id": session_id})


def encode_audio_chunk(chunk: AudioChunk) -> bytes:
    return chunk.pcm_bytes


def parse_event(raw: str) -> AsrEvent:
    if len(raw) > MAX_CONTROL_MESSAGE_CHARS:
        raise ProtocolError("control message exceeds the size limit")
    try:
        decoded = cast(object, json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ProtocolError("control message is not valid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ProtocolError("control message must be a JSON object")
    data = cast(Mapping[str, object], decoded)

    event_type = _required_str(data, "type")
    session_id = _required_str(data, "session_id")

    try:
        if event_type == "stream.ready":
            _require_exact_keys(data, {"type", "session_id"})
            return StreamReady(session_id=session_id)
        if event_type == "transcript.final":
            _require_exact_keys(
                data,
                {
                    "type",
                    "session_id",
                    "seq",
                    "text",
                    "audio_start_ms",
                    "audio_end_ms",
                    "decode_ms",
                },
            )
            return TranscriptFinal(
                session_id=session_id,
                seq=_required_int(data, "seq"),
                text=_required_str(data, "text").strip(),
                audio_start_ms=_required_int(data, "audio_start_ms"),
                audio_end_ms=_required_int(data, "audio_end_ms"),
                decode_ms=_required_int(data, "decode_ms"),
            )
        if event_type == "runtime.overloaded":
            _require_exact_keys(data, {"type", "session_id", "dropped_audio_ms"})
            return RuntimeOverloaded(
                session_id=session_id,
                dropped_audio_ms=_required_int(data, "dropped_audio_ms"),
            )
        if event_type == "stream.stopped":
            _require_exact_keys(data, {"type", "session_id"})
            return StreamStopped(session_id=session_id)
        if event_type == "error":
            _require_exact_keys(
                data,
                {"type", "session_id", "code", "message", "retryable"},
            )
            return AsrError(
                session_id=session_id,
                code=_required_str(data, "code"),
                message=_required_str(data, "message"),
                retryable=_required_bool(data, "retryable"),
            )
    except ValueError as exc:
        raise ProtocolError(str(exc)) from exc

    raise ProtocolError(f"unsupported event type: {event_type}")


def _encode(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _required_str(data: Mapping[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError(f"{key} must be a non-empty string")
    return value


def _required_int(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{key} must be an integer")
    return value


def _required_bool(data: Mapping[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ProtocolError(f"{key} must be a boolean")
    return value


def _require_exact_keys(data: Mapping[str, object], expected: set[str]) -> None:
    unexpected = set(data) - expected
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ProtocolError(f"control message contains unexpected fields: {names}")


def assert_never(value: Never) -> Never:
    raise AssertionError(f"unexpected value: {value!r}")
