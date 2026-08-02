"""Fake Corvus Node client for Phase 2 integration testing."""

from __future__ import annotations

import argparse
import asyncio
import os
from uuid import uuid4

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


async def connect(host: str, port: int):
    use_tcp = os.environ.get("CORVUS_USE_TCP", "1") == "1"
    if use_tcp:
        return await asyncio.open_connection(host, port)
    raise RuntimeError("AF_VSOCK client not implemented; set CORVUS_USE_TCP=1")


async def send_and_receive(reader, writer, message: FrameworkMessage) -> FrameworkMessage:
    writer.write((encode_message(message) + "\n").encode("utf-8"))
    await writer.drain()
    while True:
        line = await reader.readline()
        if not line:
            raise RuntimeError("Connection closed")
        response = decode_line(line.decode("utf-8"))
        if response.type != "handshake" or response.message_class != MessageClass.SYSTEM:
            return response
        if "session_token" in response.payload:
            return response


async def run_flow(host: str, port: int, send_invalid: bool) -> None:
    reader, writer = await connect(host, port)
    vm_id = "fc-test-vm"
    correlation_id = uuid4()

    handshake = FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.CORVUS_NODE, vm_id=vm_id),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.SYSTEM,
        type="handshake",
        correlation_id=correlation_id,
        tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
        payload={
            "manifest_hash": TEST_MANIFEST_HASH,
            "protocol_version": "2.0",
            "vm_instance_id": vm_id,
            "agent_id": TEST_AGENT_ID,
            "registered_engines": ["engine1", "engine2", "engine3", "engine4"],
        },
    )

    hs_response = await send_and_receive(reader, writer, handshake)
    session_token = hs_response.payload["session_token"]
    print(f"Handshake OK — session_token={session_token[:8]}...")

    ack = FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.CORVUS_NODE, vm_id=vm_id),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.RESPONSE,
        type="handshake",
        correlation_id=correlation_id,
        tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
        payload={"ack": True, "_session": {"token": session_token}},
    )
    writer.write((encode_message(ack) + "\n").encode("utf-8"))
    await writer.drain()

    user_query = FrameworkMessage(
        source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE2, vm_id=vm_id),
        destination=MessageDestination(type=DestinationType.CORVUS_SERVER, target="corvus_server"),
        message_class=MessageClass.REQUEST,
        type="user_query",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.USER_INPUT, scope=Scope.EXTERNAL),
        security=MessageSecurity(may_leave_vm=True),
        payload={
            "_session": {"token": session_token},
            "user_id": "test-user",
            "platform": "api",
            "channel_id": "test-channel",
            "content": {"text": "Hello Corvus"},
        },
    )
    uq_response = await send_and_receive(reader, writer, user_query)
    print(f"user_query -> {uq_response.type} success={uq_response.payload.get('success')}")

    if send_invalid:
        bad = FrameworkMessage(
            source=MessageSource(agent_id=TEST_AGENT_ID, engine=EngineId.ENGINE3, vm_id=vm_id),
            destination=MessageDestination(
                type=DestinationType.CORVUS_SERVER, target="corvus_server"
            ),
            message_class=MessageClass.REQUEST,
            type="memory:query",
            correlation_id=uuid4(),
            tags=MessageTags(
                triggered_by=TriggeredBy.AGENT_INITIATED,
                origin_correlation_id=user_query.correlation_id,
            ),
            payload={"_session": {"token": session_token}, "namespace": "private"},
        )
        bad_response = await send_and_receive(reader, writer, bad)
        print(
            f"memory:query from engine3 -> {bad_response.type} "
            f"code={bad_response.payload.get('code')}"
        )

    writer.close()
    await writer.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description="Corvus fake Node integration client")
    parser.add_argument("--host", default=os.environ.get("CORVUS_TCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CORVUS_TCP_PORT", "4040")))
    parser.add_argument(
        "--invalid",
        action="store_true",
        help="Send denied memory:query from engine3",
    )
    args = parser.parse_args()
    asyncio.run(run_flow(args.host, args.port, args.invalid))


if __name__ == "__main__":
    main()
