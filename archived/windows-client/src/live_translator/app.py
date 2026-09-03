from __future__ import annotations

import argparse
import asyncio
import sys
import threading
from collections.abc import Sequence
from typing import Protocol

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from .asr import FakeAsrClient, WebSocketAsrClient
from .audio import IterableAudioSource
from .config import AppConfig, ConfigError, load_config
from .controller import SessionController
from .diagnostics import configure_file_logging, get_logger
from .models import CHUNK_BYTES, AudioChunk, SubtitleState
from .qt_control import ControlWindow
from .qt_overlay import SubtitleOverlay
from .subtitle import CompositeSubtitleSink
from .translator import AnthropicTranslator, MockTranslator
from .windows_audio import (
    LoopbackDevice,
    WasapiLoopbackSource,
    WindowsAudioError,
    list_loopback_devices,
)

_LOGGER = get_logger("app")


class SessionLifecycle(Protocol):
    async def run(self) -> object: ...

    def request_stop(self) -> None: ...


class SessionRunner(QObject):
    finished = Signal()
    failed = Signal(str)

    def __init__(self, controller: SessionLifecycle) -> None:
        super().__init__()
        self._controller = controller
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self._stop_pending = False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("session runner is already active")
        self._thread = threading.Thread(
            target=self._run,
            name="live-translator-session",
            daemon=False,
        )
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            loop = self._loop
            if loop is None or loop.is_closed():
                self._stop_pending = True
                return
        loop.call_soon_threadsafe(self._controller.request_stop)

    def join(self, timeout: float = 15.0) -> bool:
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
            return not thread.is_alive()
        return True

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        run_task = loop.create_task(self._controller.run())
        with self._lock:
            self._loop = loop
            stop_pending = self._stop_pending
            self._stop_pending = False
        if stop_pending:
            loop.call_soon(self._controller.request_stop)
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_task)
        except Exception as exc:
            _LOGGER.exception("Session worker failed.")
            self.failed.emit(str(exc))
        else:
            self.finished.emit()
        finally:
            loop.close()
            with self._lock:
                self._loop = None


class DesktopApplication(QObject):
    def __init__(
        self,
        qt_app: QApplication,
        *,
        config: AppConfig | None,
        demo: bool,
    ) -> None:
        super().__init__()
        self._qt_app = qt_app
        self._config = config
        self._demo = demo
        self._runner: SessionRunner | None = None

        devices, audio_error = self._load_devices()
        self._overlay = SubtitleOverlay()
        self._control = ControlWindow(
            devices,
            allow_start_without_device=demo,
            overlay_position_locked=self._overlay.position_locked,
            overlay_background_opacity=self._overlay.background_opacity,
        )
        if config is not None:
            self._control.select_device(config.audio.device_index)
        startup_messages = [audio_error] if audio_error else []
        if config is not None:
            startup_messages.extend(config.security_warnings)
        if startup_messages:
            self._control.set_state(
                SubtitleState(status="degraded", message=" ".join(startup_messages))
            )

        self._control.start_requested.connect(self._start_session)
        self._control.stop_requested.connect(self._stop_session)
        self._control.overlay_lock_changed.connect(self._overlay.set_position_locked)
        self._control.overlay_opacity_changed.connect(self._overlay.set_background_opacity)
        self._qt_app.aboutToQuit.connect(self._shutdown)

    def show(self) -> None:
        self._control.show()

    def _load_devices(self) -> tuple[list[LoopbackDevice], str]:
        if self._demo:
            return [], ""
        try:
            return list_loopback_devices(), ""
        except WindowsAudioError as exc:
            return [], str(exc)

    def _start_session(self, raw_device_index: object) -> None:
        if self._runner is not None:
            return

        sink = CompositeSubtitleSink((self._overlay, self._control))
        if self._demo:
            chunks = [
                AudioChunk(
                    chunk_id=index,
                    pcm_bytes=b"\x00" * CHUNK_BYTES,
                    captured_at_ms=index * 100,
                )
                for index in range(3)
            ]
            controller = SessionController(
                audio_source=IterableAudioSource(chunks),
                asr_client=FakeAsrClient(
                    transcripts=("これはデモ字幕です。",),
                    chunks_per_final=3,
                ),
                translator=MockTranslator({"これはデモ字幕です。": "这是演示字幕。"}),
                subtitle_sink=sink,
            )
        else:
            config = self._config
            if config is None:
                self._control.set_state(
                    SubtitleState(status="error", message="Configuration is missing.")
                )
                return
            device_index = raw_device_index if isinstance(raw_device_index, int) else None
            controller = SessionController(
                audio_source=WasapiLoopbackSource(device_index=device_index),
                asr_client=WebSocketAsrClient(config.asr),
                translator=AnthropicTranslator(config.translator),
                subtitle_sink=sink,
            )

        runner = SessionRunner(controller)
        runner.finished.connect(self._session_finished)
        runner.failed.connect(self._session_failed)
        self._runner = runner
        runner.start()

    def _stop_session(self) -> None:
        runner = self._runner
        if runner is not None:
            runner.stop()

    def _session_finished(self) -> None:
        self._runner = None

    def _session_failed(self, message: str) -> None:
        self._control.set_state(SubtitleState(status="error", message=message))
        self._runner = None

    def _shutdown(self) -> None:
        runner = self._runner
        if runner is not None:
            runner.stop()
            if not runner.join():
                _LOGGER.error("Session worker did not stop before the shutdown deadline.")
        self._overlay.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows live subtitle client")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the UI with fake ASR and mock translation.",
    )
    args = parser.parse_args(argv)

    qt_app = QApplication(sys.argv[:1])
    config: AppConfig | None = None
    if not args.demo:
        try:
            config = load_config()
        except ConfigError as exc:
            _LOGGER.error("Configuration failed (%s).", type(exc).__name__)
            QMessageBox.critical(None, "Live Translator", str(exc))
            return 2
        configure_file_logging(api_key=config.translator.api_key)

    application = DesktopApplication(qt_app, config=config, demo=args.demo)
    application.show()
    return qt_app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
