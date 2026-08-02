"""Default chat manifest contract tests."""

from __future__ import annotations

import pytest

from corvus.server.bootstrap import TEST_MANIFEST, TEST_MANIFEST_HASH
from corvus.server.manifest import (
    AgentManifest,
    default_chat_manifest,
    full_capability_manifest,
    manifest_hash,
    resolve_manifest,
)


def test_empty_manifest_resolves_to_chat_defaults():
    manifest = resolve_manifest(AgentManifest())
    engine3 = manifest.engines.engine3
    assert engine3.allowed_providers == ["stub"]
    assert engine3.allowed_models == ["stub-v1"]
    assert engine3.tool_execution_mode == "local"
    assert manifest.engines.engine1.tools == []
    assert manifest.engines.engine2.platforms == ["api"]
    assert manifest.engines.engine4.namespaces == []
    assert manifest.skills == []


def test_default_chat_manifest_matches_bootstrap_test_agent():
    chat = default_chat_manifest()
    assert manifest_hash(chat) == TEST_MANIFEST_HASH
    assert TEST_MANIFEST["engines"]["engine3"]["allowed_providers"] == ["stub"]
    assert TEST_MANIFEST["engines"]["engine1"]["tools"] == []


def test_full_capability_manifest_includes_tools_and_memory():
    full = full_capability_manifest()
    assert "echo" in full.engines.engine1.tools
    assert "private" in full.engines.engine4.namespaces
    assert full.skills == ["base-runtime"]


@pytest.mark.asyncio
async def test_llm_request_allowed_for_default_chat_agent(app_ctx):
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

    message = FrameworkMessage(
        source=MessageSource(agent_id="test-agent-01", engine=EngineId.ENGINE3, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="llm_request",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={
            "provider": "stub",
            "model": "stub-v1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    prepared, error = await app_ctx.llm.prepare(message, user_id="test-user")
    assert error is None
    assert prepared is not None
