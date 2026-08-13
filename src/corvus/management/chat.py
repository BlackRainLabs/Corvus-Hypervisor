"""Operator chat through the server-side LLM gateway.

The console and Management API use this helper so inference still goes through
``LlmGatewayService`` (manifest allowlists, credentials, audit, token quotas).
It does not give Engine 3 a tool/memory bypass: operator chat is text-only and
never executes local or provider-hosted tools.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
)
from corvus.server.bootstrap import AppContext

OPERATOR_CHAT_VM_ID = "operator-console"


class OperatorChatError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def _normalize_messages(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise OperatorChatError(
            "CHAT_MESSAGES_REQUIRED",
            "At least one chat message is required",
        )
    messages: list[dict[str, str]] = []
    allowed_roles = {"system", "user", "assistant"}
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise OperatorChatError(
                "CHAT_MESSAGE_INVALID",
                f"Message {index} must be an object with role and content",
            )
        role = str(item.get("role", "")).strip()
        content = item.get("content")
        if role not in allowed_roles:
            raise OperatorChatError(
                "CHAT_MESSAGE_INVALID",
                f"Message {index} has unsupported role",
                details={"role": role},
            )
        if content is None:
            raise OperatorChatError(
                "CHAT_MESSAGE_INVALID",
                f"Message {index} is missing content",
            )
        text = str(content)
        if not text.strip() and role == "user":
            raise OperatorChatError(
                "CHAT_MESSAGE_INVALID",
                f"Message {index} content is empty",
            )
        messages.append({"role": role, "content": text})
    if not any(message["role"] == "user" for message in messages):
        raise OperatorChatError(
            "CHAT_MESSAGES_REQUIRED",
            "Conversation must include a user message",
        )
    if messages[-1]["role"] != "user":
        raise OperatorChatError(
            "CHAT_MESSAGE_INVALID",
            "The last message must be from the user",
        )
    return messages


def _resolve_provider_model(
    agent: dict[str, Any],
    *,
    requested_provider: str | None,
    requested_model: str | None,
    default_provider: str,
) -> tuple[str, str]:
    engine3 = (agent.get("manifest") or {}).get("engines", {}).get("engine3", {})
    allowed_providers = [str(item) for item in engine3.get("allowed_providers") or ["stub"]]
    allowed_models = [str(item) for item in engine3.get("allowed_models") or ["stub-v1"]]
    provider = (requested_provider or "").strip() or (
        default_provider if default_provider in allowed_providers else allowed_providers[0]
    )
    model = (requested_model or "").strip() or allowed_models[0]
    return provider, model


def _status_for_llm_error(error_code: str | None) -> int:
    if error_code == "LLM_AGENT_NOT_FOUND":
        return 404
    if error_code in {"LLM_PROVIDER_NOT_ALLOWED", "LLM_MODEL_NOT_ALLOWED"}:
        return 403
    if (error_code or "").startswith("LLM_PROVIDER"):
        return 502
    return 422


async def run_operator_chat(
    ctx: AppContext,
    *,
    agent_id: str,
    messages: Any,
    provider: str | None = None,
    model: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Run one operator chat completion against ``agent_id``'s manifest."""
    agent = await ctx.db.get_agent(agent_id)
    if agent is None:
        raise OperatorChatError(
            "AGENT_NOT_FOUND",
            "Agent not found",
            status_code=404,
            details={"agent_id": agent_id},
        )

    normalized = _normalize_messages(messages)
    provider_id, model_name = _resolve_provider_model(
        agent,
        requested_provider=provider,
        requested_model=model,
        default_provider=ctx.config.llm_default_provider,
    )
    correlation_id = uuid4()
    message = FrameworkMessage(
        source=MessageSource(
            agent_id=agent_id,
            engine=EngineId.ENGINE3,
            vm_id=OPERATOR_CHAT_VM_ID,
        ),
        destination=MessageDestination(
            type=DestinationType.CORVUS_SERVER,
            target="corvus_server",
        ),
        message_class=MessageClass.REQUEST,
        type="llm_request",
        correlation_id=correlation_id,
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={
            "provider": provider_id,
            "model": model_name,
            "messages": normalized,
        },
    )
    result = await ctx.llm.handle(message, user_id=user_id)
    if result.success:
        await ctx.quotas.increment_llm_tokens(
            user_id,
            result.total_tokens,
            daily_limit=ctx.config.llm_tokens_daily_limit,
        )
    await ctx.audit.log_api_mutation(
        endpoint=f"POST /v1/agents/{agent_id}/chat",
        details={
            "agent_id": agent_id,
            "provider": result.provider,
            "model": result.model,
            "user_id": user_id,
            "correlation_id": str(correlation_id),
            "success": result.success,
            "error_code": result.error_code,
        },
    )
    if not result.success:
        raise OperatorChatError(
            result.error_code or "LLM_REQUEST_FAILED",
            result.error or "LLM request failed",
            status_code=_status_for_llm_error(result.error_code),
            details={
                "provider": result.provider,
                "model": result.model,
                "correlation_id": str(correlation_id),
            },
        )

    reply = result.content or ""
    if not reply.strip() and result.tool_calls:
        reply = "(LLM returned tool calls; operator chat is text-only.)"
    return {
        "success": True,
        "reply": reply,
        "provider": result.provider,
        "model": result.model,
        "usage": result.usage,
        "finish_reason": result.finish_reason,
        "correlation_id": str(correlation_id),
        "tool_calls": result.tool_calls,
    }
