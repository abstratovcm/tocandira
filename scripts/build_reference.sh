#!/usr/bin/env bash
# Build the frozen reference opponent: upstream nokamute at a release tag, into reference/.
# Usage: scripts/build_reference.sh [tag]   (default v1.0.3)
set -euo pipefail
TAG="${1:-v1.0.3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/reference/nokamute-${TAG#v}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone -q --depth 1 --branch "$TAG" https://github.com/edre/nokamute "$TMP/nokamute"
( cd "$TMP/nokamute" && CARGO_PROFILE_RELEASE_LTO=true CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 cargo build --release -q )
mkdir -p "$ROOT/reference"
cp "$TMP/nokamute/target/release/nokamute" "$OUT"
echo "built $OUT ($("$OUT" --help 2>/dev/null | head -1 || true))"
