from __future__ import annotations

import asyncio
import io
import json

import numpy as np
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from live_translator.asr_client import AsrClient, AsrClientConfig, AsrClientError
from live_translator.asr_protocol import (
    AudioFrame,
    ProtocolError,
    SessionStopped,
    decode_audio_frame,
    encode_audio_frame,
    parse_client,
    parse_server,
)
from live_translator.asr_worker import QwenBackend, ScriptedBackend, run_server
from live_translator.audio.framer import FRAME_SAMPLES, Framer
from live_translator.host import Host
from live_translator.models import AsrSnapshot, SourceUpdate, SpeechActivity

TOKEN = "t" * 32


class _ReadyCapture(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.port: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    def flush(self) -> None:
        line = self.getvalue().strip().splitlines()[-1]
        if not self.port.done():
            self.port.set_result(json.loads(line)["port"])


def _tone(ms: int, amplitude: int = 6000) -> np.ndarray:
    t = np.arange(16 * ms) / 16000
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


async def _with_worker(backend, body):  # type: ignore[no-untyped-def]
    ready = _ReadyCapture()
    server = asyncio.create_task(run_server(backend, TOKEN, 0, ready))
    try:
        port = await asyncio.wait_for(ready.port, 5)
        return await body(f"ws://127.0.0.1:{port}/v1/asr")
    finally:
        server.cancel()
        try:
            await asyncio.wait_for(server, 5)
        except (asyncio.CancelledError, TimeoutError):
            pass


def test_protocol_round_trip_and_validation() -> None:
    frame = AudioFrame(1600, b"\x01\x00\x02\x00")
    assert decode_audio_frame(encode_audio_frame(frame)) == frame
    with pytest.raises(ProtocolError):
        parse_client('{"type":"session.start","protocol":"asr.v0","session_id":"a","sample_rate":16000,"channels":1,"encoding":"pcm_s16le","language":"ja"}')
    with pytest.raises(ProtocolError):
        parse_server('{"type":"transcript.snapshot","session_id":"a","seq":1,"window_id":1,"text":"x","audio_end_ms":1,"window_final":false,"extra":1}')


def test_worker_streams_snapshots_activity_and_drained_stop() -> None:
    async def body(url: str) -> list[object]:
        client = AsrClient(AsrClientConfig(url=url, token=TOKEN))
        backend = await client.start("sess")
        assert backend == "scripted"
        audio = np.concatenate([_tone(1500), np.zeros(16 * 1200, dtype=np.int16), _tone(400)])
        for start in range(0, len(audio), FRAME_SAMPLES):
            chunk = audio[start : start + FRAME_SAMPLES]
            await client.send_audio(AudioFrame(start, chunk.astype("<i2").tobytes()))
        await client.stop()
        events = []
        async for event in client.events():
            events.append(event)
        await client.close()
        return events

    events = asyncio.run(_with_worker(ScriptedBackend(), body))
    snaps = [e for e in events if isinstance(e, AsrSnapshot)]
    activity = [e for e in events if isinstance(e, SpeechActivity)]
    assert snaps and snaps[0].text and snaps[0].window_id == 1
    assert any(s.window_final for s in snaps)  # silence closed window 1
    assert any(s.window_id == 2 for s in snaps)  # speech after silence opened window 2
    assert snaps[-1].window_final  # stop drained the tail
    assert any(a.active for a in activity) and any(not a.active and a.silence_ms > 0 for a in activity)
    assert isinstance(events[-1], SessionStopped)
    assert [s.seq for s in snaps] == sorted(s.seq for s in snaps)


def test_worker_rejects_missing_token() -> None:
    async def body(url: str) -> None:
        with pytest.raises(InvalidStatus):
            async with connect(url, additional_headers={"Authorization": "Bearer wrong-token-xxxxxxxx"}):
                pass

    asyncio.run(_with_worker(ScriptedBackend(), body))


def test_unconfigured_model_reports_error_instead_of_fake_text() -> None:
    async def body(url: str) -> str:
        client = AsrClient(AsrClientConfig(url=url, token=TOKEN))
        with pytest.raises(AsrClientError) as info:
            await client.start("sess")
        await client.close()
        return str(info.value)

    message = asyncio.run(_with_worker(QwenBackend(), body))
    assert "model_not_configured" in message


def test_framer_keeps_sample_timeline_and_true_tail() -> None:
    framer = Framer(48_000, 2)
    stereo = np.zeros(48_000 * 2 // 4, dtype=np.int16)  # 250 ms of stereo silence
    frames = framer.push(stereo)
    frames += framer.push(stereo)
    flushed, gap = framer.gap(4_800)  # 100 ms missing at 48 kHz
    frames += flushed
    after = framer.push(stereo)
    tail = framer.finish()
    everything = frames + after + tail
    assert gap is not None and gap.missing_samples == 1600
    starts = [f.start_sample for f in everything]
    assert starts == sorted(starts)
    assert after[0].start_sample >= gap.start_sample + 1600
    assert all(f.samples == FRAME_SAMPLES for f in everything[:-1]) or tail
    assert sum(f.samples for f in everything) == pytest.approx(16_000 * 0.75, abs=200)


def _lines(buf: io.BytesIO) -> list[dict]:
    return [json.loads(line) for line in buf.getvalue().decode().splitlines()]


def test_host_protocol_translate_round_trip() -> None:
    async def body() -> list[dict]:
        out = io.BytesIO()
        host = Host(out)
        await host.handle({"type": "hello", "protocol": "host-core.v1"})
        await host.handle({"type": "config.update", "translation": {"executor": "host", "mode": "structured"}, "glossary": {"ぺこら": "佩克拉"}})
        host.engine.start_session("s", host.now_ms())
        host.mode = "live"
        host.engine.source_update(SourceUpdate("s", 1, 1, "ぺこらです", True), host.now_ms())
        host._flush_requests()
        request = next(m for m in _lines(out) if m["type"] == "translate.request")
        user = json.loads(request["messages"][1]["content"])
        assert user["glossary"] == {"ぺこら": "佩克拉"}
        await host.handle({
            "type": "translation.result",
            "request_id": request["request_id"],
            "content": json.dumps({"translated_zh_cn": "我是佩克拉"}, ensure_ascii=False),
        })
        host._emit_snapshot(force=True)
        return _lines(out)

    lines = asyncio.run(body())
    assert lines[0]["type"] == "core.ready" and lines[0]["scenarios"]
    snap = [m for m in lines if m["type"] == "snapshot"][-1]
    assert snap["history"][0]["translation"] == "我是佩克拉"
    assert "api_key" not in json.dumps(lines)


def test_host_rejects_bad_commands_without_dying() -> None:
    async def body() -> list[dict]:
        out = io.BytesIO()
        host = Host(out)
        await host._dispatch_line(b"not json\n")
        await host._dispatch_line(b'{"type":"session.start","source":{"kind":"application","root_pid":-1},"asr":{}}\n')
        await host._dispatch_line(b'{"type":"translation.result","request_id":"x","content":"a","error":"b"}\n')
        await host._dispatch_line(b'{"type":"session.start","source":{"kind":"application","root_pid":5},"asr":{"url":"ws://example.com/v1/asr","token":"' + b"t" * 32 + b'"}}\n')
        return _lines(out)

    lines = asyncio.run(body())
    assert [m["code"] for m in lines] == ["invalid_command"] * 4


def test_host_demo_runs_to_completion() -> None:
    async def body() -> list[dict]:
        out = io.BytesIO()
        host = Host(out)
        lines: asyncio.Queue[bytes | None] = asyncio.Queue()
        runner = asyncio.create_task(host.run(lines))
        await lines.put(b'{"type":"demo.start","scenario":"basic"}\n')
        for _ in range(300):
            await asyncio.sleep(0.1)
            snaps = [m for m in _lines(out) if m["type"] == "snapshot"]
            if len(snaps) > 3 and snaps[-1]["mode"] == "idle" and snaps[-1]["history"]:
                break
        await lines.put(None)
        await runner
        return _lines(out)

    lines = asyncio.run(body())
    snaps = [m for m in lines if m["type"] == "snapshot"]
    assert any(s["current"] for s in snaps)
    assert snaps[-1]["mode"] == "idle"
    assert [h["quality"] for h in snaps[-1]["history"]] == ["normal", "normal"]
