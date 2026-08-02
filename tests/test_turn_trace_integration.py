"""Turn trace audit linkage integration tests."""

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
from corvus.runtime.memory_client import build_memory_write, parse_memory_response
from corvus.server.bootstrap import FULL_TEST_MANIFEST_HASH, TEST_AGENT_ID
from corvus.server.vsock import TransportGateway


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
            "content": {"text": "register turn for trace test"},
        },
    )
    ack = await client.submit_and_wait(user_query)
    assert ack.payload.get("success") is True
    await client.close()
    return turn_id


@pytest.mark.asyncio
async def test_turn_trace_links_audit_by_origin_correlation_id(
    app_ctx, tmp_path, full_manifest_agent
):
    gateway, node, node_task, ipc_path, config = await _start_node_stack(
        app_ctx, tmp_path, vm_id="vm-turn-trace"
    )
    engine4 = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE4,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
    )
    await engine4.connect()
    assert await engine4.wait_handshake()

    try:
        turn_id = await _register_turn(ipc_path, config.vm_id)
        write_result = parse_memory_response(
            await engine4.submit_and_wait(
                build_memory_write(
                    TEST_AGENT_ID,
                    config.vm_id,
                    turn_id,
                    key="trace-note",
                    content="turn trace content",
                )
            )
        )
        assert write_result.ok is True

        logs = await app_ctx.audit.query_logs(
            origin_correlation_id=str(turn_id),
            agent_id=TEST_AGENT_ID,
            limit=50,
        )
        event_types = {entry["event_type"] for entry in logs}
        hop_types = {
            entry["details"].get("type")
            for entry in logs
            if entry["event_type"] == "message_hop"
        }

        assert "message_hop" in event_types
        assert "user_query" in hop_types
        assert "memory:write" in hop_types
        assert "policy_decision" in event_types
        assert "memory_write" in event_types
        assert all(
            entry.get("origin_correlation_id") == str(turn_id)
            for entry in logs
            if entry.get("origin_correlation_id")
        )
    finally:
        await engine4.close()
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()
