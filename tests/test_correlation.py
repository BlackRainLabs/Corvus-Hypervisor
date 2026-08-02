"""Correlation store and router validation tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSecurity,
    MessageSource,
    MessageTags,
    Scope,
    TriggeredBy,
    decode_line,
    encode_message,
)
from corvus.server.bootstrap import TEST_AGENT_ID, TEST_MANIFEST_HASH
from corvus.server.config import ServerConfig
from corvus.server.correlation import CorrelationStore
from corvus.server.db import Database
from corvus.server.vsock import TransportGateway


def _rules_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "default_rules.yaml"


def _server_config(tmp_path: Path, **overrides) -> ServerConfig:
    defaults = {
        "db_path": tmp_path / "corr.db",
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


async def _open_store(tmp_path: Path, **config_overrides) -> tuple[Database, CorrelationStore]:
    config = _server_config(tmp_path, **config_overrides)
    db = Database(config.db_path)
    await db.connect()
    store = CorrelationStore(db, config)
    await store.startup()
    return db, store


def _user_query(turn_id, *, token: str | None = None) -> FrameworkMessage:
    payload: dict = {
        "user_id": "test-user",
        "platform": "api",
        "channel_id": "c1",
        "content": {"text": "hello"},
    }
    if token:
        payload["_session"] = {"token": token}
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE2, vm_id="vm-corr"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=turn_id,
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT, scope=Scope.EXTERNAL),
        security=MessageSecurity(may_leave_vm=True),
        payload=payload,
    )


def _memory_write(turn_id, *, token: str) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id="vm-corr"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:write",
        correlation_id=uuid4(),
        tags=MessageTags(
            triggered_by=TriggeredBy.AGENT_INITIATED,
            origin_correlation_id=turn_id,
        ),
        payload={
            "_session": {"token": token},
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "record": {"key": "corr-note", "content": "correlation test"},
        },
    )


@pytest.mark.asyncio
async def test_correlation_store_valid_turn_chain(tmp_path):
    db, store = await _open_store(tmp_path)
    try:
        turn_id = uuid4()
        await store.register_user_query(_user_query(turn_id))

        valid, error = await store.validate(_memory_write(turn_id, token="unused"))
        assert valid is True
        assert error is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_correlation_store_rejects_unknown_origin(tmp_path):
    db, store = await _open_store(tmp_path)
    try:
        valid, error = await store.validate(_memory_write(uuid4(), token="unused"))
        assert valid is False
        assert error == "SERVER_CORRELATION_INVALID"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_correlation_store_rejects_expired_turn(tmp_path):
    db, store = await _open_store(tmp_path, turn_timeout_seconds=60)
    try:
        turn_id = uuid4()
        await store.register_user_query(_user_query(turn_id))
        stale = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
        await db.conn.execute(
            "UPDATE turn_state SET last_activity = ? WHERE root_correlation_id = ?",
            (stale, str(turn_id)),
        )
        await db.conn.commit()

        valid, error = await store.validate(_memory_write(turn_id, token="unused"))
        assert valid is False
        assert error == "SERVER_CORRELATION_EXPIRED"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_correlation_store_rejects_max_depth(tmp_path):
    db, store = await _open_store(tmp_path, max_chain_depth=1)
    try:
        turn_id = uuid4()
        await store.register_user_query(_user_query(turn_id))

        first = _memory_write(turn_id, token="unused")
        assert await store.validate(first) == (True, None)
        second = _memory_write(turn_id, token="unused")
        valid, error = await store.validate(second)
        assert valid is False
        assert error == "SERVER_CORRELATION_INVALID"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_correlation_store_persists_across_restart(tmp_path):
    db, store = await _open_store(tmp_path)
    turn_id = uuid4()
    await store.register_user_query(_user_query(turn_id))
    await db.close()

    db2, store2 = await _open_store(tmp_path)
    try:
        valid, error = await store2.validate(_memory_write(turn_id, token="unused"))
        assert valid is True
        assert error is None
    finally:
        await db2.close()


@pytest.mark.asyncio
async def test_router_rejects_memory_without_registered_turn(app_ctx):
    import socket
    from dataclasses import replace

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    config = replace(app_ctx.config, tcp_port=port, use_tcp=True)
    gateway = TransportGateway(
        config,
        app_ctx.handle_message,
        app_ctx.sessions.unbind_connection,
        transport=app_ctx.transport,
    )
    await gateway.start()
    await asyncio.sleep(0.05)

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        vm_id = "vm-corr"
        hs = FrameworkMessage(
            source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.CORVUS_NODE, vm_id=vm_id),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.SYSTEM,
            type="handshake",
            correlation_id=uuid4(),
            tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
            payload={
                "manifest_hash": TEST_MANIFEST_HASH,
                "protocol_version": "2.0",
                "vm_instance_id": vm_id,
                "agent_id": TEST_AGENT_ID,
                "registered_engines": ["engine1", "engine2", "engine3", "engine4"],
            },
        )
        writer.write((encode_message(hs) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        token = decode_line(line.decode()).payload["session_token"]

        orphan_turn = uuid4()
        bad = _memory_write(orphan_turn, token=token)
        writer.write((encode_message(bad) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        err = decode_line(line.decode())
        assert err.message_class == MessageClass.ERROR
        assert err.payload["code"] == "SERVER_CORRELATION_INVALID"
        writer.close()
        await writer.wait_closed()
    finally:
        await gateway.stop()
