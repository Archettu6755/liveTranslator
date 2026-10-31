"""Bounded translation scheduling (PRODUCT_DISCUSSION.md Q2).

Per segment: at most one in-flight request and one latest pending snapshot. Across segments:
shared concurrency and a bounded number of segments waiting. This module only tracks slots;
SubtitleEngine decides what a result means.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from .config import SchedulerConfig
from .models import TranslationRequest


@dataclass(frozen=True, slots=True)
class PendingSnapshot:
    segment_id: int
    revision: int
    text: str
    final: bool
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class InFlight:
    request: TranslationRequest
    sent_ms: int
    deadline_ms: int


class TranslationScheduler:
    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()
        self._pending: OrderedDict[int, PendingSnapshot] = OrderedDict()
        self._in_flight: dict[str, InFlight] = {}
        self._segment_in_flight: dict[int, str] = {}
        self.merged_revisions = 0
        self.evicted_segments = 0

    def submit(self, snapshot: PendingSnapshot) -> list[int]:
        """Queue the latest snapshot for a segment; return segments evicted for overload."""
        if snapshot.segment_id in self._pending:
            # Replace the stale unsent version instead of queueing both (Q2 item 1).
            self.merged_revisions += 1
            self._pending[snapshot.segment_id] = snapshot
            return []
        self._pending[snapshot.segment_id] = snapshot
        evicted: list[int] = []
        while len(self._pending) > self.config.max_pending_segments:
            oldest = next(iter(self._pending))
            if oldest == snapshot.segment_id:
                break
            del self._pending[oldest]
            self.evicted_segments += 1
            evicted.append(oldest)
        return evicted

    def dispatchable(self) -> list[PendingSnapshot]:
        """Pop snapshots that may be sent now, oldest segment first."""
        ready: list[PendingSnapshot] = []
        free = self.config.api_concurrency - len(self._in_flight)
        for segment_id in list(self._pending):
            if free <= 0:
                break
            if segment_id in self._segment_in_flight:
                continue
            ready.append(self._pending.pop(segment_id))
            free -= 1
        return ready

    def mark_sent(self, request: TranslationRequest, now_ms: int) -> None:
        if request.segment_id in self._segment_in_flight:
            raise RuntimeError("segment already has a request in flight")
        self._in_flight[request.request_id] = InFlight(
            request=request,
            sent_ms=now_ms,
            deadline_ms=now_ms + self.config.request_timeout_ms,
        )
        self._segment_in_flight[request.segment_id] = request.request_id

    def complete(self, request_id: str) -> InFlight | None:
        flight = self._in_flight.pop(request_id, None)
        if flight is not None:
            self._segment_in_flight.pop(flight.request.segment_id, None)
        return flight

    def request_by_id(self, request_id: str) -> TranslationRequest | None:
        flight = self._in_flight.get(request_id)
        return None if flight is None else flight.request

    def expired(self, now_ms: int) -> list[InFlight]:
        late = [f for f in self._in_flight.values() if f.deadline_ms <= now_ms]
        for flight in late:
            self.complete(flight.request.request_id)
        return late

    def cancel_segment(self, segment_id: int) -> None:
        """Drop unsent work for a segment. A sent request cannot be assumed free to cancel."""
        self._pending.pop(segment_id, None)

    def has_pending(self, segment_id: int) -> bool:
        return segment_id in self._pending

    def pending_for(self, segment_id: int) -> PendingSnapshot | None:
        return self._pending.get(segment_id)

    def in_flight_for(self, segment_id: int) -> TranslationRequest | None:
        request_id = self._segment_in_flight.get(segment_id)
        return None if request_id is None else self._in_flight[request_id].request

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def idle(self) -> bool:
        return not self._pending and not self._in_flight
