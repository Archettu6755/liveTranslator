"""Deterministic offline translator used by demos and tests.

It answers TranslationRequest objects with the same raw content shape a real provider would
return, so replies travel the real parsing/version path. Preset Chinese is for UI and state
checks only and says nothing about translation quality (PRODUCT_DISCUSSION.md section 17).
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from .models import TranslationRequest
from .translation import TranslationMode, derive_display

DEMO_PHRASES: dict[str, str] = {
    "みなさんこんばんは": "大家晚上好",
    "今日は": "今天",
    "ゲームをやります": "要玩游戏",
    "雑談をします": "来闲聊",
    "昨日": "昨天",
    "コンビニに行ったら": "去便利店的时候",
    "推しのグッズがありました": "看到了推的周边",
    "なかったです": "没有",
    "ありました": "有",
    "でも": "不过",
    "買わなかった": "没有买",
    "買った": "买了",
    "スパチャありがとう": "谢谢醒目留言",
    "ございます": "",
    "本当に": "真的",
    "嬉しい": "很开心",
    "ちょっと待って": "等一下",
    "えっと": "那个……",
    "マイクの調子が": "麦克风的状态",
    "おかしいかも": "可能有点奇怪",
    "じゃあ": "那么",
    "始めましょう": "开始吧",
    "次は": "接下来",
    "歌を歌います": "唱歌",
    "笑": "（笑）",
    "わはは": "哇哈哈",
}


def mock_translate_text(source: str, phrases: Mapping[str, str] = DEMO_PHRASES) -> str:
    """Greedy phrase substitution; unknown text is kept in brackets so it is obviously fake."""
    out: list[str] = []
    index = 0
    unknown: list[str] = []
    keys = sorted(phrases, key=len, reverse=True)
    while index < len(source):
        for key in keys:
            if source.startswith(key, index):
                if unknown:
                    out.append(f"〔{''.join(unknown)}〕")
                    unknown.clear()
                out.append(phrases[key])
                index += len(key)
                break
        else:
            char = source[index]
            if char in "。！？!?、，,…":
                if unknown:
                    out.append(f"〔{''.join(unknown)}〕")
                    unknown.clear()
                out.append({"、": "，", ",": "，", "!": "！", "?": "？"}.get(char, char))
            elif not char.isspace():
                unknown.append(char)
            index += 1
    if unknown:
        out.append(f"〔{''.join(unknown)}〕")
    return "".join(out) or "〔模拟〕"


def mock_reply(
    request: TranslationRequest,
    *,
    mode: TranslationMode = TranslationMode.STRUCTURED,
    overrides: Mapping[str, str] | None = None,
    locked_correction: Mapping[str, str] | None = None,
) -> str:
    """Build provider-shaped raw content for a request."""
    translated = (overrides or {}).get(request.source_text) or mock_translate_text(
        request.source_text
    )
    if mode is TranslationMode.PLAIN:
        return translated
    payload = {
        "corrected_ja": request.source_text,
        "translated_zh_cn": translated,
        "display_zh_cn": derive_display(translated, request.locked_texts),
        "corrections": [],
        "uncertain_spans": [],
        "locked_correction": dict(locked_correction) if locked_correction else None,
    }
    return json.dumps(payload, ensure_ascii=False)
