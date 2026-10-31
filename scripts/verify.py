"""Run deterministic project checks with existing local dependencies; install nothing."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desktop-smoke", action="store_true", help="also start hidden Electron windows and verify the shared demo")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    python = root / "core/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not python.exists() or not npm:
        print("Missing project environment or npm. See README.md for setup.", file=sys.stderr)
        return 2
    checks = [([str(python), "-m", "pytest", "-q"], root / "core"), ([npm, "run", "typecheck"], root / "desktop"), ([npm, "run", "build"], root / "desktop"), ([npm, "test"], root / "desktop")]
    if args.desktop_smoke:
        checks.append(([npm, "run", "smoke"], root / "desktop"))
    for command, cwd in checks:
        print(f"Running {command[1:]} in {cwd.name}", flush=True)
        result = subprocess.run(command, cwd=cwd, timeout=90)
        if result.returncode:
            return result.returncode
    print("All requested checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
