"""Phase 5.4 production hardening tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from corvus.management.api import create_app
from corvus.memory.encryption import decrypt_content, encrypt_content
from corvus.policy.quota import QuotaService
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
from corvus.server.bootstrap import TEST_AGENT_ID, AppContext
from corvus.server.config import ServerConfig


def _rules_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "default_rules.yaml"


def _server_config(tmp_path: Path, **overrides) -> ServerConfig:
    defaults = {
        "db_path": tmp_path / "prod.db",
        "use_tcp": True,
        "tcp_host": "127.0.0.1",
        "tcp_port": 0,
        "vsock_host_cid": 2,
        "vsock_port": 4040,
        "mgmt_host": "127.0.0.1",
        "mgmt_port": 0,
        "api_key": "test-key",
        "rules_path": _rules_path(),
        "turn_timeout_seconds": 300,
        "max_chain_depth": 8,
        "session_ttl_hours": 24,
        "vm_state_dir": tmp_path / "vms",
        "memory_sweep_interval_seconds": 86400.0,
        "memory_soft_delete_retention_hours": 24,
        "elevation_sweep_interval_seconds": 86400.0,
        "elevation_ttl_hours": 1,
        "elevation_webhook_url": None,
        "behavioral_grant_denial_window_minutes": 10,
        "behavioral_grant_denial_threshold": 3,
        "behavioral_cross_agent_window_minutes": 1,
        "behavioral_cross_agent_threshold": 10,
        "behavioral_rate_baseline_minutes": 60,
        "behavioral_rate_zscore_threshold": 3.0,
        "behavioral_tool_zscore_threshold": 3.0,
        "behavioral_counter_retention_hours": 24,
        "memory_encryption_enabled": False,
        "memory_master_key": None,
        "memory_writes_daily_limit": 10_000,
        "llm_providers_path": Path(__file__).resolve().parents[1] / "config" / "llm_providers.yaml",
        "llm_default_provider": "stub",
        "llm_request_timeout_seconds": 60.0,
        "llm_tokens_daily_limit": 100_000,
    }
    defaults.update(overrides)
    return ServerConfig(**defaults)


def _memory_write_message(*, content: str = "secret payload") -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:write",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "record": {"key": "enc-key", "content": content},
        },
    )


def _memory_query_message() -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "query_type": "key",
            "query": {"key": "enc-key"},
        },
    )


def test_encryption_helpers_round_trip():
    encoded = encrypt_content(
        master_key="master-secret",
        agent_id=TEST_AGENT_ID,
        plaintext="hello encrypted world",
    )
    assert encoded != "hello encrypted world"
    assert (
        decrypt_content(
            master_key="master-secret",
            agent_id=TEST_AGENT_ID,
            encoded=encoded,
        )
        == "hello encrypted world"
    )


@pytest.mark.asyncio
async def test_quota_increment_memory_write(app_ctx):
    counter = await app_ctx.quotas.increment_memory_write(TEST_AGENT_ID)
    assert counter["used"] == 1
    assert counter["limit"] == app_ctx.config.memory_writes_daily_limit

    stored = await app_ctx.db.get_quota_counter(QuotaService.memory_write_key(TEST_AGENT_ID))
    assert stored is not None
    assert stored["used"] == 1


@pytest.mark.asyncio
async def test_memory_encryption_round_trip(tmp_path):
    config = _server_config(
        tmp_path,
        memory_encryption_enabled=True,
        memory_master_key="phase-54-master-key",
    )
    ctx = AppContext(config)
    await ctx.startup()
    from corvus.server.bootstrap import FULL_TEST_MANIFEST, FULL_TEST_MANIFEST_HASH, TEST_AGENT_ID

    await ctx.db.upsert_agent(TEST_AGENT_ID, FULL_TEST_MANIFEST_HASH, FULL_TEST_MANIFEST)
    try:
        write = _memory_write_message(content="classified note")
        result = await ctx.memory.write(write, grant_id=None)
        assert result.success is True

        rows = await ctx.db.query_memory_by_key(
            agent_id=TEST_AGENT_ID,
            namespace="private",
            key="enc-key",
            now=datetime.now(UTC),
            limit=1,
        )
        assert len(rows) == 1
        assert rows[0]["metadata"]["encrypted"] is True
        assert rows[0]["content"] != "classified note"

        query = _memory_query_message()
        queried = await ctx.memory.query(query, grant_id=None)
        assert queried.success is True
        assert len(queried.records) == 1
        assert queried.records[0].content == "classified note"
    finally:
        await ctx.shutdown()


@pytest.mark.asyncio
async def test_health_reports_ops_metrics(app_ctx):
    app = create_app(app_ctx)
    headers = {"X-API-Key": app_ctx.config.api_key}
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/v1/health", headers=headers)
        assert health.status_code == 200
        server = health.json()["server"]
        assert server["memory_sweeper_running"] is True
        assert server["elevation_sweeper_running"] is True
        assert server["pending_replay_depth"] == 0
        assert "behavioral_counters_latest_at" in server


@pytest.mark.asyncio
async def test_production_state_survives_restart(tmp_path):
    config = _server_config(tmp_path)
    ctx = AppContext(config)
    await ctx.startup()

    await ctx.quotas.increment_memory_write(TEST_AGENT_ID)
    hop = FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload={"target_agent_id": "other-agent", "namespace": "private"},
    )
    await ctx.behavioral.record_message_hop(hop)

    elevation_id = await ctx.db.create_elevation(
        message={"type": "memory:query"},
        context={},
        expires_at="2999-01-01T00:00:00+00:00",
    )
    await ctx.pending_replay.enqueue(
        TEST_AGENT_ID,
        "vm-persist",
        elevation_id,
        "grant-persist",
        FrameworkMessage(
            source=MessageSource(
                agent_id="corvus-server", engine=EngineId.CORVUS_NODE, vm_id="server"
            ),
            destination=MessageDestination(type=DestinationType.ENGINE, target="engine4"),
            message_class=MessageClass.RESPONSE,
            type="memory:query_response",
            correlation_id=uuid4(),
            tags=MessageTags(triggered_by=TriggeredBy.MEMORY_RESULT),
            payload={"success": True, "records": []},
        ),
    )
    quota_key = QuotaService.memory_write_key(TEST_AGENT_ID)
    await ctx.shutdown()

    ctx2 = AppContext(config)
    await ctx2.startup()
    try:
        quota = await ctx2.db.get_quota_counter(quota_key)
        assert quota is not None
        assert quota["used"] == 1
        assert await ctx2.db.count_pending_replays() == 1
        assert await ctx2.db.get_latest_behavioral_counter_activity() is not None
    finally:
        await ctx2.shutdown()
