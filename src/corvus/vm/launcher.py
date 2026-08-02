"""Firecracker VM lifecycle orchestration."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from corvus.server.manifest import canonical_manifest, manifest_hash, resolve_manifest
from corvus.vm.config import VmConfig, load_config
from corvus.vm.fc_client import FirecrackerClient, wait_for_api_socket
from corvus.vm.registry import VMRecord, VMRegistry
from corvus.vm.spec import (
    VmSpec,
    build_boot_source,
    build_machine_config,
    build_root_drive,
    build_vsock,
)


class VMLauncher:
    def __init__(self, config: VmConfig | None = None) -> None:
        self.config = config or load_config()
        self.registry = VMRegistry(self.config.state_dir)

    async def launch(
        self,
        agent_id: str,
        manifest: dict[str, Any],
        *,
        vm_instance_id: str | None = None,
        manifest_hash_value: str | None = None,
    ) -> VMRecord:
        existing = self.registry.get_by_agent(agent_id)
        if existing is not None:
            raise RuntimeError(f"Agent {agent_id} already has running VM {existing.vm_instance_id}")

        resolved_manifest = canonical_manifest(resolve_manifest(manifest))
        mh = manifest_hash_value or manifest_hash(resolved_manifest)

        if not self.config.kernel_path.exists():
            raise FileNotFoundError(f"Kernel not found: {self.config.kernel_path}")
        rootfs_path = self._resolve_rootfs_path(resolved_manifest)
        if not rootfs_path.exists():
            raise FileNotFoundError(f"Rootfs not found: {rootfs_path}")

        vm_id = vm_instance_id or str(uuid4())
        guest_cid = self.registry.next_guest_cid(self.config.guest_cid_start)
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        api_socket = self.config.state_dir / f"fc-{vm_id}.sock"
        vsock_uds = self.config.state_dir / f"vsock-{vm_id}.sock"
        stdout_log = self.config.state_dir / f"fc-{vm_id}.stdout.log"
        stderr_log = self.config.state_dir / f"fc-{vm_id}.stderr.log"
        launch_package_dir = self.config.state_dir / "launch-packages" / vm_id

        for path in (api_socket, vsock_uds, stdout_log, stderr_log):
            if path.exists():
                path.unlink()

        env = self._build_launch_env(agent_id, vm_id, mh, resolved_manifest)
        self._write_launch_package(launch_package_dir, resolved_manifest, env)

        limits = resolved_manifest.get("resource_limits", {})
        spec = VmSpec(
            vm_instance_id=vm_id,
            agent_id=agent_id,
            guest_cid=guest_cid,
            kernel_path=self.config.kernel_path,
            rootfs_path=rootfs_path,
            vcpu_count=int(limits.get("vcpu_count", 1)),
            mem_size_mib=int(limits.get("memory_mb", 512)),
            vsock_port=self.config.vsock_port,
            api_socket=api_socket,
            vsock_uds=vsock_uds,
            boot_env=env,
        )
        record = VMRecord(
            vm_instance_id=vm_id,
            agent_id=agent_id,
            guest_cid=guest_cid,
            api_socket=str(api_socket),
            pid=None,
            status="launching",
            manifest_hash=mh,
            vsock_uds=str(vsock_uds),
            launch_package_dir=str(launch_package_dir),
            stdout_log=str(stdout_log),
            stderr_log=str(stderr_log),
        )
        self.registry.register(record)

        stdout_fh = stdout_log.open("wb")
        stderr_fh = stderr_log.open("wb")
        try:
            proc = subprocess.Popen(
                [
                    self.config.firecracker_bin,
                    "--api-sock",
                    str(api_socket),
                ],
                stdout=stdout_fh,
                stderr=stderr_fh,
                env={**os.environ, "CORVUS_VM_INSTANCE_ID": vm_id, **env},
            )
        finally:
            stdout_fh.close()
            stderr_fh.close()
        record.pid = proc.pid
        record.status = "booting"
        self.registry.register(record)

        try:
            if not await wait_for_api_socket(api_socket):
                detail = self._read_launch_logs(stdout_log, stderr_log)
                raise RuntimeError(f"Firecracker API socket did not appear{detail}")

            client = FirecrackerClient(api_socket)
            try:
                await client.put("/machine-config", build_machine_config(spec))
                await client.put("/boot-source", build_boot_source(spec))
                await client.put("/drives/rootfs", build_root_drive(spec))
                await client.put("/vsock", build_vsock(spec))
                await client.put("/actions", {"action_type": "InstanceStart"})
            finally:
                await client.close()
        except Exception as exc:
            self.registry.update_status(vm_id, "failed", last_error=str(exc))
            self._cleanup_failed_launch(proc, api_socket, vsock_uds)
            raise

        record.status = "running"
        self.registry.register(record)
        return record

    async def stop(self, vm_instance_id: str) -> None:
        record = self.registry.get(vm_instance_id)
        if record is None:
            raise KeyError(f"Unknown VM {vm_instance_id}")

        api_socket = Path(record.api_socket)
        graceful_stop = False
        stop_error: str | None = None
        self.registry.update_status(vm_instance_id, "stopping")
        if api_socket.exists():
            client = FirecrackerClient(api_socket)
            try:
                await client.put("/actions", {"action_type": "SendCtrlAltDel"})
                await asyncio.sleep(0.5)
                graceful_stop = True
            except Exception:
                stop_error = "Firecracker graceful stop request failed"
            finally:
                await client.close()

        if record.pid:
            try:
                os.kill(record.pid, 9)
            except ProcessLookupError:
                pass

        if api_socket.exists():
            api_socket.unlink()
        vsock_uds = Path(record.api_socket).parent / f"vsock-{vm_instance_id}.sock"
        if vsock_uds.exists():
            vsock_uds.unlink()

        self.registry.update_status(
            vm_instance_id,
            "stopped",
            last_error=stop_error,
            stop_reason="api_stop",
            graceful_stop=graceful_stop,
        )

    def status(self) -> list[VMRecord]:
        return self.registry.list_all()

    @staticmethod
    def _read_launch_logs(stdout_log: Path, stderr_log: Path) -> str:
        parts = []
        for label, path in (("stdout", stdout_log), ("stderr", stderr_log)):
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    parts.append(f"{label}: {text[-1000:]}")
        if not parts:
            return ""
        return " (" + " | ".join(parts) + ")"

    @staticmethod
    def _cleanup_failed_launch(
        proc: subprocess.Popen, api_socket: Path, vsock_uds: Path
    ) -> None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass

        for path in (api_socket, vsock_uds):
            if path.exists():
                path.unlink()

    def _resolve_rootfs_path(self, manifest: dict[str, Any]) -> Path:
        rootfs_image = str(manifest.get("rootfs_image") or "")
        if rootfs_image:
            candidate = Path(rootfs_image)
            if candidate.is_absolute() and candidate.exists():
                return candidate
            artifact_candidate = self.config.artifacts_dir / rootfs_image
            if artifact_candidate.exists():
                return artifact_candidate
        return self.config.rootfs_path

    def _build_launch_env(
        self, agent_id: str, vm_id: str, mh: str, manifest: dict[str, Any]
    ) -> dict[str, str]:
        engines = sorted((manifest.get("engines") or {}).keys())
        return {
            "CORVUS_AGENT_ID": agent_id,
            "CORVUS_VM_ID": vm_id,
            "CORVUS_MANIFEST_HASH": mh,
            "CORVUS_USE_TCP": "0",
            "CORVUS_VSOCK_HOST_CID": "2",
            "CORVUS_VSOCK_PORT": str(self.config.vsock_port),
            "CORVUS_NODE_SOCK": "/run/corvus/node.sock",
            "CORVUS_COORDINATOR_PATH": "/run/corvus/coordinator.json",
            "CORVUS_REGISTERED_ENGINES": ",".join(engines),
        }

    @staticmethod
    def _write_launch_package(
        launch_package_dir: Path, manifest: dict[str, Any], env: dict[str, str]
    ) -> None:
        launch_package_dir.mkdir(parents=True, exist_ok=True)
        (launch_package_dir / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        env_text = "".join(f"{key}={value}\n" for key, value in sorted(env.items()))
        (launch_package_dir / "env").write_text(env_text, encoding="utf-8")
