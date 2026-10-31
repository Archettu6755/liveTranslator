"""SubtitleEngine: the single owner of segments, translation scheduling and cue versions.

The engine is synchronous and clock-free: every input carries ``now_ms`` from a monotonic
clock. Translation is not executed here; the engine emits TranslationRequest objects through
``drain_requests`` and receives raw replies via ``translation_reply``. The same path is used by
demo scenarios, tests and the live session (PRODUCT_DISCUSSION.md U6).
"""

from __future__ import annotations

import itertools
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

from .config import CoreConfig
from .display import CueBoard, cue_to_dict
from .models import (
    ContextEntry,
    HistoryEntry,
    SegmentQuality,
    SegmentState,
    SourceUpdate,
    TranslationOutput,
    TranslationRequest,
)
from .scheduler import PendingSnapshot, TranslationScheduler
from .translation import (
    PromptInput,
    TranslationFormatError,
    TranslationMode,
    build_messages,
    parse_output,
    select_context,
)


@dataclass(slots=True)
class _Segment:
    segment_id: int
    state: SegmentState = SegmentState.ACCUMULATING
    quality: SegmentQuality = SegmentQuality.PENDING
    revision: int = 0
    source_text: str = ""
    closed: bool = False
    closed_at_ms: int = 0
    source_incomplete: bool = False
    source_diagnostic: str | None = None
    translated_text: str | None = None
    translated_revision: int = 0
    applied_source: str | None = None
    corrected_ja: str | None = None
    uncertain_spans: tuple[str, ...] = ()
    corrections: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EngineStats:
    requests_sent: int = 0
    results_applied: int = 0
    results_rejected: int = 0
    results_provisional: int = 0
    failures: int = 0
    retries: int = 0
    timeouts: int = 0
    skipped_segments: int = 0
    duplicate_sources: int = 0
    corrections: int = 0


