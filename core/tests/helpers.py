from __future__ import annotations

from live_translator.config import CoreConfig
from live_translator.engine import SubtitleEngine
from live_translator.mock_translation import mock_reply
from live_translator.models import SourceUpdate, TranslationRequest


class Harness:
    """Drives SubtitleEngine with a virtual clock and manual translation replies."""

    def __init__(self, config: CoreConfig | None = None, **engine_kwargs: object) -> None:
        self.now = 0
        self.engine = SubtitleEngine(config, **engine_kwargs)  # type: ignore[arg-type]
        self.engine.start_session("s1", self.now)
        self.sent: list[TranslationRequest] = []

    def advance(self, ms: int) -> None:
        self.now += ms
        self.engine.tick(self.now)
        self.collect()

    def source(self, segment_id: int, revision: int, text: str, closed: bool = False, **kw: object) -> None:
        self.engine.source_update(
            SourceUpdate("s1", segment_id, revision, text, closed, **kw),  # type: ignore[arg-type]
            self.now,
        )
        self.collect()

    def collect(self) -> list[TranslationRequest]:
        new = self.engine.drain_requests()
        self.sent.extend(new)
        return new

    def reply(self, request: TranslationRequest, content: str | None = None, **kw: object) -> None:
        if content is None:
            content = mock_reply(request, **kw)  # type: ignore[arg-type]
        self.engine.translation_reply(request.request_id, self.now, content=content)
        self.collect()

    def fail(self, request: TranslationRequest, error: str = "http_500") -> None:
        self.engine.translation_reply(request.request_id, self.now, error=error)
        self.collect()

    def snap(self) -> dict:
        return self.engine.snapshot(self.now)

    def current_text(self) -> str | None:
        current = self.snap()["current"]
        return None if current is None else current["text"]

    def previous_text(self) -> str | None:
        previous = self.snap()["previous"]
        return None if previous is None else previous["text"]
