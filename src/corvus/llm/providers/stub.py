"""Deterministic stub provider for CI and local dev."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from corvus.llm.models import LlmRequestPayload
from corvus.llm.providers.base import ProviderCompletion, ProviderStreamChunk
from corvus.llm.tool_policy import normalize_tools_schema


class StubProviderAdapter:
    async def complete(
        self,
        *,
        provider_id: str,
        api_base_url: str,
        api_key: str | None,
        request: LlmRequestPayload,
        timeout_seconds: float,
        provider_tool_entries: list[dict[str, Any]] | None = None,
    ) -> ProviderCompletion:
        del provider_id, api_base_url, api_key, timeout_seconds

        provider_tools_used = [
            str(entry.get("type"))
            for entry in (provider_tool_entries or [])
            if entry.get("type")
        ]
        if provider_tool_entries:
            text = "Stub provider-hosted tool result"
            return ProviderCompletion(
                content=text,
                tool_calls=[],
                usage={"prompt_tokens": 1, "completion_tokens": len(text)},
                finish_reason="stop",
                provider_tools_used=provider_tools_used,
            )

        tool_messages = [m for m in request.messages if str(m.get("role")) == "tool"]
        if tool_messages:
            combined = "; ".join(str(m.get("content", "")) for m in tool_messages)
            text = f"Stub LLM after tools: {combined}"
            return ProviderCompletion(
                content=text,
                tool_calls=[],
                usage={"prompt_tokens": max(len(combined), 1), "completion_tokens": len(text)},
                finish_reason="stop",
            )

        tools_schema = normalize_tools_schema(request.tools_schema)
        if tools_schema:
            tool_calls = self._build_tool_calls(tools_schema)
            return ProviderCompletion(
                content="",
                tool_calls=tool_calls,
                usage={"prompt_tokens": 1, "completion_tokens": len(tool_calls)},
                finish_reason="tool_calls",
            )

        text, prompt_tokens = self._plain_text(request)
        completion_tokens = len(text)
        return ProviderCompletion(
            content=text,
            tool_calls=[],
            usage={
                "prompt_tokens": max(prompt_tokens, 1),
                "completion_tokens": max(completion_tokens, 1),
            },
            finish_reason="stop",
        )

    async def stream(
        self,
        *,
        provider_id: str,
        api_base_url: str,
        api_key: str | None,
        request: LlmRequestPayload,
        timeout_seconds: float,
        provider_tool_entries: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[ProviderStreamChunk]:
        del provider_id, api_base_url, api_key, timeout_seconds

        provider_tools_used = [
            str(entry.get("type"))
            for entry in (provider_tool_entries or [])
            if entry.get("type")
        ]
        if provider_tool_entries:
            text = "Stub provider-hosted tool result"
            completion = ProviderCompletion(
                content=text,
                tool_calls=[],
                usage={"prompt_tokens": 1, "completion_tokens": len(text)},
                finish_reason="stop",
                provider_tools_used=provider_tools_used,
            )
            yield ProviderStreamChunk(
                index=0, delta="", is_terminal=True, completion=completion
            )
            return

        tool_messages = [m for m in request.messages if str(m.get("role")) == "tool"]
        tools_schema = normalize_tools_schema(request.tools_schema)
        if tools_schema and not tool_messages:
            tool_calls = self._build_tool_calls(tools_schema)
            completion = ProviderCompletion(
                content="",
                tool_calls=tool_calls,
                usage={"prompt_tokens": 1, "completion_tokens": len(tool_calls)},
                finish_reason="tool_calls",
            )
            yield ProviderStreamChunk(
                index=0, delta="", is_terminal=True, completion=completion
            )
            return

        if tool_messages:
            combined = "; ".join(str(m.get("content", "")) for m in tool_messages)
            text = f"Stub LLM after tools: {combined}"
            prompt_tokens = max(len(combined), 1)
        else:
            text, prompt_tokens = self._plain_text(request, stream_prefix=True)
        chunk_size = 8
        index = 0
        for offset in range(0, len(text), chunk_size):
            yield ProviderStreamChunk(index=index, delta=text[offset : offset + chunk_size])
            index += 1
        completion = ProviderCompletion(
            content=text,
            tool_calls=[],
            usage={
                "prompt_tokens": max(prompt_tokens, 1),
                "completion_tokens": max(len(text), 1),
            },
            finish_reason="stop",
        )
        yield ProviderStreamChunk(index=index, delta="", is_terminal=True, completion=completion)

    @staticmethod
    def _build_tool_calls(tools_schema: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []
        for index, entry in enumerate(tools_schema):
            fn = entry.get("function") or {}
            tool_name = str(fn.get("name", "echo"))
            if tool_name == "echo":
                args = {"text": "Hello from tool gateway"}
            elif tool_name == "terminal":
                args = {"argv": ["echo", "agentvm terminal ok"]}
            else:
                args = {}
            tool_calls.append(
                {
                    "id": f"call_stub_{index + 1}",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args),
                    },
                }
            )
        return tool_calls

    @staticmethod
    def _plain_text(request: LlmRequestPayload, *, stream_prefix: bool = False) -> tuple[str, int]:
        last_user = ""
        for message in reversed(request.messages):
            if str(message.get("role")) == "user":
                last_user = str(message.get("content", ""))
                break
        prefix = "Stub LLM stream: " if stream_prefix else "Stub LLM response: "
        if last_user:
            text = f"{prefix}{last_user}"
        else:
            text = (
                f"{prefix.rstrip(': ')} for turn."
                if stream_prefix
                else "Stub LLM response for turn."
            )
        prompt_tokens = sum(len(str(m.get("content", ""))) for m in request.messages)
        return text, prompt_tokens

