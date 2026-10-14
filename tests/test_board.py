import os
import random

import pytest

from tocandira.board import DIRS, ON_TOP, Board, hand_for, hex_distance, parse_move
from tocandira.uhp import NOKAMUTE, Engine, PlayerSpec, game_state


def test_six_glyphs_match_nokamute_directions():
    cases = {
        "\\wA1": DIRS["NW"],
        "-wA1": DIRS["W"],
        "/wA1": DIRS["SW"],
        "wA1/": DIRS["NE"],
        "wA1-": DIRS["E"],
        "wA1\\": DIRS["SE"],
    }
    for ref, offset in cases.items():
        board = Board.replay(["wA1", f"bG1 {ref}"])
        assert board.where["bG1"] == offset, ref


def test_hex_distance_uses_nokamute_axes():
    assert hex_distance((0, 0), DIRS["NW"]) == 1
    assert hex_distance((0, 0), DIRS["NE"]) == 1
    assert hex_distance((0, 0), (2, -1)) == 3  # E, E, NE
    assert hex_distance((0, 0), (2, 2)) == 2  # SE, SE


def test_stacking_and_unstacking():
    board = Board.replay(["wA1", "bQ wA1-", "wQ -wA1", "bA1 bQ-", "wB1 wQ\\"])
    board.apply("bA1 bQ")  # black ant climbs its own queen? notation only: on top
    assert board.where["bA1"] == board.where["bQ"] == (1, 0)
    assert board.top((1, 0)) == "bA1"
    assert board.level("bA1") == 1 and board.level("bQ") == 0
    board.apply("wB1 wA1")  # beetle onto the first ant
    assert board.top((0, 0)) == "wB1" and board.level("wB1") == 1
    board.apply("bA1 /wQ")  # ant climbs down
    assert board.top((1, 0)) == "bQ"
    assert board.stacks[(1, 0)] == ["bQ"]


def test_first_move_pass_and_to_move():
    board = Board()
    assert board.to_move == "w"
    board.apply("wA1")
    assert board.where["wA1"] == (0, 0) and board.ply == 1 and board.to_move == "b"
    board.apply("pass")
    assert board.ply == 2 and board.to_move == "w"


def test_hand_counts():
    assert hand_for("Base") == {"Q": 1, "A": 3, "G": 3, "B": 2, "S": 2}
    assert hand_for("Base+MLP") == {"Q": 1, "A": 3, "G": 3, "B": 2, "S": 2, "M": 1, "L": 1, "P": 1}
    board = Board.replay(["wA1", "bQ wA1-", "wA1 bQ/"])
    assert board.hand["w"]["A"] == 2 and board.hand["b"]["Q"] == 0
    assert board.hand["w"]["Q"] == 1


def test_errors():
    with pytest.raises(ValueError, match="game type"):
        hand_for("Chess")
    with pytest.raises(ValueError, match="bare move"):
        Board.replay(["wA1", "bQ"])
    with pytest.raises(ValueError, match="not on the board"):
        Board.replay(["wA1", "bQ wS1-"])
    with pytest.raises(ValueError, match="covered"):
        Board.replay(["wA1", "bQ wA1-", "wB1 -wA1", "bQ wA1", "wA1 -wB1"])
    with pytest.raises(ValueError, match="left in hand"):
        Board.replay(
            ["wA1", "bA1 wA1-", "wA2 -wA1", "bA2 bA1-", "wA3 -wA2", "bA3 bA2-", "wA4 -wA3"]
        )


@pytest.mark.skipif(not os.path.exists(NOKAMUTE), reason="engine not built")
def test_tracker_agrees_with_engine():
    """Every move the engine calls legal must make sense on our board, for 4 random games."""
    for seed in range(4):
        rng = random.Random(seed)
        board = Board("Base+MLP")
        with Engine(PlayerSpec(depth=1)) as engine:
            engine.newgame("Base+MLP")
            for _ in range(80):
                legal = engine.validmoves()
                for move in legal:
                    if move == "pass":
                        continue
                    piece, ref, offset = parse_move(move)
                    if ref is None:
                        assert not board.stacks
                        continue
                    assert ref in board.where, (move, board.where)
                    rq, rr = board.where[ref]
                    dest = (rq + offset[0], rr + offset[1])
                    if piece in board.where:
                        assert board.top(board.where[piece]) == piece, move
                    if offset != ON_TOP:
                        assert dest not in board.stacks, (move, board.stacks)
                on_board = len(board.where)
                in_hand = sum(sum(h.values()) for h in board.hand.values())
                assert on_board + in_hand == 28
                play = rng.choice(legal)
                state = game_state(engine.play(play))
                board.apply(play)
                if state not in ("NotStarted", "InProgress"):
                    break
