from __future__ import annotations

import logging
from pathlib import Path

from live_translator.diagnostics import (
    LOGGER_NAME,
    close_file_logging,
    configure_file_logging,
    get_logger,
)


def test_file_log_redacts_the_configured_api_key_and_header_values(tmp_path: Path) -> None:
    api_key = "private-test-key"
    log_path = configure_file_logging(
        api_key=api_key,
        environ={"LOCALAPPDATA": str(tmp_path)},
    )
    assert log_path is not None

    try:
        logger = get_logger("test")
        logger.error("raw=%s x-api-key=%s", api_key, api_key)
        for handler in logging.getLogger(LOGGER_NAME).handlers:
            handler.flush()

        content = log_path.read_text(encoding="utf-8")
        assert api_key not in content
        assert "[REDACTED]" in content
    finally:
        close_file_logging()


def test_file_log_is_disabled_without_local_app_data() -> None:
    assert configure_file_logging(environ={}) is None
