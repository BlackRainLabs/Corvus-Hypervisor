"""Handshake and routing integration tests."""

import asyncio
import socket
from dataclasses import replace
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
from corvus.server.bootstrap import FULL_TEST_MANIFEST_HASH, TEST_AGENT_ID, TEST_MANIFEST_HASH
from corvus.server.vsock import TransportGateway


@pytest.mark.asyncio
async def test_handshake_and_user_query(app_ctx, full_manifest_agent):
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
        vm_id = "vm-test"
        cid = uuid4()

        hs = FrameworkMessage(
            source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.CORVUS_NODE, vm_id=vm_id),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.SYSTEM,
            type="handshake",
            correlation_id=cid,
            tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
            payload={
                "manifest_hash": FULL_TEST_MANIFEST_HASH,
                "protocol_version": "2.0",
                "vm_instance_id": vm_id,
                "agent_id": TEST_AGENT_ID,
                "registered_engines": ["engine1", "engine2", "engine3", "engine4"],
            },
        )
        writer.write((encode_message(hs) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        resp = decode_line(line.decode())
        assert "session_token" in resp.payload

        token = resp.payload["session_token"]
        uq = FrameworkMessage(
            source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE2, vm_id=vm_id),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.REQUEST,
            type="user_query",
            correlation_id=uuid4(),
            tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT, scope=Scope.EXTERNAL),
            security=MessageSecurity(may_leave_vm=True),
            payload={
                "_session": {"token": token},
                "user_id": "test-user",
                "platform": "api",
                "channel_id": "c1",
                "content": {"text": "hello"},
            },
        )
        writer.write((encode_message(uq) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        uq_resp = decode_line(line.decode())
        assert uq_resp.payload.get("success") is True

        turn_id = uq.correlation_id
        memory_write = FrameworkMessage(
            source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE4, vm_id=vm_id),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
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
                "record": {"key": "router-note", "content": "via router"},
            },
        )
        writer.write((encode_message(memory_write) + "\n").encode())
        await writer.drain()
        line = await reader.readline()
        memory_resp = decode_line(line.decode())
        assert memory_resp.type == "memory:write_response"
        assert memory_resp.payload["success"] is True
        assert memory_resp.payload["record_id"]

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
        assert app_ctx.sessions.active_connection_count == 0
    finally:
        await gateway.stop()


@pytest.mark.asyncio
async def test_handshake_rejects_unmanifested_engine(app_ctx):
    hs = FrameworkMessage(
        source=MessageSource(
            agent_id=TEST_AGENT_ID,
            engine=EngineId.CORVUS_NODE,
            vm_id="vm-test",
        ),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.SYSTEM,
        type="handshake",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
        payload={
            "manifest_hash": TEST_MANIFEST_HASH,
            "protocol_version": "2.0",
            "vm_instance_id": "vm-test",
            "agent_id": TEST_AGENT_ID,
            "registered_engines": ["engine1", "engine5"],
        },
    )

    resp = await app_ctx.handle_message(hs, 99)
    assert resp is not None
    assert resp.message_class == MessageClass.ERROR
    assert resp.payload["code"] == "NODE_VALIDATION_FAILED"
    assert resp.payload["details"]["unknown_engines"] == ["engine5"]
