"""Host-side polling for guest full-turn completion via server audit log."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def _load_details(row: sqlite3.Row) -> dict[str, Any]:
    try:
        return json.loads(row["details_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def _candidate_turn_roots(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    limit: int = 20,
) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT origin_correlation_id
        FROM audit_log
        WHERE agent_id = ?
          AND origin_correlation_id IS NOT NULL
        ORDER BY id DESC
        LIMIT ?
        """,
        (agent_id, limit),
    ).fetchall()
    return [str(row["origin_correlation_id"]) for row in rows if row["origin_correlation_id"]]


def _turn_has_required_hops(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    turn_root: str,
) -> bool:
    rows = conn.execute(
        """
        SELECT event_type, details_json
        FROM audit_log
        WHERE agent_id = ?
          AND origin_correlation_id = ?
        ORDER BY id ASC
        """,
        (agent_id, turn_root),
    ).fetchall()

    has_user_query = False
    has_llm = False
    has_memory = False
    for row in rows:
        details = _load_details(row)
        if row["event_type"] == "message_hop":
            msg_type = details.get("type")
            if msg_type == "user_query":
                has_user_query = True
            elif msg_type in {"llm_request", "llm_response"}:
                has_llm = True
            elif msg_type == "memory:write":
                has_memory = True
        elif row["event_type"] == "memory_write":
            has_memory = True

    return has_user_query and has_llm and has_memory


def find_full_turn(
    db_path: Path,
    *,
    agent_id: str = "test-agent-01",
) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        for turn_root in _candidate_turn_roots(conn, agent_id=agent_id):
            if _turn_has_required_hops(conn, agent_id=agent_id, turn_root=turn_root):
                return {"agent_id": agent_id, "origin_correlation_id": turn_root}
    finally:
        conn.close()
    return None


def wait_for_full_turn(
    db_path: Path,
    *,
    agent_id: str = "test-agent-01",
    timeout: float = 120.0,
    poll_interval: float = 1.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        turn = find_full_turn(db_path, agent_id=agent_id)
        if turn is not None:
            return turn
        time.sleep(poll_interval)
    raise TimeoutError(
        f"No full turn audit trace for {agent_id} within {timeout}s "
        "(expected user_query + llm + memory hops)"
    )
