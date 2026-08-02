"""Server-side LLM gateway service."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import ValidationError

from corvus.audit.store import AuditStore
from corvus.llm.credentials import CredentialResolutionError, resolve_credential
from corvus.llm.models import LlmOperationResult, LlmRequestPayload
from corvus.llm.prepared import LlmPreparedRequest
from corvus.llm.providers.base import ProviderStreamChunk
from corvus.llm.providers.openai_compat import OpenAiCompatProviderAdapter
from corvus.llm.providers.stub import StubProviderAdapter
from corvus.llm.tool_policy import (
    build_provider_tool_entries,
    detect_opaque_provider_execution,
    filter_local_tools_schema,
    function_tool_names,
    normalize_tools_schema,
    parse_tool_execution_mode,
    provider_tools_from_manifest,
    validate_provider_tools,
)
from corvus.protocol import FrameworkMessage
from corvus.server.db import Database

if TYPE_CHECKING:
    from corvus.llm.registry import LlmProviderRegistry


class LlmGatewayService:
    def __init__(
        self,
        db: Database,
        audit: AuditStore,
        registry: LlmProviderRegistry,
        *,
        default_provider: str = "stub",
        request_timeout_seconds: float = 60.0,
    ) -> None:
        self.db = db
        self.audit = audit
        self.registry = registry
        self.default_provider = default_provider
        self.request_timeout_seconds = request_timeout_seconds
        self._stub = StubProviderAdapter()
        self._openai_compat = OpenAiCompatProviderAdapter()

    async def handle(
        self,
        message: FrameworkMessage,
        *,
        user_id: str | None,
    ) -> LlmOperationResult:
        prepared, error = await self.prepare(message, user_id=user_id)
        if error is not None:
            return error
        assert prepared is not None
        return await self._complete_prepared(prepared, user_id=user_id)

    async def prepare(
        self,
        message: FrameworkMessage,
        *,
        user_id: str | None,
    ) -> tuple[LlmPreparedRequest | None, LlmOperationResult | None]:
        del user_id
        try:
            payload = LlmRequestPayload.model_validate(message.payload)
        except ValidationError as exc:
            return None, await self._failure(
                message,
                provider=str(message.payload.get("provider", self.default_provider)),
                model=str(message.payload.get("model", "unknown")),
                code="LLM_PAYLOAD_INVALID",
                reason=str(exc),
            )

        provider_id = payload.provider or self.default_provider
        provider = self.registry.get(provider_id)
        if provider is None:
            return None, await self._failure(
                message,
                provider=provider_id,
                model=payload.model,
                code="LLM_PROVIDER_NOT_FOUND",
                reason=f"unknown provider: {provider_id}",
            )

        if payload.model not in provider.supported_models:
            return None, await self._failure(
                message,
                provider=provider_id,
                model=payload.model,
                code="LLM_MODEL_NOT_SUPPORTED",
                reason="model not supported by provider registry",
            )

        agent = await self.db.get_agent(message.source.agent_id)
        if agent is None:
            return None, await self._failure(
                message,
                provider=provider_id,
                model=payload.model,
                code="LLM_AGENT_NOT_FOUND",
                reason="agent not found",
            )

        engine3 = agent["manifest"].get("engines", {}).get("engine3", {})
        engine1 = agent["manifest"].get("engines", {}).get("engine1", {})
        allowed_providers = set(engine3.get("allowed_providers", []))
        allowed_models = set(engine3.get("allowed_models", []))
        if provider_id not in allowed_providers:
            return None, await self._failure(
                message,
                provider=provider_id,
                model=payload.model,
                code="LLM_PROVIDER_NOT_ALLOWED",
                reason="provider not allowed by agent manifest",
            )
        if payload.model not in allowed_models:
            return None, await self._failure(
                message,
                provider=provider_id,
                model=payload.model,
                code="LLM_MODEL_NOT_ALLOWED",
                reason="model not allowed by agent manifest",
            )

        tool_mode = parse_tool_execution_mode(engine3)
        allowed_local_tools = set(engine1.get("tools", []))
        filtered_schema, provider_tool_names, prep_error = self._prepare_tools(
            payload,
            tool_mode=tool_mode,
            allowed_local_tools=allowed_local_tools,
            engine3=engine3,
            provider_id=provider_id,
            provider=provider,
        )
        if prep_error:
            return None, await self._failure(
                message,
                provider=provider_id,
                model=payload.model,
                code="LLM_TOOL_POLICY_VIOLATION",
                reason=prep_error,
            )

        upstream_payload = payload.model_copy(
            update={
                "tools_schema": filtered_schema or None,
                "provider_tools_requested": provider_tool_names or None,
            }
        )

        try:
            api_key = resolve_credential(provider.credential_ref)
        except CredentialResolutionError as exc:
            return None, await self._failure(
                message,
                provider=provider_id,
                model=payload.model,
                code="LLM_PROVIDER_UNAVAILABLE",
                reason=str(exc),
            )

        adapter = self._adapter_for(provider.api_base_url)
        return (
            LlmPreparedRequest(
                message=message,
                payload=payload,
                provider_id=provider_id,
                upstream_payload=upstream_payload,
                api_base_url=provider.api_base_url,
                api_key=api_key,
                adapter=adapter,
                tool_mode=tool_mode,
                provider_tool_names=provider_tool_names,
            ),
            None,
        )

    async def iter_stream(
        self, prepared: LlmPreparedRequest
    ) -> AsyncIterator[ProviderStreamChunk]:
        provider_tool_entries = build_provider_tool_entries(prepared.provider_tool_names)
        async for chunk in prepared.adapter.stream(
            provider_id=prepared.provider_id,
            api_base_url=prepared.api_base_url,
            api_key=prepared.api_key,
            request=prepared.upstream_payload,
            timeout_seconds=self.request_timeout_seconds,
            provider_tool_entries=provider_tool_entries or None,
        ):
            yield chunk

    async def finalize_stream(
        self,
        prepared: LlmPreparedRequest,
        *,
        user_id: str | None,
        completion,
        duration_ms: int,
        reason: str = "stream_completion",
    ) -> LlmOperationResult:
        provider_tools_used = list(
            completion.provider_tools_used or prepared.provider_tool_names
        )

        if detect_opaque_provider_execution(
            finish_reason=completion.finish_reason,
            tool_calls=completion.tool_calls,
            content=completion.content,
        ):
            await self.audit.log_provider_tool_event(
                prepared.message,
                provider=prepared.provider_id,
                model=prepared.payload.model,
                user_id=user_id,
                event="provider_tool_execution_opaque",
                provider_tools=provider_tools_used,
                finish_reason=completion.finish_reason,
            )

        if provider_tools_used and prepared.tool_mode == "hybrid":
            await self.audit.log_provider_tool_event(
                prepared.message,
                provider=prepared.provider_id,
                model=prepared.payload.model,
                user_id=user_id,
                event="provider_tool_invocation",
                provider_tools=provider_tools_used,
                finish_reason=completion.finish_reason,
            )

        await self._log(
            prepared.message,
            provider=prepared.provider_id,
            model=prepared.payload.model,
            user_id=user_id,
            result="allow",
            reason=reason,
            usage=completion.usage,
            duration_ms=duration_ms,
        )
        return LlmOperationResult(
            success=True,
            provider=prepared.provider_id,
            model=prepared.payload.model,
            content=completion.content,
            tool_calls=completion.tool_calls,
            usage=completion.usage,
            finish_reason=completion.finish_reason,
            provider_tools_used=provider_tools_used,
            trust_boundary="provider" if provider_tools_used else None,
        )

    async def _complete_prepared(
        self,
        prepared: LlmPreparedRequest,
        *,
        user_id: str | None,
    ) -> LlmOperationResult:
        started = time.monotonic()
        try:
            completion = await prepared.adapter.complete(
                provider_id=prepared.provider_id,
                api_base_url=prepared.api_base_url,
                api_key=prepared.api_key,
                request=prepared.upstream_payload,
                timeout_seconds=self.request_timeout_seconds,
                provider_tool_entries=build_provider_tool_entries(
                    prepared.provider_tool_names
                ),
            )
        except httpx.HTTPStatusError as exc:
            return await self._failure(
                prepared.message,
                provider=prepared.provider_id,
                model=prepared.payload.model,
                code="LLM_PROVIDER_ERROR",
                reason=f"provider HTTP {exc.response.status_code}",
            )
        except httpx.HTTPError as exc:
            return await self._failure(
                prepared.message,
                provider=prepared.provider_id,
                model=prepared.payload.model,
                code="LLM_PROVIDER_ERROR",
                reason=str(exc),
            )

        duration_ms = int((time.monotonic() - started) * 1000)
        return await self.finalize_stream(
            prepared,
            user_id=user_id,
            completion=completion,
            duration_ms=duration_ms,
            reason="completion",
        )

    def _prepare_tools(
        self,
        payload: LlmRequestPayload,
        *,
        tool_mode: str,
        allowed_local_tools: set[str],
        engine3: dict[str, Any],
        provider_id: str,
        provider: Any,
    ) -> tuple[list[dict[str, Any]], list[str], str | None]:
        raw_schema = normalize_tools_schema(payload.tools_schema)
        requested_names = function_tool_names(raw_schema)
        disallowed = sorted(set(requested_names) - allowed_local_tools)
        if disallowed:
            return [], [], f"tools not allowed by manifest: {', '.join(disallowed)}"

        filtered_schema = filter_local_tools_schema(
            raw_schema,
            allowed_tools=allowed_local_tools,
        )

        manifest_provider_tools = provider_tools_from_manifest(
            engine3,
            provider_id=provider_id,
        )
        if tool_mode == "local":
            if manifest_provider_tools:
                return [], [], "provider_tools require hybrid tool_execution_mode"
            if payload.provider_tools_requested:
                return [], [], "provider_tools_requested not allowed in local mode"
            native_in_schema = [
                entry
                for entry in raw_schema
                if str(entry.get("type", "function")) != "function"
            ]
            if native_in_schema:
                return [], [], "provider-native tools not allowed in local mode"
            return filtered_schema, [], None

        validated, error = validate_provider_tools(
            [f"{provider_id}:{name}" for name in manifest_provider_tools],
            provider_id=provider_id,
            provider=provider,
        )
        if error:
            return [], [], error
        return filtered_schema, validated, None

    def _adapter_for(self, api_base_url: str):
        if api_base_url.startswith("stub://"):
            return self._stub
        return self._openai_compat

    async def _failure(
        self,
        message: FrameworkMessage,
        *,
        provider: str,
        model: str,
        code: str,
        reason: str,
    ) -> LlmOperationResult:
        await self._log(
            message,
            provider=provider,
            model=model,
            user_id=None,
            result="deny",
            reason=reason,
            usage={},
            duration_ms=0,
        )
        return LlmOperationResult(
            success=False,
            provider=provider,
            model=model,
            error=reason,
            error_code=code,
        )

    async def _log(
        self,
        message: FrameworkMessage,
        *,
        provider: str,
        model: str,
        user_id: str | None,
        result: str,
        reason: str,
        usage: dict[str, int],
        duration_ms: int,
    ) -> None:
        await self.audit.log_llm_operation(
            message,
            provider=provider,
            model=model,
            user_id=user_id,
            result=result,
            reason=reason,
            usage=usage,
            duration_ms=duration_ms,
        )
