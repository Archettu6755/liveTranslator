from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

import pytest

from live_translator.app import SessionRunner
from live_translator.bootstrap import main as bootstrap_main


@dataclass(slots=True)
class StopAwareController:
    stopped: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self) -> object:
        await self.stopped.wait()
        return object()

    def request_stop(self) -> None:
        self.stopped.set()


def test_session_runner_honors_an_immediate_stop_request() -> None:
    controller = StopAwareController()
    runner = SessionRunner(controller)

    runner.start()
    runner.stop()

    assert runner.join(timeout=2.0)
    assert controller.stopped.is_set()


@pytest.mark.skipif(sys.platform != "win32", reason="frozen dependencies are Windows-only")
def test_bootstrap_self_test_runs_before_the_desktop_application() -> None:
    assert bootstrap_main(["--self-test"]) == 0
