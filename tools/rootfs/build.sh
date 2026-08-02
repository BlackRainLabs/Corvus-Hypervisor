#!/usr/bin/env bash
# Build Corvus agent rootfs ext4 image (requires Docker and root/sudo for loop mount).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACTS="${CORVUS_ARTIFACTS_DIR:-$ROOT/artifacts}"
OVERLAY="$ROOT/tools/rootfs/overlay"
MANIFEST="${CORVUS_MANIFEST_PATH:-$ROOT/tools/rootfs/manifest.json}"
IMAGE_SIZE_MB="${CORVUS_ROOTFS_SIZE_MB:-512}"
DOCKER_CMD=(docker)
if ! docker info >/dev/null 2>&1; then
  DOCKER_CMD=(sudo docker)
fi

mkdir -p "$ARTIFACTS"
MH=$(python3 -c "import json,hashlib; d=json.load(open('$MANIFEST')); print(hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':')).encode()).hexdigest())")

echo "==> Building rootfs in Docker (Python 3.12 Debian)..."
"${DOCKER_CMD[@]}" run --rm -v "$ROOT:/src:ro" -v "$ARTIFACTS:/out" -v "$MANIFEST:/manifest.json:ro" -e "CORVUS_BUILD_MANIFEST_HASH=$MH" python:3.12-slim-bookworm sh -c '
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates systemd
  apt-get clean
  rm -rf /var/lib/apt/lists/*
  ROOTFS=/tmp/rootfs
  mkdir -p "$ROOTFS"
  for d in bin sbin usr lib lib64 etc var run tmp opt dev proc sys; do
    mkdir -p "$ROOTFS/$d"
  done
  cp -a /bin/. "$ROOTFS/bin/"
  cp -a /sbin/. "$ROOTFS/sbin/"
  cp -a /lib/. "$ROOTFS/lib/"
  if [ -d /lib64 ]; then
    cp -a /lib64/. "$ROOTFS/lib64/"
  fi
  cp -a /usr/. "$ROOTFS/usr/"
  ln -sf /usr/local/bin/python3 "$ROOTFS/usr/bin/python3"
  ln -sf /lib/systemd/systemd "$ROOTFS/sbin/init"
  # Install corvus package into rootfs
  python3 -m pip install --target="$ROOTFS/opt/corvus" /src
  mkdir -p "$ROOTFS/etc/corvus" "$ROOTFS/run/corvus"
  cp /manifest.json "$ROOTFS/etc/corvus/manifest.json"
  cat > "$ROOTFS/etc/corvus/env" <<EOF
CORVUS_USE_TCP=0
CORVUS_VSOCK_HOST_CID=2
CORVUS_VSOCK_PORT=4040
CORVUS_NODE_SOCK=/run/corvus/node.sock
CORVUS_COORDINATOR_PATH=/run/corvus/coordinator.json
CORVUS_AGENT_ID=test-agent-01
CORVUS_VM_ID=fc-test-vm
CORVUS_MANIFEST_HASH=$CORVUS_BUILD_MANIFEST_HASH
EOF
  # systemd units
  mkdir -p "$ROOTFS/etc/systemd/system"
  cp /src/tools/rootfs/overlay/etc/systemd/system/*.service "$ROOTFS/etc/systemd/system/"
  ln -sf /etc/systemd/system/corvus-node.service "$ROOTFS/etc/systemd/system/multi-user.target.wants/corvus-node.service" 2>/dev/null || \
    mkdir -p "$ROOTFS/etc/systemd/system/multi-user.target.wants" && \
    ln -sf /etc/systemd/system/corvus-node.service "$ROOTFS/etc/systemd/system/multi-user.target.wants/corvus-node.service"
  for u in corvus-loop corvus-engine1 corvus-engine2 corvus-engine3 corvus-engine4; do
    ln -sf "/etc/systemd/system/${u}.service" "$ROOTFS/etc/systemd/system/multi-user.target.wants/${u}.service"
  done
  tar -C "$ROOTFS" -cf /out/rootfs.tar .
'

ROOTFS_EXT4="$ARTIFACTS/rootfs.ext4"
echo "==> Creating ext4 image (${IMAGE_SIZE_MB}MB)..."
rm -f "$ROOTFS_EXT4"
dd if=/dev/zero of="$ROOTFS_EXT4" bs=1M count="$IMAGE_SIZE_MB" status=none
mkfs.ext4 -F "$ROOTFS_EXT4" >/dev/null
MNT=$(mktemp -d)
if mount -o loop "$ROOTFS_EXT4" "$MNT" 2>/dev/null; then
  tar -xf "$ARTIFACTS/rootfs.tar" -C "$MNT"
  umount "$MNT"
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "==> Populating ext4 via privileged Docker (no sudo mount)..."
  docker run --rm --privileged -v "$ARTIFACTS:/artifacts" debian:bookworm-slim bash -c \
    'apt-get update -qq && apt-get install -y -qq e2fsprogs >/dev/null && mkdir -p /mnt && mount -o loop /artifacts/rootfs.ext4 /mnt && find /mnt -mindepth 1 -delete && tar --overwrite -xf /artifacts/rootfs.tar -C /mnt && umount /mnt'
else
  rmdir "$MNT"
  echo "ERROR: need sudo mount or Docker to populate rootfs.ext4"
  exit 1
fi
rmdir "$MNT"
rm -f "$ARTIFACTS/rootfs.tar"

cat > "$ARTIFACTS/version.json" <<EOF
{"manifest_hash":"$MH","built_at":"$(date -Iseconds)"}
EOF

echo "==> Rootfs ready: $ROOTFS_EXT4"
echo "    Fetch kernel: tools/rootfs/fetch-kernel.sh"
