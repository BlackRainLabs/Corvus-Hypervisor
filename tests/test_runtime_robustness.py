"""Robustness tests: stalled turns must not hang engines or the --once runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from corvus.runtime.config import RunMode, RuntimeConfig
from corvus.runtime.coordinator import Coordinator, TurnPhase
from corvus.runtime.engines.engine1 import ToolsEngine


def _config(tmp_path: Path, *, turn_timeout: float) -> RuntimeConfig:
    return RuntimeConfig(
        agent_id="test-agent-01",
        vm_id="fc-test-vm",
        ipc_socket_path=tmp_path / "node.sock",
        coordinator_path=tmp_path / "coordinator.json",
        manifest_hash="deadbeef",
        run_mode=RunMode.ONCE,
        turn_timeout_seconds=turn_timeout,
    )


@pytest.mark.asyncio
async def test_engine1_collect_loop_exits_on_turn_deadline(tmp_path):
    """A turn stuck in COLLECT (no tool batch ever arrives) must not spin forever."""
    config = _config(tmp_path, turn_timeout=0.4)
    coord = Coordinator(config.coordinator_path)
    coord.set_phase(TurnPhase.COLLECT, correlation_id=str(uuid4()))

    engine = ToolsEngine(config)
    # Should return within the deadline (+ scheduling slack), never hang.
    await asyncio.wait_for(engine.serve(), timeout=5.0)
    # Phase is still COLLECT because nothing advanced it, but the engine gave up.
    assert coord.get_phase() == TurnPhase.COLLECT


@pytest.mark.asyncio
async def test_engine1_collect_loop_exits_on_abort(tmp_path):
    """When another engine aborts the turn, Engine 1 must exit promptly."""
    config = _config(tmp_path, turn_timeout=30.0)
    coord = Coordinator(config.coordinator_path)
    coord.set_phase(TurnPhase.COLLECT, correlation_id=str(uuid4()))

    engine = ToolsEngine(config)
    serve_task = asyncio.create_task(engine.serve())
    await asyncio.sleep(0.1)
    coord.abort("engine3_llm_failed")
    # Must return well before the 30s turn timeout.
    await asyncio.wait_for(serve_task, timeout=5.0)
    assert coord.get_phase() == TurnPhase.ABORTED


@pytest.mark.asyncio
async def test_engine1_collect_loop_exits_on_stop(tmp_path):
    """A stop request (supervisor teardown) must break the COLLECT loop."""
    config = _config(tmp_path, turn_timeout=30.0)
    coord = Coordinator(config.coordinator_path)
    coord.set_phase(TurnPhase.COLLECT, correlation_id=str(uuid4()))

    engine = ToolsEngine(config)
    serve_task = asyncio.create_task(engine.serve())
    await asyncio.sleep(0.1)
    engine.request_stop()
    await asyncio.wait_for(serve_task, timeout=5.0)
