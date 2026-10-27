"""The release build plays exactly what was measured: the plain build with its net and flags."""

import os
import random

import pytest

from tocandira.uhp import NOKAMUTE, REPO_ROOT, Engine, PlayerSpec, game_state

RELEASE = os.path.join(REPO_ROOT, "engine", "nokamute", "target", "bundled", "release", "nokamute")
WASM_PKG = os.path.join(REPO_ROOT, "engine", "nokamute", "target", "bundled-wasm", "pkg")
MATCH_SWITCHES = "--null-move-pruning --lmr --partial-iteration --killers"
pytestmark = pytest.mark.skipif(
    not (os.path.exists(RELEASE) and os.path.exists(NOKAMUTE)),
    reason="engine or release build (scripts/build_release.sh) not built",
)


def _release_env() -> dict[str, str]:
    with open(os.path.join(REPO_ROOT, "nets", "release.env")) as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return dict(line.split("=", 1) for line in lines)


def test_release_build_searches_like_the_measured_configuration():
    env = _release_env()
    net = os.path.join(REPO_ROOT, env["TOCANDIRA_NET"])
    flags = f"--nnue {net} {MATCH_SWITCHES} --rfp={env['TOCANDIRA_RFP']}"
    measured = PlayerSpec(cmd=f"{NOKAMUTE} {flags}", depth=4, options={"NumThreads": "1"})
    # No options for the release: its own default must be the one thread search.
    rng = random.Random(0)
    with Engine(PlayerSpec(cmd=RELEASE, depth=4)) as release, Engine(measured) as reference:
        release.newgame()
        reference.newgame()
        for _ in range(40):
            assert release.search() == reference.search()
            move = rng.choice(release.validmoves())
            state = game_state(release.play(move))
            reference.play(move)
            if state != "InProgress":
                break


@pytest.mark.skipif(
    not os.path.isdir(WASM_PKG), reason="wasm build (scripts/build_wasm.sh) not built"
)
def test_wasm_package_exports_uhp_with_the_net_inside():
    """The browser package is the same engine: one `uhp` export, the net embedded."""
    with open(os.path.join(WASM_PKG, "nokamute.js")) as f:
        assert "export function uhp(" in f.read()
    net = os.path.join(REPO_ROOT, _release_env()["TOCANDIRA_NET"])
    assert os.path.getsize(os.path.join(WASM_PKG, "nokamute_bg.wasm")) > os.path.getsize(net)
