#!/usr/bin/env bash
# Export OpenAPI schema for the Management API without starting a long-lived server.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUTPUT="${1:-openapi.json}"
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PYTHON="$ROOT/.venv/bin/python"
  else
    PYTHON="python3"
  fi
fi

"$PYTHON" - <<'PY' "$OUTPUT"
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from corvus.management.api import create_app
from corvus.server.bootstrap import AppContext
from corvus.server.config import ServerConfig

output = Path(sys.argv[1])
rules = Path("config/default_rules.yaml")

async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        config = ServerConfig(
            db_path=tmp_path / "openapi.db",
            use_tcp=True,
            tcp_host="127.0.0.1",
            tcp_port=0,
            vsock_host_cid=2,
            vsock_port=4040,
            mgmt_host="127.0.0.1",
            mgmt_port=0,
            api_key="export-key",
            rules_path=rules,
            turn_timeout_seconds=300,
            max_chain_depth=8,
            session_ttl_hours=24,
            vm_state_dir=tmp_path / "vms",
            memory_sweep_interval_seconds=86400.0,
            memory_soft_delete_retention_hours=24,
            elevation_sweep_interval_seconds=86400.0,
            elevation_ttl_hours=1,
            elevation_webhook_url=None,
            behavioral_grant_denial_window_minutes=10,
            behavioral_grant_denial_threshold=3,
            behavioral_cross_agent_window_minutes=1,
            behavioral_cross_agent_threshold=10,
            behavioral_rate_baseline_minutes=60,
            behavioral_rate_zscore_threshold=3.0,
            behavioral_tool_zscore_threshold=3.0,
            behavioral_counter_retention_hours=24,
            memory_encryption_enabled=False,
            memory_master_key=None,
            memory_writes_daily_limit=10_000,
            llm_providers_path=Path("config/llm_providers.yaml"),
            llm_default_provider="stub",
            llm_request_timeout_seconds=60.0,
            llm_tokens_daily_limit=100_000,
        )
        ctx = AppContext(config)
        await ctx.startup()
        try:
            app = create_app(ctx)
            output.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
        finally:
            await ctx.shutdown()

asyncio.run(main())
print(f"Wrote {output}")
PY
