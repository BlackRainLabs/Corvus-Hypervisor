"""Engine 1 tool IPC integration tests."""

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
from corvus.runtime.tool_client import (
    build_tool_call,
    build_tool_result,
    parse_tool_call_response,
    parse_tool_result_ack,
)
from corvus.server.bootstrap import FULL_TEST_MANIFEST_HASH, TEST_AGENT_ID
from corvus.server.vsock import TransportGateway


async def _start_node_stack(app_ctx, tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = tmp_path / "node.sock"
    config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id="vm-tool-test",
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
            "content": {"text": "register turn for tools"},
        },
    )
    ack = await client.submit_and_wait(user_query)
    assert ack.payload.get("success") is True
    await client.close()
    return turn_id


@pytest.mark.asyncio
async def test_engine1_tool_call_and_result_via_server(app_ctx, tmp_path, full_manifest_agent):
    gateway, node, node_task, ipc_path, config = await _start_node_stack(app_ctx, tmp_path)
    client = NodeIpcClient(
        str(ipc_path),
        EngineId.ENGINE1,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
    )
    try:
        await client.connect()
        assert await client.wait_handshake()
        turn_id = await _register_turn(ipc_path, config.vm_id)
        tool_call = build_tool_call(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            tool_name="echo",
            arguments={"text": "integration test"},
        )
        call_ack = await client.submit_and_wait(tool_call, timeout=30.0)
        approval = parse_tool_call_response(call_ack)
        assert approval.ok is True
        assert approval.approved is True
        assert approval.tool_name == "echo"

        tool_result = build_tool_result(
            TEST_AGENT_ID,
            config.vm_id,
            turn_id,
            tool_name="echo",
            request_correlation_id=tool_call.correlation_id,
            success=True,
            result={"text": "integration test"},
            duration_ms=1,
        )
        result_ack = await client.submit_and_wait(tool_result, timeout=30.0)
        assert parse_tool_result_ack(result_ack).ok
    finally:
        await client.close()
        node.request_stop()
        await asyncio.gather(node_task, return_exceptions=True)
        await gateway.stop()
