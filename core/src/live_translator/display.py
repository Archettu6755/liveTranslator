"""On-screen cue board: previous (dimmed) + current (emphasized) subtitle.

PRODUCT_DISCUSSION.md U1-U4: only the current cue is revised in place; a cue locks when it
leaves the current position or expires; important errors in locked text get a separate
"更正" cue; reading time starts when Chinese appears and punctuation edits do not extend it.
Pixel-accurate paging is the renderer's job; here text is split by meaning and a char budget.
"""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from dataclasses import asdict

from .config import DisplayConfig
from .models import Cue

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?…])")
_SOFT_SPLIT = re.compile(r"(?<=[，、；,;：:])")
_IGNORED_FOR_MEANING = re.compile(r"[\s。、，,.!！?？…~～「」『』（）()\"'：:；;—\-]")


def has_content(text: str) -> bool:
    return bool(_IGNORED_FOR_MEANING.sub("", text))


def meaningful_change(old: str, new: str) -> bool:
    """Punctuation/whitespace-only edits are not meaningful (U4)."""
    return _IGNORED_FOR_MEANING.sub("", old) != _IGNORED_FOR_MEANING.sub("", new)


def _safe_cut(text: str, limit: int) -> int:
    """Cut index <= limit that does not split combining marks, ZWJ sequences or selectors."""
    cut = min(limit, len(text))
    while 0 < cut < len(text):
        nxt, prev = text[cut], text[cut - 1]
        if (
            unicodedata.combining(nxt)
            or nxt in "‍︎️"
            or prev == "‍"
            or 0x1F3FB <= ord(nxt) <= 0x1F3FF
            or 0xE0100 <= ord(nxt) <= 0xE01EF
        ):
            cut -= 1
            continue
        break
    return cut if cut > 0 else min(limit, len(text))


def split_for_cues(text: str, max_chars: int) -> list[str]:
    """Split Chinese text into readable cues without truncating or summarizing (U2 item 5)."""
    text = text.strip()
    if not text:
        return []
    pieces: list[str] = []
    for sentence in (s for s in _SENTENCE_SPLIT.split(text) if s.strip()):
        if len(sentence) <= max_chars:
            pieces.append(sentence)
            continue
        for clause in (c for c in _SOFT_SPLIT.split(sentence) if c):
            while len(clause) > max_chars:
                cut = _safe_cut(clause, max_chars)
                pieces.append(clause[:cut])
                clause = clause[cut:]
            if clause:
                pieces.append(clause)
    cues: list[str] = []
    for piece in pieces:
        if cues and len(cues[-1]) + len(piece) <= max_chars:
            cues[-1] += piece
        else:
            cues.append(piece)
    return [cue.strip() for cue in cues if cue.strip()]


