"""Tool execution mode policy tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from corvus.llm.registry import ProviderConfig
from corvus.llm.service import LlmGatewayService
from corvus.llm.tool_policy import (
    filter_local_tools_schema,
    validate_provider_tools,
)
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


def _llm_request(
    *,
    provider: str = "stub",
    model: str = "stub-v1",
    agent_id: str = TEST_AGENT_ID,
    tools_schema: list[dict] | None = None,
) -> FrameworkMessage:
    payload: dict = {
        "provider": provider,
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
    }
    if tools_schema is not None:
        payload["tools_schema"] = tools_schema
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE3, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="llm_request",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload=payload,
    )


def test_filter_local_tools_schema_drops_provider_native():
    schema = [
        {"type": "function", "function": {"name": "echo", "parameters": {}}},
        {"type": "web_search"},
    ]
    filtered = filter_local_tools_schema(schema, allowed_tools={"echo"})
    assert len(filtered) == 1
    assert filtered[0]["function"]["name"] == "echo"


def test_validate_provider_tools_requires_registry_allowlist():
    provider = ProviderConfig(
        provider_id="openai",
        api_base_url="https://api.openai.com/v1",
        credential_ref="none",
        supported_models=["gpt-4o"],
        hosted_tools_allowed=False,
        allowed_hosted_tools=[],
    )
    allowed, error = validate_provider_tools(
        ["openai:web_search"],
        provider_id="openai",
        provider=provider,
    )
    assert allowed == []
    assert error is not None


@pytest.mark.asyncio
async def test_local_mode_rejects_disallowed_tool_in_schema(app_ctx):
    message = _llm_request(
        tools_schema=[
            {
                "type": "function",
                "function": {"name": "unknown-tool", "parameters": {}},
            }
        ]
    )
    result = await app_ctx.llm.handle(message, user_id="test-user")
    assert result.success is False
    assert result.error_code == "LLM_TOOL_POLICY_VIOLATION"


@pytest.mark.asyncio
async def test_local_mode_stub_returns_tool_calls(app_ctx, full_manifest_agent):
    message = _llm_request(
        tools_schema=[
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "echo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    )
    result = await app_ctx.llm.handle(message, user_id="test-user")
    assert result.success is True
    assert result.tool_calls
    assert result.tool_calls[0]["function"]["name"] == "echo"


@pytest.mark.asyncio
async def test_hybrid_mode_forwards_provider_tools(app_ctx, tmp_path):
    db = Database(tmp_path / "hybrid.db")
    await db.connect()
    manifest = {
        **TEST_MANIFEST,
        "engines": {
            **TEST_MANIFEST["engines"],
            "engine3": {
                **TEST_MANIFEST["engines"]["engine3"],
                "tool_execution_mode": "hybrid",
                "provider_tools": ["stub:hosted_echo"],
            },
        },
    }
    await db.upsert_agent("hybrid-agent", TEST_MANIFEST_HASH, manifest)

    registry = app_ctx.llm_registry
    providers = dict(registry.providers)
    providers["stub"] = ProviderConfig(
        provider_id="stub",
        api_base_url="stub://local",
        credential_ref="none",
        supported_models=["stub-v1"],
        hosted_tools_allowed=True,
        allowed_hosted_tools=["hosted_echo"],
    )
    from corvus.llm.registry import LlmProviderRegistry

    hybrid_registry = LlmProviderRegistry(providers)
    gateway = LlmGatewayService(
        db,
        app_ctx.audit,
        hybrid_registry,
        default_provider="stub",
    )
    message = _llm_request(agent_id="hybrid-agent")
    result = await gateway.handle(message, user_id="admin-user")
    assert result.success is True
    assert result.provider_tools_used == ["hosted_echo"]
    assert result.trust_boundary == "provider"
    await db.close()
