"""Command line entry: ``python -m live_translator <command>``.

Commands:
  host                       JSON Lines core for the desktop shell (stdin/stdout)
  asr-worker [--backend ..]  loopback ASR worker (asr.v1); needs LIVE_TRANSLATOR_ASR_TOKEN
  demo [--scenario NAME|all] run demo scenarios headless and print a summary
  sources                    list Windows audio source candidates
"""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    command, rest = args[0], args[1:]
    if command == "host":
        from .host import main as host_main

        return host_main()
    if command == "asr-worker":
        from .asr_worker import main as worker_main

        return worker_main(rest)
    if command == "demo":
        from .demo import SCENARIOS, run_headless

        parser = argparse.ArgumentParser(prog="live_translator demo")
        parser.add_argument("--scenario", default="all")
        parser.add_argument("--list", action="store_true")
        opts = parser.parse_args(rest)
        if opts.list:
            for s in SCENARIOS.values():
                print(f"{s.name:18} {s.title}")
            return 0
        names = list(SCENARIOS) if opts.scenario == "all" else [opts.scenario]
        for name in names:
            if name not in SCENARIOS:
                print(f"unknown scenario: {name}", file=sys.stderr)
                return 2
            snap = run_headless(name)
            print(f"== {name}: state={snap['state']} cues={snap['shown_cues']}")
            for entry in snap["history"]:  # type: ignore[union-attr]
                print(f"   [{entry['quality']}] {entry['source']} -> {entry['translation']}")
        return 0
    if command == "sources":
        from .audio import sessions

        print(json.dumps({
            "applications": [c.to_dict() for c in sessions.list_application_candidates()],
            "devices": [d.to_dict() for d in sessions.list_output_devices()],
        }, ensure_ascii=False, indent=2))
        return 0
    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
