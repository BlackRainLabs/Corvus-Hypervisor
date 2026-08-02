"""LLM message builders and response parsing for Engine 3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from corvus.protocol import (
    DestinationType,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)
from corvus.protocol.models import EngineId


@dataclass(frozen=True)
class LlmOpResult:
    ok: bool
    content: str | None = None
    model: str | None = None
    provider: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None
    error: str | None = None
    error_code: str | None = None


def build_llm_request(
    agent_id: str,
    vm_id: str,
    turn_id: UUID,
    *,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
    temperature: float | None = None,
    stream: bool = False,
    tools_schema: list[dict[str, Any]] | None = None,
    estimated_tokens: int | None = None,
) -> FrameworkMessage:
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "messages": messages,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    if stream:
        payload["stream"] = True
    if tools_schema is not None:
        payload["tools_schema"] = tools_schema
    if estimated_tokens is not None:
        payload["estimated_tokens"] = estimated_tokens
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE3, vm_id=vm_id),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="llm_request",
        correlation_id=uuid4(),
        tags=MessageTags(
            triggered_by=TriggeredBy.AGENT_INITIATED,
            origin_correlation_id=turn_id,
        ),
        payload=payload,
    )


def parse_llm_response(message: FrameworkMessage) -> LlmOpResult:
    if message.message_class == MessageClass.ERROR:
        code = message.payload.get("code")
        return LlmOpResult(
            ok=False,
            error=message.payload.get("message"),
            error_code=str(code) if code is not None else None,
        )

    payload = message.payload
    success = payload.get("success") is True
    if not success:
        return LlmOpResult(
            ok=False,
            provider=payload.get("provider"),
            model=payload.get("model"),
            error=str(payload.get("error") or "LLM request failed"),
            error_code=str(payload.get("error_code")) if payload.get("error_code") else None,
        )

    content = payload.get("content")
    if content is not None and not isinstance(content, str):
        content = str(content)

    usage_raw = payload.get("usage")
    usage: dict[str, int] | None = None
    if isinstance(usage_raw, dict):
        usage = {str(k): int(v) for k, v in usage_raw.items()}

    tool_calls_raw = payload.get("tool_calls")
    tool_calls: list[dict[str, Any]] | None = None
    if isinstance(tool_calls_raw, list):
        tool_calls = [item for item in tool_calls_raw if isinstance(item, dict)]

    return LlmOpResult(
        ok=True,
        content=content,
        model=payload.get("model"),
        provider=payload.get("provider"),
        tool_calls=tool_calls,
        usage=usage,
        finish_reason=payload.get("finish_reason"),
    )


async def collect_llm_stream(
    ipc,
    message: FrameworkMessage,
    *,
    timeout: float = 120.0,
) -> LlmOpResult:
    """Submit a streaming llm_request and collect chunks until llm_response."""
    resp = await ipc.submit(message)
    if not resp.get("accepted"):
        err = resp.get("error")
        raise RuntimeError(f"submit rejected: {err}")

    start = await ipc.wait_inbound(timeout=timeout)
    if start.type == "llm_stream_start":
        if start.payload.get("success") is not True:
            return LlmOpResult(
                ok=False,
                provider=start.payload.get("provider"),
                model=start.payload.get("model"),
                error=str(start.payload.get("error") or "LLM stream start failed"),
                error_code=str(start.payload.get("error_code"))
                if start.payload.get("error_code")
                else None,
            )
    elif start.type == "llm_response":
        return parse_llm_response(start)
    elif start.message_class == MessageClass.ERROR:
        return parse_llm_response(start)
    else:
        return LlmOpResult(
            ok=False,
            error=f"unexpected first inbound type: {start.type}",
        )

    chunks: list[str] = []
    while True:
        inbound = await ipc.wait_inbound(timeout=timeout)
        if inbound.type == "llm_stream_chunk":
            delta = inbound.payload.get("delta")
            if isinstance(delta, str) and delta:
                chunks.append(delta)
            continue
        if inbound.type == "llm_response":
            result = parse_llm_response(inbound)
            if result.ok and not result.content and chunks:
                return LlmOpResult(
                    ok=True,
                    content="".join(chunks),
                    model=result.model,
                    provider=result.provider,
                    tool_calls=result.tool_calls,
                    usage=result.usage,
                    finish_reason=result.finish_reason,
                )
            return result
        if inbound.message_class == MessageClass.ERROR:
            return parse_llm_response(inbound)
        return LlmOpResult(
            ok=False,
            error=f"unexpected inbound type during stream: {inbound.type}",
        )
