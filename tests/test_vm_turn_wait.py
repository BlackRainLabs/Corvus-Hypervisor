"""Unit tests for full-turn audit waiter."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from corvus.vm.turn_wait import find_full_turn, wait_for_full_turn


def _init_audit(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            correlation_id TEXT,
            origin_correlation_id TEXT,
            agent_id TEXT,
            message_id TEXT,
            decision TEXT,
            matched_rules TEXT,
            details_json TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def _insert(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    agent_id: str,
    turn_root: str,
    details: dict,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (
            timestamp, event_type, correlation_id, origin_correlation_id,
            agent_id, message_id, decision, matched_rules, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "2026-07-05T00:00:00+00:00",
            event_type,
            turn_root,
            turn_root,
            agent_id,
            "msg-1",
            None,
            "[]",
            json.dumps(details),
        ),
    )


def test_find_full_turn_requires_user_query_llm_and_memory(tmp_path):
    db_path = tmp_path / "audit.db"
    _init_audit(db_path)
    conn = sqlite3.connect(db_path)
    turn_root = "turn-abc"
    agent_id = "test-agent-01"
    _insert(
        conn,
        event_type="message_hop",
        agent_id=agent_id,
        turn_root=turn_root,
        details={"type": "user_query"},
    )
    conn.commit()
    assert find_full_turn(db_path, agent_id=agent_id) is None

    _insert(
        conn,
        event_type="message_hop",
        agent_id=agent_id,
        turn_root=turn_root,
        details={"type": "llm_request"},
    )
    conn.commit()
    assert find_full_turn(db_path, agent_id=agent_id) is None

    _insert(
        conn,
        event_type="memory_write",
        agent_id=agent_id,
        turn_root=turn_root,
        details={"operation": "write"},
    )
    conn.commit()
    conn.close()

    found = find_full_turn(db_path, agent_id=agent_id)
    assert found is not None
    assert found["origin_correlation_id"] == turn_root


def test_wait_for_full_turn_returns_when_trace_complete(tmp_path):
    db_path = tmp_path / "audit.db"
    _init_audit(db_path)
    turn_root = "turn-xyz"
    agent_id = "test-agent-01"

    conn = sqlite3.connect(db_path)
    for event_type, details in (
        ("message_hop", {"type": "user_query"}),
        ("message_hop", {"type": "llm_response"}),
        ("message_hop", {"type": "memory:write"}),
    ):
        _insert(
            conn,
            event_type=event_type,
            agent_id=agent_id,
            turn_root=turn_root,
            details=details,
        )
    conn.commit()
    conn.close()

    turn = wait_for_full_turn(db_path, agent_id=agent_id, timeout=1.0, poll_interval=0.05)
    assert turn["origin_correlation_id"] == turn_root
