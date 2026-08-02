"""Tool gateway request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCallPayload(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int | None = None


class ToolResultPayload(BaseModel):
    tool_name: str
    success: bool
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0


class ToolApprovalResult(BaseModel):
    success: bool
    approved: bool
    tool_name: str
    error: str | None = None
    error_code: str | None = None

    def to_payload(self) -> dict[str, Any]:
        if not self.success or not self.approved:
            return {
                "success": False,
                "approved": False,
                "tool_name": self.tool_name,
                "error": self.error,
                "error_code": self.error_code,
            }
        return {
            "success": True,
            "approved": True,
            "tool_name": self.tool_name,
        }


class ToolResultAck(BaseModel):
    success: bool
    tool_name: str
    error: str | None = None
    error_code: str | None = None

    def to_payload(self) -> dict[str, Any]:
        if not self.success:
            return {
                "success": False,
                "tool_name": self.tool_name,
                "error": self.error,
                "error_code": self.error_code,
            }
        return {"success": True, "tool_name": self.tool_name}
