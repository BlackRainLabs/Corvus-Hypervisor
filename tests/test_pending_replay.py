"""Pending replay queue tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

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


def _memory_query_message() -> dict:
    turn_id = uuid4()
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id="vm-replay"),
        destination=MessageDestination(
            type=DestinationType.CORVUS_SERVER, target="corvus_server"
        ),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(
            triggered_by=TriggeredBy.AGENT_INITIATED,
            origin_correlation_id=turn_id,
        ),
        payload={
            "target_agent_id": "other-agent",
            "namespace": "private",
            "query_type": "key",
            "query": {"key": "secret"},
        },
    ).model_dump(mode="json")


def _sample_response() -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id="corvus-server", engine=EngineId.CORVUS_NODE, vm_id="server"),
        destination=MessageDestination(type=DestinationType.ENGINE, target=EngineId.ENGINE4.value),
        message_class=MessageClass.RESPONSE,
        type="memory:query_response",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.MEMORY_RESULT),
        payload={"success": True, "records": [], "original_type": "memory:query"},
    )


@pytest.mark.asyncio
async def test_enqueue_and_flush_delivers_messages(app_ctx):
    message = _sample_response()
    elevation_id = await app_ctx.db.create_elevation(
        message={"type": "memory:query"},
        context={},
        expires_at="2999-01-01T00:00:00+00:00",
    )
    grant_id = "grant-1"
    await app_ctx.pending_replay.enqueue(
        TEST_AGENT_ID, "vm-replay", elevation_id, grant_id, message
    )

    delivered: list[FrameworkMessage] = []

    async def capture(agent_id: str, vm_id: str, msg: FrameworkMessage) -> bool:
        delivered.append(msg)
        return agent_id == TEST_AGENT_ID and vm_id == "vm-replay"

    app_ctx.transport.deliver = capture  # type: ignore[method-assign]
    count = await app_ctx.pending_replay.flush_for_vm(TEST_AGENT_ID, "vm-replay")

    assert count == 1
    assert len(delivered) == 1
    assert delivered[0].type == "memory:query_response"
    assert await app_ctx.db.count_pending_replays(TEST_AGENT_ID) == 0


@pytest.mark.asyncio
async def test_flush_is_scoped_to_the_reconnecting_vm(app_ctx):
    """Two VMs of one agent queue replays; a flush only drains the matching VM's rows."""
    elevation_id = await app_ctx.db.create_elevation(
        message={"type": "memory:query"},
        context={},
        expires_at="2999-01-01T00:00:00+00:00",
    )
    await app_ctx.pending_replay.enqueue(
        TEST_AGENT_ID, "vm-a", elevation_id, "grant-a", _sample_response()
    )
    await app_ctx.pending_replay.enqueue(
        TEST_AGENT_ID, "vm-b", elevation_id, "grant-b", _sample_response()
    )

    delivered_vms: list[str] = []

    async def capture(agent_id: str, vm_id: str, msg: FrameworkMessage) -> bool:
        delivered_vms.append(vm_id)
        return True

    app_ctx.transport.deliver = capture  # type: ignore[method-assign]

    count = await app_ctx.pending_replay.flush_for_vm(TEST_AGENT_ID, "vm-a")

    assert count == 1
    assert delivered_vms == ["vm-a"]
    # vm-b's replay is untouched; vm-a's is delivered.
    assert await app_ctx.db.count_pending_replays(TEST_AGENT_ID) == 1
    assert await app_ctx.db.count_pending_replays(TEST_AGENT_ID, "vm-a") == 0
    assert await app_ctx.db.count_pending_replays(TEST_AGENT_ID, "vm-b") == 1


@pytest.mark.asyncio
async def test_flush_stops_on_delivery_failure(app_ctx):
    message = _sample_response()
    elevation_id = await app_ctx.db.create_elevation(
        message={"type": "memory:query"},
        context={},
        expires_at="2999-01-01T00:00:00+00:00",
    )
    await app_ctx.pending_replay.enqueue(
        TEST_AGENT_ID, "vm-replay", elevation_id, "grant-1", message
    )
    await app_ctx.pending_replay.enqueue(
        TEST_AGENT_ID, "vm-replay", elevation_id, "grant-1", message
    )

    call_count = 0

    async def fail_first(agent_id: str, vm_id: str, msg: FrameworkMessage) -> bool:
        nonlocal call_count
        call_count += 1
        return False

    app_ctx.transport.deliver = fail_first  # type: ignore[method-assign]
    count = await app_ctx.pending_replay.flush_for_vm(TEST_AGENT_ID, "vm-replay")

    assert count == 0
    assert call_count == 1
    assert await app_ctx.db.count_pending_replays(TEST_AGENT_ID) == 2


@pytest.mark.asyncio
async def test_replay_after_approval_queues_when_deliver_fails(app_ctx, tmp_path):
    from corvus.server.manifest import canonical_manifest, manifest_hash, resolve_manifest

    other_manifest = canonical_manifest(
        resolve_manifest(
            {"manifest_version": "1.0", "engines": {"engine4": {"namespaces": ["private"]}}}
        )
    )
    await app_ctx.db.upsert_agent("other-agent", manifest_hash(other_manifest), other_manifest)
    await app_ctx.db.create_memory_record(
        agent_id="other-agent",
        namespace="private",
        key="secret",
        content="cross-agent secret",
        metadata={},
        embedding_ref=None,
        expires_at=None,
    )

    from corvus.memory.elevation_replay import resolve_replay_message

    query = _memory_query_message()
    assert resolve_replay_message({"message": query, "context": {}}) == query

    elevation_id = await app_ctx.db.create_elevation(
        message=query,
        context={},
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

    async def always_fail(agent_id: str, vm_id: str, msg: FrameworkMessage) -> bool:
        return False

    app_ctx.transport.deliver = always_fail  # type: ignore[method-assign]

    replay = await app_ctx.elevation_replay.replay_after_approval(
        elevation_id,
        grant_id=grant_id,
        approver_user_id="admin-user",
    )
    assert replay["replayed"] is True
    assert replay["replay_delivered"] is False
    assert replay["pending_replay_queued"] is True
    assert await app_ctx.db.count_pending_replays(TEST_AGENT_ID) == 2
