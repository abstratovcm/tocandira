import os
import random

import pytest

from tocandira.game import play_game, random_opening
from tocandira.uhp import NOKAMUTE, Engine, PlayerSpec, game_state

pytestmark = pytest.mark.skipif(not os.path.exists(NOKAMUTE), reason="engine not built")

TERMINAL = {"WhiteWins", "BlackWins", "Draw"}


def test_random_opening_is_legal_and_reproducible():
    with Engine(PlayerSpec(depth=1)) as engine:
        first, state = random_opening(engine, 4, random.Random(7))
        second, _ = random_opening(engine, 4, random.Random(7))
    assert len(first) == 4
    assert first == second
    assert state == "InProgress"


def test_play_game_finishes_and_replays():
    spec = PlayerSpec.parse("depth=1")
    with Engine(spec) as engine:
        opening, _ = random_opening(engine, 4, random.Random(1))
    record = play_game(spec, spec, opening, ply_cap=120)

    assert record.result in TERMINAL | {"PlyCap"}
    assert record.error == ""
    assert record.plies == len(record.moves)
    assert record.moves[:4] == opening
    assert record.score_for_white() in (0.0, 0.5, 1.0)

    with Engine(spec) as engine:
        engine.newgame()
        state = "NotStarted"
        for move in record.moves:
            state = game_state(engine.play(move))
    assert state == ("InProgress" if record.result == "PlyCap" else record.result)
