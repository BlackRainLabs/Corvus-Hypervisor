"""Append-only audit log."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from corvus.policy.combiner import PolicyDecision
from corvus.protocol import FrameworkMessage
from corvus.server.db import Database


class AuditStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def turn_root_id(message: FrameworkMessage) -> str:
        origin = message.tags.origin_correlation_id or message.correlation_id
        return str(origin)

    async def log_message_hop(self, message: FrameworkMessage, *, connection_id: int) -> None:
        await self._insert(
            event_type="message_hop",
            correlation_id=str(message.correlation_id),
            origin_correlation_id=self.turn_root_id(message),
            agent_id=message.source.agent_id,
            message_id=str(message.id),
            decision=None,
            matched_rules=[],
            details={
                "connection_id": connection_id,
                "type": message.type,
                "origin_correlation_id": self.turn_root_id(message),
            },
        )

    async def log_policy_decision(
        self,
        message: FrameworkMessage,
        decision: PolicyDecision,
    ) -> None:
        await self._insert(
            event_type="policy_decision",
            correlation_id=str(message.correlation_id),
            origin_correlation_id=self.turn_root_id(message),
            agent_id=message.source.agent_id,
            message_id=str(message.id),
            decision=decision.decision,
            matched_rules=[m.rule_id for m in decision.matched_rules],
            details={
                "explanation_trace": decision.explanation_trace,
                "effective_error_code": decision.effective_error_code,
                "metadata": decision.metadata,
                "user_id": decision.metadata.get("user_id"),
                "rule_ids": [m.rule_id for m in decision.matched_rules],
                "grant_id": decision.metadata.get("grant_id"),
                "quota_key": decision.metadata.get("quota_key"),
                "elevation_id": decision.metadata.get("elevation_id"),
                "identity_channel": decision.metadata.get("identity_channel"),
                "auth_method": decision.metadata.get("auth_method"),
                "origin_correlation_id": self.turn_root_id(message),
            },
        )

    async def log_api_mutation(self, *, endpoint: str, details: dict[str, Any]) -> None:
        await self._insert(
            event_type="api_mutation",
            correlation_id=None,
            origin_correlation_id=None,
            agent_id=None,
            message_id=None,
            decision=None,
            matched_rules=[],
            details={"endpoint": endpoint, **details},
        )

    async def log_security_event(
        self,
        *,
        event_type: str,
        details: dict[str, Any],
        correlation_id: str | None = None,
        origin_correlation_id: str | None = None,
        agent_id: str | None = None,
        message_id: str | None = None,
        decision: str | None = None,
        matched_rules: list[str] | None = None,
    ) -> None:
        await self._insert(
            event_type=event_type,
            correlation_id=correlation_id,
            origin_correlation_id=origin_correlation_id,
            agent_id=agent_id,
            message_id=message_id,
            decision=decision,
            matched_rules=matched_rules or [],
            details=self._redact(details),
        )

    async def log_memory_operation(
        self,
        message: FrameworkMessage,
        *,
        operation: str,
        target_agent_id: str,
        namespace: str,
        record_id: str | None,
        grant_id: str | None,
        result: str,
        reason: str,
    ) -> None:
        turn_root = self.turn_root_id(message)
        await self._insert(
            event_type=f"memory_{operation}",
            correlation_id=str(message.correlation_id),
            origin_correlation_id=turn_root,
            agent_id=message.source.agent_id,
            message_id=str(message.id),
            decision=result,
            matched_rules=[],
            details={
                "operation": operation,
                "agent_id": message.source.agent_id,
                "target_agent_id": target_agent_id,
                "namespace": namespace,
                "record_id": record_id,
                "grant_id": grant_id,
                "correlation_id": str(message.correlation_id),
                "origin_correlation_id": turn_root,
                "result": result,
                "reason": reason,
            },
        )

    async def log_llm_operation(
        self,
        message: FrameworkMessage,
        *,
        provider: str,
        model: str,
        user_id: str | None,
        result: str,
        reason: str,
        usage: dict[str, int],
        duration_ms: int,
    ) -> None:
        turn_root = self.turn_root_id(message)
        await self._insert(
            event_type="llm_completion",
            correlation_id=str(message.correlation_id),
            origin_correlation_id=turn_root,
            agent_id=message.source.agent_id,
            message_id=str(message.id),
            decision=result,
            matched_rules=[],
            details={
                "provider": provider,
                "model": model,
                "user_id": user_id,
                "result": result,
                "reason": reason,
                "usage": usage,
                "duration_ms": duration_ms,
                "origin_correlation_id": turn_root,
            },
        )

    async def log_provider_tool_event(
        self,
        message: FrameworkMessage,
        *,
        provider: str,
        model: str,
        user_id: str | None,
        event: str,
        provider_tools: list[str],
        finish_reason: str | None,
    ) -> None:
        turn_root = self.turn_root_id(message)
        await self._insert(
            event_type=event,
            correlation_id=str(message.correlation_id),
            origin_correlation_id=turn_root,
            agent_id=message.source.agent_id,
            message_id=str(message.id),
            decision="warn",
            matched_rules=[],
            details={
                "provider": provider,
                "model": model,
                "user_id": user_id,
                "provider_tools": provider_tools,
                "finish_reason": finish_reason,
                "trust_boundary": "provider",
                "origin_correlation_id": turn_root,
            },
        )

    async def log_tool_operation(
        self,
        message: FrameworkMessage,
        *,
        phase: str,
        tool_name: str,
        user_id: str | None,
        result: str,
        reason: str,
        matched_rules: list[str],
        duration_ms: int,
        success: bool | None,
    ) -> None:
        turn_root = self.turn_root_id(message)
        await self._insert(
            event_type="tool_operation",
            correlation_id=str(message.correlation_id),
            origin_correlation_id=turn_root,
            agent_id=message.source.agent_id,
            message_id=str(message.id),
            decision=result,
            matched_rules=matched_rules,
            details={
                "phase": phase,
                "tool_name": tool_name,
                "user_id": user_id,
                "result": result,
                "reason": reason,
                "duration_ms": duration_ms,
                "success": success,
                "origin_correlation_id": turn_root,
            },
        )

    async def query_logs(
        self,
        *,
        correlation_id: str | None = None,
        origin_correlation_id: str | None = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        rule_id: str | None = None,
        grant_id: str | None = None,
        elevation_id: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if correlation_id:
            query += " AND correlation_id = ?"
            params.append(correlation_id)
        if origin_correlation_id:
            query += " AND origin_correlation_id = ?"
            params.append(origin_correlation_id)
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if from_ts:
            query += " AND timestamp >= ?"
            params.append(from_ts)
        if to_ts:
            query += " AND timestamp <= ?"
            params.append(to_ts)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cursor = await self.db.conn.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            item = {
                "id": row["id"],
                "timestamp": row["timestamp"],
                "event_type": row["event_type"],
                "correlation_id": row["correlation_id"],
                "origin_correlation_id": row["origin_correlation_id"],
                "agent_id": row["agent_id"],
                "message_id": row["message_id"],
                "decision": row["decision"],
                "matched_rules": json.loads(row["matched_rules"] or "[]"),
                "details": json.loads(row["details_json"]),
            }
            details = item["details"]
            if user_id and details.get("user_id") != user_id:
                continue
            if rule_id and rule_id not in details.get("rule_ids", item["matched_rules"]):
                continue
            if grant_id and details.get("grant_id") != grant_id:
                continue
            if elevation_id and details.get("elevation_id") != elevation_id:
                continue
            results.append(item)
        return results

    async def _insert(
        self,
        *,
        event_type: str,
        correlation_id: str | None,
        origin_correlation_id: str | None,
        agent_id: str | None,
        message_id: str | None,
        decision: str | None,
        matched_rules: list[str],
        details: dict[str, Any],
    ) -> None:
        await self.db.conn.execute(
            """
            INSERT INTO audit_log (
                timestamp, event_type, correlation_id, origin_correlation_id,
                agent_id, message_id, decision, matched_rules, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                event_type,
                correlation_id,
                origin_correlation_id,
                agent_id,
                message_id,
                decision,
                json.dumps(matched_rules),
                json.dumps(self._redact(details), sort_keys=True),
            ),
        )
        await self.db.conn.commit()

    def _redact(self, details: dict[str, Any]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, value in details.items():
            lowered = key.lower()
            secret_keys = ("password", "pin", "secret", "token", "api_key")
            if any(secret in lowered for secret in secret_keys):
                redacted[key] = "[REDACTED]"
            elif isinstance(value, dict):
                redacted[key] = self._redact(value)
            else:
                redacted[key] = value
        return redacted
