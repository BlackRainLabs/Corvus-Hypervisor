"""Agent Loop once-mode tests."""

from __future__ import annotations

import asyncio
import socket
from dataclasses import replace
from pathlib import Path

import pytest

from corvus.node.config import NodeConfig
from corvus.node.main import CorvusNode
from corvus.runtime.config import RunMode, RuntimeConfig
from corvus.runtime.coordinator import Coordinator, TurnPhase
from corvus.runtime.engines.engine2 import GatewayEngine
from corvus.runtime.engines.engine3 import LlmEngine
from corvus.runtime.loop import AgentLoop
from corvus.server.bootstrap import TEST_AGENT_ID, TEST_MANIFEST_HASH
from corvus.server.vsock import TransportGateway


def _runtime_config(tmp_path: Path, ipc_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id="vm-loop-test",
        ipc_socket_path=ipc_path,
        coordinator_path=tmp_path / "coordinator.json",
        manifest_hash=TEST_MANIFEST_HASH,
        run_mode=RunMode.ONCE,
    )


@pytest.mark.asyncio
async def test_loop_exits_after_done_in_once_mode(app_ctx, tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = tmp_path / "node.sock"
    rt = _runtime_config(tmp_path, ipc_path)

    node_config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id=rt.vm_id,
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
    loop = AgentLoop(rt)
    engines = [GatewayEngine(rt), LlmEngine(rt)]

    node_task = asyncio.create_task(node.run())
    engine_tasks = [asyncio.create_task(e.run()) for e in engines]

    try:
        for _ in range(50):
            if node.session.handshake_complete:
                break
            await asyncio.sleep(0.05)

        success = await asyncio.wait_for(loop.run(), timeout=30.0)
        assert success is True
        coord = Coordinator(rt.coordinator_path)
        assert coord.get_phase() == TurnPhase.DONE
    finally:
        node.request_stop()
        await asyncio.gather(node_task, *engine_tasks, return_exceptions=True)
        await gateway.stop()


@pytest.mark.asyncio
async def test_loop_does_not_clear_engine_ready_on_init(tmp_path):
    coord_path = tmp_path / "coordinator.json"
    coord = Coordinator(coord_path)
    coord.mark_ready("engine2")
    coord.mark_ready("engine3")

    rt = _runtime_config(tmp_path, tmp_path / "node.sock")
    loop = AgentLoop(rt)
    loop.coordinator.set_phase(TurnPhase.INIT)

    missing = loop.coordinator.missing_engines({"engine2", "engine3"})
    assert missing == set()
