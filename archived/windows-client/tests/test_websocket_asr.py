from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from socket import socket
from typing import cast

import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from live_translator.asr import AsrClientConfig, AsrClientError, WebSocketAsrClient
from live_translator.models import (
    CHUNK_BYTES,
    AudioChunk,
    StartStream,
    StreamStopped,
    TranscriptFinal,
)


def make_chunk() -> AudioChunk:
    return AudioChunk(chunk_id=0, pcm_bytes=b"\x00" * CHUNK_BYTES, captured_at_ms=0)


def get_server_port(sockets: Iterable[socket]) -> int:
    address = cast(tuple[str, int], next(iter(sockets)).getsockname())
    return address[1]


async def test_websocket_client_receives_finals_and_filters_stale_events() -> None:
    async def handler(websocket: ServerConnection) -> None:
        start = json.loads(await websocket.recv())
        session_id = start["session_id"]
        await websocket.send(json.dumps({"type": "stream.ready", "session_id": session_id}))
        assert isinstance(await websocket.recv(), bytes)
        await websocket.send(
            json.dumps(
                {
                    "type": "transcript.final",
                    "session_id": "another-session",
                    "seq": 1,
                    "text": "無視",
                    "audio_start_ms": 0,
                    "audio_end_ms": 100,
                    "decode_ms": 1,
                }
            )
        )
        await websocket.send(
            json.dumps(
                {
                    "type": "transcript.final",
                    "session_id": session_id,
                    "seq": 2,
                    "text": "採用",
                    "audio_start_ms": 0,
                    "audio_end_ms": 100,
                    "decode_ms": 1,
                }
            )
        )
        await websocket.send(
            json.dumps(
                {
                    "type": "transcript.final",
                    "session_id": session_id,
                    "seq": 1,
                    "text": "古い",
                    "audio_start_ms": 0,
                    "audio_end_ms": 100,
                    "decode_ms": 1,
                }
            )
        )
        stop = json.loads(await websocket.recv())
        assert stop["type"] == "stream.stop"
        await websocket.send(json.dumps({"type": "stream.stopped", "session_id": session_id}))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = get_server_port(server.sockets)
        client = WebSocketAsrClient(
            AsrClientConfig(
                ws_url=f"ws://127.0.0.1:{port}",
                ready_url=f"http://127.0.0.1:{port}/ready",
            )
        )
        await client.connect()
        await client.start_stream(StartStream(session_id="session"))
        await client.send_audio(make_chunk())
        await client.stop_stream()
        events = [event async for event in client.events()]
        await client.close()

    finals = [event for event in events if isinstance(event, TranscriptFinal)]
    assert [(event.seq, event.text) for event in finals] == [(2, "採用")]


async def test_stop_waits_for_server_acknowledgement() -> None:
    stop_received = False

    async def handler(websocket: ServerConnection) -> None:
        nonlocal stop_received
        start = json.loads(await websocket.recv())
        await websocket.send(
            json.dumps({"type": "stream.ready", "session_id": start["session_id"]})
        )
        stop = json.loads(await websocket.recv())
        stop_received = stop["type"] == "stream.stop"
        await websocket.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = get_server_port(server.sockets)
        client = WebSocketAsrClient(
            AsrClientConfig(
                ws_url=f"ws://127.0.0.1:{port}",
                ready_url=f"http://127.0.0.1:{port}/ready",
                stop_timeout_s=0.05,
            )
        )
        await client.connect()
        await client.start_stream(StartStream(session_id="session"))
        with pytest.raises(AsrClientError, match=r"stream\.stop"):
            await client.stop_stream()
        await client.close()

    assert stop_received


async def test_invalid_server_message_becomes_a_stable_error() -> None:
    async def handler(websocket: ServerConnection) -> None:
        start = json.loads(await websocket.recv())
        await websocket.send(
            json.dumps({"type": "stream.ready", "session_id": start["session_id"]})
        )
        await websocket.send('{"type":"transcript.partial","session_id":"session"}')
        await websocket.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = get_server_port(server.sockets)
        client = WebSocketAsrClient(
            AsrClientConfig(
                ws_url=f"ws://127.0.0.1:{port}",
                ready_url=f"http://127.0.0.1:{port}/ready",
            )
        )
        await client.connect()
        await client.start_stream(StartStream(session_id="session"))
        events = [event async for event in client.events()]
        await client.close()

    assert any(getattr(event, "code", "") == "invalid_server_message" for event in events)


async def test_close_cancels_a_receiver_blocked_by_a_full_event_queue() -> None:
    async def handler(websocket: ServerConnection) -> None:
        start = json.loads(await websocket.recv())
        session_id = start["session_id"]
        await websocket.send(json.dumps({"type": "stream.ready", "session_id": session_id}))
        try:
            for seq in range(1, 100):
                await websocket.send(
                    json.dumps(
                        {
                            "type": "transcript.final",
                            "session_id": session_id,
                            "seq": seq,
                            "text": f"字幕 {seq}",
                            "audio_start_ms": seq * 100,
                            "audio_end_ms": (seq + 1) * 100,
                            "decode_ms": 1,
                        }
                    )
                )
        except ConnectionClosed:
            return
        await websocket.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = get_server_port(server.sockets)
        client = WebSocketAsrClient(
            AsrClientConfig(
                ws_url=f"ws://127.0.0.1:{port}",
                ready_url=f"http://127.0.0.1:{port}/ready",
            )
        )
        await client.connect()
        await client.start_stream(StartStream(session_id="session"))
        await asyncio.sleep(0.05)

        await asyncio.wait_for(client.close(), timeout=1.0)
        drained = [event async for event in client.events()]

    assert len(drained) <= 64


async def test_full_event_queue_does_not_block_stream_stopped_acknowledgement() -> None:
    async def handler(websocket: ServerConnection) -> None:
        start = json.loads(await websocket.recv())
        session_id = start["session_id"]
        await websocket.send(json.dumps({"type": "stream.ready", "session_id": session_id}))
        for seq in range(1, 100):
            await websocket.send(
                json.dumps(
                    {
                        "type": "transcript.final",
                        "session_id": session_id,
                        "seq": seq,
                        "text": f"字幕 {seq}",
                        "audio_start_ms": seq * 100,
                        "audio_end_ms": (seq + 1) * 100,
                        "decode_ms": 1,
                    }
                )
            )
        stop = json.loads(await websocket.recv())
        assert stop["type"] == "stream.stop"
        await websocket.send(json.dumps({"type": "stream.stopped", "session_id": session_id}))

    async with serve(handler, "127.0.0.1", 0) as server:
        port = get_server_port(server.sockets)
        client = WebSocketAsrClient(
            AsrClientConfig(
                ws_url=f"ws://127.0.0.1:{port}",
                ready_url=f"http://127.0.0.1:{port}/ready",
                stop_timeout_s=1.0,
            )
        )
        await client.connect()
        await client.start_stream(StartStream(session_id="session"))
        await asyncio.sleep(0.05)

        await asyncio.wait_for(client.stop_stream(), timeout=1.0)
        events = [event async for event in client.events()]
        await client.close()

    assert isinstance(events[-1], StreamStopped)
    assert any(getattr(event, "code", "") == "client_event_queue_overflow" for event in events)
