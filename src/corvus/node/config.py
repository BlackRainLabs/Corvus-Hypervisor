"""Corvus Node configuration from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NodeConfig:
    agent_id: str
    vm_id: str
    manifest_hash: str
    ipc_socket_path: Path
    use_tcp: bool
    tcp_host: str
    tcp_port: int
    vsock_host_cid: int
    vsock_port: int
    registered_engines: tuple[str, ...] = (
        "engine1",
        "engine2",
        "engine3",
        "engine4",
    )
    outbound_queue_max: int = 100
    handshake_max_retries: int = 5
    reconnect_base_seconds: float = 1.0
    reconnect_max_seconds: float = 60.0

    @property
    def vsock_cid(self) -> int:
        return self.vsock_host_cid


def load_config() -> NodeConfig:
    return NodeConfig(
        agent_id=os.environ.get("CORVUS_AGENT_ID", "test-agent-01"),
        vm_id=os.environ.get("CORVUS_VM_ID", "fc-test-vm"),
        manifest_hash=os.environ.get("CORVUS_MANIFEST_HASH", ""),
        ipc_socket_path=Path(
            os.environ.get("CORVUS_NODE_SOCK", "/run/corvus/node.sock")
        ),
        use_tcp=os.environ.get("CORVUS_USE_TCP", "1") == "1",
        tcp_host=os.environ.get("CORVUS_TCP_HOST", "127.0.0.1"),
        tcp_port=int(os.environ.get("CORVUS_TCP_PORT", "4040")),
        vsock_host_cid=int(os.environ.get("CORVUS_VSOCK_HOST_CID", "2")),
        vsock_port=int(os.environ.get("CORVUS_VSOCK_PORT", "4040")),
        registered_engines=tuple(
            e.strip()
            for e in os.environ.get(
                "CORVUS_REGISTERED_ENGINES",
                "engine1,engine2,engine3,engine4",
            ).split(",")
            if e.strip()
        ),
    )


def resolve_manifest_hash(config: NodeConfig) -> str:
    if config.manifest_hash:
        return config.manifest_hash
    from corvus.server.bootstrap import TEST_MANIFEST_HASH

    return TEST_MANIFEST_HASH
