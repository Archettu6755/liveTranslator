"""Deterministic demo scenarios that drive the real engine path (PRODUCT_DISCUSSION.md U6).

No audio device, ASR model or network is used. Translation replies come from the offline mock
after a simulated latency, through the same parser and version checks as real replies. Preset
Chinese is for experiencing the display behavior only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .engine import SubtitleEngine
from .mock_translation import mock_reply
from .models import AsrSnapshot, CaptureGap, SourceUpdate, SpeechActivity, TranslationRequest
from .source_organizer import StableSourceOrganizer


@dataclass(frozen=True, slots=True)
class Step:
    at_ms: int
    kind: str  # "source" | "asr" | "silence" | "speech" | "gap"
    segment_id: int = 0
    revision: int = 0
    text: str = ""
    closed: bool = False
    window: int = 1
    final: bool = False
    silence_ms: int = 0


@dataclass(frozen=True, slots=True)
class TranslationPolicy:
    latency_ms: int = 600
    per_request_latency: dict[int, int] = field(default_factory=dict)  # by send order (1-based)
    never_reply: frozenset[int] = frozenset()
    fail: frozenset[int] = frozenset()
    overrides: dict[str, str] = field(default_factory=dict)
    locked_corrections: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    title: str
    description: str
    steps: tuple[Step, ...]
    policy: TranslationPolicy = TranslationPolicy()
    tail_ms: int = 9_000


def _asr_typing(text: str, start_ms: int, window: int, cps: float = 8.0, final: bool = True) -> list[Step]:
    steps = []
    step_ms = int(1000 / cps)
    at = start_ms
    for end in range(1, len(text) + 1):
        steps.append(Step(at, "speech"))
        steps.append(Step(at, "asr", text=text[:end], window=window))
        at += step_ms
    steps.append(Step(at, "asr", text=text, window=window))
    if final:
        steps.append(Step(at + 100, "asr", text=text, window=window, final=True))
    return steps


def _silence(at: int, total: int) -> list[Step]:
    return [Step(at + t, "silence", silence_ms=t) for t in range(100, total + 1, 100)]


SCENARIOS: dict[str, Scenario] = {}


def _register(s: Scenario) -> None:
    SCENARIOS[s.name] = s


_register(Scenario(
    "basic", "语义短句先译与当前条修订",
    "A 先出初译，A+B 原位修订当前条，段落关闭后定稿；下一段把前一条推为弱化。",
    (
        Step(0, "source", 1, 1, "みなさんこんばんは"),
        Step(1200, "source", 1, 2, "みなさんこんばんは。今日は雑談をします", closed=True),
        Step(3500, "source", 2, 1, "昨日コンビニに行ったら"),
        Step(5000, "source", 2, 2, "昨日コンビニに行ったら、推しのグッズがありました", closed=True),
    ),
))

_register(Scenario(
    "late-negation", "句尾否定晚到与独立更正",
    "否定在下一段才出现：已锁定的“买了”不被偷改，而是追加关联的“更正”条，且只出现一次。",
    (
        Step(0, "source", 1, 1, "推しのグッズを買った", closed=True),
        Step(2500, "source", 2, 1, "でも買わなかった"),
        Step(4000, "source", 2, 2, "でも買わなかった。", closed=True),
    ),
    TranslationPolicy(
        overrides={"推しのグッズを買った": "买了推的周边"},
        locked_corrections={
            "でも買わなかった": {"target_text": "买了推的周边", "corrected_text": "上一句应为：其实没有买", "category": "negation"},
            "でも買わなかった。": {"target_text": "买了推的周边", "corrected_text": "上一句应为：其实没有买", "category": "negation"},
        },
    ),
))

_register(Scenario(
    "out-of-order", "重复快照与乱序返回",
    "同一快照重复到达不重复请求；待处理槽只保留最新版本；旧版本晚到不回退显示。",
    (
        Step(0, "source", 1, 1, "スパチャ"),
        Step(100, "source", 1, 1, "スパチャ"),
        Step(200, "source", 1, 2, "スパチャありがとう"),
        Step(300, "source", 1, 3, "スパチャありがとうございます"),
        Step(2600, "source", 1, 4, "スパチャありがとうございます。本当に嬉しい", closed=True),
    ),
    TranslationPolicy(per_request_latency={1: 2000, 2: 400}),
))

_register(Scenario(
    "overload", "积压时主字幕跟上直播",
    "翻译很慢且连续来多段：合并未发送的修订，超预算时跳过最旧未发送段并在历史标记“翻译跳过”。",
    tuple(
        Step(i * 300, "source", i + 1, 1, text, closed=True)
        for i, text in enumerate(["今日は", "雑談をします", "ちょっと待って", "えっと", "マイクの調子が", "おかしいかも", "じゃあ", "始めましょう"])
    ),
    TranslationPolicy(latency_ms=2500),
))

_register(Scenario(
    "failure", "翻译超时与失败",
    "第一段首个请求无响应→超时后重试成功；第二段返回无效结构→重试仍无响应→标记翻译失败；后续不被阻塞。",
    (
        Step(0, "source", 1, 1, "えっと", closed=True),
        Step(500, "source", 2, 1, "じゃあ始めましょう", closed=True),
    ),
    TranslationPolicy(never_reply=frozenset({1, 3}), fail=frozenset({2})),
    tail_ms=20_000,
))

_register(Scenario(
    "long-text", "长译文拆条不截断",
    "一段很长的译文拆成多个短条按条展示，不缩字、不截断，完整内容可在历史查看。",
    (
        Step(0, "source", 1, 1, "長い話", closed=True),
    ),
    TranslationPolicy(overrides={"長い話": "今天想跟大家聊一聊昨天发生的事情。我去了便利店，结果看到了推的周边，犹豫了很久要不要买，最后还是决定先忍一忍，等下次活动再说吧。"}),
))

_register(Scenario(
    "incomplete-source", "采集缺口与来源不完整标记",
    "模拟 ASR 文本经真实 StableSourceOrganizer 组织；中途出现采集缺口，当前条标题显示“原文不完整”。",
    tuple(
        _asr_typing("本当に嬉しい。", 0, 1)
        + [Step(1300, "gap", silence_ms=300)]
        + _asr_typing("スパチャありがとう。", 1500, 2)
        + _silence(3000, 1000)
    ),
))

_register(Scenario(
    "organizer", "流式 ASR 快照到语义片段",
    "逐字增长的 ASR 快照经稳定前缀、句末确认和停顿规则切成语义片段，再进入翻译与显示。",
    tuple(
        _asr_typing("みなさんこんばんは。今日は雑談をします。", 0, 1, final=False)
        + _silence(2700, 1000)
        + _asr_typing("ちょっと待って、マイクの調子がおかしいかも。", 3800, 2)
        + _silence(6800, 1200)
    ),
))


@dataclass(slots=True)
class _PendingReply:
    due_ms: int
    request: TranslationRequest
    order: int


class DemoRunner:
    """Feeds one scenario into an engine. Call ``advance(now_ms)`` with a monotonic clock."""

    def __init__(self, scenario: Scenario, engine: SubtitleEngine, session_id: str, start_ms: int) -> None:
        self.scenario = scenario
        self.engine = engine
        self.session_id = session_id
        self.start_ms = start_ms
        self._steps = sorted(scenario.steps, key=lambda s: s.at_ms)
        self._index = 0
        self._replies: list[_PendingReply] = []
        self._sent = 0
        self._organizer: StableSourceOrganizer | None = None
        self._seq = 0
        self.on_request: Callable[[TranslationRequest], None] | None = None

    @property
    def end_ms(self) -> int:
        last = self._steps[-1].at_ms if self._steps else 0
        return self.start_ms + last + self.scenario.tail_ms

    def done(self, now_ms: int) -> bool:
        return self._index >= len(self._steps) and (
            now_ms >= self.end_ms or (not self._replies and self.engine.scheduler.idle() and now_ms >= self.end_ms - self.scenario.tail_ms + 4000)
        )

    def advance(self, now_ms: int) -> None:
        rel = now_ms - self.start_ms
        while self._index < len(self._steps) and self._steps[self._index].at_ms <= rel:
            self._apply(self._steps[self._index], now_ms)
            self._index += 1
        self._collect(now_ms)
        for reply in sorted((r for r in self._replies if r.due_ms <= now_ms), key=lambda r: r.due_ms):
            self._replies.remove(reply)
            self._answer(reply, now_ms)
        self.engine.tick(now_ms)
        self._collect(now_ms)

    def finish(self, now_ms: int) -> None:
        self._index = len(self._steps)
        if self._organizer is not None:
            for update in self._organizer.stop():
                self.engine.source_update(update, now_ms)
        self._collect(now_ms)

    def _apply(self, step: Step, now_ms: int) -> None:
        if step.kind == "source":
            self.engine.source_update(
                SourceUpdate(self.session_id, step.segment_id, step.revision, step.text, step.closed),
                now_ms,
            )
            return
        organizer = self._organizer or StableSourceOrganizer(self.session_id)
        self._organizer = organizer
        audio_ms = step.at_ms
        if step.kind == "asr":
            self._seq += 1
            updates = organizer.push_snapshot(
                AsrSnapshot(self.session_id, self._seq, step.window, step.text, audio_ms, step.final)
            )
        elif step.kind == "speech":
            updates = organizer.push_activity(SpeechActivity(self.session_id, audio_ms, True, 0))
        elif step.kind == "silence":
            updates = organizer.push_activity(SpeechActivity(self.session_id, audio_ms, False, step.silence_ms))
        else:
            updates = organizer.push_gap(CaptureGap(self.session_id, audio_ms, step.silence_ms))
        for update in updates:
            self.engine.source_update(update, now_ms)

    def _collect(self, now_ms: int) -> None:
        policy = self.scenario.policy
        for request in self.engine.drain_requests():
            self._sent += 1
            if self.on_request is not None:
                self.on_request(request)
            if self._sent in policy.never_reply:
                continue
            latency = policy.per_request_latency.get(self._sent, policy.latency_ms)
            self._replies.append(_PendingReply(now_ms + latency, request, self._sent))

    def _answer(self, reply: _PendingReply, now_ms: int) -> None:
        policy = self.scenario.policy
        if reply.order in policy.fail:
            self.engine.translation_reply(reply.request.request_id, now_ms, content="{not json")
            return
        content = mock_reply(
            reply.request,
            mode=self.engine.mode,
            overrides=policy.overrides,
            locked_correction=policy.locked_corrections.get(reply.request.source_text),
        )
        self.engine.translation_reply(reply.request.request_id, now_ms, content=content)


def run_headless(name: str, step_ms: int = 50) -> dict[str, object]:
    """Run a scenario on a virtual clock and return the final engine snapshot."""
    scenario = SCENARIOS[name]
    engine = SubtitleEngine()
    engine.start_session(f"demo-{name}", 0)
    runner = DemoRunner(scenario, engine, f"demo-{name}", 0)
    now = 0
    max_visible: list[str] = []
    while not runner.done(now):
        runner.advance(now)
        snap = engine.snapshot(now)
        current = snap["current"]
        if isinstance(current, dict) and (not max_visible or max_visible[-1] != current["text"]):
            max_visible.append(str(current["text"]))
        now += step_ms
    runner.finish(now)
    engine.stop_session(now)
    for _ in range(400):
        if engine.state == "idle":
            break
        now += step_ms
        runner.advance(now)
    snap = engine.snapshot(now)
    snap["shown_cues"] = max_visible
    return snap
