"""Memory Service MVP tests."""

from datetime import UTC, datetime, timedelta
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
from corvus.server.manifest import canonical_manifest, manifest_hash, resolve_manifest

pytestmark = pytest.mark.usefixtures("full_manifest_agent")


def _memory_message(
    message_type: str,
    payload: dict,
    *,
    agent_id: str = TEST_AGENT_ID,
) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE4, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type=message_type,
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload=payload,
    )


@pytest.mark.asyncio
async def test_own_namespace_write_and_key_query(app_ctx):
    write = _memory_message(
        "memory:write",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "record": {"key": "note-1", "content": "hello memory"},
        },
    )
    result = await app_ctx.memory.write(write, grant_id=None)
    assert result.success is True
    assert result.record_id

    query = _memory_message(
        "memory:query",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "query_type": "key",
            "query": {"key": "note-1"},
        },
    )
    result = await app_ctx.memory.query(query, grant_id=None)
    assert result.success is True
    assert len(result.records) == 1
    assert result.records[0].content == "hello memory"


@pytest.mark.asyncio
async def test_list_query_and_delete(app_ctx):
    for index in range(2):
        write = _memory_message(
            "memory:write",
            {
                "target_agent_id": TEST_AGENT_ID,
                "namespace": "private",
                "record": {"key": f"item-{index}", "content": f"value-{index}"},
            },
        )
        await app_ctx.memory.write(write, grant_id=None)

    list_query = _memory_message(
        "memory:query",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "query_type": "list",
            "query": {"limit": 10},
        },
    )
    listed = await app_ctx.memory.query(list_query, grant_id=None)
    assert listed.success is True
    assert len(listed.records) == 2

    record_id = listed.records[0].id
    delete = _memory_message(
        "memory:delete",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "record_id": record_id,
        },
    )
    deleted = await app_ctx.memory.delete(delete, grant_id=None)
    assert deleted.success is True
    assert deleted.deleted is True

    listed_after = await app_ctx.memory.query(list_query, grant_id=None)
    assert len(listed_after.records) == 1


@pytest.mark.asyncio
async def test_semantic_query_finds_similar_content(app_ctx):
    for key, content in (
        ("cats", "The cat sat on the mat near the window"),
        ("physics", "Quantum field theory and particle physics research"),
    ):
        write = _memory_message(
            "memory:write",
            {
                "target_agent_id": TEST_AGENT_ID,
                "namespace": "private",
                "record": {"key": key, "content": content},
            },
        )
        assert (await app_ctx.memory.write(write, grant_id=None)).success is True

    query = _memory_message(
        "memory:query",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "query_type": "semantic",
            "query": {"text": "cat on the mat", "limit": 1},
        },
    )
    result = await app_ctx.memory.query(query, grant_id=None)
    assert result.success is True
    assert len(result.records) == 1
    assert result.records[0].key == "cats"


@pytest.mark.asyncio
async def test_semantic_query_requires_text(app_ctx):
    query = _memory_message(
        "memory:query",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "query_type": "semantic",
            "query": {},
        },
    )
    result = await app_ctx.memory.query(query, grant_id=None)
    assert result.success is False
    assert result.error_code == "MEMORY_QUERY_INVALID"


@pytest.mark.asyncio
async def test_cross_agent_requires_grant_at_service_boundary(app_ctx):
    other_manifest = canonical_manifest(
        resolve_manifest(
            {
                "manifest_version": "1.0",
                "engines": {"engine4": {"namespaces": ["private"]}},
            }
        )
    )
    await app_ctx.db.upsert_agent("other-agent", manifest_hash(other_manifest), other_manifest)

    query = _memory_message(
        "memory:query",
        {
            "target_agent_id": "other-agent",
            "namespace": "private",
            "query_type": "list",
            "query": {"limit": 5},
        },
    )
    result = await app_ctx.memory.query(query, grant_id=None)
    assert result.success is False
    assert result.error_code == "SERVER_GRANT_DENIED"

    grant_id = await app_ctx.db.create_grant(
        subject_agent=TEST_AGENT_ID,
        target_agent="other-agent",
        namespace="private",
        permissions=["read"],
        created_by="test",
    )
    result = await app_ctx.memory.query(query, grant_id=grant_id)
    assert result.success is True


@pytest.mark.asyncio
async def test_namespace_quota_enforcement(app_ctx):
    await app_ctx.db.upsert_namespace_quota(
        agent_id=TEST_AGENT_ID,
        namespace="private",
        max_records=1,
        max_record_bytes=65536,
        default_ttl_seconds=None,
    )

    first = _memory_message(
        "memory:write",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "record": {"key": "one", "content": "first"},
        },
    )
    assert (await app_ctx.memory.write(first, grant_id=None)).success is True

    second = _memory_message(
        "memory:write",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "record": {"key": "two", "content": "second"},
        },
    )
    result = await app_ctx.memory.write(second, grant_id=None)
    assert result.success is False
    assert result.error_code == "SERVER_QUOTA_EXCEEDED"


@pytest.mark.asyncio
async def test_expired_records_are_not_returned(app_ctx):
    expired_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    await app_ctx.db.create_memory_record(
        agent_id=TEST_AGENT_ID,
        namespace="private",
        key="expired",
        content="gone",
        metadata={},
        embedding_ref=None,
        expires_at=expired_at,
    )

    query = _memory_message(
        "memory:query",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "query_type": "key",
            "query": {"key": "expired"},
        },
    )
    result = await app_ctx.memory.query(query, grant_id=None)
    assert result.success is True
    assert result.records == []


@pytest.mark.asyncio
async def test_memory_write_audit_logged(app_ctx):
    write = _memory_message(
        "memory:write",
        {
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "record": {"key": "audit", "content": "tracked"},
        },
    )
    result = await app_ctx.memory.write(write, grant_id=None)
    assert result.success is True

    logs = await app_ctx.audit.query_logs(event_type="memory_write")
    assert logs
    assert logs[0]["details"]["target_agent_id"] == TEST_AGENT_ID
    assert logs[0]["details"]["namespace"] == "private"
    assert logs[0]["details"]["record_id"] == result.record_id
