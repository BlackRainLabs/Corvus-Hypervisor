"""Runtime configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RunMode(StrEnum):
    ONCE = "once"
    DAEMON = "daemon"


@dataclass(frozen=True)
class RuntimeConfig:
    agent_id: str
    vm_id: str
    ipc_socket_path: Path
    coordinator_path: Path
    manifest_hash: str = ""
    ipc_connect_timeout: float = 60.0
    run_mode: RunMode = RunMode.ONCE
    llm_local_tools: tuple[str, ...] = ()
    llm_stream: bool = False
    turn_timeout_seconds: float = 120.0


def resolve_manifest_hash(config: RuntimeConfig) -> str:
    if config.manifest_hash:
        return config.manifest_hash
    from corvus.server.bootstrap import TEST_MANIFEST_HASH

    return TEST_MANIFEST_HASH


def load_config(*, run_mode: RunMode | None = None) -> RuntimeConfig:
    tools_raw = os.environ.get("CORVUS_LLM_LOCAL_TOOLS", "")
    llm_local_tools = tuple(part.strip() for part in tools_raw.split(",") if part.strip())
    llm_stream = os.environ.get("CORVUS_LLM_STREAM", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return RuntimeConfig(
        agent_id=os.environ.get("CORVUS_AGENT_ID", "test-agent-01"),
        vm_id=os.environ.get("CORVUS_VM_ID", "fc-test-vm"),
        ipc_socket_path=Path(
            os.environ.get("CORVUS_NODE_SOCK", "/run/corvus/node.sock")
        ),
        coordinator_path=Path(
            os.environ.get("CORVUS_COORDINATOR_PATH", "/run/corvus/coordinator.json")
        ),
        manifest_hash=os.environ.get("CORVUS_MANIFEST_HASH", ""),
        ipc_connect_timeout=float(os.environ.get("CORVUS_IPC_CONNECT_TIMEOUT", "60")),
        run_mode=run_mode or RunMode(os.environ.get("CORVUS_RUN_MODE", "once")),
        llm_local_tools=llm_local_tools,
        llm_stream=llm_stream,
        turn_timeout_seconds=float(os.environ.get("CORVUS_TURN_TIMEOUT_SECONDS", "120")),
    )
