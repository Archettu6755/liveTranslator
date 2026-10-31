from __future__ import annotations

import json
import os
import subprocess
import sys


def test_stdio_host_exits_cleanly_while_parent_still_holds_input_open() -> None:
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", "-u", "-m", "live_translator", "host"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert child.stdin is not None and child.stdout is not None and child.stderr is not None
    try:
        child.stdin.write(b'{"type":"hello","protocol":"host-core.v1","command_id":"hello"}\n')
        child.stdin.write(b'{"type":"shutdown","command_id":"exit"}\n')
        child.stdin.flush()
        child.wait(timeout=8)
        messages = [json.loads(line) for line in child.stdout.read().splitlines()]
        diagnostics = child.stderr.read().decode(errors="replace")
        assert child.returncode == 0, diagnostics
        assert any(message["type"] == "core.ready" for message in messages)
        assert messages[-1]["type"] == "core.exiting"
        assert "Fatal Python error" not in diagnostics
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()
        child.stderr.close()


def test_stdio_host_discards_oversized_lines_and_accepts_the_next_command() -> None:
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", "-u", "-m", "live_translator", "host"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        payload = b"x" * (1024 * 1024 + 100) + b'\n{"type":"hello","protocol":"host-core.v1"}\n{"type":"shutdown"}\n'
        output, diagnostics = child.communicate(payload, timeout=8)
        assert child.returncode == 0, diagnostics.decode(errors="replace")
        messages = [json.loads(line) for line in output.splitlines()]
        assert messages[0]["type"] == "error" and messages[0]["code"] == "invalid_command"
        assert any(message["type"] == "core.ready" for message in messages)
        assert messages[-1]["type"] == "core.exiting"
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


def test_demo_cli_emits_utf8_with_a_legacy_parent_encoding() -> None:
    result = subprocess.run(
        [sys.executable, "-B", "-m", "live_translator", "demo", "--list"],
        env={**os.environ, "PYTHONIOENCODING": "cp1252"}, capture_output=True, timeout=5,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert "字幕" in result.stdout.decode("utf-8") or "语义" in result.stdout.decode("utf-8")
