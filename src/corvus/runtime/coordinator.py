"""Filesystem turn coordinator for multi-process runtime."""

from __future__ import annotations

import asyncio
import fcntl
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any


class TurnPhase(StrEnum):
    INIT = "INIT"
    RECEIVE = "RECEIVE"
    DISPATCH = "DISPATCH"
    COLLECT = "COLLECT"
    RESPOND = "RESPOND"
    DONE = "DONE"
    ABORTED = "ABORTED"


# Phases after which a turn is finished; engines must stop waiting/looping.
TERMINAL_PHASES: frozenset[TurnPhase] = frozenset({TurnPhase.DONE, TurnPhase.ABORTED})


class Coordinator:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock_path = path.with_suffix(path.suffix + ".lock")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, "a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _default_state(self) -> dict[str, Any]:
        return {"phase": TurnPhase.INIT.value, "ready": []}

    def read(self) -> dict[str, Any]:
        with self._locked():
            if not self.path.exists():
                return self._default_state()
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("ready", [])
            return data

    def write(self, data: dict[str, Any]) -> None:
        with self._locked():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    def _mutate(self, mutator) -> dict[str, Any]:
        with self._locked():
            if self.path.exists():
                state = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                state = self._default_state()
            state.setdefault("ready", [])
            mutator(state)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
            return state

    def set_phase(self, phase: TurnPhase, **extra: Any) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state["phase"] = phase.value
            state.update(extra)

        self._mutate(mutate)

    def merge_fields(self, **extra: Any) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state.update(extra)

        self._mutate(mutate)

    def get_phase(self) -> TurnPhase:
        raw = self.read().get("phase", TurnPhase.INIT.value)
        return TurnPhase(raw)

    def mark_ready(self, engine: str) -> None:
        def mutate(state: dict[str, Any]) -> None:
            ready = list(state.get("ready", []))
            if engine not in ready:
                ready.append(engine)
            state["ready"] = ready

        self._mutate(mutate)

    def get_ready(self) -> set[str]:
        return set(self.read().get("ready", []))

    def missing_engines(self, required: set[str]) -> set[str]:
        return required - self.get_ready()

    def wait_phase(self, target: TurnPhase, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get_phase() == target:
                return True
            time.sleep(0.05)
        return False

    async def await_phase(self, target: TurnPhase, timeout: float = 30.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self.get_phase() == target:
                return True
            await asyncio.sleep(0.05)
        return False

    async def await_phase_in(
        self, targets: set[TurnPhase] | frozenset[TurnPhase], timeout: float = 30.0
    ) -> TurnPhase | None:
        """Wait until the phase is one of ``targets``; returns the matched phase or None."""
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            phase = self.get_phase()
            if phase in targets:
                return phase
            await asyncio.sleep(0.05)
        return None

    def is_terminal(self) -> bool:
        return self.get_phase() in TERMINAL_PHASES

    def abort(self, reason: str, **extra: Any) -> None:
        """Move the turn to the terminal ABORTED phase (idempotent for finished turns)."""
        def mutate(state: dict[str, Any]) -> None:
            current = state.get("phase")
            if current in (TurnPhase.DONE.value, TurnPhase.ABORTED.value):
                return
            state["phase"] = TurnPhase.ABORTED.value
            state["abort_reason"] = reason
            state.update(extra)

        self._mutate(mutate)

    async def await_engines_ready(
        self, required: set[str], timeout: float = 30.0
    ) -> tuple[bool, set[str]]:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            missing = self.missing_engines(required)
            if not missing:
                return True, set()
            await asyncio.sleep(0.05)
        return False, self.missing_engines(required)

    def publish_tool_batch(self, batch_id: str, calls: list[dict[str, Any]]) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state["tool_batch_id"] = batch_id
            state["pending_tool_calls"] = calls
            state["tool_batch_status"] = "pending"
            state.pop("tool_results", None)

        self._mutate(mutate)

    def complete_tool_batch(self, batch_id: str, results: list[dict[str, Any]]) -> bool:
        outcome = {"ok": False}

        def mutate(state: dict[str, Any]) -> None:
            if state.get("tool_batch_id") != batch_id:
                return
            if state.get("tool_batch_status") != "pending":
                return
            state["tool_results"] = results
            state["tool_batch_status"] = "complete"
            state["pending_tool_calls"] = []
            outcome["ok"] = True

        self._mutate(mutate)
        return outcome["ok"]

    async def await_tool_batch_complete(
        self, batch_id: str, timeout: float = 60.0
    ) -> list[dict[str, Any]] | None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            state = self.read()
            if state.get("tool_batch_id") != batch_id:
                await asyncio.sleep(0.05)
                continue
            if state.get("tool_batch_status") == "complete":
                raw = state.get("tool_results")
                if isinstance(raw, list):
                    return raw
                return []
            await asyncio.sleep(0.05)
        return None

    async def await_tool_batch_pending(self, timeout: float = 60.0) -> dict[str, Any] | None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            state = self.read()
            if state.get("tool_batch_status") == "pending":
                calls = state.get("pending_tool_calls")
                batch_id = state.get("tool_batch_id")
                if batch_id and isinstance(calls, list) and calls:
                    return {"batch_id": str(batch_id), "calls": calls}
            await asyncio.sleep(0.05)
        return None
