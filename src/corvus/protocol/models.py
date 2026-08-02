"""FrameworkMessage protocol models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EngineId(StrEnum):
    LOOP = "loop"
    ENGINE1 = "engine1"
    ENGINE2 = "engine2"
    ENGINE3 = "engine3"
    ENGINE4 = "engine4"
    CORVUS_NODE = "corvus_node"


class MessageClass(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    ERROR = "error"
    SYSTEM = "system"


class DestinationType(StrEnum):
    ENGINE = "engine"
    LOOP = "loop"
    CORVUS_SERVER = "corvus_server"
    BROADCAST = "broadcast"


class TriggeredBy(StrEnum):
    USER_INPUT = "user_input"
    AGENT_INITIATED = "agent_initiated"
    TOOL_RESULT = "tool_result"
    TOOL_APPROVAL = "tool_approval"
    MEMORY_RESULT = "memory_result"
    LLM_RESULT = "llm_result"
    SYSTEM = "system"


class Scope(StrEnum):
    LOCAL = "local"
    CROSS_AGENT = "cross_agent"
    EXTERNAL = "external"


class MessageSource(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    agent_id: str
    engine: EngineId
    vm_id: str


class MessageDestination(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    type: DestinationType
    target: str


class MessageTags(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    triggered_by: TriggeredBy
    origin_correlation_id: UUID | None = None
    requested_capability: str | None = None
    scope: Scope = Scope.LOCAL


class MessageSecurity(BaseModel):
    may_leave_vm: bool = False
    requires_elevation: bool = False
    risk_score: int = Field(default=1, ge=1, le=5)


class FrameworkMessage(BaseModel):
    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)

    version: Literal["2.0"] = "2.0"
    id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID = Field(default_factory=uuid4)
    sequence: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: MessageSource
    destination: MessageDestination
    message_class: MessageClass = Field(alias="class")
    type: str
    tags: MessageTags
    security: MessageSecurity = Field(default_factory=MessageSecurity)
    payload: dict[str, Any] = Field(default_factory=dict)


DEFAULT_POLICY_SNAPSHOT: dict[str, Any] = {
    "version": "1.0",
    "rate_limits": {
        "engine1": {"messages_per_sec": 10, "burst": 20},
        "engine2": {"messages_per_sec": 10, "burst": 20},
        "engine3": {"messages_per_sec": 5, "burst": 10},
        "engine4": {"messages_per_sec": 10, "burst": 20},
        "loop": {"messages_per_sec": 20, "burst": 40},
    },
    "allowed_message_types": {
        "engine1": ["tool_call", "tool_result"],
        "engine2": ["user_query", "agent_response"],
        "engine3": ["llm_request", "llm_response"],
        "engine4": ["memory:query", "memory:write", "memory:delete", "memory:grant_request"],
    },
}
