#!/usr/bin/env python3
"""Poll server SQLite audit log for a complete guest turn trace."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from corvus.vm.turn_wait import wait_for_full_turn  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait for guest full turn in server audit log")
    parser.add_argument(
        "--db",
        default=os.environ.get("CORVUS_DB_PATH", str(ROOT / "corvus.db")),
        help="Corvus server SQLite path",
    )
    parser.add_argument("--agent", default=os.environ.get("CORVUS_AGENT_ID", "test-agent-01"))
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    turn = wait_for_full_turn(
        Path(args.db),
        agent_id=args.agent,
        timeout=args.timeout,
    )
    print(
        "full turn trace: "
        f"agent={turn['agent_id']} origin_correlation_id={turn['origin_correlation_id']}"
    )


if __name__ == "__main__":
    try:
        main()
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
