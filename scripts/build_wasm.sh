#!/usr/bin/env bash
# Build the release engine for the browser: the fork's library with the net of
# nets/release.env embedded (cargo feature bundled-net) for wasm32-unknown-unknown, then
# wasm-bindgen's web target, into engine/nokamute/target/bundled-wasm/pkg/ (nokamute.js,
# nokamute_bg.wasm). Needs the wasm32-unknown-unknown target and wasm-bindgen-cli at the
# version of the wasm-bindgen crate in the fork's Cargo.lock. The browser build uses the
# scalar network path (no AVX2), so it is slower per node than the native binary.
# Usage: scripts/build_wasm.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a
source "$ROOT/nets/release.env"
set +a
export TOCANDIRA_NET="$ROOT/$TOCANDIRA_NET"
if command -v cygpath > /dev/null; then TOCANDIRA_NET="$(cygpath -m "$TOCANDIRA_NET")"; fi
cd "$ROOT/engine/nokamute"
WANT="$(grep -A1 '^name = "wasm-bindgen"$' Cargo.lock | sed -n 's/^version = "\(.*\)"/\1/p')"
HAVE="$(wasm-bindgen --version 2>/dev/null | awk '{print $2}' || true)"
if [ "$HAVE" != "$WANT" ]; then
  echo "need wasm-bindgen-cli $WANT (have '${HAVE:-none}'): cargo install wasm-bindgen-cli --version $WANT --locked" >&2
  exit 1
fi
TARGET_DIR=target/bundled-wasm
cargo build --lib --release -q --features bundled-net --target wasm32-unknown-unknown --target-dir $TARGET_DIR
rm -rf $TARGET_DIR/pkg
wasm-bindgen --target web --out-dir $TARGET_DIR/pkg --no-typescript \
  $TARGET_DIR/wasm32-unknown-unknown/release/nokamute.wasm
echo "built $ROOT/engine/nokamute/$TARGET_DIR/pkg ($(basename "$TOCANDIRA_NET"), rfp $TOCANDIRA_RFP)"
