from __future__ import annotations

import json

import pytest

from live_translator.display import meaningful_change, split_for_cues
from live_translator.translation import (
    TranslationFormatError,
    TranslationMode,
    parse_output,
)


def parse(content: str, source: str = "買わなかった", locked: tuple[str, ...] = (), correctable: tuple[str, ...] = ()):
    return parse_output(
        content,
        mode=TranslationMode.STRUCTURED,
        source_text=source,
        locked_texts=locked,
        correctable_texts=correctable,
    )


def test_structured_output_accepts_code_fence() -> None:
    out = parse('```json\n{"translated_zh_cn": "没买", "display_zh_cn": "没买"}\n```')
    assert out.translated_zh == "没买"


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[]", '{"translated_zh_cn": ""}', '{"translated_zh_cn": 3}'],
)
def test_invalid_structure_is_rejected(content: str) -> None:
    with pytest.raises(TranslationFormatError):
        parse(content)


def test_correction_must_anchor_in_raw_asr() -> None:
    content = json.dumps(
        {
            "translated_zh_cn": "没买",
            "corrections": [
                {"original": "買わなかった", "replacement": "買わなかった", "kind": "replace", "reason": "x"},
                {"original": "存在しない", "replacement": "x", "kind": "replace", "reason": "invented"},
            ],
        },
        ensure_ascii=False,
    )
    out = parse(content)
    assert [c.original for c in out.corrections] == ["買わなかった"]


def test_locked_correction_requires_known_target_and_key_category() -> None:
    base = {"translated_zh_cn": "没买"}
    ok = parse(
        json.dumps({**base, "locked_correction": {"target_text": "买了", "corrected_text": "没买", "category": "negation"}}),
        correctable=("买了周边",),
    )
    assert ok.locked_correction is not None
    style_only = parse(
        json.dumps({**base, "locked_correction": {"target_text": "买了", "corrected_text": "购买了", "category": "style"}}),
        correctable=("买了周边",),
    )
    assert style_only.locked_correction is None
    unknown_target = parse(
        json.dumps({**base, "locked_correction": {"target_text": "卖了", "corrected_text": "没卖", "category": "negation"}}),
        correctable=("买了周边",),
    )
    assert unknown_target.locked_correction is None


def test_display_falls_back_to_unlocked_tail() -> None:
    out = parse('{"translated_zh_cn": "甲乙丙"}', locked=("甲",))
    assert out.display_zh == "乙丙"


def test_plain_mode_returns_text() -> None:
    out = parse_output("没买。", mode=TranslationMode.PLAIN, source_text="x", locked_texts=())
    assert out.translated_zh == "没买。" and out.corrected_ja is None


def test_split_never_truncates_and_respects_budget() -> None:
    text = "这是一句非常非常长而且完全没有任何标点符号的中文字幕需要被拆开显示才能读完" * 2
    cues = split_for_cues(text, 20)
    assert "".join(cues) == text
    assert all(len(c) <= 20 for c in cues)


def test_split_keeps_emoji_zwj_sequences_together() -> None:
    family = "👨‍👩‍👧"
    text = "一" * 18 + family + "二"
    cues = split_for_cues(text, 20)
    assert "".join(cues) == text
    assert any(family in c for c in cues)


def test_meaningful_change_ignores_punctuation() -> None:
    assert not meaningful_change("你好", "你好。")
    assert meaningful_change("有", "没有")
