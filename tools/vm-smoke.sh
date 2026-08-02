#!/usr/bin/env bash
# Firecracker launch/stop smoke test (requires KVM, firecracker, built rootfs + kernel).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export CORVUS_USE_TCP=0
export CORVUS_VSOCK_HOST_CID=2
export CORVUS_VSOCK_PORT=4040
export CORVUS_DB_PATH="${CORVUS_DB_PATH:-$ROOT/corvus-smoke.db}"
export CORVUS_ARTIFACTS_DIR="${CORVUS_ARTIFACTS_DIR:-$ROOT/artifacts}"
export CORVUS_VM_STATE_DIR="${CORVUS_VM_STATE_DIR:-/tmp/corvus-vms}"
export PYTHONPATH="${PYTHONPATH:-$ROOT/src}"

if [[ -z "${PYTHON:-}" && -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
export PATH="${ROOT}/.venv/bin:${HOME}/.local/bin:${PATH}"

# Stop stale VM for test agent if registry still tracks one
if command -v corvus-vm >/dev/null 2>&1; then
  STALE=$(
    corvus-vm status 2>/dev/null | "$PYTHON" -c "import sys,json; recs=json.load(sys.stdin); print(next((r['vm_instance_id'] for r in recs if r.get('agent_id')=='test-agent-01' and r.get('status') in {'launching','booting','handshaking','running','degraded'}), ''))" 2>/dev/null || true
  )
  if [[ -n "$STALE" ]]; then
    corvus-vm stop --vm "$STALE" || true
  fi
fi
if command -v corvus-server >/dev/null 2>&1; then
  CORVUS_SERVER=(corvus-server)
else
  CORVUS_SERVER=("$PYTHON" -m corvus.server.main)
fi
if command -v corvus-vm >/dev/null 2>&1; then
  CORVUS_VM=(corvus-vm)
else
  CORVUS_VM=("$PYTHON" -m corvus.vm.main)
fi

if [[ ! -c /dev/kvm ]]; then
  echo "ERROR: /dev/kvm not available"
  exit 1
fi
if [[ ! -r /dev/kvm || ! -w /dev/kvm ]]; then
  echo "ERROR: /dev/kvm exists but is not readable/writable by $(id -un)"
  echo "       Add the user to the kvm group or grant an ACL, then start a new shell."
  exit 1
fi
if ! command -v firecracker >/dev/null 2>&1; then
  echo "ERROR: firecracker binary not on PATH"
  exit 1
fi
if [[ ! -f "$CORVUS_ARTIFACTS_DIR/vmlinux" ]]; then
  echo "==> Fetching kernel..."
  bash tools/rootfs/fetch-kernel.sh
fi
if [[ ! -f "$CORVUS_ARTIFACTS_DIR/rootfs.ext4" ]]; then
  echo "==> Building rootfs (requires Docker + sudo)..."
  bash tools/rootfs/build.sh
fi

if pgrep -f '[c]orvus-server' >/dev/null 2>&1; then
  echo "==> Stopping stale corvus-server..."
  pkill -f '[c]orvus-server' || true
  sleep 1
fi

echo "==> Starting corvus-server..."
rm -f "$CORVUS_DB_PATH" "$CORVUS_DB_PATH-journal"
"${CORVUS_SERVER[@]}" &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  if curl -sf -H "X-API-Key: dev-api-key" "http://127.0.0.1:8080/v1/agents" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "ERROR: corvus-server exited before becoming ready"
    wait "$SERVER_PID" || true
    exit 1
  fi
  sleep 0.5
done
if ! curl -sf -H "X-API-Key: dev-api-key" "http://127.0.0.1:8080/v1/agents" >/dev/null 2>&1; then
  echo "ERROR: corvus-server management API not reachable"
  exit 1
fi

echo "==> Launching microVM..."
LAUNCH_JSON=$("${CORVUS_VM[@]}" launch --agent test-agent-01)
VM_ID=$(echo "$LAUNCH_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['vm_instance_id'])")
echo "    VM instance: $VM_ID"

echo "==> Waiting for VM registry status..."
RUNNING_SEEN=0
for _ in $(seq 1 60); do
  if curl -sf -H "X-API-Key: dev-api-key" "http://127.0.0.1:8080/v1/agents" | grep -q '"status":"running"'; then
    RUNNING_SEEN=1
    break
  fi
  sleep 1
done
if [[ "$RUNNING_SEEN" != "1" ]]; then
  echo "ERROR: VM did not reach running status in Management API"
  curl -sf -H "X-API-Key: dev-api-key" "http://127.0.0.1:8080/v1/agents" | python3 -m json.tool || true
  "${CORVUS_VM[@]}" stop --vm "$VM_ID" || true
  exit 1
fi

if [[ "${CORVUS_VM_SMOKE_SKIP_MEMORY:-0}" != "1" ]]; then
  echo "==> Waiting for Engine 4 memory turn in server DB..."
  export CORVUS_AGENT_ID="${CORVUS_AGENT_ID:-test-agent-01}"
  if ! "$PYTHON" tools/wait_vm_memory_turn.py --timeout "${CORVUS_VM_MEMORY_TIMEOUT:-120}"; then
    echo "ERROR: Guest memory turn not observed (rebuild rootfs after Phase 4.1 if stale)"
    "${CORVUS_VM[@]}" stop --vm "$VM_ID" || true
    exit 1
  fi
else
  echo "==> Skipping memory turn check (CORVUS_VM_SMOKE_SKIP_MEMORY=1)"
fi

if [[ "${CORVUS_VM_SMOKE_SKIP_FULL_TURN:-0}" != "1" ]]; then
  echo "==> Waiting for full guest turn trace in server audit log..."
  export CORVUS_AGENT_ID="${CORVUS_AGENT_ID:-test-agent-01}"
  if ! "$PYTHON" tools/wait_vm_full_turn.py --timeout "${CORVUS_VM_FULL_TURN_TIMEOUT:-120}"; then
    echo "ERROR: Guest full turn audit trace not observed (rebuild rootfs if stale)"
    "${CORVUS_VM[@]}" stop --vm "$VM_ID" || true
    exit 1
  fi
else
  echo "==> Skipping full turn audit check (CORVUS_VM_SMOKE_SKIP_FULL_TURN=1)"
fi

echo "==> Checking agent status..."
curl -sf -H "X-API-Key: dev-api-key" "http://127.0.0.1:8080/v1/agents" | python3 -m json.tool

echo "==> Stopping VM..."
"${CORVUS_VM[@]}" stop --vm "$VM_ID"

echo "==> Smoke test complete"