class CueBoard:
    def __init__(self, config: DisplayConfig | None = None) -> None:
        self.config = config or DisplayConfig()
        self._cues: deque[Cue] = deque(maxlen=self.config.correction_window_cues + 2)
        self._next_cue_id = 1
        self._corrections_seen: set[tuple[int, str]] = set()
        self._segment_locked: dict[int, list[str]] = {}
        self._ended: set[int] = set()
        self._pending: deque[Cue] = deque()
        self.version = 0

    # -- queries ------------------------------------------------------------------------

    def locked_texts(self, segment_id: int) -> tuple[str, ...]:
        return tuple(self._segment_locked.get(segment_id, ()))

    def recent_locked_texts(self) -> tuple[str, ...]:
        """Locked subtitles still inside the correction window (U3)."""
        return tuple(c.text for c in self._cues if c.locked and c.kind == "subtitle")

    def visible(self, now_ms: int) -> tuple[Cue | None, Cue | None]:
        live = [c for c in list(self._cues)[-2:] if c.expires_at_ms > now_ms]
        if not live:
            return None, None
        current = live[-1]
        previous = live[0] if len(live) == 2 else None
        return current, previous

    def all_cues(self) -> list[Cue]:
        return list(self._cues)

    # -- updates ------------------------------------------------------------------------

    def apply_segment_display(
        self,
        segment_id: int,
        display_text: str,
        now_ms: int,
        *,
        source_incomplete: bool,
        source_diagnostic: str | None,
    ) -> None:
        """Show the unlocked display text of one segment."""
        chunks = split_for_cues(display_text, self.config.cue_max_chars)
        if not chunks:
            return
        if self._pending and self._pending[0].segment_id != segment_id:
            self._flush_pending(now_ms)  # keep order: older segment text first
        else:
            self._pending.clear()  # unshown chunks are superseded by the newer text
        current = self._cues[-1] if self._cues else None
        if (
            current is not None
            and current.segment_id == segment_id
            and current.kind == "subtitle"
            and not current.locked
        ):
            self._revise(current, chunks[0], now_ms)
            rest = chunks[1:]
        else:
            # A punctuation-only tail is not worth a new cue (U4).
            while chunks and not has_content(chunks[0]):
                chunks = chunks[1:]
            if not chunks:
                return
            self._push(self._new_cue(segment_id, chunks[0], source_incomplete, source_diagnostic), now_ms)
            rest = chunks[1:]
        for chunk in rest:
            self._pending.append(self._new_cue(segment_id, chunk, source_incomplete, source_diagnostic))
        while len(self._pending) > self.config.max_reveal_backlog:
            self._push(self._pending.popleft(), now_ms)

    def update_source_flags(
        self, segment_id: int, source_incomplete: bool, source_diagnostic: str | None
    ) -> None:
        """Metadata refresh: never touches text or reading timers (U5)."""
        changed = False
        for cue in self._cues:
            if cue.segment_id == segment_id and cue.kind == "subtitle":
                if (cue.source_incomplete, cue.source_diagnostic) != (
                    source_incomplete,
                    source_diagnostic,
                ):
                    cue.source_incomplete = source_incomplete
                    cue.source_diagnostic = source_diagnostic
                    changed = True
        if changed:
            self.version += 1

    def lock_segment(self, segment_id: int) -> None:
        for cue in self._cues:
            if cue.segment_id == segment_id:
                self._lock(cue)

    def add_correction(
        self, segment_id: int, target_text: str, corrected_text: str, now_ms: int
    ) -> Cue | None:
        target = next(
            (
                c
                for c in reversed(self._cues)
                if c.kind == "subtitle" and c.locked and target_text in c.text
            ),
            None,
        )
        if target is None:
            return None
        key = (target.cue_id, corrected_text)
        if key in self._corrections_seen:
            return None
        self._corrections_seen.add(key)
        cue = Cue(
            cue_id=0,
            segment_id=segment_id,
            text=f"更正：{corrected_text}",
            kind="correction",
            corrects_cue_id=target.cue_id,
        )
        self._push(cue, now_ms)
        return cue

    def expire(self, now_ms: int) -> None:
        """A cue that left the screen is locked so late results never pop it back (Q3)."""
        for cue in self._cues:
            if cue.expires_at_ms <= now_ms:
                self._lock(cue)
        if self._pending:
            current = self._cues[-1] if self._cues else None
            if current is None or now_ms - current.shown_at_ms >= self.config.cue_min_ms:
                self._push(self._pending.popleft(), now_ms)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def forget_segment(self, segment_id: int) -> None:
        self._segment_locked.pop(segment_id, None)
        self._ended.add(segment_id)
        self._prune_tracking()

    def clear(self) -> None:
        self._cues.clear()
        self._pending.clear()
        self._segment_locked.clear()
        self._ended.clear()
        self.version += 1

    # -- internals ----------------------------------------------------------------------

    def _prune_tracking(self) -> None:
        segment_ids = {cue.segment_id for cue in (*self._cues, *self._pending)}
        cue_ids = {cue.cue_id for cue in self._cues}
        self._ended.intersection_update(segment_ids)
        self._corrections_seen = {key for key in self._corrections_seen if key[0] in cue_ids}

    def _reading_ms(self, text: str) -> int:
        cfg = self.config
        ms = int(len(text) / cfg.reading_chars_per_second * 1000)
        return max(cfg.cue_min_ms, min(cfg.cue_max_ms, ms))

    @staticmethod
    def _new_cue(segment_id: int, text: str, incomplete: bool, diagnostic: str | None) -> Cue:
        return Cue(
            cue_id=0,
            segment_id=segment_id,
            text=text,
            source_incomplete=incomplete,
            source_diagnostic=diagnostic,
        )

    def _flush_pending(self, now_ms: int) -> None:
        while self._pending:
            self._push(self._pending.popleft(), now_ms)

    def _lock(self, cue: Cue) -> None:
        if cue.locked:
            return
        cue.locked = True
        if cue.kind == "subtitle" and cue.segment_id not in self._ended:
            self._segment_locked.setdefault(cue.segment_id, []).append(cue.text)
        self.version += 1

    def _push(self, cue: Cue, now_ms: int) -> None:
        for existing in self._cues:
            self._lock(existing)
        cue.cue_id = self._next_cue_id
        self._next_cue_id += 1
        cue.shown_at_ms = now_ms
        cue.expires_at_ms = now_ms + self._reading_ms(cue.text)
        cue.locked = cue.kind == "correction"
        self._cues.append(cue)
        self._prune_tracking()
        self.version += 1

    def _revise(self, cue: Cue, text: str, now_ms: int) -> None:
        if text == cue.text:
            return
        meaningful = meaningful_change(cue.text, text)
        cue.text = text
        cue.version += 1
        if meaningful:
            cap = cue.shown_at_ms + self.config.cue_max_age_ms
            wanted = now_ms + self._reading_ms(text) + self.config.meaningful_change_bonus_ms
            cue.expires_at_ms = min(cap, max(cue.expires_at_ms, wanted))
        self.version += 1


def cue_to_dict(cue: Cue | None) -> dict[str, object] | None:
    return None if cue is None else asdict(cue)
