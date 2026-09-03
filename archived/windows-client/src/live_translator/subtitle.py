from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import SubtitleState


class SubtitleSink(Protocol):
    def set_state(self, state: SubtitleState) -> None: ...

    def clear(self) -> None: ...


@dataclass(slots=True)
class MemorySubtitleSink:
    state: SubtitleState = field(default_factory=SubtitleState)
    history: list[SubtitleState] = field(default_factory=lambda: [])

    def set_state(self, state: SubtitleState) -> None:
        self.state = state
        self.history.append(state)

    def clear(self) -> None:
        self.state = SubtitleState()
        self.history.append(self.state)


@dataclass(slots=True)
class CompositeSubtitleSink:
    sinks: tuple[SubtitleSink, ...]

    def set_state(self, state: SubtitleState) -> None:
        for sink in self.sinks:
            sink.set_state(state)

    def clear(self) -> None:
        for sink in self.sinks:
            sink.clear()
