"""Track running microVM instances."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

ACTIVE_STATES = {"launching", "booting", "handshaking", "running", "degraded", "stopping"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class VMRecord:
    vm_instance_id: str
    agent_id: str
    guest_cid: int
    api_socket: str
    pid: int | None
    status: str = "running"
    manifest_hash: str = ""
    vsock_uds: str = ""
    launch_package_dir: str = ""
    stdout_log: str = ""
    stderr_log: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_heartbeat_at: str | None = None
    last_error: str | None = None
    stop_reason: str | None = None
    graceful_stop: bool | None = None


class VMRegistry:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = state_dir / "registry.json"
        self._records: dict[str, VMRecord] = {}
        self._load()

    def _load(self) -> None:
        self._records = {}
        if not self._index_path.exists():
            return
        data = json.loads(self._index_path.read_text(encoding="utf-8"))
        for item in data.get("vms", []):
            item.setdefault("created_at", utc_now())
            item.setdefault("updated_at", item["created_at"])
            rec = VMRecord(**item)
            self._records[rec.vm_instance_id] = rec

    def refresh(self) -> None:
        self._load()
        changed = False
        for rec in self._records.values():
            if rec.status in ACTIVE_STATES and not self._pid_is_alive(rec.pid):
                rec.status = "failed"
                rec.last_error = "Firecracker process is not running"
                rec.updated_at = utc_now()
                changed = True
        if changed:
            self._save()

    def _save(self) -> None:
        payload = {"vms": [asdict(r) for r in self._records.values()]}
        self._index_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def register(self, record: VMRecord) -> None:
        self.refresh()
        now = utc_now()
        if not record.created_at:
            record.created_at = now
        record.updated_at = now
        self._records[record.vm_instance_id] = record
        self._save()

    def get(self, vm_instance_id: str) -> VMRecord | None:
        self.refresh()
        return self._records.get(vm_instance_id)

    def get_by_agent(self, agent_id: str) -> VMRecord | None:
        self.refresh()
        for rec in self._records.values():
            if rec.agent_id == agent_id and rec.status in ACTIVE_STATES:
                return rec
        return None

    def latest_by_agent(self, agent_id: str) -> VMRecord | None:
        self.refresh()
        records = [rec for rec in self._records.values() if rec.agent_id == agent_id]
        if not records:
            return None
        return max(records, key=lambda rec: rec.updated_at or rec.created_at)

    def list_by_agent(self, agent_id: str) -> list[VMRecord]:
        self.refresh()
        return [rec for rec in self._records.values() if rec.agent_id == agent_id]

    def update_status(
        self,
        vm_instance_id: str,
        status: str,
        *,
        last_error: str | None = None,
        stop_reason: str | None = None,
        graceful_stop: bool | None = None,
    ) -> None:
        self.refresh()
        rec = self._records.get(vm_instance_id)
        if rec is None:
            return
        rec.status = status
        rec.updated_at = utc_now()
        if last_error is not None:
            rec.last_error = last_error
        if stop_reason is not None:
            rec.stop_reason = stop_reason
        if graceful_stop is not None:
            rec.graceful_stop = graceful_stop
        self._save()

    def remove(self, vm_instance_id: str) -> None:
        self.refresh()
        self._records.pop(vm_instance_id, None)
        self._save()

    def list_all(self) -> list[VMRecord]:
        self.refresh()
        return list(self._records.values())

    def next_guest_cid(self, start: int) -> int:
        self.refresh()
        used = {r.guest_cid for r in self._records.values() if r.status in ACTIVE_STATES}
        cid = start
        while cid in used:
            cid += 1
        return cid

    @staticmethod
    def pid_is_alive(pid: int | None) -> bool:
        if pid is None:
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    _pid_is_alive = pid_is_alive
