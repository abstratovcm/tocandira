#!/usr/bin/env bash
# Build the release engine: the fork with the net of nets/release.env embedded (cargo feature
# bundled-net), into engine/nokamute/target/bundled/. --windows also cross builds win64
# (needs mingw-w64 and the x86_64-pc-windows-gnu target); the release workflow builds
# Windows natively instead.
# Usage: scripts/build_release.sh [--windows]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
set -a
source "$ROOT/nets/release.env"
set +a
export TOCANDIRA_NET="$ROOT/$TOCANDIRA_NET"
# Git Bash on Windows: rustc needs a Windows path for include_bytes!.
if command -v cygpath > /dev/null; then TOCANDIRA_NET="$(cygpath -m "$TOCANDIRA_NET")"; fi
cd "$ROOT/engine/nokamute"
cargo build --release -q --features bundled-net --target-dir target/bundled
if [ "${1:-}" = --windows ]; then
  cargo build --release -q --features bundled-net --target-dir target/bundled --target x86_64-pc-windows-gnu
fi
echo "built $ROOT/engine/nokamute/target/bundled/release/nokamute ($(basename "$TOCANDIRA_NET"), rfp $TOCANDIRA_RFP)"
