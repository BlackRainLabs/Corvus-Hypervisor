"""Typed memory request and record contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    agent_id: str
    namespace: str
    key: str | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding_ref: str | None = None
    expires_at: str | None = None
    version: int
    created_at: str
    updated_at: str


class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_agent_id: str
    namespace: str = "private"
    key: str | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int | None = Field(default=None, ge=1)


class MemoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_agent_id: str
    namespace: str = "private"
    query_type: Literal["key", "list", "semantic"]
    key: str | None = None
    text: str | None = None
    limit: int = Field(default=10, ge=1, le=100)


class MemoryDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_agent_id: str
    namespace: str = "private"
    record_id: str


class MemoryOperationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    records: list[MemoryRecord] = Field(default_factory=list)
    record_id: str | None = None
    deleted: bool | None = None
    error: str | None = None
    error_code: str | None = None
    grant_evaluated: str | None = None
