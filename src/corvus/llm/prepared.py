"""Prepared LLM gateway request context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from corvus.llm.models import LlmRequestPayload
from corvus.protocol import FrameworkMessage


@dataclass(frozen=True)
class LlmPreparedRequest:
    message: FrameworkMessage
    payload: LlmRequestPayload
    provider_id: str
    upstream_payload: LlmRequestPayload
    api_base_url: str
    api_key: str | None
    adapter: Any
    tool_mode: str
    provider_tool_names: list[str]
