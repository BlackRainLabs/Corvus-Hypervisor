"""OpenAI-compatible chat/completions client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from corvus.llm.models import LlmRequestPayload
from corvus.llm.providers.base import ProviderCompletion, ProviderStreamChunk


class OpenAiCompatProviderAdapter:
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
        del provider_id
        if api_base_url.startswith("stub://"):
            raise ValueError("stub URLs must use StubProviderAdapter")

        body = self._build_body(request, provider_tool_entries)
        headers = self._headers(api_key)

        url = f"{api_base_url.rstrip('/')}/chat/completions"
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()

        return self._parse_completion(payload, provider_tool_entries)

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
        del provider_id
        if api_base_url.startswith("stub://"):
            raise ValueError("stub URLs must use StubProviderAdapter")

        body = self._build_body(request, provider_tool_entries, stream=True)
        headers = self._headers(api_key)
        url = f"{api_base_url.rstrip('/')}/chat/completions"

        content_parts: list[str] = []
        usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        finish_reason: str | None = None
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        index = 0

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            async with client.stream("POST", url, json=body, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    usage_raw = payload.get("usage")
                    if isinstance(usage_raw, dict):
                        usage = {
                            "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
                            "completion_tokens": int(
                                usage_raw.get("completion_tokens", 0)
                            ),
                        }

                    for choice in payload.get("choices") or []:
                        if choice.get("finish_reason"):
                            finish_reason = str(choice["finish_reason"])
                        delta_obj = choice.get("delta") or {}
                        delta = delta_obj.get("content")
                        if delta:
                            content_parts.append(str(delta))
                            yield ProviderStreamChunk(index=index, delta=str(delta))
                            index += 1
                        for tc in delta_obj.get("tool_calls") or []:
                            self._merge_tool_call_delta(tool_calls_acc, tc)

        if not usage["prompt_tokens"] and not usage["completion_tokens"]:
            full = "".join(content_parts)
            usage = {
                "prompt_tokens": max(
                    sum(
                        len(str(item.get("content", "")))
                        for item in request.messages
                        if isinstance(item, dict)
                    ),
                    1,
                ),
                "completion_tokens": max(len(full), 1),
            }

        tool_calls = [tool_calls_acc[key] for key in sorted(tool_calls_acc)]
        content = "".join(content_parts) or None
        if content is None and tool_calls:
            content = ""
        completion = ProviderCompletion(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason or ("tool_calls" if tool_calls else "stop"),
            provider_tools_used=[
                str(entry.get("type"))
                for entry in (provider_tool_entries or [])
                if entry.get("type")
            ]
            or None,
        )
        yield ProviderStreamChunk(index=index, delta="", is_terminal=True, completion=completion)

    @staticmethod
    def _merge_tool_call_delta(
        acc: dict[int, dict[str, Any]], delta: dict[str, Any]
    ) -> None:
        idx = int(delta.get("index", 0))
        entry = acc.setdefault(
            idx,
            {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if delta.get("id"):
            entry["id"] = str(delta["id"])
        if delta.get("type"):
            entry["type"] = str(delta["type"])
        fn = delta.get("function") or {}
        if fn.get("name"):
            entry["function"]["name"] += str(fn["name"])
        if fn.get("arguments"):
            entry["function"]["arguments"] += str(fn["arguments"])

    @staticmethod
    def _headers(api_key: str | None) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    @staticmethod
    def _build_body(
        request: LlmRequestPayload,
        provider_tool_entries: list[dict[str, Any]] | None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
        }
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if stream:
            body["stream"] = True

        tools: list[dict[str, Any]] = []
        if request.tools_schema:
            tools.extend(request.tools_schema)
        if provider_tool_entries:
            tools.extend(provider_tool_entries)
        if tools:
            body["tools"] = tools
        return body

    @staticmethod
    def _parse_completion(
        payload: dict[str, Any],
        provider_tool_entries: list[dict[str, Any]] | None,
    ) -> ProviderCompletion:
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage_raw = payload.get("usage") or {}
        tool_calls = message.get("tool_calls") or []
        content = message.get("content")
        if content is None and tool_calls:
            content = ""
        provider_tools_used = [
            str(entry.get("type"))
            for entry in (provider_tool_entries or [])
            if entry.get("type")
        ]
        return ProviderCompletion(
            content=str(content) if content is not None else None,
            tool_calls=list(tool_calls),
            usage={
                "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
                "completion_tokens": int(usage_raw.get("completion_tokens", 0)),
            },
            finish_reason=choice.get("finish_reason"),
            provider_tools_used=provider_tools_used or None,
        )
