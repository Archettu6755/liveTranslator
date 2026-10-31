"""Turns ASR window snapshots into stable, versioned Japanese source segments.

Implements PRODUCT_DISCUSSION.md S1 (stable prefix + mutable tail), G1 (local rules decide
translation opportunities) and T2 (window reset does not silently drop the tail). All times
are on the audio timeline, never wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import OrganizerConfig
from .models import AsrSnapshot, CaptureGap, SourceUpdate, SpeechActivity

SENTENCE_END = frozenset("。！？!?…♪\n")
SOFT_BOUNDARY = frozenset("、，,；;：: 　")
CLOSING_MARKS = frozenset("」』）)】〉》\"'～〜ー")
# Particles that usually leave a clause open. This is a heuristic for *not* translating yet,
# never a proof that a sentence is complete (G1 counter-example rule).
OPEN_ENDINGS = frozenset("はがをにへでともの")


def common_prefix(a: str, b: str) -> str:
    limit = min(len(a), len(b))
    index = 0
    while index < limit and a[index] == b[index]:
        index += 1
    return a[:index]


def _first_sentence_end(text: str) -> int | None:
    """Return the end index (exclusive) of the first sentence, including closing marks."""
    for index, char in enumerate(text):
        if char in SENTENCE_END:
            end = index + 1
            while end < len(text) and (text[end] in SENTENCE_END or text[end] in CLOSING_MARKS):
                end += 1
            return end
    return None


def _last_boundary(text: str) -> int | None:
    for index in range(len(text) - 1, -1, -1):
        if text[index] in SENTENCE_END or text[index] in SOFT_BOUNDARY:
            return index + 1
    return None


def _ends_open(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in OPEN_ENDINGS


@dataclass(slots=True)
class _OpenSegment:
    segment_id: int
    revision: int = 0
    emitted_text: str = ""
    first_seen_ms: int = 0
    last_emit_ms: int | None = None
    source_incomplete: bool = False
    source_diagnostic: str | None = None


class StableSourceOrganizer:
    """Per-session organizer. Feed it snapshots/activity; it returns source updates."""

    def __init__(self, session_id: str, config: OrganizerConfig | None = None) -> None:
        self.session_id = session_id
        self.config = config or OrganizerConfig()
        self._next_segment_id = 1
        self._window_id: int | None = None
        self._last_text: str | None = None
        self._stable = ""
        self._consumed = 0
        self._consumed_text = ""
        self._open: _OpenSegment | None = None
        self._audio_ms = 0
        self._silence_ms = 0
        self._speech_active = False
        self._punct_key: tuple[int, int] | None = None
        self._punct_seen_ms = 0
        self._pending_incomplete: str | None = None
        self.rewrite_conflicts = 0
        self.stopped = False

    # -- inputs -------------------------------------------------------------------------

    def push_snapshot(self, snapshot: AsrSnapshot) -> list[SourceUpdate]:
        self._check_session(snapshot.session_id)
        updates: list[SourceUpdate] = []
        if self._window_id is not None and snapshot.window_id != self._window_id:
            # The previous window ended without an explicit final: drain what it had.
            if self._last_text is not None:
                self._stable = self._last_text
            updates += self._evaluate(force_close=True)
            self._reset_window()
        self._window_id = snapshot.window_id
        self._audio_ms = max(self._audio_ms, snapshot.audio_end_ms)

        text = snapshot.text
        if self._consumed_text and not text.startswith(self._consumed_text):
            # The backend rewrote text that already became a closed segment. Closed segments
            # are not reopened (S1 item 5); record the conflict and realign the offset.
            self.rewrite_conflicts += 1
            self._realign(text)

        if snapshot.window_final:
            stable = text
        elif self._last_text is None:
            stable = ""
        elif text == self._last_text:
            stable = text
        else:
            agreed = common_prefix(self._last_text, text)
            stable = agreed[: max(0, len(agreed) - self.config.stability_tail_chars)]
            # Agreement only grows while the backend keeps extending the same prefix.
            if len(stable) < len(self._stable) and text.startswith(self._stable):
                stable = self._stable
        self._last_text = text
        self._stable = stable

        updates += self._evaluate(force_close=snapshot.window_final)
        if snapshot.window_final:
            self._reset_window()
        return updates

    def push_activity(self, activity: SpeechActivity) -> list[SourceUpdate]:
        self._check_session(activity.session_id)
        self._audio_ms = max(self._audio_ms, activity.audio_end_ms)
        self._speech_active = activity.active
        self._silence_ms = 0 if activity.active else activity.silence_ms
        return self._evaluate(force_close=False)

    def push_gap(self, gap: CaptureGap) -> list[SourceUpdate]:
        self._check_session(gap.session_id)
        if self._open is not None:
            self._open.source_incomplete = True
            self._open.source_diagnostic = gap.reason
            if self._open.emitted_text:
                return [self._emit(self._open.emitted_text, closed=False, force=True)]
            return []
        self._pending_incomplete = gap.reason
        return []

    def stop(self) -> list[SourceUpdate]:
        """Drain the tail on session stop; nothing stable or tentative is silently dropped."""
        if self.stopped:
            return []
        if self._last_text is not None:
            self._stable = self._last_text
        updates = self._evaluate(force_close=True)
        self.stopped = True
        return updates

    # -- core rules ---------------------------------------------------------------------

    def _evaluate(self, *, force_close: bool) -> list[SourceUpdate]:
        if self.stopped:
            return []
        updates: list[SourceUpdate] = []
        cfg = self.config
        while True:
            unconsumed = self._stable[self._consumed :]
            if not unconsumed.strip():
                if self._consumed < len(self._stable):
                    self._consume(len(unconsumed))
                return updates
            segment = self._ensure_open()

            close_at: int | None = None
            sentence_end = _first_sentence_end(unconsumed)
            if sentence_end is not None:
                key = (self._consumed, sentence_end)
                if self._punct_key != key:
                    self._punct_key = key
                    self._punct_seen_ms = self._audio_ms
                more_after = bool(unconsumed[sentence_end:].strip())
                confirmed = self._audio_ms - self._punct_seen_ms >= cfg.sentence_confirm_ms
                if more_after or confirmed or force_close or self._long_pause():
                    close_at = sentence_end
            if close_at is None and (force_close or self._long_pause()):
                close_at = len(unconsumed)
            if close_at is None and self._over_limit(unconsumed, segment):
                boundary = _last_boundary(unconsumed)
                if boundary is not None and unconsumed[:boundary].strip():
                    close_at = boundary
                else:
                    close_at = len(unconsumed)
                    segment.source_incomplete = True
                    segment.source_diagnostic = "segment_length_cap"

            if close_at is not None:
                text = unconsumed[:close_at].strip()
                updates.append(self._emit(text, closed=True, force=True))
                self._consume(close_at)
                self._open = None
                self._punct_key = None
                continue

            update = self._maybe_open_update(unconsumed, segment)
            if update is not None:
                updates.append(update)
            return updates

    def _maybe_open_update(self, unconsumed: str, segment: _OpenSegment) -> SourceUpdate | None:
        cfg = self.config
        if (
            segment.last_emit_ms is not None
            and self._audio_ms - segment.last_emit_ms < cfg.min_emit_interval_ms
        ):
            return None
        short_pause = not self._speech_active and self._silence_ms >= cfg.short_pause_ms
        waited = self._audio_ms - segment.first_seen_ms >= cfg.max_initial_wait_ms
        if not (short_pause or waited):
            return None

        candidate: str | None = None
        if short_pause and not _ends_open(unconsumed):
            candidate = unconsumed
        else:
            boundary = _last_boundary(unconsumed)
            if boundary is not None:
                candidate = unconsumed[:boundary]
        if candidate is None:
            return None
        candidate = candidate.strip()
        if candidate == segment.emitted_text:
            return None
        grew = len(candidate) - len(segment.emitted_text)
        if grew < cfg.min_new_chars and candidate.startswith(segment.emitted_text):
            return None
        return self._emit(candidate, closed=False)

    def _long_pause(self) -> bool:
        return not self._speech_active and self._silence_ms >= self.config.long_pause_ms

    def _over_limit(self, unconsumed: str, segment: _OpenSegment) -> bool:
        cfg = self.config
        too_long = len(unconsumed.strip()) >= cfg.max_segment_chars
        too_old = self._audio_ms - segment.first_seen_ms >= cfg.max_segment_ms
        return too_long or too_old

    # -- helpers ------------------------------------------------------------------------

    def _ensure_open(self) -> _OpenSegment:
        if self._open is None:
            self._open = _OpenSegment(segment_id=self._next_segment_id, first_seen_ms=self._audio_ms)
            self._next_segment_id += 1
            if self._pending_incomplete is not None:
                self._open.source_incomplete = True
                self._open.source_diagnostic = self._pending_incomplete
                self._pending_incomplete = None
        return self._open

    def _emit(self, text: str, *, closed: bool, force: bool = False) -> SourceUpdate:
        segment = self._ensure_open()
        if not force and text == segment.emitted_text:
            raise AssertionError("duplicate open emission")
        segment.revision += 1
        segment.emitted_text = text
        segment.last_emit_ms = self._audio_ms
        return SourceUpdate(
            session_id=self.session_id,
            segment_id=segment.segment_id,
            revision=segment.revision,
            text=text,
            closed=closed,
            source_incomplete=segment.source_incomplete,
            source_diagnostic=segment.source_diagnostic,
            audio_end_ms=self._audio_ms,
        )

    def _consume(self, length: int) -> None:
        self._consumed += length
        self._consumed_text = self._stable[: self._consumed]

    def _realign(self, text: str) -> None:
        old = self._consumed_text
        position = min(len(old), len(text))
        if old.rstrip()[-1:] in SENTENCE_END or old.rstrip()[-1:] in CLOSING_MARKS:
            agreed = len(common_prefix(old, text))
            end = _first_sentence_end(text[agreed:])
            if end is not None:
                position = agreed + end
        self._consumed = position
        self._consumed_text = text[:position]
        self._punct_key = None

    def _reset_window(self) -> None:
        self._window_id = None
        self._last_text = None
        self._stable = ""
        self._consumed = 0
        self._consumed_text = ""
        self._punct_key = None

    def _check_session(self, session_id: str) -> None:
        if session_id != self.session_id:
            raise ValueError("event belongs to a different session")
