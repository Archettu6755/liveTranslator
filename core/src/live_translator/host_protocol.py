"""Validation for the bounded host-core.v1 JSONL command channel."""

from __future__ import annotations

from typing import Any


class CommandError(ValueError):
    pass


FIELDS = {
    "hello": ({"protocol"}, set()),
    "config.update": (set(), {"translation", "glossary"}),
    "sources.list": ({"request_id"}, set()),
    "session.start": ({"source", "asr"}, set()),
    "session.stop": (set(), set()),
    "demo.start": ({"scenario"}, set()),
    "translation.result": ({"request_id"}, {"content", "error", "session_id", "source_revision"}),
    "shutdown": (set(), set()),
}


def validate_command(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise CommandError("command must be an object with a string type")
    kind = value["type"]
    if kind not in FIELDS:
        raise CommandError("unsupported command")
    required, optional = FIELDS[kind]
    if required - value.keys() or value.keys() - required - optional - {"type", "command_id"}:
        raise CommandError("command fields do not match the protocol")
    if "command_id" in value:
        command_id = value["command_id"]
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 80:
            raise CommandError("invalid command_id")
    for field in ("protocol", "request_id", "scenario", "session_id"):
        if field in value and (not isinstance(value[field], str) or not 1 <= len(value[field]) <= 200):
            raise CommandError(f"invalid {field}")
    if "source_revision" in value:
        revision = value["source_revision"]
        if type(revision) is not int or revision < 1:
            raise CommandError("invalid source_revision")
    return value
