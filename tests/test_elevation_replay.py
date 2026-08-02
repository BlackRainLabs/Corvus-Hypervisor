"""Elevation replay and grant notification tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from corvus.memory.elevation_replay import resolve_replay_message
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


def _memory_query_message(*, target_agent_id: str = "other-agent", key: str = "secret") -> dict:
    turn_id = uuid4()
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id="vm-replay"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(
            triggered_by=TriggeredBy.AGENT_INITIATED,
            origin_correlation_id=turn_id,
        ),
        payload={
            "target_agent_id": target_agent_id,
            "namespace": "private",
            "query_type": "key",
            "query": {"key": key},
        },
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_resolve_replay_message_prefers_pending_replay(app_ctx):
    pending = _memory_query_message()
    elevation = {
        "message": {"type": "memory:grant_request", "payload": {}},
        "context": {"pending_replay": pending},
    }
    assert resolve_replay_message(elevation) == pending


@pytest.mark.asyncio
async def test_replay_after_approval_delivers_memory_response(app_ctx, tmp_path):
    other_manifest = {
        "manifest_version": "1.0",
        "engines": {"engine4": {"namespaces": ["private"]}},
    }
    from corvus.server.manifest import canonical_manifest, manifest_hash, resolve_manifest

    resolved = canonical_manifest(resolve_manifest(other_manifest))
    await app_ctx.db.upsert_agent("other-agent", manifest_hash(resolved), resolved)
    await app_ctx.db.create_memory_record(
        agent_id="other-agent",
        namespace="private",
        key="secret",
        content="cross-agent secret",
        metadata={},
        embedding_ref=None,
        expires_at=None,
    )

    query = _memory_query_message()
    elevation_id = await app_ctx.db.create_elevation(
        message=query,
        context={"matched_rules": ["allow-engine4-memory-with-grant"]},
        expires_at="2999-01-01T00:00:00+00:00",
    )
    grant_id = await app_ctx.db.create_grant(
        subject_agent=TEST_AGENT_ID,
        target_agent="other-agent",
        namespace="private",
        permissions=["read"],
        expires_at=None,
        created_by="admin-user",
    )

    delivered: list[FrameworkMessage] = []

    async def capture(agent_id: str, vm_id: str, message: FrameworkMessage) -> bool:
        delivered.append(message)
        return agent_id == TEST_AGENT_ID

    app_ctx.transport.deliver = capture  # type: ignore[method-assign]

    replay = await app_ctx.elevation_replay.replay_after_approval(
        elevation_id,
        grant_id=grant_id,
        approver_user_id="admin-user",
    )
    assert replay["replayed"] is True
    assert replay["success"] is True
    assert replay["replay_delivered"] is True
    assert replay.get("pending_replay_queued") is False
    assert any(msg.type == "memory:query_response" for msg in delivered)
    assert any(msg.type == "memory:grant_created" for msg in delivered)
    response = next(msg for msg in delivered if msg.type == "memory:query_response")
    assert response.payload["success"] is True
    assert response.payload["records"][0]["content"] == "cross-agent secret"
