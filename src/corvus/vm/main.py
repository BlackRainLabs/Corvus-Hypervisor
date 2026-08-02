"""corvus-vm CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from corvus.server.manifest import canonical_manifest, manifest_hash, resolve_manifest
from corvus.vm.launcher import VMLauncher

logger = logging.getLogger(__name__)


async def _launch(agent_id: str, manifest_path: str | None) -> None:
    launcher = VMLauncher()
    manifest: dict | None = None
    if manifest_path:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    else:
        from corvus.server.bootstrap import TEST_AGENT_ID, TEST_MANIFEST

        if agent_id != TEST_AGENT_ID:
            raise SystemExit("Provide --manifest or use test-agent-01")
        manifest = TEST_MANIFEST

    resolved_manifest = canonical_manifest(resolve_manifest(manifest))
    record = await launcher.launch(
        agent_id,
        resolved_manifest,
        manifest_hash_value=manifest_hash(resolved_manifest),
    )
    print(json.dumps({"vm_instance_id": record.vm_instance_id, "guest_cid": record.guest_cid}))


async def _stop(vm_id: str) -> None:
    launcher = VMLauncher()
    await launcher.stop(vm_id)
    print(f"stopped {vm_id}")


async def _status() -> None:
    launcher = VMLauncher()
    records = launcher.status()
    print(json.dumps([r.__dict__ for r in records], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Corvus Firecracker VM launcher")
    sub = parser.add_subparsers(dest="command", required=True)

    launch_p = sub.add_parser("launch", help="Launch agent microVM")
    launch_p.add_argument("--agent", required=True)
    launch_p.add_argument("--manifest", help="Path to manifest JSON file")

    stop_p = sub.add_parser("stop", help="Stop microVM")
    stop_p.add_argument("--vm", required=True)

    sub.add_parser("status", help="List VM instances")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.command == "launch":
        asyncio.run(_launch(args.agent, args.manifest))
    elif args.command == "stop":
        asyncio.run(_stop(args.vm))
    elif args.command == "status":
        asyncio.run(_status())


if __name__ == "__main__":
    main()
