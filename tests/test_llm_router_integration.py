"""TCP stack integration: Engine 3 receives server-origin llm_response."""

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
from corvus.runtime.llm_client import build_llm_request, parse_llm_response
from corvus.server.bootstrap import TEST_AGENT_ID, TEST_MANIFEST_HASH
from corvus.server.vsock import TransportGateway


async def _start_node_stack(app_ctx, tmp_path, *, vm_id: str = "vm-llm-test"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = tmp_path / "node.sock"
    config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id=vm_id,
        manifest_hash=TEST_MANIFEST_HASH,
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
        manifest_hash=TEST_MANIFEST_HASH,
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
            "content": {"text": "register turn for llm"},
        },
    )
    ack = await client.submit_and_wait(user_query)
    assert ack.payload.get("success") is True
    await client.close()
    return turn_id


@pytest.mark.asyncio
async def test_engine3_receives_server_llm_response(app_ctx, tmp_path):
    gateway, node, node_task, ipc_path, config = await _start_node_stack(app_ctx, tmp_path)
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE3,
        manifest_hash=TEST_MANIFEST_HASH,
    )
    try:
        await client.connect()
        assert await client.wait_handshake()
        turn_id = await _register_turn(ipc_path, config.vm_id)
        llm_req = build_llm_request(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            provider="stub",
            model="stub-v1",
            messages=[{"role": "user", "content": "integration test"}],
        )
        inbound = await client.submit_and_wait(llm_req, timeout=30.0)
        assert inbound.type == "llm_response"
        result = parse_llm_response(inbound)
        assert result.ok is True
        assert result.provider == "stub"
        assert "integration test" in (result.content or "")
        assert "api_key" not in str(inbound.payload).lower()
    finally:
        await client.close()
        node.request_stop()
        await asyncio.gather(node_task, return_exceptions=True)
        await gateway.stop()


@pytest.mark.asyncio
async def test_llm_audit_row_written(app_ctx, tmp_path):
    gateway, node, node_task, ipc_path, config = await _start_node_stack(app_ctx, tmp_path)
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE3,
        manifest_hash=TEST_MANIFEST_HASH,
    )
    try:
        await client.connect()
        assert await client.wait_handshake()
        turn_id = await _register_turn(ipc_path, config.vm_id)
        llm_req = build_llm_request(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            provider="stub",
            model="stub-v1",
            messages=[{"role": "user", "content": "audit me"}],
        )
        await client.submit_and_wait(llm_req, timeout=30.0)
        logs = await app_ctx.audit.query_logs(event_type="llm_completion", limit=20)
        assert logs
        latest = logs[0]
        assert latest["details"]["provider"] == "stub"
        assert latest["details"]["model"] == "stub-v1"
        assert "api_key" not in str(latest).lower()
    finally:
        await client.close()
        node.request_stop()
        await asyncio.gather(node_task, return_exceptions=True)
        await gateway.stop()
