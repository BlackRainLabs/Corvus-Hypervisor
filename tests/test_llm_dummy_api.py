"""Dummy OpenAI-compatible LLM HTTP server tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from corvus.llm.dummy_server import DEFAULT_SUCCESS_MESSAGE, DummyLlmServer
from corvus.llm.models import LlmRequestPayload
from corvus.llm.providers.openai_compat import OpenAiCompatProviderAdapter
from corvus.llm.registry import LlmProviderRegistry, ProviderConfig
from corvus.llm.service import LlmGatewayService
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
from corvus.server.bootstrap import TEST_AGENT_ID


@pytest.fixture
async def dummy_llm_server():
    async with DummyLlmServer() as server:
        yield server


def _llm_request(*, provider: str, model: str) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE3, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="llm_request",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={
            "provider": provider,
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
        },
    )


def _dummy_http_registry(base_url: str) -> LlmProviderRegistry:
    return LlmProviderRegistry(
        {
            "dummy-http": ProviderConfig(
                provider_id="dummy-http",
                api_base_url=base_url,
                credential_ref="none",
                supported_models=["dummy-v1"],
            )
        }
    )


@pytest.mark.asyncio
async def test_dummy_server_chat_completions_returns_success(dummy_llm_server: DummyLlmServer):
    adapter = OpenAiCompatProviderAdapter()
    request = LlmRequestPayload(
        model="dummy-v1",
        messages=[{"role": "user", "content": "hello dummy"}],
    )
    completion = await adapter.complete(
        provider_id="dummy-http",
        api_base_url=dummy_llm_server.base_url,
        api_key=None,
        request=request,
        timeout_seconds=5.0,
    )
    assert completion.content is not None
    assert DEFAULT_SUCCESS_MESSAGE in completion.content
    assert "hello dummy" in completion.content
    assert completion.finish_reason == "stop"
    assert completion.usage["prompt_tokens"] > 0
    assert completion.usage["completion_tokens"] > 0


@pytest.mark.asyncio
async def test_gateway_uses_dummy_http_server(
    app_ctx, dummy_llm_server: DummyLlmServer, full_manifest_agent
):
    registry = _dummy_http_registry(dummy_llm_server.base_url)
    gateway = LlmGatewayService(
        app_ctx.db,
        app_ctx.audit,
        registry,
        default_provider="dummy-http",
    )
    message = _llm_request(provider="dummy-http", model="dummy-v1")
    result = await gateway.handle(message, user_id="test-user")
    assert result.success is True
    assert result.provider == "dummy-http"
    assert result.model == "dummy-v1"
    assert result.content is not None
    assert DEFAULT_SUCCESS_MESSAGE in result.content
    assert result.total_tokens > 0
