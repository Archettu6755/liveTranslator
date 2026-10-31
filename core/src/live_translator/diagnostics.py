"""Redacting logging to stderr (stdout is reserved for protocol lines).

Adapted from archived/windows-client/src/live_translator/diagnostics.py (commit 3e91d93):
known secrets and common credential patterns are masked. Masking covers only registered values
and the patterns below; it is not a guarantee that arbitrary text is safe to log.
"""

from __future__ import annotations

import logging
import re
import sys
from logging import LogRecord

LOGGER_NAME = "live_translator"
_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,;\"']+)"),
    re.compile(r"(?i)(x-api-key|api[_-]?key|token)(\s*[:=]\s*)([^\s,;\"']+)"),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,})\b"),
)
_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    if value and len(value) >= 6:
        _secrets.add(value)


def redact(text: str) -> str:
    for secret in _secrets:
        text = text.replace(secret, "[REDACTED]")
    text = _PATTERNS[0].sub(r"\1[REDACTED]", text)
    text = _PATTERNS[1].sub(r"\1\2[REDACTED]", text)
    return _PATTERNS[2].sub("[REDACTED]", text)


class _RedactingFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
        return redact(super().format(record))


def configure_stderr_logging(level: int = logging.INFO) -> None:
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")
