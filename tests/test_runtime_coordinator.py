"""Coordinator readiness tests."""


import pytest

from corvus.runtime.coordinator import TERMINAL_PHASES, Coordinator, TurnPhase


@pytest.mark.asyncio
async def test_await_engines_ready_success(tmp_path):
    coord = Coordinator(tmp_path / "coord.json")
    coord.mark_ready("engine2")
    coord.mark_ready("engine3")
    ok, missing = await coord.await_engines_ready({"engine2", "engine3"}, timeout=1.0)
    assert ok is True
    assert missing == set()


@pytest.mark.asyncio
async def test_await_engines_ready_timeout(tmp_path):
    coord = Coordinator(tmp_path / "coord.json")
    coord.mark_ready("engine2")
    ok, missing = await coord.await_engines_ready({"engine2", "engine3"}, timeout=0.2)
    assert ok is False
    assert missing == {"engine3"}


def test_set_phase_preserves_ready(tmp_path):
    coord = Coordinator(tmp_path / "coord.json")
    coord.mark_ready("engine2")
    coord.set_phase(TurnPhase.RECEIVE)
    assert "engine2" in coord.get_ready()


def test_abort_sets_terminal_phase_and_reason(tmp_path):
    coord = Coordinator(tmp_path / "coord.json")
    coord.set_phase(TurnPhase.COLLECT)
    coord.abort("engine3_llm_failed", correlation_id="turn-1")
    assert coord.get_phase() == TurnPhase.ABORTED
    assert coord.is_terminal() is True
    state = coord.read()
    assert state["abort_reason"] == "engine3_llm_failed"
    assert state["correlation_id"] == "turn-1"


def test_abort_is_noop_when_already_done(tmp_path):
    coord = Coordinator(tmp_path / "coord.json")
    coord.set_phase(TurnPhase.DONE)
    coord.abort("late_abort")
    assert coord.get_phase() == TurnPhase.DONE
    assert "abort_reason" not in coord.read()


def test_abort_is_noop_when_already_aborted(tmp_path):
    coord = Coordinator(tmp_path / "coord.json")
    coord.abort("first_reason")
    coord.abort("second_reason")
    assert coord.get_phase() == TurnPhase.ABORTED
    assert coord.read()["abort_reason"] == "first_reason"


@pytest.mark.asyncio
async def test_await_phase_in_matches_terminal(tmp_path):
    coord = Coordinator(tmp_path / "coord.json")
    coord.abort("boom")
    matched = await coord.await_phase_in(TERMINAL_PHASES, timeout=1.0)
    assert matched == TurnPhase.ABORTED


@pytest.mark.asyncio
async def test_await_phase_in_timeout_returns_none(tmp_path):
    coord = Coordinator(tmp_path / "coord.json")
    coord.set_phase(TurnPhase.COLLECT)
    matched = await coord.await_phase_in({TurnPhase.RESPOND, TurnPhase.ABORTED}, timeout=0.2)
    assert matched is None
