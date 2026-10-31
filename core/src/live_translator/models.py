"""Shared value types for the subtitle core.

Three units are deliberately separate (PRODUCT_DISCUSSION.md U2):
ASR snapshots, translation segments and on-screen cues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SegmentState(StrEnum):
    ACCUMULATING = "accumulating"
    ACTIVE = "active"
    FINALIZING = "finalizing"
    ENDED = "ended"


class SegmentQuality(StrEnum):
    PENDING = "pending"
    NORMAL = "normal"
    INCOMPLETE_TRANSLATION = "incomplete_translation"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class AsrSnapshot:
    """One recognition snapshot of the current ASR window (S1).

    ``text`` is the full text of the window so far; it may rewrite earlier characters.
    ``audio_end_ms`` is the audio position covered, not a word timestamp (T1).
    """

    session_id: str
    seq: int
    window_id: int
    text: str
    audio_end_ms: int
    window_final: bool = False


@dataclass(frozen=True, slots=True)
class SpeechActivity:
    """Voice activity derived on the audio timeline, used for pause detection (G2)."""

    session_id: str
    audio_end_ms: int
    active: bool
    silence_ms: int


@dataclass(frozen=True, slots=True)
class CaptureGap:
    """Audio that never reached the recognizer (T1 item 2)."""

    session_id: str
    audio_start_ms: int | None  # None when only a dropped-duration counter is available.
    missing_ms: int
    reason: str = "capture_gap"


@dataclass(frozen=True, slots=True)
class SourceUpdate:
    """A stable Japanese source revision for one translation segment."""

    session_id: str
    segment_id: int
    revision: int
    text: str
    closed: bool
    source_incomplete: bool = False
    source_diagnostic: str | None = None
    audio_end_ms: int = 0


@dataclass(frozen=True, slots=True)
class ContextEntry:
    source: str
    translation: str | None
    quality: SegmentQuality


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    """A translation command bound to an immutable snapshot (Q1).

    The host executes ``messages`` against the configured provider and returns the raw
    response content; association is kept by ``request_id`` on the core side.
    """

    request_id: str
    session_id: str
    segment_id: int
    source_revision: int
    source_text: str
    final: bool
    locked_texts: tuple[str, ...]
    correctable_texts: tuple[str, ...]
    context: tuple[ContextEntry, ...]
    messages: tuple[dict[str, str], ...]
    attempt: int = 1


@dataclass(frozen=True, slots=True)
class CorrectionSpan:
    original: str
    replacement: str
    kind: str
    reason: str


@dataclass(frozen=True, slots=True)
class LockedCorrection:
    """A key-meaning fix for already locked text (U3)."""

    target_text: str
    corrected_text: str
    category: str


@dataclass(frozen=True, slots=True)
class TranslationOutput:
    """Validated structured translation result (C2)."""

    translated_zh: str
    display_zh: str
    corrected_ja: str | None = None
    corrections: tuple[CorrectionSpan, ...] = ()
    uncertain_spans: tuple[str, ...] = ()
    locked_correction: LockedCorrection | None = None


@dataclass(slots=True)
class Cue:
    """A short readable block of Chinese on screen."""

    cue_id: int
    segment_id: int
    text: str
    kind: str = "subtitle"  # "subtitle" | "correction"
    locked: bool = False
    shown_at_ms: int = 0
    expires_at_ms: int = 0
    source_incomplete: bool = False
    source_diagnostic: str | None = None
    corrects_cue_id: int | None = None
    version: int = 1


@dataclass(slots=True)
class HistoryEntry:
    segment_id: int
    source: str
    translation: str | None
    quality: SegmentQuality
    source_incomplete: bool
    source_diagnostic: str | None
    corrections: list[str] = field(default_factory=list)
