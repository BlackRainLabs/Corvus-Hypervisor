"""Host-side polling for guest memory turn completion via server DB."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any


def find_engine4_turn_record(
    db_path: Path,
    *,
    agent_id: str = "test-agent-01",
    namespace: str = "private",
) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT id, agent_id, namespace, key, content, created_at, updated_at
            FROM memory_records
            WHERE agent_id = ? AND namespace = ?
              AND deleted_at IS NULL
              AND key LIKE 'turn-%'
              AND content LIKE ?
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (agent_id, namespace, "%Engine4 memory snapshot%"),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def wait_for_engine4_turn_record(
    db_path: Path,
    *,
    agent_id: str = "test-agent-01",
    namespace: str = "private",
    timeout: float = 120.0,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = find_engine4_turn_record(
            db_path, agent_id=agent_id, namespace=namespace
        )
        if record is not None:
            return record
        time.sleep(poll_interval)
    raise TimeoutError(
        f"No Engine 4 turn memory record for {agent_id}/{namespace} within {timeout}s"
    )
