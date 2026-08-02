"""VM spec builder unit tests."""

from pathlib import Path

from corvus.vm.spec import (
    VmSpec,
    build_boot_source,
    build_machine_config,
    build_root_drive,
    build_vsock,
)


def test_build_machine_config():
    spec = VmSpec(
        vm_instance_id="vm-1",
        agent_id="agent-1",
        guest_cid=3,
        kernel_path=Path("/kernels/vmlinux"),
        rootfs_path=Path("/images/rootfs.ext4"),
        vcpu_count=2,
        mem_size_mib=512,
        vsock_port=4040,
        api_socket=Path("/tmp/fc.sock"),
        vsock_uds=Path("/tmp/vsock.sock"),
        boot_env={"CORVUS_AGENT_ID": "agent-1", "CORVUS_VM_ID": "vm-1"},
    )
    mc = build_machine_config(spec)
    assert mc["vcpu_count"] == 2
    assert mc["mem_size_mib"] == 512

    boot = build_boot_source(spec)
    assert boot["kernel_image_path"] == "/kernels/vmlinux"
    assert "console=ttyS0" in boot["boot_args"]
    assert "systemd.setenv=CORVUS_AGENT_ID=agent-1" in boot["boot_args"]

    drive = build_root_drive(spec)
    assert drive["is_read_only"] is True
    assert drive["path_on_host"] == "/images/rootfs.ext4"

    vsock = build_vsock(spec)
    assert vsock["guest_cid"] == 3
    assert vsock["uds_path"] == "/tmp/vsock.sock"
