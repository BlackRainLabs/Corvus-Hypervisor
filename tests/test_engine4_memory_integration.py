"""Engine 4 memory IPC integration tests."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from corvus.node.config import NodeConfig
from corvus.node.main import CorvusNode
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
)
from corvus.runtime.ipc_client import NodeIpcClient
from corvus.runtime.memory_client import (
    build_memory_delete,
    build_memory_grant_request,
    build_memory_query_key,
    build_memory_write,
    is_elevation_required,
    parse_memory_response,
)
from corvus.server.bootstrap import FULL_TEST_MANIFEST_HASH, TEST_AGENT_ID
from corvus.server.manifest import canonical_manifest, manifest_hash, resolve_manifest
from corvus.server.vsock import TransportGateway


def _seed_memory_write(agent_id: str, payload: dict) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=agent_id, engine=EngineId.ENGINE4, vm_id="vm"),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:write",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
        payload=payload,
    )


async def _start_node_stack(app_ctx, tmp_path, *, vm_id: str):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = tmp_path / "node.sock"
    config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id=vm_id,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
        ipc_socket_path=ipc_path,
        use_tcp=True,
        tcp_host="127.0.0.1",
        tcp_port=port,
        vsock_host_cid=2,
        vsock_port=4040,
    )
    server_config = replace(app_ctx.config, tcp_port=port, use_tcp=True)
    gateway = TransportGateway(
        server_config,
        app_ctx.handle_message,
        app_ctx.sessions.unbind_connection,
        transport=app_ctx.transport,
    )
    await gateway.start()
    await asyncio.sleep(0.05)

    node = CorvusNode(config)
    node_task = asyncio.create_task(node.run())
    for _ in range(50):
        if node.session.handshake_complete:
            break
        await asyncio.sleep(0.05)
    assert node.session.handshake_complete
    return gateway, node, node_task, ipc_path, config


async def _engine4_client(ipc_path) -> NodeIpcClient:
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE4,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
    )
    await client.connect()
    assert await client.wait_handshake()
    return client


def _build_memory_query(
    turn_id: UUID,
    vm_id: str,
    *,
    query_type: str,
    query: dict,
) -> FrameworkMessage:
    return FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id=vm_id),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="memory:query",
        correlation_id=uuid4(),
        tags=MessageTags(
            triggered_by=TriggeredBy.AGENT_INITIATED,
            origin_correlation_id=turn_id,
        ),
        payload={
            "target_agent_id": TEST_AGENT_ID,
            "namespace": "private",
            "query_type": query_type,
            "query": query,
        },
    )


async def _register_turn(ipc_path, vm_id: str) -> UUID:
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE2,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
    )
    await client.connect()
    assert await client.wait_handshake()
    turn_id = uuid4()
    user_query = FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE2, vm_id=vm_id),
        destination=MessageDestination(
            type=DestinationType.CORVUS_SERVER, target="corvus_server"
        ),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=turn_id,
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT, scope=Scope.EXTERNAL),
        security=MessageSecurity(may_leave_vm=True),
        payload={
            "user_id": "test-user",
            "platform": "api",
            "channel_id": "c1",
            "content": {"text": "register turn for engine4"},
        },
    )
    ack = await client.submit_and_wait(user_query)
    assert ack.payload.get("success") is True
    await client.close()
    return turn_id


@pytest.mark.asyncio
async def test_engine4_memory_full_cycle_via_node(app_ctx, tmp_path, full_manifest_agent):
    """Engine 4 → Node → Server → MemoryService → Node → Engine 4."""
    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx, tmp_path, vm_id="vm-engine4-full-cycle"
    )
    client = await _engine4_client(ipc_path)

    try:
        turn_id = await _register_turn(ipc_path, config.vm_id)
        records = (
            ("cats", "The cat sat on the mat near the window"),
            ("physics", "Quantum field theory and particle physics research"),
        )
        record_ids: list[str] = []
        for key, content in records:
            write_result = parse_memory_response(
                await client.submit_and_wait(
                    build_memory_write(
                        TEST_AGENT_ID,
                        config.vm_id,
                        turn_id,
                        key=key,
                        content=content,
                    )
                )
            )
            assert write_result.ok is True
            assert write_result.record_id
            record_ids.append(write_result.record_id)

        key_result = parse_memory_response(
            await client.submit_and_wait(
                build_memory_query_key(
                    TEST_AGENT_ID,
                    config.vm_id,
                    turn_id,
                    key="cats",
                )
            )
        )
        assert key_result.ok is True
        assert key_result.records
        assert key_result.records[0]["content"] == records[0][1]

        semantic_result = parse_memory_response(
            await client.submit_and_wait(
                _build_memory_query(
                    turn_id,
                    config.vm_id,
                    query_type="semantic",
                    query={"text": "cat on the mat", "limit": 1},
                )
            )
        )
        assert semantic_result.ok is True
        assert semantic_result.records
        assert semantic_result.records[0]["key"] == "cats"

        list_result = parse_memory_response(
            await client.submit_and_wait(
                _build_memory_query(
                    turn_id,
                    config.vm_id,
                    query_type="list",
                    query={"limit": 10},
                )
            )
        )
        assert list_result.ok is True
        assert len(list_result.records) == 2

        delete_result = parse_memory_response(
            await client.submit_and_wait(
                build_memory_delete(
                    TEST_AGENT_ID,
                    config.vm_id,
                    turn_id,
                    record_id=record_ids[0],
                )
            )
        )
        assert delete_result.ok is True

        missing = parse_memory_response(
            await client.submit_and_wait(
                build_memory_query_key(
                    TEST_AGENT_ID,
                    config.vm_id,
                    turn_id,
                    key="cats",
                )
            )
        )
        assert missing.ok is True
        assert missing.records == []
    finally:
        await client.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()


@pytest.mark.asyncio
async def test_engine4_ipc_write_and_query(app_ctx, tmp_path, full_manifest_agent):
    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx, tmp_path, vm_id="vm-engine4-ipc"
    )
    client = await _engine4_client(ipc_path)

    try:
        turn_id = await _register_turn(ipc_path, config.vm_id)
        write_msg = build_memory_write(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            key="ipc-note",
            content="via engine4 ipc",
        )
        write_result = parse_memory_response(await client.submit_and_wait(write_msg))
        assert write_result.ok is True
        assert write_result.record_id

        query_msg = build_memory_query_key(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            key="ipc-note",
        )
        query_result = parse_memory_response(await client.submit_and_wait(query_msg))
        assert query_result.ok is True
        assert query_result.records
        assert query_result.records[0]["content"] == "via engine4 ipc"
    finally:
        await client.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()


@pytest.mark.asyncio
async def test_engine4_cross_agent_query_with_grant(app_ctx, tmp_path, full_manifest_agent):
    other_manifest = canonical_manifest(
        resolve_manifest(
            {
                "manifest_version": "1.0",
                "engines": {"engine4": {"namespaces": ["private"]}},
            }
        )
    )
    await app_ctx.db.upsert_agent("other-agent", manifest_hash(other_manifest), other_manifest)

    seed = _seed_memory_write(
        "other-agent",
        {
            "target_agent_id": "other-agent",
            "namespace": "private",
            "record": {"key": "shared-note", "content": "cross-agent secret"},
        },
    )
    seeded = await app_ctx.memory.write(seed, grant_id=None)
    assert seeded.success is True

    grant_id = await app_ctx.db.create_grant(
        subject_agent=TEST_AGENT_ID,
        target_agent="other-agent",
        namespace="private",
        permissions=["read"],
        created_by="test",
    )

    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx, tmp_path, vm_id="vm-engine4-cross"
    )
    client = await _engine4_client(ipc_path)

    try:
        turn_id = await _register_turn(ipc_path, config.vm_id)
        query_msg = build_memory_query_key(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            namespace="private",
            key="shared-note",
            target_agent_id="other-agent",
            grant_id=grant_id,
        )
        query_result = parse_memory_response(await client.submit_and_wait(query_msg))
        assert query_result.ok is True
        assert query_result.records
        assert query_result.records[0]["content"] == "cross-agent secret"
    finally:
        await client.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()


@pytest.mark.asyncio
async def test_engine4_elevation_emits_grant_request(app_ctx, tmp_path, full_manifest_agent):
    other_manifest = canonical_manifest(
        resolve_manifest(
            {
                "manifest_version": "1.0",
                "engines": {"engine4": {"namespaces": ["private"]}},
            }
        )
    )
    await app_ctx.db.upsert_agent("other-agent", manifest_hash(other_manifest), other_manifest)

    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx, tmp_path, vm_id="vm-engine4-elev"
    )
    client = await _engine4_client(ipc_path)

    try:
        turn_id = await _register_turn(ipc_path, config.vm_id)
        query_msg = build_memory_query_key(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            namespace="private",
            key="missing",
            target_agent_id="other-agent",
        )
        query_result = parse_memory_response(await client.submit_and_wait(query_msg))
        assert is_elevation_required(query_result)
        assert query_result.elevation_id

        grant_req = build_memory_grant_request(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            target_agent_id="other-agent",
            namespace="private",
            permissions=["read"],
            reason="Need read access for integration test",
        )
        grant_result = parse_memory_response(await client.submit_and_wait(grant_req))
        assert is_elevation_required(grant_result)
        assert grant_result.elevation_id
    finally:
        await client.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()


@pytest.mark.asyncio
async def test_elevation_auto_replay_after_management_approval(
    app_ctx, tmp_path, full_manifest_agent
):
    from httpx import ASGITransport, AsyncClient

    from corvus.management.api import create_app

    other_manifest = canonical_manifest(
        resolve_manifest(
            {
                "manifest_version": "1.0",
                "engines": {"engine4": {"namespaces": ["private"]}},
            }
        )
    )
    await app_ctx.db.upsert_agent("other-agent", manifest_hash(other_manifest), other_manifest)
    await app_ctx.db.create_memory_record(
        agent_id="other-agent",
        namespace="private",
        key="shared-note",
        content="cross-agent secret",
        metadata={},
        embedding_ref=None,
        expires_at=None,
    )

    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx, tmp_path, vm_id="vm-engine4-replay"
    )
    client = await _engine4_client(ipc_path)

    try:
        turn_id = await _register_turn(ipc_path, config.vm_id)
        query_msg = build_memory_query_key(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            namespace="private",
            key="shared-note",
            target_agent_id="other-agent",
        )
        denied = parse_memory_response(await client.submit_and_wait(query_msg))
        assert is_elevation_required(denied)

        elevations = await app_ctx.db.list_elevations(status="pending")
        elevation_id = elevations[0]["id"]

        app = create_app(app_ctx)
        transport = ASGITransport(app=app)
        headers = {"X-API-Key": app_ctx.config.api_key}
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            approved = await http.post(
                f"/v1/elevations/{elevation_id}/approve",
                headers=headers,
                json={
                    "approver_user_id": "admin-user",
                    "pin": "0000",
                    "create_grant": {
                        "subject_agent": TEST_AGENT_ID,
                        "target_agent": "other-agent",
                        "namespace": "private",
                        "permissions": ["read"],
                    },
                },
            )
        assert approved.status_code == 200
        body = approved.json()
        assert body["replay"]["replayed"] is True
        assert body["replay"]["success"] is True

        replay_response = await client.wait_inbound(timeout=5.0)
        assert replay_response.type == "memory:query_response"
        assert replay_response.payload["success"] is True
        assert replay_response.payload["records"][0]["content"] == "cross-agent secret"
    finally:
        await client.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()


@pytest.mark.asyncio
async def test_elevation_replay_on_reconnect_after_offline_approval(
    app_ctx, tmp_path, full_manifest_agent
):
    from httpx import ASGITransport, AsyncClient

    from corvus.management.api import create_app

    other_manifest = canonical_manifest(
        resolve_manifest(
            {
                "manifest_version": "1.0",
                "engines": {"engine4": {"namespaces": ["private"]}},
            }
        )
    )
    await app_ctx.db.upsert_agent("other-agent", manifest_hash(other_manifest), other_manifest)
    await app_ctx.db.create_memory_record(
        agent_id="other-agent",
        namespace="private",
        key="shared-note",
        content="cross-agent secret",
        metadata={},
        embedding_ref=None,
        expires_at=None,
    )

    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx, tmp_path, vm_id="vm-engine4-offline-replay"
    )
    client = await _engine4_client(ipc_path)

    try:
        turn_id = await _register_turn(ipc_path, config.vm_id)
        query_msg = build_memory_query_key(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            namespace="private",
            key="shared-note",
            target_agent_id="other-agent",
        )
        denied = parse_memory_response(await client.submit_and_wait(query_msg))
        assert is_elevation_required(denied)

        elevations = await app_ctx.db.list_elevations(status="pending")
        elevation_id = elevations[0]["id"]

        await client.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()
        assert not app_ctx.transport.is_agent_connected(TEST_AGENT_ID, config.vm_id)

        app = create_app(app_ctx)
        asgi_transport = ASGITransport(app=app)
        headers = {"X-API-Key": app_ctx.config.api_key}
        async with AsyncClient(transport=asgi_transport, base_url="http://test") as http:
            approved = await http.post(
                f"/v1/elevations/{elevation_id}/approve",
                headers=headers,
                json={
                    "approver_user_id": "admin-user",
                    "pin": "0000",
                    "create_grant": {
                        "subject_agent": TEST_AGENT_ID,
                        "target_agent": "other-agent",
                        "namespace": "private",
                        "permissions": ["read"],
                    },
                },
            )
        assert approved.status_code == 200
        body = approved.json()
        assert body["replay"]["replayed"] is True
        assert body["replay"]["replay_delivered"] is False
        assert body["pending_replay_queued"] is True
        assert await app_ctx.db.count_pending_replays(TEST_AGENT_ID) == 2

        gateway, node, node_task, ipc_path, config = await _start_node_stack(
            app_ctx, tmp_path, vm_id="vm-engine4-offline-replay"
        )
        client = await _engine4_client(ipc_path)

        replay_response = await client.wait_inbound(timeout=5.0)
        assert replay_response.type == "memory:query_response"
        assert replay_response.payload["success"] is True
        assert replay_response.payload["records"][0]["content"] == "cross-agent secret"

        grant_created = await client.wait_inbound(timeout=5.0)
        assert grant_created.type == "memory:grant_created"
        assert grant_created.payload["elevation_id"] == elevation_id
        assert await app_ctx.db.count_pending_replays(TEST_AGENT_ID) == 0
    finally:
        await client.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()
