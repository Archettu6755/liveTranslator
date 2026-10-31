from __future__ import annotations

from live_translator.config import OrganizerConfig
from live_translator.models import AsrSnapshot, CaptureGap, SpeechActivity
from live_translator.source_organizer import StableSourceOrganizer


class Feed:
    def __init__(self, **cfg: int) -> None:
        self.org = StableSourceOrganizer("s1", OrganizerConfig(**cfg))
        self.ms = 0
        self.seq = 0
        self.window = 1
        self.updates: list = []

    def text(self, text: str, step: int = 100, final: bool = False) -> list:
        self.ms += step
        self.seq += 1
        out = self.org.push_snapshot(
            AsrSnapshot("s1", self.seq, self.window, text, self.ms, window_final=final)
        )
        self.updates += out
        return out

    def silence(self, silence_ms: int) -> list:
        self.ms += 100
        out = self.org.push_activity(SpeechActivity("s1", self.ms, False, silence_ms))
        self.updates += out
        return out

    def speech(self) -> list:
        self.ms += 100
        out = self.org.push_activity(SpeechActivity("s1", self.ms, True, 0))
        self.updates += out
        return out


def test_sentence_closes_once_following_text_is_stable() -> None:
    f = Feed()
    steps = ["みなさん", "みなさんこんば", "みなさんこんばんは。", "みなさんこんばんは。今日",
             "みなさんこんばんは。今日は雑", "みなさんこんばんは。今日は雑談を"]
    for text in steps:
        f.text(text)
    closed = [u for u in f.updates if u.closed]
    assert [(u.segment_id, u.text) for u in closed] == [(1, "みなさんこんばんは。")]


def test_unagreed_tail_is_never_emitted() -> None:
    f = Feed(short_pause_ms=100, min_new_chars=1)
    f.text("今日はゲーム")
    f.text("今日は雑談")
    f.silence(500)
    assert all(not u.text.endswith("ゲーム") for u in f.updates)


def test_punctuation_waits_for_confirm_window_without_following_text() -> None:
    f = Feed(sentence_confirm_ms=400)
    f.text("始めましょう。")
    f.text("始めましょう。")
    assert not [u for u in f.updates if u.closed]
    f.speech()
    f.speech()
    f.speech()
    f.speech()
    assert [u.text for u in f.updates if u.closed] == ["始めましょう。"]


def test_short_pause_gives_open_opportunity_but_not_on_dangling_particle() -> None:
    f = Feed(short_pause_ms=300, min_new_chars=2)
    f.text("昨日コンビニに")
    f.text("昨日コンビニに")
    f.silence(400)
    assert not f.updates  # ends with に: clause still open
    f.text("昨日コンビニに行ったら")
    f.text("昨日コンビニに行ったら")
    f.silence(400)
    assert [(u.text, u.closed) for u in f.updates] == [("昨日コンビニに行ったら", False)]


def test_long_pause_closes_unpunctuated_segment() -> None:
    f = Feed(long_pause_ms=900)
    f.text("えっと")
    f.text("えっと")
    f.silence(1000)
    assert [(u.text, u.closed) for u in f.updates][-1] == ("えっと", True)


def test_window_final_drains_and_next_window_starts_fresh() -> None:
    f = Feed()
    f.text("じゃあ始め")
    f.text("じゃあ始めましょう", final=True)
    f.window = 2
    f.text("次は")
    f.text("次は歌を歌います", final=True)
    closed = [(u.segment_id, u.text) for u in f.updates if u.closed]
    assert closed == [(1, "じゃあ始めましょう"), (2, "次は歌を歌います")]


def test_window_switch_without_final_still_drains_tail() -> None:
    f = Feed()
    f.text("マイクの調子が")
    f.window = 2
    f.text("おかし")
    assert [(u.text, u.closed) for u in f.updates] == [("マイクの調子が", True)]


def test_capture_gap_marks_segment_incomplete() -> None:
    f = Feed()
    f.text("本当に")
    f.org.push_gap(CaptureGap("s1", 0, 300))
    f.text("本当に嬉しい", final=True)
    last = f.updates[-1]
    assert last.closed and last.source_incomplete and last.source_diagnostic == "capture_gap"


def test_length_cap_without_boundary_marks_incomplete() -> None:
    f = Feed(max_segment_chars=10)
    long = "あ" * 12
    f.text(long)
    f.text(long + "い")
    closed = [u for u in f.updates if u.closed]
    assert closed and closed[0].source_incomplete
    assert closed[0].source_diagnostic == "segment_length_cap"


def test_stop_drains_tentative_tail() -> None:
    f = Feed()
    f.text("ありがとうございま")
    out = f.org.stop()
    assert [(u.text, u.closed) for u in out] == [("ありがとうございま", True)]
    assert f.org.stop() == []


def test_rewrite_of_consumed_text_is_recorded_not_reopened() -> None:
    f = Feed()
    f.text("買った。次")
    f.text("買った。次は")
    f.text("買った。次は歌")
    f.text("買った。次は歌を")
    assert [u.text for u in f.updates if u.closed] == ["買った。"]
    f.text("買わなかった。次は歌を")
    f.text("買わなかった。次は歌を")
    assert f.org.rewrite_conflicts == 1
    assert all(u.segment_id != 1 for u in f.updates[1:])
    assert f.org.stop()[-1].text == "次は歌を"
