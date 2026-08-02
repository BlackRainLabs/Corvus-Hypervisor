"""LLM gateway request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LlmRequestPayload(BaseModel):
    provider: str | None = None
    model: str
    messages: list[dict[str, Any]]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False
    tools_schema: list[dict[str, Any]] | None = None
    provider_tools_requested: list[str] | None = None


class LlmOperationResult(BaseModel):
    success: bool
    provider: str
    model: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    finish_reason: str | None = None
    error: str | None = None
    error_code: str | None = None
    provider_tools_used: list[str] = Field(default_factory=list)
    trust_boundary: str | None = None

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("prompt_tokens", 0)) + int(
            self.usage.get("completion_tokens", 0)
        )

    def to_payload(self) -> dict[str, Any]:
        if not self.success:
            return {
                "success": False,
                "provider": self.provider,
                "model": self.model,
                "error": self.error,
                "error_code": self.error_code,
            }
        return {
            "success": True,
            "provider": self.provider,
            "model": self.model,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "usage": self.usage,
            "finish_reason": self.finish_reason,
            "provider_tools_used": self.provider_tools_used,
            "trust_boundary": self.trust_boundary,
        }
