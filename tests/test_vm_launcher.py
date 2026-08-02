"""VM launcher lifecycle tests."""

from __future__ import annotations

import pytest

import corvus.vm.launcher as launcher_module
from corvus.vm.config import VmConfig
from corvus.vm.launcher import VMLauncher


@pytest.mark.asyncio
async def test_launch_cleans_up_process_on_firecracker_api_failure(tmp_path, monkeypatch):
    kernel = tmp_path / "vmlinux"
    rootfs = tmp_path / "rootfs.ext4"
    state_dir = tmp_path / "state"
    kernel.write_bytes(b"kernel")
    rootfs.write_bytes(b"rootfs")

    processes: list[FakeProcess] = []

    class FakeProcess:
        pid = 4242

        def __init__(self, *_args, **kwargs) -> None:
            self.killed = False
            self.env = kwargs.get("env", {})
            processes.append(self)

        def kill(self) -> None:
            self.killed = True

    class FakeFirecrackerClient:
        def __init__(self, _api_socket) -> None:
            self.closed = False

        async def put(self, path: str, _body: dict) -> None:
            if path == "/boot-source":
                raise RuntimeError("firecracker rejected boot source")

        async def close(self) -> None:
            self.closed = True

    async def fake_wait_for_api_socket(path, timeout=10.0):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return True

    monkeypatch.setattr(launcher_module.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(launcher_module, "FirecrackerClient", FakeFirecrackerClient)
    monkeypatch.setattr(launcher_module, "wait_for_api_socket", fake_wait_for_api_socket)

    launcher = VMLauncher(
        VmConfig(
            artifacts_dir=tmp_path,
            kernel_path=kernel,
            rootfs_path=rootfs,
            firecracker_bin="firecracker",
            vsock_port=4040,
            guest_cid_start=3,
            state_dir=state_dir,
        )
    )

    with pytest.raises(RuntimeError, match="firecracker rejected boot source"):
        await launcher.launch("agent-1", {"resource_limits": {}})

    assert processes and processes[0].killed is True
    records = launcher.status()
    assert len(records) == 1
    assert records[0].status == "failed"
    assert records[0].last_error == "firecracker rejected boot source"
    assert records[0].manifest_hash
    assert processes[0].env["CORVUS_AGENT_ID"] == "agent-1"
    assert processes[0].env["CORVUS_MANIFEST_HASH"] == records[0].manifest_hash
    launch_package = state_dir / "launch-packages" / records[0].vm_instance_id
    assert (launch_package / "manifest.json").exists()
    assert (launch_package / "env").exists()
    assert not list(state_dir.glob("fc-*.sock"))
    assert not list(state_dir.glob("vsock-*.sock"))
