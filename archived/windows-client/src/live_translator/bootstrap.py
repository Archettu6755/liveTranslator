from __future__ import annotations

import os
import sys
from collections.abc import Sequence

from .diagnostics import configure_file_logging, get_logger

_LOGGER = get_logger("bootstrap")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    configure_file_logging()
    if "--self-test" in arguments:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from .self_test import run_self_test

            return run_self_test()
        except Exception:
            _LOGGER.exception("Could not start the portable client self-test.")
            return 3

    try:
        from .app import main as run_application

        return run_application(arguments)
    except Exception:
        _LOGGER.exception("Could not start the Windows application.")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
