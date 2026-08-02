"""Concurrent multi-agent runtime integration test.

Two distinct agents run full streaming turns (with local tools) at the same time
against a single server. They share the same user id, so they contend on the same
LLM-token quota counter — the path that previously raced (IntegrityError) and could
hang a turn. Both turns must reach DONE without either runtime hanging.
"""

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
    FULL_TEST_MANIFEST,
    FULL_TEST_MANIFEST_HASH,
    TEST_AGENT_ID,
)
from corvus.server.vsock import TransportGateway


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _build_stack(tmp_path: Path, name: str, agent_id: str, port: int):
    ipc_path = tmp_path / f"{name}.sock"
    rt = RuntimeConfig(
        agent_id=agent_id,
        vm_id=f"vm-{name}",
        ipc_socket_path=ipc_path,
        coordinator_path=tmp_path / f"coord-{name}.json",
        manifest_hash=FULL_TEST_MANIFEST_HASH,
        run_mode=RunMode.ONCE,
        llm_local_tools=("echo", "terminal"),
        llm_stream=True,
        turn_timeout_seconds=30.0,
    )
    node_config = NodeConfig(
        agent_id=agent_id,
        vm_id=rt.vm_id,
        manifest_hash=FULL_TEST_MANIFEST_HASH,
        ipc_socket_path=ipc_path,
        use_tcp=True,
        tcp_host="127.0.0.1",
        tcp_port=port,
        vsock_host_cid=2,
        vsock_port=4040,
    )
    node = CorvusNode(node_config)
    loop = AgentLoop(rt)
    engines = [ToolsEngine(rt), GatewayEngine(rt), LlmEngine(rt), MemoryEngine(rt)]
    return rt, node, loop, engines


@pytest.mark.asyncio
async def test_two_agents_concurrent_streaming_tools(app_ctx, tmp_path):
    # Two distinct authorized agents, same user => shared LLM-token quota counter
    # (the counter creation path we made race-safe).
    agent_a = TEST_AGENT_ID
    agent_b = "test-agent-02"
    await app_ctx.db.upsert_agent(agent_a, FULL_TEST_MANIFEST_HASH, FULL_TEST_MANIFEST)
    await app_ctx.db.upsert_agent(agent_b, FULL_TEST_MANIFEST_HASH, FULL_TEST_MANIFEST)

    # Authorize both agents for the turn's user (engine2 uses user_id="test-user").
    user = await app_ctx.db.get_user("test-user")
    role = user.pop("role")
    user.pop("id")
    user["allowed_agents"] = sorted({*user.get("allowed_agents", []), agent_a, agent_b})
    await app_ctx.db.upsert_user("test-user", role, user)

    port = _free_port()
    server_config = replace(app_ctx.config, tcp_port=port, use_tcp=True)
    gateway = TransportGateway(
        server_config,
        app_ctx.handle_message,
        app_ctx.sessions.unbind_connection,
        transport=app_ctx.transport,
    )
    await gateway.start()
    await asyncio.sleep(0.05)

    rt_a, node_a, loop_a, engines_a = _build_stack(tmp_path, "a", agent_a, port)
    rt_b, node_b, loop_b, engines_b = _build_stack(tmp_path, "b", agent_b, port)

    tasks = [
        asyncio.create_task(node_a.run()),
        asyncio.create_task(node_b.run()),
        asyncio.create_task(loop_a.run()),
        asyncio.create_task(loop_b.run()),
        *[asyncio.create_task(e.run()) for e in engines_a],
        *[asyncio.create_task(e.run()) for e in engines_b],
    ]

    try:
        coord_a = Coordinator(rt_a.coordinator_path)
        coord_b = Coordinator(rt_b.coordinator_path)

        async def _await_done(coord: Coordinator) -> TurnPhase:
            phase = await coord.await_phase_in(
                {TurnPhase.DONE, TurnPhase.ABORTED}, timeout=30.0
            )
            return phase or coord.get_phase()

        phase_a, phase_b = await asyncio.wait_for(
            asyncio.gather(_await_done(coord_a), _await_done(coord_b)),
            timeout=35.0,
        )

        assert phase_a == TurnPhase.DONE, f"agent A ended in {phase_a}"
        assert phase_b == TurnPhase.DONE, f"agent B ended in {phase_b}"
        # Local tools executed under streaming for both agents.
        assert coord_a.read().get("tool_echo_text") == "Hello from tool gateway"
        assert coord_b.read().get("tool_echo_text") == "Hello from tool gateway"
    finally:
        for eng in (loop_a, loop_b, *engines_a, *engines_b):
            eng.request_stop()
        node_a.request_stop()
        node_b.request_stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        await gateway.stop()


@pytest.mark.asyncio
async def test_same_agent_two_vms_concurrent_streaming_tools(app_ctx, tmp_path):
    # Same agent, two distinct VMs -> distinct (agent_id, vm_id) transport bindings.
    # Before the routing fix this scenario stalled because the second VM's handshake
    # overwrote the first's connection, so one VM never received its stream/response.
    await app_ctx.db.upsert_agent(TEST_AGENT_ID, FULL_TEST_MANIFEST_HASH, FULL_TEST_MANIFEST)

    port = _free_port()
    server_config = replace(app_ctx.config, tcp_port=port, use_tcp=True)
    gateway = TransportGateway(
        server_config,
        app_ctx.handle_message,
        app_ctx.sessions.unbind_connection,
        transport=app_ctx.transport,
    )
    await gateway.start()
    await asyncio.sleep(0.05)

    rt_a, node_a, loop_a, engines_a = _build_stack(tmp_path, "a", TEST_AGENT_ID, port)
    rt_b, node_b, loop_b, engines_b = _build_stack(tmp_path, "b", TEST_AGENT_ID, port)

    tasks = [
        asyncio.create_task(node_a.run()),
        asyncio.create_task(node_b.run()),
        asyncio.create_task(loop_a.run()),
        asyncio.create_task(loop_b.run()),
        *[asyncio.create_task(e.run()) for e in engines_a],
        *[asyncio.create_task(e.run()) for e in engines_b],
    ]

    try:
        coord_a = Coordinator(rt_a.coordinator_path)
        coord_b = Coordinator(rt_b.coordinator_path)

        async def _await_done(coord: Coordinator) -> TurnPhase:
            phase = await coord.await_phase_in(
                {TurnPhase.DONE, TurnPhase.ABORTED}, timeout=30.0
            )
            return phase or coord.get_phase()

        phase_a, phase_b = await asyncio.wait_for(
            asyncio.gather(_await_done(coord_a), _await_done(coord_b)),
            timeout=35.0,
        )

        assert phase_a == TurnPhase.DONE, f"vm-a ended in {phase_a}"
        assert phase_b == TurnPhase.DONE, f"vm-b ended in {phase_b}"
        assert coord_a.read().get("tool_echo_text") == "Hello from tool gateway"
        assert coord_b.read().get("tool_echo_text") == "Hello from tool gateway"
    finally:
        for eng in (loop_a, loop_b, *engines_a, *engines_b):
            eng.request_stop()
        node_a.request_stop()
        node_b.request_stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        await gateway.stop()
