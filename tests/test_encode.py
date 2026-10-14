import json

import numpy as np

from tocandira.board import Board, hex_distance
from tocandira.encode import (
    MAX_PIECES,
    NUM_CELLS,
    NUM_FEATURES,
    RADIUS,
    anchor,
    clamp_to_radius,
    d6_tables,
    encode,
    encode_dataset,
    feature_index,
)

OPENING = ["wA1", "bQ wA1-", "wQ -wA1", "bA1 bQ-"]


def test_constants_the_engine_side_will_hardcode():
    assert NUM_CELLS == 469
    assert NUM_FEATURES == 30016


def test_feature_count_range_and_hand():
    enc = encode(Board.replay(OPENING))
    assert len(enc.own) == len(enc.opp) == 4
    assert all(0 <= f < NUM_FEATURES for f in enc.own + enc.opp)
    assert len(enc.hand) == 16
    assert enc.hand[0] == 0  # white to move, white queen placed
    assert sum(enc.hand) == 28 - 4


def test_queen_sits_at_origin_of_its_own_perspective():
    board = Board.replay(OPENING)  # white to move
    enc = encode(board)
    origin_queen = feature_index((0, 0), 0, "Q", 0)
    assert origin_queen in enc.own  # white queen, seen by white
    assert origin_queen in enc.opp  # black queen, seen by black
    # White's ant at (0, 0) sits at (0, 0) - (-1, 0) = (1, 0) from the white queen.
    assert feature_index((1, 0), 0, "A", 0) in enc.own
    # The same ant is an enemy piece at (0, 0) - (1, 0) = (-1, 0) from the black queen.
    assert feature_index((-1, 0), 1, "A", 0) in enc.opp


def test_anchor_fallbacks():
    board = Board.replay(["wA1"])
    assert anchor(board, "w") == anchor(board, "b") == (0, 0)
    board.apply("bQ wA1-")
    assert anchor(board, "w") == (1, 0)  # no white queen yet: use black's
    assert anchor(board, "b") == (1, 0)


def test_stack_levels_are_features():
    board = Board.replay([*OPENING, "wB1 wQ\\", "bA1 bQ"])
    enc = encode(board)  # white to move, black ant on top of black queen
    assert feature_index((2, 0), 1, "A", 1) in enc.own


def test_clamp_to_radius():
    assert clamp_to_radius(5, 5) == (5, 5)
    assert clamp_to_radius(RADIUS, 0) == (RADIUS, 0)
    for far in [(20, 0), (0, 25), (-30, -30), (17, -14), (-9, 20)]:
        clamped = clamp_to_radius(*far)
        assert RADIUS - 1 <= hex_distance(clamped, (0, 0)) <= RADIUS, far


def test_d6_tables_are_symmetries():
    tables = d6_tables()
    assert tables.shape == (12, NUM_FEATURES)
    identity = np.arange(NUM_FEATURES)
    for k in range(12):
        assert np.array_equal(np.sort(tables[k]), identity), k
    assert np.array_equal(tables[0], identity)
    rot = tables[1]
    composed = identity.copy()
    for _ in range(6):
        composed = rot[composed]
    assert np.array_equal(composed, identity)
    assert np.array_equal(tables[6][tables[6]], identity)
    origin_queen = feature_index((0, 0), 0, "Q", 0)
    assert all(tables[k][origin_queen] == origin_queen for k in range(12))
    # A 60 degree rotation moves E to a neighbour, never back onto itself.
    east = feature_index((1, 0), 1, "A", 0)
    assert rot[east] != east


def test_encode_dataset(tmp_path):
    moves = [*OPENING, "wA2 \\wQ", "bA1 /wQ"]
    positions = [
        {"ply": 2, "score": 5, "best": "wQ -wA1", "played": "wQ -wA1", "random": False, "pvlen": 3},
        {
            "ply": 3,
            "score": -7,
            "best": "bA1 bQ-",
            "played": "bA1 bQ-",
            "random": False,
            "pvlen": 2,
        },
        {
            "ply": 4,
            "score": 32767,
            "best": "wA2 \\wQ",
            "played": "wA2 \\wQ",
            "random": True,
            "pvlen": 1,
        },
    ]
    for p in positions:
        p["outcome"] = 1 if p["ply"] % 2 == 0 else -1
    game = {
        "id": 7,
        "game_type": "Base+MLP",
        "result": "WhiteWins",
        "moves": moves,
        "positions": positions,
    }
    labels = tmp_path / "labels.jsonl"
    labels.write_text(json.dumps(game) + "\n")
    out = tmp_path / "labels.npz"

    assert encode_dataset(str(labels), str(out)) == 3
    data = np.load(out)
    assert data["own"].shape == data["opp"].shape == (3, MAX_PIECES)
    assert data["own"].dtype == np.int16 and data["hand"].dtype == np.int8
    assert data["score"].tolist() == [5, -7, 32767]
    assert data["outcome"].tolist() == [1, -1, 1]
    assert data["ply"].tolist() == [2, 3, 4]
    assert data["game"].tolist() == [7, 7, 7]
    assert data["random"].tolist() == [False, False, True]
    assert (data["own"][0] >= 0).sum() == 2 and (data["own"][2] >= 0).sum() == 4
    assert data["hand"].shape == (3, 16)
    assert json.loads(str(data["meta"]))["num_features"] == NUM_FEATURES
