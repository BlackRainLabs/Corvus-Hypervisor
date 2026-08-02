"""Prometheus text exposition for Corvus server ops metrics."""

from __future__ import annotations

from corvus.server.bootstrap import AppContext
from corvus.vm.launcher import VMLauncher


def _gauge(lines: list[str], name: str, help_text: str, value: int | float) -> None:
    lines.append(f"# HELP {name} {help_text}")
    lines.append(f"# TYPE {name} gauge")
    lines.append(f"{name} {value}")


async def collect_metric_values(
    ctx: AppContext,
    vm_launcher: VMLauncher,
) -> dict[str, int | float]:
    vms = vm_launcher.status()
    degraded = [vm for vm in vms if vm.status in {"degraded", "failed"}]
    active_vm_statuses = {"launching", "booting", "handshaking", "running", "degraded"}
    return {
        "corvus_server_degraded": 1 if degraded else 0,
        "corvus_active_sessions": ctx.sessions.active_connection_count,
        "corvus_pending_replay_depth": await ctx.db.count_pending_replays(),
        "corvus_memory_sweeper_running": 1 if ctx.memory_sweeper.is_running else 0,
        "corvus_elevation_sweeper_running": 1 if ctx.elevation_sweeper.is_running else 0,
        "corvus_vm_registry_total": len(vms),
        "corvus_vm_registry_active": len([vm for vm in vms if vm.status in active_vm_statuses]),
        "corvus_vm_registry_failed": len(degraded),
    }


def render_prometheus_metrics(values: dict[str, int | float]) -> str:
    help_text = {
        "corvus_server_degraded": "1 when any VM is degraded or failed",
        "corvus_active_sessions": "Active agent transport sessions",
        "corvus_pending_replay_depth": "Undelivered pending replay messages",
        "corvus_memory_sweeper_running": "1 when memory retention sweeper task is running",
        "corvus_elevation_sweeper_running": "1 when elevation expiry sweeper task is running",
        "corvus_vm_registry_total": "Total VM records in registry",
        "corvus_vm_registry_active": "VMs in launching through degraded states",
        "corvus_vm_registry_failed": "VMs in degraded or failed state",
    }
    lines: list[str] = []
    for name, value in values.items():
        _gauge(lines, name, help_text[name], value)
    return "\n".join(lines) + "\n"


async def render_prometheus_metrics_for_context(
    ctx: AppContext,
    vm_launcher: VMLauncher,
) -> str:
    values = await collect_metric_values(ctx, vm_launcher)
    return render_prometheus_metrics(values)
