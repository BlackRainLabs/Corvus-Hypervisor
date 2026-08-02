#!/usr/bin/env bash
# Download a Firecracker-compatible Linux kernel.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACTS="${CORVUS_ARTIFACTS_DIR:-$ROOT/artifacts}"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64) KERNEL_ARCH=x86_64 ;;
  aarch64|arm64) KERNEL_ARCH=aarch64 ;;
  *) echo "Unsupported kernel architecture: $ARCH"; exit 1 ;;
esac
URL="${CORVUS_KERNEL_URL:-https://s3.amazonaws.com/spec.ccfc.min/ci-artifacts/kernels/${KERNEL_ARCH}/vmlinux-5.10.bin}"

mkdir -p "$ARTIFACTS"
DEST="$ARTIFACTS/vmlinux"
if [[ -f "$DEST" ]]; then
  echo "Kernel already present: $DEST"
  exit 0
fi
echo "==> Downloading $URL"
curl -fsSL "$URL" -o "$DEST"
chmod +x "$DEST"
echo "==> Kernel saved to $DEST"
