from __future__ import annotations

import json

import pytest

from live_translator.models import (
    AsrError,
    RuntimeOverloaded,
    StartStream,
    StreamReady,
    StreamStopped,
    TranscriptFinal,
)
from live_translator.protocol import (
    ProtocolError,
    encode_start_stream,
    encode_stop_stream,
    parse_event,
)


def test_start_message_matches_contract() -> None:
    encoded = encode_start_stream(StartStream(session_id="s-1"))

    assert json.loads(encoded) == {
        "type": "stream.start",
        "session_id": "s-1",
        "sample_rate": 16_000,
        "channels": 1,
        "encoding": "pcm_s16le",
        "language": "ja",
    }


def test_stop_message_matches_contract() -> None:
    assert json.loads(encode_stop_stream("s-1")) == {
        "type": "stream.stop",
        "session_id": "s-1",
    }


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {"type": "stream.ready", "session_id": "s-1"},
            StreamReady(session_id="s-1"),
        ),
        (
            {
                "type": "transcript.final",
                "session_id": "s-1",
                "seq": 1,
                "text": " こんにちは ",
                "audio_start_ms": 100,
                "audio_end_ms": 800,
                "decode_ms": 42,
            },
            TranscriptFinal(
                session_id="s-1",
                seq=1,
                text="こんにちは",
                audio_start_ms=100,
                audio_end_ms=800,
                decode_ms=42,
            ),
        ),
        (
            {
                "type": "runtime.overloaded",
                "session_id": "s-1",
                "dropped_audio_ms": 300,
            },
            RuntimeOverloaded(session_id="s-1", dropped_audio_ms=300),
        ),
        (
            {"type": "stream.stopped", "session_id": "s-1"},
            StreamStopped(session_id="s-1"),
        ),
        (
            {
                "type": "error",
                "session_id": "s-1",
                "code": "runtime_unavailable",
                "message": "ASR is unavailable.",
                "retryable": True,
            },
            AsrError(
                session_id="s-1",
                code="runtime_unavailable",
                message="ASR is unavailable.",
                retryable=True,
            ),
        ),
    ],
)
def test_parse_supported_events(payload: dict[str, object], expected: object) -> None:
    assert parse_event(json.dumps(payload, ensure_ascii=False)) == expected


def test_partial_is_not_part_of_the_protocol() -> None:
    payload = json.dumps(
        {
            "type": "transcript.partial",
            "session_id": "s-1",
            "seq": 1,
            "text": "partial",
        }
    )

    with pytest.raises(ProtocolError, match="unsupported event type"):
        parse_event(payload)


@pytest.mark.parametrize(
    "payload",
    [
        "[]",
        "{",
        '{"type":"stream.ready","session_id":""}',
        '{"type":"transcript.final","session_id":"s","seq":true,"text":"x","audio_start_ms":0,"audio_end_ms":1,"decode_ms":1}',
        '{"type":"transcript.final","session_id":"s","seq":1,"text":"","audio_start_ms":0,"audio_end_ms":1,"decode_ms":1}',
        '{"type":"error","session_id":"s","code":"x","message":"x","retryable":"yes"}',
    ],
)
def test_invalid_control_messages_are_rejected(payload: str) -> None:
    with pytest.raises(ProtocolError):
        parse_event(payload)
