"""Agent runtime full-turn integration tests."""

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
from corvus.runtime.engines.engine1 import ToolsEngine
from corvus.runtime.engines.engine2 import GatewayEngine
from corvus.runtime.engines.engine3 import LlmEngine
from corvus.runtime.engines.engine4 import MemoryEngine
from corvus.runtime.loop import AgentLoop
from corvus.server.bootstrap import (
    FULL_TEST_MANIFEST_HASH,
    TEST_AGENT_ID,
)
from corvus.server.vsock import TransportGateway


def _runtime_config(tmp_path: Path, ipc_path: Path) -> RuntimeConfig:
    coord = tmp_path / "coordinator.json"
    return RuntimeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id="vm-runtime-test",
        ipc_socket_path=ipc_path,
        coordinator_path=coord,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
        run_mode=RunMode.ONCE,
        llm_local_tools=("echo", "terminal"),
    )


async def _await_memory_fields(coord: Coordinator, timeout: float = 2.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        state = coord.read()
        if state.get("memory_write_record_id"):
            return state
        await asyncio.sleep(0.05)
    return coord.read()


@pytest.mark.asyncio
async def test_runtime_full_turn(app_ctx, tmp_path, full_manifest_agent):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    ipc_path = tmp_path / "node.sock"
    rt = _runtime_config(tmp_path, ipc_path)

    node_config = NodeConfig(
        agent_id=TEST_AGENT_ID,
        vm_id=rt.vm_id,
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

    node = CorvusNode(node_config)
    loop = AgentLoop(rt)
    engines = [
        ToolsEngine(rt),
        GatewayEngine(rt),
        LlmEngine(rt),
        MemoryEngine(rt),
    ]

    tasks = [
        asyncio.create_task(node.run()),
        asyncio.create_task(loop.run()),
        *[asyncio.create_task(e.run()) for e in engines],
    ]

    try:
        coord = Coordinator(rt.coordinator_path)
        assert await coord.await_phase(TurnPhase.DONE, timeout=30.0)
        assert coord.get_phase() == TurnPhase.DONE
        state = await _await_memory_fields(coord)
        assert state.get("memory_write_record_id")
        assert state.get("memory_query_hit") is True
        assert "Engine4 memory snapshot" in (state.get("memory_query_content") or "")
        assert state.get("tool_echo_text") == "Hello from tool gateway"
        assert "agentvm terminal ok" in (state.get("tool_terminal_stdout") or "")
    finally:
        node.request_stop()
        loop.request_stop()
        for e in engines:
            e.request_stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        await gateway.stop()
