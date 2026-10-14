import gzip
import json

import numpy as np
import pytest

from tocandira.board import Board, hex_distance
from tocandira.encode import (
    MAX_PIECES,
    RADIUS,
    anchor,
    encode,
    encode_dataset,
    geometry,
)

OPENING = ["wA1", "bQ wA1-", "wQ -wA1", "bA1 bQ-"]


@pytest.mark.parametrize(("radius", "cells", "features"), [(6, 127, 8128), (12, 469, 30016)])
def test_geometry_sizes_the_engine_side_will_hardcode(radius, cells, features):
    g = geometry(radius)
    assert g.num_cells == cells
    assert g.num_features == features


def test_feature_count_range_and_hand():
    enc = encode(Board.replay(OPENING))
    assert len(enc.own) == len(enc.opp) == 4
    assert all(0 <= f < geometry(RADIUS).num_features for f in enc.own + enc.opp)
    assert len(enc.hand) == 16
    assert enc.hand[0] == 0  # white to move, white queen placed
    assert sum(enc.hand) == 28 - 4


def test_queen_sits_at_origin_of_its_own_perspective():
    g = geometry(RADIUS)
    enc = encode(Board.replay(OPENING))  # white to move
    origin_queen = g.feature_index((0, 0), 0, "Q", 0)
    assert origin_queen in enc.own  # white queen, seen by white
    assert origin_queen in enc.opp  # black queen, seen by black
    # White's ant at (0, 0) sits at (0, 0) - (-1, 0) = (1, 0) from the white queen.
    assert g.feature_index((1, 0), 0, "A", 0) in enc.own
    # The same ant is an enemy piece at (0, 0) - (1, 0) = (-1, 0) from the black queen.
    assert g.feature_index((-1, 0), 1, "A", 0) in enc.opp


def test_anchor_fallbacks():
    board = Board.replay(["wA1"])
    assert anchor(board, "w") == anchor(board, "b") == (0, 0)
    board.apply("bQ wA1-")
    assert anchor(board, "w") == (1, 0)  # no white queen yet: use black's
    assert anchor(board, "b") == (1, 0)


def test_stack_levels_are_features():
    board = Board.replay([*OPENING, "wB1 wQ\\", "bA1 bQ"])
    enc = encode(board)  # white to move, black ant on top of black queen
    assert geometry(RADIUS).feature_index((2, 0), 1, "A", 1) in enc.own


@pytest.mark.parametrize("radius", [6, 12])
def test_clamp_to_radius(radius):
    g = geometry(radius)
    assert g.clamp(2, 2) == (2, 2)
    assert g.clamp(radius, 0) == (radius, 0)
    for far in [(20, 0), (0, 25), (-30, -30), (17, -14), (-9, 20)]:
        clamped = g.clamp(*far)
        assert radius - 1 <= hex_distance(clamped, (0, 0)) <= radius, far


@pytest.mark.parametrize("radius", [6, 12])
def test_d6_tables_are_symmetries(radius):
    g = geometry(radius)
    tables = g.d6_tables()
    assert tables.shape == (12, g.num_features)
    identity = np.arange(g.num_features)
    for k in range(12):
        assert np.array_equal(np.sort(tables[k]), identity), k
    assert np.array_equal(tables[0], identity)
    rot = tables[1]
    composed = identity.copy()
    for _ in range(6):
        composed = rot[composed]
    assert np.array_equal(composed, identity)
    assert np.array_equal(tables[6][tables[6]], identity)
    origin_queen = g.feature_index((0, 0), 0, "Q", 0)
    assert all(tables[k][origin_queen] == origin_queen for k in range(12))
    east = g.feature_index((1, 0), 1, "A", 0)
    assert rot[east] != east  # a 60 degree rotation moves E to a neighbour


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
        p["static"] = p["ply"] * 10
    game = {
        "id": 7,
        "game_type": "Base+MLP",
        "result": "WhiteWins",
        "moves": moves,
        "positions": positions,
    }
    labels = tmp_path / "labels.jsonl.gz"
    with gzip.open(labels, "wt") as f:
        f.write(json.dumps(game) + "\n")
    out = tmp_path / "labels.npz"

    assert encode_dataset(str(labels), str(out), radius=6) == 3
    data = np.load(out)
    assert data["own"].shape == data["opp"].shape == (3, MAX_PIECES)
    assert data["own"].dtype == np.int16 and data["hand"].dtype == np.int8
    assert data["score"].tolist() == [5, -7, 32767]
    assert data["static"].tolist() == [20, 30, 40]
    assert data["outcome"].tolist() == [1, -1, 1]
    assert data["ply"].tolist() == [2, 3, 4]
    assert data["game"].tolist() == [7, 7, 7]
    assert data["random"].tolist() == [False, False, True]
    assert (data["own"][0] >= 0).sum() == 2 and (data["own"][2] >= 0).sum() == 4
    assert data["own"].max() < geometry(6).num_features
    meta = json.loads(str(data["meta"]))
    assert meta["radius"] == 6 and meta["num_features"] == 8128


def test_encode_relabeled_games(tmp_path):
    # Per depth scores follow their own position even when a record lists plies out of
    # order, and games sharing an opening share its key (they are held out together).
    moves = [*OPENING, "wA2 \\wQ", "bA1 /wQ"]

    def pos(ply: int, s3: int, s5: int | None) -> dict:
        return {
            "ply": ply,
            "score": 0,
            "static": 0,
            "outcome": 0,
            "random": False,
            "scores": {"3": s3, "5": s5},
        }

    games = [
        {"id": 1, "game_type": "Base+MLP", "moves": moves, "depth": 4,
         "positions": [pos(5, 50, 55), pos(4, 40, None)]},
        {"id": 2, "game_type": "Base+MLP", "moves": moves[:5], "depth": 5,
         "positions": [pos(4, 41, 46)]},
        {"id": 3, "game_type": "Base+MLP", "moves": [*OPENING[:3], "bA1 bQ/"],
         "positions": [pos(3, 30, 35)]},
    ]  # fmt: skip
    labels = tmp_path / "labels.jsonl"
    labels.write_text("".join(json.dumps(g) + "\n" for g in games))
    out = tmp_path / "labels.npz"
    encode_dataset(str(labels), str(out), radius=6)
    data = np.load(out)
    assert json.loads(str(data["meta"]))["depths"] == [3, 5]
    assert data["ply"].tolist() == [4, 5, 4, 3]
    assert data["score3"].tolist() == [40, 50, 41, 30]
    assert data["score5"].tolist() == [0, 55, 46, 35]
    assert data["source"].tolist() == [4, 4, 5, 0]
    opening = data["opening"].tolist()
    assert opening[0] == opening[1] == opening[2] != opening[3]
