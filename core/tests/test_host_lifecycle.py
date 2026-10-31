from __future__ import annotations

import asyncio
import io
import json

from live_translator.host import Host
from live_translator.models import SourceUpdate


def messages(out: io.BytesIO) -> list[dict]:
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_stop_and_shutdown_keep_reading_translation_results() -> None:
    async def body() -> list[dict]:
        out = io.BytesIO()
        host = Host(out)
        host.executor = "host"
        host.engine.start_session("drain", host.now_ms())
        host.mode = "live"
        host.engine.source_update(SourceUpdate("drain", 1, 1, "こんにちは", True), host.now_ms())
        host._flush_requests()
        request = messages(out)[0]
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        for command in [
            {"type": "session.stop", "command_id": "stop-1"},
            {"type": "translation.result", "request_id": request["request_id"], "session_id": "drain", "source_revision": 1, "content": '{"translated_zh_cn":"你好"}'},
            {"type": "shutdown", "command_id": "exit-1"},
        ]:
            await queue.put(json.dumps(command).encode())
        await asyncio.wait_for(host.run(queue), 2)
        return messages(out)

    output = asyncio.run(body())
    stopped = next(item for item in output if item["type"] == "session.stopped")
    assert stopped["command_id"] == "stop-1"
    last_snapshot = [item for item in output if item["type"] == "snapshot"][-1]
    assert last_snapshot["state"] == "idle" and last_snapshot["current"] is None
    assert last_snapshot["history"][0]["translation"] == "你好"
    assert output[-1]["type"] == "core.exiting"
    assert [item["seq"] for item in output] == list(range(1, len(output) + 1))


def test_command_validation_is_bounded_correlated_and_does_not_echo_secrets() -> None:
    async def body() -> list[dict]:
        out = io.BytesIO()
        host = Host(out)
        await host._dispatch_line(b'{"type":"hello","protocol":"host-core.v1","command_id":"bad","api_key":"private-value"}')
        await host._dispatch_line(b'{"type":"config.update","translation":{"api_key":"private-value"}}')
        await host._dispatch_line(b"x" * (1024 * 1024 + 1))
        await host._dispatch_line(b'{"type":"hello","protocol":"host-core.v1","command_id":"ok"}')
        return messages(out)

    output = asyncio.run(body())
    assert [item["code"] for item in output if item["type"] == "error"] == ["invalid_command"] * 3
    assert output[0]["command_id"] == "bad"
    assert output[-1]["type"] == "command.accepted"
    assert "private-value" not in json.dumps(output)


def test_mismatched_translation_revision_does_not_consume_request() -> None:
    out = io.BytesIO()
    host = Host(out)
    host.executor = "host"
    host.engine.start_session("s", 0)
    host.engine.source_update(SourceUpdate("s", 1, 1, "こんにちは", True), 0)
    host._flush_requests()
    request = messages(out)[0]
    host._translation_result({"type": "translation.result", "request_id": request["request_id"], "session_id": "s", "source_revision": 2, "content": '{"translated_zh_cn":"错误"}'})
    assert host.engine.scheduler.in_flight_count == 1
    host._translation_result({"type": "translation.result", "request_id": request["request_id"], "session_id": "s", "source_revision": 1, "content": '{"translated_zh_cn":"你好"}'})
    assert host.engine.snapshot(0)["history"][0]["translation"] == "你好"


def test_stop_of_already_translated_open_text_needs_no_duplicate_request() -> None:
    from live_translator.engine import SubtitleEngine
    from live_translator.translation import TranslationMode

    engine = SubtitleEngine(mode=TranslationMode.PLAIN)
    engine.start_session("s", 0)
    engine.source_update(SourceUpdate("s", 1, 1, "こんばんは", False), 0)
    request = engine.drain_requests()[0]
    engine.translation_reply(request.request_id, 1, content="晚上好")
    engine.stop_session(2)
    assert engine.state == "idle"
    assert not engine.drain_requests()
    assert engine.snapshot(2)["history"][0]["quality"] == "normal"
