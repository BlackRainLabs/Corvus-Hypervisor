"""VM registry unit tests."""

import os

from corvus.vm.registry import VMRecord, VMRegistry


def test_registry_next_guest_cid(tmp_path):
    reg = VMRegistry(tmp_path)
    reg.register(
        VMRecord(
            vm_instance_id="a",
            agent_id="agent-1",
            guest_cid=3,
            api_socket="/tmp/a.sock",
            pid=os.getpid(),
            manifest_hash="mh",
        )
    )
    assert reg.next_guest_cid(3) == 4
    assert reg.get_by_agent("agent-1") is not None


def test_registry_marks_dead_pid_failed(tmp_path):
    reg = VMRegistry(tmp_path)
    reg.register(
        VMRecord(
            vm_instance_id="dead",
            agent_id="agent-1",
            guest_cid=3,
            api_socket="/tmp/dead.sock",
            pid=99999999,
            manifest_hash="mh",
        )
    )

    rec = reg.latest_by_agent("agent-1")
    assert rec is not None
    assert rec.status == "failed"
    assert rec.last_error == "Firecracker process is not running"
