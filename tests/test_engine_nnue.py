"""Cross check: the engine computes the same features and score as the Python side."""

import os
import random

import numpy as np
import pytest

from tocandira.board import Board
from tocandira.encode import encode, geometry
from tocandira.uhp import NOKAMUTE, Engine, PlayerSpec, UhpError, game_state
from tocandira.weights import Weights, evaluate, evaluate_quantized, write_bin

RADIUS = 6
pytestmark = pytest.mark.skipif(not os.path.exists(NOKAMUTE), reason="engine not built")


def _weights(seed: int) -> Weights:
    rng = np.random.default_rng(seed)
    w = Weights(RADIUS, geometry(RADIUS).num_features, 8, 4, 400.0, {})
    w.arrays = {k: rng.normal(0, 0.2, s).astype(np.float32) for k, s in w.shapes().items()}
    return w


def test_engine_features_and_eval_match_python(tmp_path):
    w = _weights(0)
    path = tmp_path / "tiny.bin"
    write_bin(w, str(path))
    spec = PlayerSpec(cmd=f"{NOKAMUTE} --nnue {path}", depth=1)
    checked = 0
    quantization_error = 0.0
    for seed in range(4):
        rng = random.Random(seed)
        board = Board("Base+MLP")
        with Engine(spec) as engine:
            engine.newgame("Base+MLP")
            for _ in range(80):
                try:
                    own_s, opp_s, hand_s = engine.cmd("features")[0].split(";")
                except UhpError as exc:  # an engine without the hook
                    pytest.skip(f"engine has no features command: {exc}")
                ints = lambda s: [int(x) for x in s.split(",") if x]  # noqa: E731
                enc = encode(board, RADIUS)
                assert ints(own_s) == sorted(enc.own), (seed, board.ply)
                assert ints(opp_s) == sorted(enc.opp), (seed, board.ply)
                assert ints(hand_s) == enc.hand, (seed, board.ply)
                score = engine.eval()
                reference = evaluate_quantized(w, enc.own, enc.opp, enc.hand)
                assert abs(score - reference) <= 1, (seed, board.ply, score, reference)
                exact = evaluate(w, enc.own, enc.opp, enc.hand)
                quantization_error = max(quantization_error, abs(reference - exact))
                checked += 1
                move = rng.choice(engine.validmoves())
                state = game_state(engine.play(move))
                board.apply(move)
                if state not in ("NotStarted", "InProgress"):
                    break
    assert checked > 100
    assert quantization_error < 0.02 * 400  # int8/int16 inference stays within 2% of a logit
