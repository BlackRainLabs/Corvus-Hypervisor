"""Protocol error codes and error message factory."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from corvus.protocol.models import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)


class ErrorLayer(StrEnum):
    NODE = "node"
    SERVER = "server"
    POLICY = "policy"


class ErrorCode(StrEnum):
    NODE_VALIDATION_FAILED = "NODE_VALIDATION_FAILED"
    NODE_ORIGIN_SPOOF = "NODE_ORIGIN_SPOOF"
    NODE_CAPABILITY_DENIED = "NODE_CAPABILITY_DENIED"
    NODE_RATE_LIMITED = "NODE_RATE_LIMITED"
    NODE_HANDSHAKE_INCOMPLETE = "NODE_HANDSHAKE_INCOMPLETE"
    NODE_ROUTING_FAILED = "NODE_ROUTING_FAILED"
    SERVER_SESSION_INVALID = "SERVER_SESSION_INVALID"
    SERVER_CORRELATION_INVALID = "SERVER_CORRELATION_INVALID"
    SERVER_CORRELATION_EXPIRED = "SERVER_CORRELATION_EXPIRED"
    SERVER_RBAC_DENIED = "SERVER_RBAC_DENIED"
    SERVER_ELEVATION_REQUIRED = "SERVER_ELEVATION_REQUIRED"
    SERVER_GRANT_DENIED = "SERVER_GRANT_DENIED"
    SERVER_QUOTA_EXCEEDED = "SERVER_QUOTA_EXCEEDED"
    SERVER_ROUTING_FAILED = "SERVER_ROUTING_FAILED"
    SERVER_INTERNAL_ERROR = "SERVER_INTERNAL_ERROR"


def make_error_message(
    *,
    code: ErrorCode,
    layer: ErrorLayer,
    message: str,
    recoverable: bool,
    agent_id: str,
    vm_id: str,
    correlation_id: UUID,
    target_engine: EngineId = EngineId.CORVUS_NODE,
    details: dict[str, Any] | None = None,
    original_message_id: UUID | None = None,
) -> FrameworkMessage:
    layer_value = layer.value if isinstance(layer, ErrorLayer) else layer
    payload: dict[str, Any] = {
        "code": code.value,
        "layer": layer_value,
        "message": message,
        "recoverable": recoverable,
        "details": details or {},
    }
    if original_message_id is not None:
        payload["original_message_id"] = str(original_message_id)

    return FrameworkMessage(
        source=MessageSource(
            agent_id=agent_id,
            engine=EngineId.CORVUS_NODE,
            vm_id=vm_id or "server",
        ),
        destination=MessageDestination(type=DestinationType.ENGINE, target=target_engine.value),
        message_class=MessageClass.ERROR,
        type="error",
        correlation_id=correlation_id,
        tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
        payload=payload,
    )
