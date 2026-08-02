"""Provider adapter protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from corvus.llm.models import LlmRequestPayload


@dataclass(frozen=True)
class ProviderCompletion:
    content: str | None
    tool_calls: list[dict[str, Any]]
    usage: dict[str, int]
    finish_reason: str | None
    provider_tools_used: list[str] | None = None


@dataclass(frozen=True)
class ProviderStreamChunk:
    index: int
    delta: str
    is_terminal: bool = False
    completion: ProviderCompletion | None = None


class ProviderAdapter(Protocol):
    async def complete(
        self,
        *,
        provider_id: str,
        api_base_url: str,
        api_key: str | None,
        request: LlmRequestPayload,
        timeout_seconds: float,
    ) -> ProviderCompletion: ...
