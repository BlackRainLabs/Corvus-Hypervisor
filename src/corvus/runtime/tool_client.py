"""Tool message builders and response parsing for Engine 1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from corvus.protocol import (
    DestinationType,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)
from corvus.protocol.models import EngineId


@dataclass(frozen=True)
class ToolApproval:
    ok: bool
    approved: bool
    tool_name: str | None = None
    error: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class ToolOpResult:
    ok: bool
    error: str | None = None
    error_code: str | None = None


def build_tool_call(
    agent_id: str,
    vm_id: str,
    turn_id: UUID,
    *,
    tool_name: str,
    arguments: dict[str, Any],
    timeout_seconds: int | None = None,
) -> FrameworkMessage:
    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "arguments": arguments,
    }
    if timeout_seconds is not None:
        payload["timeout_seconds"] = timeout_seconds
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE1, vm_id=vm_id),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="tool_call",
        correlation_id=uuid4(),
        tags=MessageTags(
            triggered_by=TriggeredBy.AGENT_INITIATED,
            origin_correlation_id=turn_id,
        ),
        payload=payload,
    )


def build_tool_result(
    agent_id: str,
    vm_id: str,
    turn_id: UUID,
    *,
    tool_name: str,
    request_correlation_id: UUID,
    success: bool,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    duration_ms: int = 0,
) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE1, vm_id=vm_id),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.RESPONSE,
        type="tool_result",
        correlation_id=request_correlation_id,
        tags=MessageTags(
            triggered_by=TriggeredBy.TOOL_RESULT,
            origin_correlation_id=turn_id,
        ),
        payload={
            "tool_name": tool_name,
            "success": success,
            "result": result,
            "error": error,
            "duration_ms": duration_ms,
        },
    )


def parse_tool_call_response(message: FrameworkMessage) -> ToolApproval:
    if message.message_class == MessageClass.ERROR:
        code = message.payload.get("code")
        return ToolApproval(
            ok=False,
            approved=False,
            error=message.payload.get("message"),
            error_code=str(code) if code is not None else None,
        )

    if message.type != "tool_call_response":
        return ToolApproval(
            ok=False,
            approved=False,
            error=f"expected tool_call_response, got {message.type}",
            error_code="TOOL_UNEXPECTED_RESPONSE",
        )

    payload = message.payload
    approved = payload.get("approved") is True and payload.get("success") is True
    if not approved:
        return ToolApproval(
            ok=False,
            approved=False,
            tool_name=payload.get("tool_name"),
            error=str(payload.get("error") or "tool call not approved"),
            error_code=str(payload.get("error_code")) if payload.get("error_code") else None,
        )
    return ToolApproval(
        ok=True,
        approved=True,
        tool_name=str(payload.get("tool_name")),
    )


def parse_tool_result_ack(message: FrameworkMessage) -> ToolOpResult:
    if message.message_class == MessageClass.ERROR:
        code = message.payload.get("code")
        return ToolOpResult(
            ok=False,
            error=message.payload.get("message"),
            error_code=str(code) if code is not None else None,
        )

    payload = message.payload
    if payload.get("success") is not True:
        return ToolOpResult(
            ok=False,
            error=str(payload.get("error") or "tool result rejected"),
            error_code=str(payload.get("error_code")) if payload.get("error_code") else None,
        )
    return ToolOpResult(ok=True)


def parse_tool_ack(message: FrameworkMessage) -> ToolOpResult:
    """Backward-compatible alias for generic success ack parsing."""
    return parse_tool_result_ack(message)
