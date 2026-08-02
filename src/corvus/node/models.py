"""IPC envelope models for Corvus Node local socket."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from corvus.protocol.models import EngineId, FrameworkMessage


class IpcOperation(StrEnum):
    SUBMIT_OUTBOUND = "submit_outbound"
    RECEIVE_INBOUND = "receive_inbound"
    SUBSCRIBE_ENGINE = "subscribe_engine"
    HEALTH_CHECK = "health_check"


class IpcEnvelope(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    operation: IpcOperation
    engine: EngineId
    message: FrameworkMessage | None = None
    payload: dict[str, Any] | None = None


class IpcResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    accepted: bool | None = None
    message_id: UUID | None = None
    error: FrameworkMessage | None = None
    status: str | None = None
    handshake_complete: bool | None = None
    session_expires_at: str | None = None
    policy_snapshot: dict[str, Any] | None = None
    operation: IpcOperation | None = Field(
        default=None, description="Set on server-initiated push envelopes"
    )
    message: FrameworkMessage | None = None
