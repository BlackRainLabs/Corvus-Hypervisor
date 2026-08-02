#!/usr/bin/env bash
# Start Corvus server + node for local TCP development.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STATE_DIR="${CORVUS_DEV_STATE_DIR:-/tmp/corvus-dev}"
mkdir -p "$STATE_DIR"

if [[ -f tools/corvus.env.example && ! -f "$STATE_DIR/env" ]]; then
  cp tools/corvus.env.example "$STATE_DIR/env"
fi
# shellcheck disable=SC1090
source "${CORVUS_DEV_ENV:-$STATE_DIR/env}"

export CORVUS_USE_TCP="${CORVUS_USE_TCP:-1}"
export CORVUS_TCP_PORT="${CORVUS_TCP_PORT:-4040}"
export CORVUS_MGMT_PORT="${CORVUS_MGMT_PORT:-8080}"
export CORVUS_NODE_SOCK="${CORVUS_NODE_SOCK:-/tmp/corvus-node.sock}"
export CORVUS_COORDINATOR_PATH="${CORVUS_COORDINATOR_PATH:-/tmp/corvus-coordinator.json}"
export CORVUS_DB_PATH="${CORVUS_DB_PATH:-$STATE_DIR/corvus.db}"

if [[ -x "$ROOT/.venv/bin/corvus-server" ]]; then
  CORVUS_SERVER_BIN="$ROOT/.venv/bin/corvus-server"
  CORVUS_NODE_BIN="$ROOT/.venv/bin/corvus-node"
elif command -v corvus-server >/dev/null 2>&1; then
  CORVUS_SERVER_BIN="$(command -v corvus-server)"
  CORVUS_NODE_BIN="$(command -v corvus-node)"
else
  echo "ERROR: corvus-server not found. Run: pip install -e '.[dev]'" >&2
  exit 1
fi

stop_stack() {
  if [[ -f "$STATE_DIR/node.pid" ]]; then
    kill "$(cat "$STATE_DIR/node.pid")" 2>/dev/null || true
    rm -f "$STATE_DIR/node.pid"
  fi
  if [[ -f "$STATE_DIR/server.pid" ]]; then
    kill "$(cat "$STATE_DIR/server.pid")" 2>/dev/null || true
    rm -f "$STATE_DIR/server.pid"
  fi
}

case "${1:-up}" in
  down)
    stop_stack
    echo "Corvus dev stack stopped."
    ;;
  up)
    stop_stack
    "$CORVUS_SERVER_BIN" >"$STATE_DIR/server.log" 2>&1 &
    echo $! >"$STATE_DIR/server.pid"
    sleep 0.5
    "$CORVUS_NODE_BIN" >"$STATE_DIR/node.log" 2>&1 &
    echo $! >"$STATE_DIR/node.pid"
    echo "Corvus dev stack running."
    echo "  transport: tcp://${CORVUS_TCP_HOST:-127.0.0.1}:${CORVUS_TCP_PORT}"
    echo "  management: http://${CORVUS_MGMT_HOST:-127.0.0.1}:${CORVUS_MGMT_PORT}"
    echo "  node ipc: ${CORVUS_NODE_SOCK}"
    echo "  logs: $STATE_DIR/{server,node}.log"
    echo "Run one turn: make run-turn"
    echo "Stop with: tools/dev-stack.sh down"
    ;;
  status)
    for name in server node; do
      pid_file="$STATE_DIR/${name}.pid"
      if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
        echo "$name: running (pid $(cat "$pid_file"))"
      else
        echo "$name: stopped"
      fi
    done
    ;;
  *)
    echo "Usage: tools/dev-stack.sh {up|down|status}" >&2
    exit 1
    ;;
esac
