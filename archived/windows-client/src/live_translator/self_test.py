from __future__ import annotations

import asyncio
import os
import ssl
import sys
from importlib import import_module
from pathlib import Path
from typing import cast

from .diagnostics import get_logger

_LOGGER = get_logger("self_test")


def run_self_test() -> int:
    try:
        import certifi
        import numpy as np
        import soxr  # pyright: ignore[reportMissingTypeStubs]

        pyaudio = import_module("pyaudiowpatch")
        if not callable(getattr(pyaudio, "PyAudio", None)):
            raise RuntimeError("PyAudioWPatch does not expose PyAudio.")
        if not callable(getattr(soxr, "resample", None)):
            raise RuntimeError("soxr does not expose its resampler.")

        ca_path = Path(str(certifi.where()))
        if not ca_path.is_file():
            raise RuntimeError("The HTTPS CA bundle is missing.")
        tls_context = ssl.create_default_context(cafile=str(ca_path))
        if tls_context.cert_store_stats().get("x509_ca", 0) < 1:
            raise RuntimeError("The HTTPS CA bundle does not contain a trusted certificate.")

        from .app import DesktopApplication
        from .asr import AsrClientConfig, WebSocketAsrClient
        from .translator import AnthropicTranslator, AnthropicTranslatorConfig

        WebSocketAsrClient(AsrClientConfig())
        translator = AnthropicTranslator(
            AnthropicTranslatorConfig(
                endpoint="http://127.0.0.1:1/v1/messages",
                api_key="portable-self-test",
                model="portable-self-test",
            )
        )
        asyncio.run(translator.close())
        if not callable(getattr(DesktopApplication, "show", None)):
            raise RuntimeError("The bundled desktop application failed to import.")

        from PySide6.QtWidgets import QApplication, QWidget

        existing_application = QApplication.instance()
        owns_application = existing_application is None
        application = (
            QApplication([])
            if existing_application is None
            else cast(QApplication, existing_application)
        )
        expected_platform = os.environ.get("QT_QPA_PLATFORM")
        if (
            expected_platform
            and application.platformName().casefold() != expected_platform.casefold()
        ):
            raise RuntimeError("Qt did not load the requested platform plugin.")
        window = QWidget()
        window.setWindowTitle("Live Translator self-test")
        window.show()
        application.processEvents()
        window.close()

        samples = np.zeros((4_800, 1), dtype="<i2")
        from .windows_audio import StreamingPcmNormalizer

        normalizer = StreamingPcmNormalizer(input_sample_rate=48_000, input_channels=1)
        chunks = normalizer.push(samples.tobytes(), captured_at_ms=0)
        chunks.extend(normalizer.finish())
        if len(chunks) != 1:
            raise RuntimeError("The bundled audio resampler failed its smoke test.")
        if owns_application:
            application.quit()
    except Exception as exc:
        _LOGGER.exception("Portable client self-test failed.")
        if sys.stderr is not None:
            print(
                f"Live Translator self-test failed ({type(exc).__name__}).",
                file=sys.stderr,
            )
        return 3
    return 0
