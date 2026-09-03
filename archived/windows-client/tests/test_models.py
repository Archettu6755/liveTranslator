from __future__ import annotations

import pytest

from live_translator.models import (
    CHUNK_BYTES,
    AudioChunk,
    AudioFormat,
    StartStream,
    SubtitleSegment,
    SubtitleState,
)


def test_fixed_audio_format_is_exactly_one_hundred_ms_pcm16() -> None:
    audio_format = AudioFormat()

    assert audio_format.sample_rate == 16_000
    assert audio_format.channels == 1
    assert audio_format.chunk_ms == 100
    assert audio_format.chunk_bytes == 3_200


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sample_rate", 48_000),
        ("channels", 2),
        ("chunk_ms", 20),
    ],
)
def test_audio_format_rejects_contract_changes(field: str, value: int) -> None:
    values: dict[str, object] = {field: value}

    with pytest.raises(ValueError):
        AudioFormat(**values)  # type: ignore[arg-type]


def test_audio_chunk_requires_exact_frame_size() -> None:
    with pytest.raises(ValueError, match="exactly 3200"):
        AudioChunk(chunk_id=0, pcm_bytes=b"\x00" * (CHUNK_BYTES - 2), captured_at_ms=0)


def test_start_stream_is_fixed_to_japanese() -> None:
    with pytest.raises(ValueError, match="language must be ja"):
        StartStream(session_id="session", language="en")  # type: ignore[arg-type]


def make_subtitle_segment(seq: int) -> SubtitleSegment:
    return SubtitleSegment(
        session_id="session",
        seq=seq,
        source_text=f"字幕 {seq}",
        audio_start_ms=(seq - 1) * 100,
        audio_end_ms=seq * 100,
    )


def test_subtitle_state_exposes_the_latest_of_two_visible_segments() -> None:
    state = SubtitleState(segments=(make_subtitle_segment(1), make_subtitle_segment(2)))

    assert state.source_text == "字幕 2"
    assert state.current_segment is state.segments[-1]


def test_subtitle_state_rejects_more_than_two_visible_segments() -> None:
    with pytest.raises(ValueError, match="at most 2"):
        SubtitleState(
            segments=(
                make_subtitle_segment(1),
                make_subtitle_segment(2),
                make_subtitle_segment(3),
            )
        )
