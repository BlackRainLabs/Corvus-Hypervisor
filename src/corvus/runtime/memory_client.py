"""Memory message builders and response parsing for Engine 4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from corvus.protocol import (
    DestinationType,
    ErrorCode,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)
from corvus.protocol.models import EngineId


@dataclass(frozen=True)
class MemoryOpResult:
    ok: bool
    record_id: str | None = None
    records: list[dict[str, Any]] | None = None
    error: str | None = None
    error_code: str | None = None
    elevation_id: str | None = None


def _memory_message(
    message_type: str,
    agent_id: str,
    vm_id: str,
    turn_id: UUID,
    payload: dict[str, Any],
) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE4, vm_id=vm_id),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type=message_type,
        correlation_id=uuid4(),
        tags=MessageTags(
            triggered_by=TriggeredBy.AGENT_INITIATED,
            origin_correlation_id=turn_id,
        ),
        payload=payload,
    )


def build_memory_write(
    agent_id: str,
    vm_id: str,
    turn_id: UUID,
    *,
    namespace: str = "private",
    key: str,
    content: str,
    target_agent_id: str | None = None,
    grant_id: str | None = None,
) -> FrameworkMessage:
    payload: dict[str, Any] = {
        "target_agent_id": target_agent_id or agent_id,
        "namespace": namespace,
        "record": {"key": key, "content": content},
    }
    if grant_id is not None:
        payload["grant_id"] = grant_id
    return _memory_message("memory:write", agent_id, vm_id, turn_id, payload)


def build_memory_query_key(
    agent_id: str,
    vm_id: str,
    turn_id: UUID,
    *,
    namespace: str = "private",
    key: str,
    target_agent_id: str | None = None,
    grant_id: str | None = None,
) -> FrameworkMessage:
    payload: dict[str, Any] = {
        "target_agent_id": target_agent_id or agent_id,
        "namespace": namespace,
        "query_type": "key",
        "query": {"key": key},
    }
    if grant_id is not None:
        payload["grant_id"] = grant_id
    return _memory_message("memory:query", agent_id, vm_id, turn_id, payload)


def build_memory_delete(
    agent_id: str,
    vm_id: str,
    turn_id: UUID,
    *,
    namespace: str = "private",
    record_id: str,
    target_agent_id: str | None = None,
    grant_id: str | None = None,
) -> FrameworkMessage:
    payload: dict[str, Any] = {
        "target_agent_id": target_agent_id or agent_id,
        "namespace": namespace,
        "record_id": record_id,
    }
    if grant_id is not None:
        payload["grant_id"] = grant_id
    return _memory_message("memory:delete", agent_id, vm_id, turn_id, payload)


def build_memory_grant_request(
    agent_id: str,
    vm_id: str,
    turn_id: UUID,
    *,
    target_agent_id: str,
    namespace: str,
    permissions: list[str],
    reason: str,
    requested_duration_seconds: int = 3600,
    pending_replay: FrameworkMessage | dict[str, Any] | None = None,
) -> FrameworkMessage:
    payload: dict[str, Any] = {
        "target_agent_id": target_agent_id,
        "namespace": namespace,
        "permissions": permissions,
        "reason": reason,
        "requested_duration_seconds": requested_duration_seconds,
    }
    if pending_replay is not None:
        if isinstance(pending_replay, FrameworkMessage):
            payload["pending_replay"] = pending_replay.model_dump(mode="json")
        else:
            payload["pending_replay"] = pending_replay
    return _memory_message(
        "memory:grant_request",
        agent_id,
        vm_id,
        turn_id,
        payload,
    )


def parse_memory_response(message: FrameworkMessage) -> MemoryOpResult:
    if message.message_class == MessageClass.ERROR:
        code = message.payload.get("code")
        details = message.payload.get("details") or {}
        elevation_id = details.get("elevation_id")
        return MemoryOpResult(
            ok=False,
            error=message.payload.get("message"),
            error_code=str(code) if code is not None else None,
            elevation_id=str(elevation_id) if elevation_id is not None else None,
        )

    payload = message.payload
    success = payload.get("success") is True
    records_raw = payload.get("records")
    records: list[dict[str, Any]] | None = None
    if isinstance(records_raw, list):
        records = []
        for item in records_raw:
            if isinstance(item, dict):
                records.append(item)
            elif hasattr(item, "model_dump"):
                records.append(item.model_dump(mode="json"))

    error = payload.get("error")
    error_code = payload.get("error_code")
    if not success and error_code is None and error:
        error_code = str(error)

    return MemoryOpResult(
        ok=success,
        record_id=payload.get("record_id"),
        records=records,
        error=str(error) if error is not None else None,
        error_code=str(error_code) if error_code is not None else None,
    )


def is_elevation_required(result: MemoryOpResult) -> bool:
    return result.error_code == ErrorCode.SERVER_ELEVATION_REQUIRED.value
