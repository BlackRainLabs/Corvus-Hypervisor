"""VM launcher configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VmConfig:
    artifacts_dir: Path
    kernel_path: Path
    rootfs_path: Path
    firecracker_bin: str
    vsock_port: int
    guest_cid_start: int
    state_dir: Path


def load_config() -> VmConfig:
    root = Path(os.environ.get("CORVUS_ROOT", Path.cwd()))
    artifacts = Path(os.environ.get("CORVUS_ARTIFACTS_DIR", root / "artifacts"))
    return VmConfig(
        artifacts_dir=artifacts,
        kernel_path=Path(os.environ.get("CORVUS_KERNEL_PATH", artifacts / "vmlinux")),
        rootfs_path=Path(os.environ.get("CORVUS_ROOTFS_PATH", artifacts / "rootfs.ext4")),
        firecracker_bin=os.environ.get("CORVUS_FIRECRACKER_BIN", "firecracker"),
        vsock_port=int(os.environ.get("CORVUS_VSOCK_PORT", "4040")),
        guest_cid_start=int(os.environ.get("CORVUS_VSOCK_GUEST_CID_START", "3")),
        state_dir=Path(os.environ.get("CORVUS_VM_STATE_DIR", "/tmp/corvus-vms")),
    )
