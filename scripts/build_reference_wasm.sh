#!/usr/bin/env bash
# Build the frozen reference opponent for the browser: upstream nokamute at a release tag,
# as a wasm-bindgen web package, into reference/nokamute-<version>-wasm/ (nokamute.js,
# nokamute_bg.wasm). Upstream commits no lock file, so wasm-bindgen is pinned to the
# version the installed wasm-bindgen-cli has (see scripts/build_wasm.sh).
# Usage: scripts/build_reference_wasm.sh [tag]   (default v1.0.3)
set -euo pipefail
TAG="${1:-v1.0.3}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/reference/nokamute-${TAG#v}-wasm"
VERSION="$(wasm-bindgen --version | awk '{print $2}')"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone -q --depth 1 --branch "$TAG" https://github.com/edre/nokamute "$TMP/nokamute"
(
  cd "$TMP/nokamute"
  cargo generate-lockfile -q
  cargo update -q -p wasm-bindgen --precise "$VERSION"
  CARGO_PROFILE_RELEASE_LTO=true CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
    cargo build --lib --release -q --target wasm32-unknown-unknown
)
rm -rf "$OUT"
wasm-bindgen --target web --no-typescript --out-dir "$OUT" \
  "$TMP/nokamute/target/wasm32-unknown-unknown/release/nokamute.wasm"
cp "$TMP/nokamute/LICENSE.md" "$OUT/LICENSE-nokamute.md"
echo "built $OUT"
