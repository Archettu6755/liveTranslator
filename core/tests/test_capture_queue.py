from __future__ import annotations

import asyncio
import io
import queue
from types import SimpleNamespace

from live_translator.asr_client import AsrClientConfig
from live_translator.asr_protocol import AudioFrame
from live_translator.audio.framer import Gap
from live_translator.host import Host, LiveSession
from live_translator.models import AsrSnapshot


def test_dropped_queued_frames_and_lost_tail_become_sample_accurate_gaps() -> None:
    async def body():
        host = Host(io.BytesIO())
        session = LiveSession(host, "queue-test", ("application", 1, None, "fixture"), AsrClientConfig("ws://127.0.0.1:8765/v1/asr", "t" * 32))
        output = queue.Queue()
        for item in [
            ("frame", AudioFrame(0, b"\0\0" * 1600)),
            ("frame", AudioFrame(4800, b"\0\0" * 1600)),
            ("gap", Gap(8000, 1600)),
            ("end", 11200),
        ]:
            output.put_nowait(item)
        session.capture = SimpleNamespace(output=output, stats=SimpleNamespace(frames_dropped=5))
        sent, gaps = [], []

        async def send_audio(frame):
            sent.append(frame.start_sample)

        async def send_gap(start, missing):
            gaps.append((start, missing))

        session.client = SimpleNamespace(send_audio=send_audio, send_gap=send_gap)
        host.status.capturing = True
        await session._pump_audio()
        assert sent == [0, 4800]
        assert gaps == [(1600, 3200), (6400, 3200), (9600, 1600)]
        assert host.status.gap_ms == 500 and host.status.frames_dropped == 5
        assert not host.status.capturing
        updates = session.organizer.push_snapshot(AsrSnapshot("queue-test", 1, 1, "こんにちは", 700, True))
        assert updates[-1].source_incomplete

    asyncio.run(body())
