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
export CORVUS_DUMMY_LLM_PORT="${CORVUS_DUMMY_LLM_PORT:-8765}"

if [[ -x "$ROOT/.venv/bin/corvus-server" ]]; then
  CORVUS_SERVER_BIN="$ROOT/.venv/bin/corvus-server"
  CORVUS_NODE_BIN="$ROOT/.venv/bin/corvus-node"
  CORVUS_DUMMY_LLM_BIN="$ROOT/.venv/bin/corvus-dummy-llm"
elif command -v corvus-server >/dev/null 2>&1; then
  CORVUS_SERVER_BIN="$(command -v corvus-server)"
  CORVUS_NODE_BIN="$(command -v corvus-node)"
  CORVUS_DUMMY_LLM_BIN="$(command -v corvus-dummy-llm || true)"
else
  echo "ERROR: corvus-server not found. Run: pip install -e '.[dev]'" >&2
  exit 1
fi

stop_stack() {
  if [[ -f "$STATE_DIR/dummy-llm.pid" ]]; then
    kill "$(cat "$STATE_DIR/dummy-llm.pid")" 2>/dev/null || true
    rm -f "$STATE_DIR/dummy-llm.pid"
  fi
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
    if [[ -n "${CORVUS_DUMMY_LLM_BIN:-}" && -x "$CORVUS_DUMMY_LLM_BIN" ]]; then
      "$CORVUS_DUMMY_LLM_BIN" --port "$CORVUS_DUMMY_LLM_PORT" >"$STATE_DIR/dummy-llm.log" 2>&1 &
      echo $! >"$STATE_DIR/dummy-llm.pid"
    fi
    echo "Corvus dev stack running."
    echo "  transport: tcp://${CORVUS_TCP_HOST:-127.0.0.1}:${CORVUS_TCP_PORT}"
    echo "  management: http://${CORVUS_MGMT_HOST:-127.0.0.1}:${CORVUS_MGMT_PORT}"
    echo "  console: http://${CORVUS_MGMT_HOST:-127.0.0.1}:${CORVUS_MGMT_PORT}/ui"
    echo "  chat: http://${CORVUS_MGMT_HOST:-127.0.0.1}:${CORVUS_MGMT_PORT}/ui/chat"
    echo "  dummy LLM: http://127.0.0.1:${CORVUS_DUMMY_LLM_PORT}/v1"
    echo "  node ipc: ${CORVUS_NODE_SOCK}"
    echo "  logs: $STATE_DIR/{server,node,dummy-llm}.log"
    echo "Sign in: admin-user / 0000"
    echo "Run one turn: make run-turn"
    echo "Stop with: tools/dev-stack.sh down"
    ;;
  status)
    for name in server node dummy-llm; do
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
