from __future__ import annotations

from live_translator.engine import SubtitleEngine
from live_translator.models import SourceUpdate
from live_translator.translation import TranslationMode


def test_long_session_keeps_bounded_history_and_rejects_ancient_replays() -> None:
    engine = SubtitleEngine(mode=TranslationMode.PLAIN)
    engine.start_session("long", 0)
    for number in range(1, 1001):
        engine.source_update(SourceUpdate("long", number, 1, f"日文{number}", True), number * 2000)
        request = engine.drain_requests()[0]
        engine.translation_reply(request.request_id, number * 2000 + 1, content=f"中文{number}")
    assert len(engine.snapshot(2_000_000)["history"]) == 50
    assert len(engine.board._ended) <= engine.config.display.correction_window_cues + 2
    assert not engine._segments
    engine.source_update(SourceUpdate("long", 1, 2, "迟到旧段", True), 2_000_001)
    assert not engine.drain_requests()


def test_stopped_history_is_available_until_a_new_session_starts() -> None:
    engine = SubtitleEngine(mode=TranslationMode.PLAIN)
    engine.start_session("first", 0)
    engine.source_update(SourceUpdate("first", 1, 1, "こんばんは", True), 0)
    request = engine.drain_requests()[0]
    engine.translation_reply(request.request_id, 1, content="晚上好")
    engine.stop_session(2)
    assert len(engine.snapshot(2)["history"]) == 1
    engine.start_session("second", 3)
    assert engine.snapshot(3)["history"] == []
    engine.source_update(SourceUpdate("first", 2, 1, "旧会话", True), 4)
    assert not engine.drain_requests()