class SubtitleEngine:
    def __init__(
        self,
        config: CoreConfig | None = None,
        *,
        mode: TranslationMode = TranslationMode.STRUCTURED,
        glossary: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config or CoreConfig()
        self.mode = mode
        self.glossary = dict(glossary or {})
        self.scheduler = TranslationScheduler(self.config.scheduler)
        self.board = CueBoard(self.config.display)
        self.stats = EngineStats()
        self.session_id: str | None = None
        self.state = "idle"  # idle | running | stopping
        self._segments: dict[int, _Segment] = {}
        self._last_segment_id = 0
        self._outbox: list[TranslationRequest] = []
        self._context: deque[ContextEntry] = deque(maxlen=32)
        self._history: deque[HistoryEntry] = deque(maxlen=self.config.display.history_max_entries)
        self._request_ids = itertools.count(1)
        self._notices: deque[dict[str, object]] = deque(maxlen=20)
        self.version = 0

    # -- session lifecycle --------------------------------------------------------------

    def start_session(self, session_id: str, now_ms: int) -> None:
        if self.state != "idle":
            raise RuntimeError(f"cannot start while {self.state}")
        self.session_id = session_id
        self.state = "running"
        self._segments.clear()
        self._last_segment_id = 0
        self._outbox.clear()
        self._context.clear()
        self._history.clear()
        self.board.clear()
        self.scheduler = TranslationScheduler(self.config.scheduler)
        self.stats = EngineStats()
        self._notice("session_started", now_ms)

    def stop_session(self, now_ms: int) -> None:
        """Stop accepting source; drain final translations within the finalize budget."""
        if self.state != "running":
            return
        self.state = "stopping"
        for segment in list(self._segments.values()):
            if segment.state is not SegmentState.ENDED and not segment.closed:
                self._close(segment, now_ms)
                if not self._work_queued(segment) and segment.applied_source == segment.source_text:
                    self._end(segment, SegmentQuality.NORMAL, now_ms)
                else:
                    self._submit(segment)
        self._pump(now_ms)
        self._maybe_finish_stop(now_ms)

    # -- inputs -------------------------------------------------------------------------

    def source_update(self, update: SourceUpdate, now_ms: int) -> None:
        if self.state != "running" or update.session_id != self.session_id:
            return
        segment = self._segments.get(update.segment_id)
        if segment is None and update.segment_id <= self._last_segment_id:
            self.stats.duplicate_sources += 1
            return
        if segment is None:
            self._last_segment_id = update.segment_id
            segment = _Segment(segment_id=update.segment_id)
            self._segments[update.segment_id] = segment
        if segment.state is SegmentState.ENDED or update.revision <= segment.revision:
            self.stats.duplicate_sources += 1
            return

        text_changed = update.text != segment.source_text
        flags_changed = (update.source_incomplete, update.source_diagnostic) != (
            segment.source_incomplete,
            segment.source_diagnostic,
        )
        segment.revision = update.revision
        segment.source_text = update.text
        segment.source_incomplete = update.source_incomplete
        segment.source_diagnostic = update.source_diagnostic
        if flags_changed:
            self.board.update_source_flags(
                segment.segment_id, update.source_incomplete, update.source_diagnostic
            )
        if update.closed and not segment.closed:
            self._close(segment, now_ms)

        if text_changed:
            self._submit(segment)
        elif segment.closed and not self._work_queued(segment):
            if segment.applied_source == segment.source_text:
                # Same text, already translated: closing alone needs no new request (G1).
                self._end(segment, SegmentQuality.NORMAL, now_ms)
            else:
                self._submit(segment)
        self._pump(now_ms)
        self.version += 1

    def translation_reply(
        self,
        request_id: str,
        now_ms: int,
        *,
        content: str | None = None,
        error: str | None = None,
    ) -> None:
        flight = self.scheduler.complete(request_id)
        if flight is None:
            self.stats.results_rejected += 1
            return
        request = flight.request
        segment = self._segments.get(request.segment_id)
        if (
            request.session_id != self.session_id
            or segment is None
            or segment.state is SegmentState.ENDED
        ):
            self.stats.results_rejected += 1
            self._pump(now_ms)
            return

        if error is None and content is not None:
            try:
                output = parse_output(
                    content,
                    mode=self.mode,
                    source_text=request.source_text,
                    locked_texts=request.locked_texts,
                    correctable_texts=request.correctable_texts,
                )
            except TranslationFormatError as exc:
                error = f"invalid_response: {exc}"
        elif error is None:
            error = "empty_response"

        if error is not None:
            self._handle_failure(segment, request, error, now_ms)
        else:
            self._apply(segment, request, output, now_ms)
        self._pump(now_ms)
        self._maybe_finish_stop(now_ms)
        self.version += 1

    def tick(self, now_ms: int) -> None:
        for flight in self.scheduler.expired(now_ms):
            self.stats.timeouts += 1
            segment = self._segments.get(flight.request.segment_id)
            if segment is not None and segment.state is not SegmentState.ENDED:
                self._handle_failure(segment, flight.request, "timeout", now_ms)
        finalize_ms = self.config.scheduler.finalize_timeout_ms
        for segment in list(self._segments.values()):
            if (
                segment.state is SegmentState.FINALIZING
                and now_ms - segment.closed_at_ms >= finalize_ms
            ):
                quality = (
                    SegmentQuality.INCOMPLETE_TRANSLATION
                    if segment.translated_text
                    else SegmentQuality.FAILED
                )
                self._end(segment, quality, now_ms)
        before = self.board.version
        self.board.expire(now_ms)
        self._pump(now_ms)
        self._maybe_finish_stop(now_ms)
        if self.board.version != before:
            self.version += 1

    def drain_requests(self) -> list[TranslationRequest]:
        out, self._outbox = self._outbox, []
        return out

    # -- snapshot for the UI ------------------------------------------------------------

    def snapshot(self, now_ms: int) -> dict[str, object]:
        current, previous = self.board.visible(now_ms)
        active = [
            s for s in self._segments.values() if s.state is not SegmentState.ENDED
        ]
        return {
            "session_id": self.session_id,
            "state": self.state,
            "current": cue_to_dict(current),
            "previous": cue_to_dict(previous),
            "history": [
                {
                    "segment_id": h.segment_id,
                    "source": h.source,
                    "translation": h.translation,
                    "quality": h.quality.value,
                    "source_incomplete": h.source_incomplete,
                    "source_diagnostic": h.source_diagnostic,
                    "corrections": list(h.corrections),
                }
                for h in sorted(self._history, key=lambda e: e.segment_id)
            ],
            "activity": {
                "active_segments": len(active),
                "in_flight": self.scheduler.in_flight_count,
                "pending": self.scheduler.pending_count,
                "queued_cues": self.board.pending_count,
                "translating": self.scheduler.in_flight_count > 0,
            },
            "stats": {
                **asdict(self.stats),
                "merged_revisions": self.scheduler.merged_revisions,
            },
            "notices": list(self._notices),
        }

    # -- internals ----------------------------------------------------------------------

    def _close(self, segment: _Segment, now_ms: int) -> None:
        segment.closed = True
        segment.closed_at_ms = now_ms
        segment.state = SegmentState.FINALIZING

    def _work_queued(self, segment: _Segment) -> bool:
        return (
            self.scheduler.has_pending(segment.segment_id)
            or self.scheduler.in_flight_for(segment.segment_id) is not None
        )

    def _submit(self, segment: _Segment, attempt: int = 1) -> None:
        if not segment.source_text.strip():
            if segment.closed:
                self._end(segment, SegmentQuality.NORMAL, 0)
            return
        flight = self.scheduler.in_flight_for(segment.segment_id)
        if (
            flight is not None
            and flight.source_text == segment.source_text
            and flight.locked_texts == self.board.locked_texts(segment.segment_id)
        ):
            return  # the request already in flight covers exactly this task
        evicted = self.scheduler.submit(
            PendingSnapshot(
                segment_id=segment.segment_id,
                revision=segment.revision,
                text=segment.source_text,
                final=segment.closed,
                attempt=attempt,
            )
        )
        for segment_id in evicted:
            victim = self._segments.get(segment_id)
            if victim is None:
                continue
            self._notice("translation_overloaded", 0, segment_id=segment_id)
            if victim.closed and self.scheduler.in_flight_for(segment_id) is None:
                self._end(victim, SegmentQuality.SKIPPED, 0)

    def _pump(self, now_ms: int) -> None:
        cfg = self.config.scheduler
        for snapshot in self.scheduler.dispatchable():
            segment = self._segments.get(snapshot.segment_id)
            if segment is None or segment.state is SegmentState.ENDED:
                continue
            locked = self.board.locked_texts(segment.segment_id)
            context = select_context(
                list(self._context),
                max_entries=cfg.context_max_entries,
                max_chars=cfg.context_max_chars,
            )
            correctable = self.board.recent_locked_texts()
            prompt = PromptInput(
                source_text=snapshot.text,
                final=snapshot.final,
                locked_texts=locked,
                correctable_texts=correctable,
                context=context,
                glossary=self.glossary,
            )
            request = TranslationRequest(
                request_id=f"{self.session_id}:{next(self._request_ids)}",
                session_id=self.session_id or "",
                segment_id=segment.segment_id,
                source_revision=snapshot.revision,
                source_text=snapshot.text,
                final=snapshot.final,
                locked_texts=locked,
                correctable_texts=correctable,
                context=context,
                messages=build_messages(prompt, self.mode),
                attempt=snapshot.attempt,
            )
            self.scheduler.mark_sent(request, now_ms)
            self._outbox.append(request)
            self.stats.requests_sent += 1

    def _handle_failure(
        self, segment: _Segment, request: TranslationRequest, error: str, now_ms: int
    ) -> None:
        self.stats.failures += 1
        self._notice("translation_failed", now_ms, segment_id=segment.segment_id, error=error)
        can_retry = (
            self.state == "running"
            and request.attempt < self.config.scheduler.max_attempts
            and not self.scheduler.has_pending(segment.segment_id)
            and request.source_text == segment.source_text
        )
        if can_retry:
            self.stats.retries += 1
            self._submit(segment, attempt=request.attempt + 1)
            return
        if segment.closed and not self._work_queued(segment):
            quality = (
                SegmentQuality.INCOMPLETE_TRANSLATION
                if segment.translated_text
                else SegmentQuality.FAILED
            )
            self._end(segment, quality, now_ms)

    def _apply(
        self,
        segment: _Segment,
        request: TranslationRequest,
        output: TranslationOutput,
        now_ms: int,
    ) -> None:
        if request.source_revision <= segment.translated_revision:
            self.stats.results_rejected += 1  # never move the display backwards (Q3)
            return
        if request.source_text != segment.source_text:
            if not segment.source_text.startswith(request.source_text):
                self.stats.results_rejected += 1  # source was rewritten under this result
                return
            self.stats.results_provisional += 1

        display_text = output.display_zh
        current_locked = self.board.locked_texts(segment.segment_id)
        if current_locked != request.locked_texts:
            sent = len(request.locked_texts)
            extra = "".join(current_locked[sent:])
            if current_locked[:sent] == request.locked_texts and display_text.startswith(extra):
                display_text = display_text[len(extra) :].strip()
            else:
                # Cues locked while the request was out; it cannot safely overwrite them.
                self.stats.results_rejected += 1
                segment.translated_text = output.translated_zh
                if not self.scheduler.has_pending(segment.segment_id):
                    self._submit(segment)
                return

        segment.translated_text = output.translated_zh
        segment.translated_revision = request.source_revision
        segment.applied_source = request.source_text
        segment.corrected_ja = output.corrected_ja
        segment.uncertain_spans = output.uncertain_spans
        if segment.state is SegmentState.ACCUMULATING:
            segment.state = SegmentState.ACTIVE

        # The correction goes up first so the new subtitle stays the revisable current cue.
        if output.locked_correction is not None:
            fix = output.locked_correction
            cue = self.board.add_correction(
                segment.segment_id, fix.target_text, fix.corrected_text, now_ms
            )
            if cue is not None:
                self.stats.corrections += 1
                segment.corrections.append(f"{fix.target_text} → {fix.corrected_text}")
                for entry in self._history:
                    if entry.translation and fix.target_text in entry.translation:
                        entry.corrections.append(f"更正：{fix.corrected_text}")

        self.board.apply_segment_display(
            segment.segment_id,
            display_text,
            now_ms,
            source_incomplete=segment.source_incomplete,
            source_diagnostic=segment.source_diagnostic,
        )
        self.stats.results_applied += 1

        if (
            segment.closed
            and request.source_text == segment.source_text
            and not self._work_queued(segment)
        ):
            self._end(segment, SegmentQuality.NORMAL, now_ms)

    def _end(self, segment: _Segment, quality: SegmentQuality, now_ms: int) -> None:
        if segment.state is SegmentState.ENDED:
            return
        segment.state = SegmentState.ENDED
        segment.quality = quality
        self.scheduler.cancel_segment(segment.segment_id)
        self.board.lock_segment(segment.segment_id)
        if quality is SegmentQuality.SKIPPED:
            self.stats.skipped_segments += 1
        translation = segment.translated_text
        self._history.append(
            HistoryEntry(
                segment_id=segment.segment_id,
                source=segment.source_text,
                translation=translation,
                quality=quality,
                source_incomplete=segment.source_incomplete,
                source_diagnostic=segment.source_diagnostic,
                corrections=list(segment.corrections),
            )
        )
        self._context.append(ContextEntry(segment.source_text, translation, quality))
        self.board.forget_segment(segment.segment_id)
        self._segments.pop(segment.segment_id, None)
        self.version += 1

    def _maybe_finish_stop(self, now_ms: int) -> None:
        if self.state != "stopping":
            return
        if self._segments or not self.scheduler.idle():
            return
        self.state = "idle"
        self.board.clear()
        self._notice("session_stopped", now_ms)
        self.version += 1

    def _notice(self, kind: str, now_ms: int, **fields: object) -> None:
        self._notices.append({"kind": kind, "at_ms": now_ms, **fields})
