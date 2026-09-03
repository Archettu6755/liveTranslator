from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from logging import LogRecord
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "live_translator"
_MAX_LOG_BYTES = 1_000_000
_BACKUP_COUNT = 3
_API_HEADER_PATTERN = re.compile(r"(?i)(x-api-key|live_translator_api_key)(\s*[:=]\s*)([^\s,;]+)")


class _RedactingFormatter(logging.Formatter):
    def __init__(self, *, secrets: tuple[str, ...]) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        self._secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: LogRecord) -> str:
        rendered = super().format(record)
        for secret in self._secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        return _API_HEADER_PATTERN.sub(r"\1\2[REDACTED]", rendered)


class _OwnedRotatingFileHandler(RotatingFileHandler):
    pass


def configure_file_logging(
    *,
    api_key: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    values = os.environ if environ is None else environ
    local_app_data = values.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    log_path = Path(local_app_data) / "LiveTranslator" / "logs" / "live-translator.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = _OwnedRotatingFileHandler(
            log_path,
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None

    handler.setFormatter(_RedactingFormatter(secrets=(api_key or "",)))
    logger = logging.getLogger(LOGGER_NAME)
    _close_owned_handlers(logger)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("Application diagnostics initialized.")
    return log_path


def close_file_logging() -> None:
    _close_owned_handlers(logging.getLogger(LOGGER_NAME))


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")


def _close_owned_handlers(logger: logging.Logger) -> None:
    for handler in tuple(logger.handlers):
        if isinstance(handler, _OwnedRotatingFileHandler):
            logger.removeHandler(handler)
            handler.close()
