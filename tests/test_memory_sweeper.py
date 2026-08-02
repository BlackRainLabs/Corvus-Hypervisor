"""Memory retention sweeper tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from corvus.memory.sweeper import MemoryRetentionSweeper
from corvus.server.bootstrap import TEST_AGENT_ID


@pytest.mark.asyncio
async def test_sweeper_purges_expired_records(app_ctx):
    expired_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    record = await app_ctx.db.create_memory_record(
        agent_id=TEST_AGENT_ID,
        namespace="private",
        key="expired",
        content="ttl expired content",
        metadata={},
        embedding_ref=None,
        expires_at=expired_at,
    )

    sweeper = MemoryRetentionSweeper(
        app_ctx.db,
        interval_seconds=3600,
        soft_delete_retention_hours=24,
    )
    expired_count, tombstones = await sweeper.sweep_once()
    assert expired_count == 1
    assert tombstones == 0
    assert await app_ctx.db.get_memory_record(record["id"]) is None


@pytest.mark.asyncio
async def test_sweeper_purges_old_soft_deleted_records(app_ctx):
    record = await app_ctx.db.create_memory_record(
        agent_id=TEST_AGENT_ID,
        namespace="private",
        key="deleted",
        content="soft deleted content",
        metadata={},
        embedding_ref=None,
        expires_at=None,
    )
    old_deleted_at = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    await app_ctx.db.conn.execute(
        """
        UPDATE memory_records
        SET deleted_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (old_deleted_at, old_deleted_at, record["id"]),
    )
    await app_ctx.db.conn.commit()

    sweeper = MemoryRetentionSweeper(
        app_ctx.db,
        interval_seconds=3600,
        soft_delete_retention_hours=24,
    )
    expired_count, tombstones = await sweeper.sweep_once()
    assert expired_count == 0
    assert tombstones == 1
    assert await app_ctx.db.get_memory_record(record["id"]) is None
