from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest

from live_translator.asr_protocol import ProtocolError, encode_activity, encode_client, encode_server, parse_client, parse_server
from live_translator.host import Host
from live_translator.host_protocol import FIELDS, validate_command
from live_translator.models import SpeechActivity

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


def matches(value, spec, root):
    """Check fixture values against the JSON Schema keywords used by these contracts."""
    if "$ref" in spec:
        return matches(value, root["$defs"][spec["$ref"].split("/")[-1]], root)
    if "const" in spec:
        if value != spec["const"] or isinstance(value, bool) != isinstance(spec["const"], bool):
            return False
    if "enum" in spec and value not in spec["enum"]:
        return False
    if "oneOf" in spec and sum(matches(value, child, root) for child in spec["oneOf"]) != 1:
        return False
    if "anyOf" in spec and not any(matches(value, child, root) for child in spec["anyOf"]):
        return False
    if "not" in spec and matches(value, spec["not"], root):
        return False
    types = spec.get("type", [])
    types = [types] if isinstance(types, str) else types
    checks = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "integer": type(value) is int, "number": type(value) in (int, float), "boolean": type(value) is bool, "null": value is None}
    if types and not any(checks[kind] for kind in types):
        return False
    if isinstance(value, dict):
        if set(spec.get("required", [])) - value.keys() or len(value) > spec.get("maxProperties", 10**9):
            return False
        properties = spec.get("properties", {})
        additional = spec.get("additionalProperties", True)
        for key, item in value.items():
            if "propertyNames" in spec and not matches(key, spec["propertyNames"], root):
                return False
            if key in properties:
                if not matches(item, properties[key], root):
                    return False
            elif additional is False or isinstance(additional, dict) and not matches(item, additional, root):
                return False
    if isinstance(value, list):
        if not spec.get("minItems", 0) <= len(value) <= spec.get("maxItems", 10**9):
            return False
        if "items" in spec and not all(matches(item, spec["items"], root) for item in value):
            return False
    if isinstance(value, str) and not spec.get("minLength", 0) <= len(value) <= spec.get("maxLength", 10**9):
        return False
    if type(value) in (int, float) and value < spec.get("minimum", float("-inf")):
        return False
    return True


def test_asr_fixtures_match_schema_and_actual_codecs() -> None:
    schema = json.loads((CONTRACTS / "asr-v1.schema.json").read_text(encoding="utf-8"))
    for example in json.loads((CONTRACTS / "asr-v1.examples.json").read_text(encoding="utf-8")):
        message = example["message"]
        assert matches(message, schema, schema), message["type"]
        parser = parse_client if example["direction"] == "client" else parse_server
        parsed = parser(json.dumps(message, ensure_ascii=False))
        if example["direction"] == "client":
            encoded = encode_client(parsed)
        else:
            seq, model = parsed
            encoded = encode_activity(model, seq) if isinstance(model, SpeechActivity) else encode_server(model)
        assert json.loads(encoded) == message
        with pytest.raises(ProtocolError):
            parser(json.dumps({**message, "unknown": True}))


def test_host_fixtures_and_live_output_match_schema() -> None:
    schema = json.loads((CONTRACTS / "host-core-v1.schema.json").read_text(encoding="utf-8"))
    kinds = {key.removeprefix("command.") for key in schema["$defs"] if key.startswith("command.")}
    assert kinds == set(FIELDS)
    for example in json.loads((CONTRACTS / "host-core-v1.examples.json").read_text(encoding="utf-8")):
        assert matches(example["message"], schema, schema), example["message"]["type"]
        if example["direction"] == "host":
            validate_command(example["message"])

    async def body():
        out = io.BytesIO()
        host = Host(out)
        for command in [{"type": "hello", "protocol": "host-core.v1", "command_id": "hello-1"}, {"type": "config.update", "command_id": "config-1"}, {"type": "invalid", "command_id": "bad"}]:
            await host._dispatch_line(json.dumps(command).encode())
        host._emit_snapshot(force=True)
        return [json.loads(line) for line in out.getvalue().splitlines()]

    for message in asyncio.run(body()):
        assert matches(message, schema, schema), message


def test_asr_rejects_boolean_audio_format_and_non_japanese_language() -> None:
    example = json.loads((CONTRACTS / "asr-v1.examples.json").read_text(encoding="utf-8"))[0]["message"]
    for change in ({"channels": True}, {"language": "en"}):
        with pytest.raises(ProtocolError):
            parse_client(json.dumps({**example, **change}))
