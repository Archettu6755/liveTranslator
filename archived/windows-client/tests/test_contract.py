from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from live_translator.models import StartStream
from live_translator.protocol import (
    ProtocolError,
    encode_start_stream,
    encode_stop_stream,
    parse_event,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "contracts" / "asr-v1.schema.json"
EXAMPLES_PATH = REPOSITORY_ROOT / "contracts" / "asr-v1.examples.json"


def load_json_object(path: Path) -> dict[str, object]:
    decoded = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(decoded, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return cast(dict[str, object], decoded)


def load_examples() -> list[dict[str, object]]:
    decoded = cast(object, json.loads(EXAMPLES_PATH.read_text(encoding="utf-8")))
    if not isinstance(decoded, list):
        raise TypeError("ASR contract examples must be a JSON array")
    examples: list[dict[str, object]] = []
    for raw_example in cast(list[object], decoded):
        if not isinstance(raw_example, dict):
            raise TypeError("Each ASR contract example must be a JSON object")
        examples.append(cast(dict[str, object], raw_example))
    return examples


def payload_of(example: Mapping[str, object]) -> dict[str, object]:
    payload = example.get("payload")
    if not isinstance(payload, dict):
        raise TypeError("ASR contract example payload must be a JSON object")
    return cast(dict[str, object], payload)


def validate_json(
    validator: Draft202012Validator,
    payload: Mapping[str, object],
) -> None:
    validator.validate(payload)  # pyright: ignore[reportUnknownMemberType]


def test_shared_asr_examples_match_the_json_schema() -> None:
    schema = load_json_object(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    for example in load_examples():
        validate_json(validator, payload_of(example))


def test_client_control_messages_match_shared_examples() -> None:
    payloads = {
        str(example["name"]): payload_of(example)
        for example in load_examples()
        if example.get("direction") == "client-to-server"
    }
    request = StartStream(session_id="contract-session")

    assert json.loads(encode_start_stream(request)) == payloads["start"]
    assert json.loads(encode_stop_stream(request.session_id)) == payloads["stop"]


def test_client_parser_accepts_every_shared_server_example() -> None:
    server_payloads = [
        payload_of(example)
        for example in load_examples()
        if example.get("direction") == "server-to-client"
    ]

    events = [parse_event(json.dumps(payload, ensure_ascii=False)) for payload in server_payloads]

    assert [event.type for event in events] == [
        "stream.ready",
        "transcript.final",
        "runtime.overloaded",
        "stream.stopped",
        "error",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "stream.ready", "session_id": "   "},
        {"type": "stream.ready", "session_id": "session", "extra": True},
    ],
)
def test_schema_and_client_reject_the_same_invalid_server_messages(
    payload: dict[str, object],
) -> None:
    validator = Draft202012Validator(load_json_object(SCHEMA_PATH))

    with pytest.raises(ValidationError):
        validate_json(validator, payload)
    with pytest.raises(ProtocolError):
        parse_event(json.dumps(payload))
