#!/usr/bin/env bash
# Run one agent turn against the local dev stack (server + node must be up).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STATE_DIR="${CORVUS_DEV_STATE_DIR:-/tmp/corvus-dev}"

if [[ -f "$STATE_DIR/env" ]]; then
  # shellcheck disable=SC1090
  source "$STATE_DIR/env"
elif [[ -f tools/corvus.env.example ]]; then
  # shellcheck disable=SC1090
  source tools/corvus.env.example
fi

export CORVUS_USE_TCP="${CORVUS_USE_TCP:-1}"
export CORVUS_NODE_SOCK="${CORVUS_NODE_SOCK:-/tmp/corvus-node.sock}"
export CORVUS_COORDINATOR_PATH="${CORVUS_COORDINATOR_PATH:-/tmp/corvus-coordinator.json}"
export CORVUS_DB_PATH="${CORVUS_DB_PATH:-$STATE_DIR/corvus.db}"

if [[ ! -S "$CORVUS_NODE_SOCK" ]] && [[ ! -f "$STATE_DIR/node.pid" ]]; then
  echo "ERROR: Corvus Node does not appear to be running." >&2
  echo "Start the dev stack first: make dev-up" >&2
  exit 1
fi

if [[ -x "$ROOT/.venv/bin/corvus-runtime" ]]; then
  CORVUS_RUNTIME_BIN="$ROOT/.venv/bin/corvus-runtime"
elif command -v corvus-runtime >/dev/null 2>&1; then
  CORVUS_RUNTIME_BIN="$(command -v corvus-runtime)"
else
  echo "ERROR: corvus-runtime not found. Run: make install" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  set -- --once
fi

exec "$CORVUS_RUNTIME_BIN" "$@"
