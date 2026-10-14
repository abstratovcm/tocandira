import os

import pytest

from tocandira.label import label_game, relabel_game
from tocandira.uhp import NOKAMUTE, PlayerSpec

pytestmark = pytest.mark.skipif(not os.path.exists(NOKAMUTE), reason="engine not built")

KEYS = {"ply", "score", "static", "best", "played", "random", "pvlen", "outcome"}


def _game(eps: float, seed: int = 3) -> dict:
    return label_game(0, PlayerSpec.parse("depth=1"), 4, eps, "Base+MLP", 80, seed)


def test_positions_have_documented_shape():
    game = _game(eps=0.0)
    positions = game["positions"]
    assert game["result"] in {"WhiteWins", "BlackWins", "Draw", "PlyCap"}
    assert positions
    assert all(set(p) == KEYS for p in positions)
    assert [p["ply"] for p in positions] == list(range(4, 4 + len(positions)))
    assert len(game["moves"]) == 4 + len(positions)


def test_outcome_follows_side_to_move():
    game = _game(eps=0.0)
    white = {"WhiteWins": 1, "BlackWins": -1}.get(game["result"], 0)
    for p in game["positions"]:
        assert p["outcome"] == (white if p["ply"] % 2 == 0 else -white)


def test_random_moves_only_with_epsilon():
    quiet = _game(eps=0.0)
    assert all(not p["random"] and p["played"] == p["best"] for p in quiet["positions"])
    noisy = _game(eps=1.0)
    assert any(p["random"] for p in noisy["positions"])


def test_relabel_scores_every_position_at_each_depth():
    game = _game(eps=0.0)
    relabeled = relabel_game(game, [1, 2], source_depth=1)
    assert relabeled["depth"] == 1
    assert [p["score"] for p in relabeled["positions"]] == [p["score"] for p in game["positions"]]
    assert all(set(p["scores"]) == {"1", "2"} for p in relabeled["positions"])
    assert all(isinstance(p["scores"]["2"], int) for p in relabeled["positions"])


def test_relabel_depends_on_the_position_only():
    # A label must not depend on the game around the position or on earlier searches: the
    # same plies cut out of a shorter record, searched again, get the same scores.
    game = _game(eps=1.0)
    full = relabel_game(game, [2, 3], source_depth=1)
    part = {**game, "moves": game["moves"][:12], "positions": game["positions"][4:8]}
    again = relabel_game(part, [2, 3], source_depth=1)
    assert [p["scores"] for p in again["positions"]] == [
        p["scores"] for p in full["positions"][4:8]
    ]
