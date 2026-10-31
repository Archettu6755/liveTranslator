"""Tunable parameters, grouped by the responsibilities in PRODUCT_DISCUSSION.md G2.

The defaults are a starting configuration only. None of them have been validated on real
Japanese live speech; see section 14 of the product document.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True, slots=True)
class OrganizerConfig:
    # Stability: tail of the agreed prefix that is held back while text is still growing.
    stability_tail_chars: int = 2
    # Three separate pause roles; they never share a single VAD threshold.
    short_pause_ms: int = 350
    sentence_confirm_ms: int = 400
    long_pause_ms: int = 900
    # Throttling of open (non-final) translation opportunities.
    min_emit_interval_ms: int = 600
    min_new_chars: int = 4
    max_initial_wait_ms: int = 2_500
    # Hard limits for one segment.
    max_segment_chars: int = 120
    max_segment_ms: int = 15_000


@dataclass(frozen=True, slots=True)
class SchedulerConfig:
    api_concurrency: int = 2
    max_pending_segments: int = 4
    request_timeout_ms: int = 8_000
    finalize_timeout_ms: int = 12_000
    max_attempts: int = 2
    context_max_entries: int = 6
    context_max_chars: int = 400


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    cue_max_chars: int = 36
    reading_chars_per_second: float = 8.0
    cue_min_ms: int = 1_500
    cue_max_ms: int = 7_000
    cue_max_age_ms: int = 12_000
    meaningful_change_bonus_ms: int = 1_000
    history_max_entries: int = 50
    correction_window_cues: int = 6
    # Extra cues from one long result are revealed one by one; beyond this they skip ahead.
    max_reveal_backlog: int = 2


@dataclass(frozen=True, slots=True)
class CoreConfig:
    organizer: OrganizerConfig = OrganizerConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    display: DisplayConfig = DisplayConfig()
    enable_asr_correction: bool = True


def _validate_positive(obj: object) -> None:
    for item in fields(obj):  # type: ignore[arg-type]
        value = getattr(obj, item.name)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value <= 0:
            raise ValueError(f"{type(obj).__name__}.{item.name} must be positive")


def validate(config: CoreConfig) -> CoreConfig:
    for part in (config.organizer, config.scheduler, config.display):
        _validate_positive(part)
    return config
