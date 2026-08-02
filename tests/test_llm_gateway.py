"""LLM gateway service unit tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

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
from corvus.server.bootstrap import TEST_AGENT_ID, TEST_MANIFEST, TEST_MANIFEST_HASH
from corvus.server.db import Database


def _llm_request(*, provider: str, model: str, agent_id: str = TEST_AGENT_ID) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE3, vm_id="vm"),
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


@pytest.mark.asyncio
async def test_stub_provider_completion(app_ctx):
    message = _llm_request(provider="stub", model="stub-v1")
    result = await app_ctx.llm.handle(message, user_id="test-user")
    assert result.success is True
    assert result.provider == "stub"
    assert result.model == "stub-v1"
    assert "Stub LLM response" in (result.content or "")
    assert result.total_tokens > 0
    payload = result.to_payload()
    assert "api_key" not in str(payload).lower()


@pytest.mark.asyncio
async def test_manifest_gate_rejects_provider(app_ctx, tmp_path):
    db = Database(tmp_path / "llm-gate.db")
    await db.connect()
    manifest = {
        **TEST_MANIFEST,
        "engines": {
            **TEST_MANIFEST["engines"],
            "engine3": {"allowed_providers": ["openai"], "allowed_models": ["gpt-4"]},
        },
    }
    await db.upsert_agent("gate-agent", TEST_MANIFEST_HASH, manifest)
    gateway = LlmGatewayService(
        db,
        app_ctx.audit,
        app_ctx.llm_registry,
        default_provider="stub",
    )
    message = _llm_request(provider="stub", model="stub-v1", agent_id="gate-agent")
    result = await gateway.handle(message, user_id="test-user")
    assert result.success is False
    assert result.error_code == "LLM_PROVIDER_NOT_ALLOWED"
    await db.close()


@pytest.mark.asyncio
async def test_registry_gate_unknown_provider(app_ctx):
    message = _llm_request(provider="does-not-exist", model="stub-v1")
    result = await app_ctx.llm.handle(message, user_id="test-user")
    assert result.success is False
    assert result.error_code == "LLM_PROVIDER_NOT_FOUND"
