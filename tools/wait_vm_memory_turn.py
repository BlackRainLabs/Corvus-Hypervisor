#!/usr/bin/env python3
"""Poll server SQLite for an Engine 4 turn-scoped memory record after VM launch."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from corvus.vm.memory_wait import wait_for_engine4_turn_record  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait for guest Engine 4 memory turn in server DB")
    parser.add_argument(
        "--db",
        default=os.environ.get("CORVUS_DB_PATH", str(ROOT / "corvus.db")),
        help="Corvus server SQLite path",
    )
    parser.add_argument("--agent", default=os.environ.get("CORVUS_AGENT_ID", "test-agent-01"))
    parser.add_argument("--namespace", default="private")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    record = wait_for_engine4_turn_record(
        Path(args.db),
        agent_id=args.agent,
        namespace=args.namespace,
        timeout=args.timeout,
    )
    print(f"memory turn record: id={record['id']} key={record['key']}")


if __name__ == "__main__":
    try:
        main()
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
