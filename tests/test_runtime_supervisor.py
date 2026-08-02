"""Runtime supervisor end-to-end tests."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import replace

import pytest

from corvus.node.config import NodeConfig
from corvus.node.main import CorvusNode
from corvus.runtime.config import RunMode
from corvus.runtime.coordinator import Coordinator, TurnPhase
from corvus.runtime.supervisor import run_supervisor
from corvus.server.bootstrap import TEST_AGENT_ID, TEST_MANIFEST_HASH
from corvus.server.vsock import TransportGateway


@pytest.mark.asyncio
async def test_supervisor_once_full_turn(app_ctx, tmp_path, monkeypatch):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = tmp_path / "node.sock"
    coord_path = tmp_path / "coordinator.json"

    monkeypatch.setenv("CORVUS_NODE_SOCK", str(ipc_path))
    monkeypatch.setenv("CORVUS_COORDINATOR_PATH", str(coord_path))
    monkeypatch.setenv("CORVUS_MANIFEST_HASH", TEST_MANIFEST_HASH)

    node_config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id="vm-supervisor-test",
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

    node = CorvusNode(node_config)
    node_task = asyncio.create_task(node.run())

    try:
        for _ in range(50):
            if node.session.handshake_complete:
                break
            await asyncio.sleep(0.05)

        success = await asyncio.wait_for(
            run_supervisor(run_mode=RunMode.ONCE, all_engines=False),
            timeout=30.0,
        )
        assert success is True
        coord = Coordinator(coord_path)
        assert coord.get_phase() == TurnPhase.DONE
    finally:
        node.request_stop()
        node_task.cancel()
        await asyncio.gather(node_task, return_exceptions=True)
        await gateway.stop()
