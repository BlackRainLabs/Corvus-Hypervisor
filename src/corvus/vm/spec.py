"""Firecracker machine configuration builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VmSpec:
    vm_instance_id: str
    agent_id: str
    guest_cid: int
    kernel_path: Path
    rootfs_path: Path
    vcpu_count: int
    mem_size_mib: int
    vsock_port: int
    api_socket: Path
    vsock_uds: Path
    boot_env: dict[str, str] | None = None


def build_machine_config(spec: VmSpec) -> dict[str, Any]:
    return {
        "vcpu_count": spec.vcpu_count,
        "mem_size_mib": spec.mem_size_mib,
        "smt": False,
        "track_dirty_pages": False,
    }


def build_boot_source(spec: VmSpec) -> dict[str, Any]:
    env_args = " ".join(
        f"systemd.setenv={key}={value.replace(' ', '_')}"
        for key, value in sorted((spec.boot_env or {}).items())
    )
    return {
        "kernel_image_path": str(spec.kernel_path),
        "boot_args": (
            "console=ttyS0 reboot=k panic=1 pci=off "
            "init=/sbin/init systemd.unified_cgroup_hierarchy=0"
            + (f" {env_args}" if env_args else "")
        ),
    }


def build_root_drive(spec: VmSpec) -> dict[str, Any]:
    return {
        "drive_id": "rootfs",
        "path_on_host": str(spec.rootfs_path),
        "is_root_device": True,
        "is_read_only": True,
    }


def build_vsock(spec: VmSpec) -> dict[str, Any]:
    return {
        "guest_cid": spec.guest_cid,
        "uds_path": str(spec.vsock_uds),
        "vsock_id": "vsock0",
    }
