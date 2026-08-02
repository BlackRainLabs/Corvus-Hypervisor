"""Corvus Node end-to-end integration tests."""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import replace
from uuid import uuid4

import pytest

from corvus.node.config import NodeConfig
from corvus.node.main import CorvusNode
from corvus.node.models import IpcOperation
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
)
from corvus.server.bootstrap import TEST_AGENT_ID, TEST_MANIFEST_HASH
from corvus.server.vsock import TransportGateway


async def _ipc_roundtrip(sock_path: str, envelope: dict) -> dict:
    reader, writer = await asyncio.open_unix_connection(sock_path)
    writer.write((json.dumps(envelope) + "\n").encode("utf-8"))
    await writer.drain()
    line = await reader.readline()
    writer.close()
    await writer.wait_closed()
    return json.loads(line.decode("utf-8"))


async def _ipc_session(sock_path: str, engine: str):
    reader, writer = await asyncio.open_unix_connection(sock_path)
    sub = {
        "operation": IpcOperation.SUBSCRIBE_ENGINE.value,
        "engine": engine,
        "payload": {"manifest_engine_hash": TEST_MANIFEST_HASH},
    }
    writer.write((json.dumps(sub) + "\n").encode("utf-8"))
    await writer.drain()
    line = await reader.readline()
    assert json.loads(line.decode("utf-8")).get("accepted") is True
    return reader, writer


@pytest.mark.asyncio
async def test_node_ipc_user_query(app_ctx, tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = str(tmp_path / "node.sock")
    config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id="vm-node-test",
        manifest_hash=TEST_MANIFEST_HASH,
        ipc_socket_path=tmp_path / "node.sock",
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

    try:
        for _ in range(50):
            if node.session.handshake_complete:
                break
            await asyncio.sleep(0.05)
        assert node.session.handshake_complete

        health = await _ipc_roundtrip(
            ipc_path,
            {"operation": IpcOperation.HEALTH_CHECK.value, "engine": "engine2"},
        )
        assert health["status"] == "ok"
        assert health["handshake_complete"] is True

        reader, writer = await _ipc_session(ipc_path, "engine2")
        uq = FrameworkMessage(
            source=MessageSource(
                agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE2, vm_id=config.vm_id
            ),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.REQUEST,
            type="user_query",
            correlation_id=uuid4(),
            tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT, scope=Scope.EXTERNAL),
            security=MessageSecurity(may_leave_vm=True),
            payload={
                "user_id": "test-user",
                "platform": "api",
                "channel_id": "c1",
                "content": {"text": "hello via node"},
            },
        )
        submit = {
            "operation": IpcOperation.SUBMIT_OUTBOUND.value,
            "engine": "engine2",
            "message": uq.model_dump(mode="json", by_alias=True),
        }
        writer.write((json.dumps(submit) + "\n").encode("utf-8"))
        await writer.drain()

        submit_line = await reader.readline()
        submit_resp = json.loads(submit_line.decode("utf-8"))
        assert submit_resp["accepted"] is True

        inbound_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        inbound = json.loads(inbound_line.decode("utf-8"))
        assert inbound["operation"] == IpcOperation.RECEIVE_INBOUND.value
        ack = decode_line(json.dumps(inbound["message"]))
        assert ack.payload.get("success") is True

        writer.close()
        await writer.wait_closed()
    finally:
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()


@pytest.mark.asyncio
async def test_node_rejects_engine3_memory_query(app_ctx, tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = str(tmp_path / "node.sock")
    config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id="vm-node-deny",
        manifest_hash=TEST_MANIFEST_HASH,
        ipc_socket_path=tmp_path / "node.sock",
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

    try:
        for _ in range(50):
            if node.session.handshake_complete:
                break
            await asyncio.sleep(0.05)
        assert node.session.handshake_complete

        reader, writer = await _ipc_session(ipc_path, "engine3")
        bad = FrameworkMessage(
            source=MessageSource(
                agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE3, vm_id=config.vm_id
            ),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.REQUEST,
            type="memory:query",
            correlation_id=uuid4(),
            tags=MessageTags(triggered_by=TriggeredBy.AGENT_INITIATED),
            payload={"namespace": "private"},
        )
        submit = {
            "operation": IpcOperation.SUBMIT_OUTBOUND.value,
            "engine": "engine3",
            "message": bad.model_dump(mode="json", by_alias=True),
        }
        writer.write((json.dumps(submit) + "\n").encode("utf-8"))
        await writer.drain()
        line = await reader.readline()
        resp = json.loads(line.decode("utf-8"))
        assert resp["accepted"] is False
        assert resp["error"]["payload"]["code"] == "NODE_CAPABILITY_DENIED"

        writer.close()
        await writer.wait_closed()
    finally:
        node.request_stop()
        await asyncio.wait_for(node_task, timeout=5.0)
        await gateway.stop()
