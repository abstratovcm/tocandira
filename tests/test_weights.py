import numpy as np
import pytest

from tocandira.encode import geometry
from tocandira.weights import Weights, evaluate, load_npz, read_bin, write_bin

RADIUS = 6
NUM_FEATURES = geometry(RADIUS).num_features


def _random_weights(hidden: int = 8, l2: int = 4, seed: int = 0) -> Weights:
    rng = np.random.default_rng(seed)
    w = Weights(RADIUS, NUM_FEATURES, hidden, l2, 400.0, {})
    w.arrays = {k: rng.normal(0, 0.1, s).astype(np.float32) for k, s in w.shapes().items()}
    return w


def test_bin_round_trip(tmp_path):
    w = _random_weights()
    write_bin(w, tmp_path / "w.bin")
    back = read_bin(str(tmp_path / "w.bin"))
    assert (back.radius, back.num_features, back.hidden, back.l2, back.scale) == (
        6,
        NUM_FEATURES,
        8,
        4,
        400.0,
    )
    for k, arr in w.arrays.items():
        assert np.array_equal(back.arrays[k], arr), k
    assert evaluate(back, [1, 2], [3], [1] * 16) == evaluate(w, [1, 2], [3], [1] * 16)


def test_npz_export_matches_torch_model(tmp_path):
    torch = pytest.importorskip("torch")
    from tocandira.nnue import Nnue, export_weights  # noqa: PLC0415

    model = Nnue(NUM_FEATURES, hidden=8, l2=4)
    export_weights(model, str(tmp_path / "w.npz"), {"radius": RADIUS, "num_features": NUM_FEATURES})
    w = load_npz(str(tmp_path / "w.npz"))
    rng = np.random.default_rng(1)
    own = rng.integers(0, NUM_FEATURES, 7).tolist()
    opp = rng.integers(0, NUM_FEATURES, 5).tolist()
    hand = rng.integers(0, 3, 16).tolist()
    pad = lambda f: torch.tensor([f + [model.pad] * (28 - len(f))])  # noqa: E731
    with torch.no_grad():
        expected = model(pad(own), pad(opp), torch.tensor([hand], dtype=torch.int8)).item()
    assert abs(evaluate(w, own, opp, hand) - expected) < 1e-3
