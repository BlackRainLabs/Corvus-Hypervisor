"""Bus client reconnect tests."""

from __future__ import annotations

import asyncio
import socket
from uuid import uuid4

import pytest

from corvus.node.bus import BusClient
from corvus.node.config import NodeConfig
from corvus.protocol import (
    DestinationType,
    EngineId,
    FrameworkMessage,
    MessageClass,
    MessageDestination,
    MessageSource,
    MessageTags,
    TriggeredBy,
    encode_message,
)


@pytest.mark.asyncio
async def test_bus_reconnect_restarts_reader_loop(tmp_path):
    delivered = asyncio.Event()

    message = FrameworkMessage(
        source=MessageSource(agent_id="server", engine=EngineId.CORVUS_NODE, vm_id="server"),
        destination=MessageDestination(type=DestinationType.ENGINE, target=EngineId.ENGINE2.value),
        message_class=MessageClass.RESPONSE,
        type="user_query_ack",
        correlation_id=uuid4(),
        tags=MessageTags(triggered_by=TriggeredBy.SYSTEM),
        payload={"success": True},
    )

    async def handle_client(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        handle_client.calls += 1
        if handle_client.calls == 1:
            writer.close()
            await writer.wait_closed()
            return

        writer.write((encode_message(message) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    handle_client.calls = 0

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    server = await asyncio.start_server(handle_client, "127.0.0.1", port)
    received: list[FrameworkMessage] = []

    async def on_inbound(inbound: FrameworkMessage) -> None:
        received.append(inbound)
        delivered.set()

    config = NodeConfig(
        agent_id="agent-1",
        vm_id="vm-1",
        manifest_hash="mh",
        ipc_socket_path=tmp_path / "node.sock",
        use_tcp=True,
        tcp_host="127.0.0.1",
        tcp_port=port,
        vsock_host_cid=2,
        vsock_port=4040,
        reconnect_base_seconds=0.01,
        reconnect_max_seconds=0.01,
    )
    client = BusClient(config, on_inbound)

    try:
        await client.start(after_handshake=True)
        await asyncio.wait_for(delivered.wait(), timeout=2.0)
        assert handle_client.calls >= 2
        assert received[0].id == message.id
    finally:
        await client.stop()
        server.close()
        await server.wait_closed()
