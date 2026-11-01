#!/usr/bin/env bash
# Build local platform packages; no publishing or FFmpeg downloading.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
out="${DIST_DIR:-$root/dist}"
mkdir -p "$out"
for target in darwin/arm64 linux/amd64 linux/arm64; do
  platform="${target%/*}"
  arch="${target#*/}"
  bundle="$out/duxue-gateway-${platform}-${arch}"
  mkdir -p "$bundle/configs" "$bundle/deploy"
  CGO_ENABLED=0 GOOS="$platform" GOARCH="$arch" go build -trimpath -ldflags='-s -w' -o "$bundle/duxue-gateway" ./cmd/duxue-gateway
  cp configs/config.example.yaml "$bundle/configs/"
  cp deploy/duxue-gateway.service "$bundle/deploy/"
  printf '%s\n' 'Requires a separately installed FFmpeg for RTSP capture.' 'No Python or Go compiler is required to run this package.' 'Configure camera credentials and the gateway token via environment variables.' > "$bundle/DEPENDENCIES.txt"
  # Archive only generated public files. A developer may have run an earlier
  # bundle in-place; its state, private config and credentials must never ship.
  name="${bundle##*/}"
  tar -C "$out" -czf "$bundle.tar.gz" \
    "$name/duxue-gateway" \
    "$name/configs/config.example.yaml" \
    "$name/deploy/duxue-gateway.service" \
    "$name/DEPENDENCIES.txt"
done
if command -v sha256sum >/dev/null; then
  (cd "$out" && sha256sum ./*.tar.gz > SHA256SUMS)
else
  (cd "$out" && shasum -a 256 ./*.tar.gz > SHA256SUMS)
fi
