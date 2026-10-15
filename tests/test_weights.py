import numpy as np
import pytest

from tocandira.encode import geometry
from tocandira.weights import NUM_SCALARS, Weights, evaluate, load_npz, read_bin, write_bin

RADIUS = 6
NUM_FEATURES = geometry(RADIUS).num_features


def _random_weights(hidden: int = 8, l2: int = 4, seed: int = 0, scalars: int = 0) -> Weights:
    rng = np.random.default_rng(seed)
    w = Weights(RADIUS, NUM_FEATURES, hidden, l2, 400.0, {}, scalars)
    w.arrays = {k: rng.normal(0, 0.1, s).astype(np.float32) for k, s in w.shapes().items()}
    return w


@pytest.mark.parametrize("scalars", [0, NUM_SCALARS])
def test_bin_round_trip(tmp_path, scalars):
    w = _random_weights(scalars=scalars)
    write_bin(w, tmp_path / "w.bin")
    # Without scalars the file stays version 1, which older engines read.
    assert (tmp_path / "w.bin").read_bytes()[4] == (2 if scalars else 1)
    back = read_bin(str(tmp_path / "w.bin"))
    assert (back.radius, back.num_features, back.hidden, back.l2, back.scale, back.scalars) == (
        6,
        NUM_FEATURES,
        8,
        4,
        400.0,
        scalars,
    )
    for k, arr in w.arrays.items():
        assert np.array_equal(back.arrays[k], arr), k
    values = list(range(NUM_SCALARS)) if scalars else None
    assert evaluate(back, [1, 2], [3], [1] * 16, values) == evaluate(
        w, [1, 2], [3], [1] * 16, values
    )


@pytest.mark.parametrize("scalars", [0, NUM_SCALARS])
def test_npz_export_matches_torch_model(tmp_path, scalars):
    torch = pytest.importorskip("torch")
    from tocandira.nnue import Nnue, export_weights  # noqa: PLC0415

    model = Nnue(NUM_FEATURES, hidden=8, l2=4, scalars=scalars)
    export_weights(model, str(tmp_path / "w.npz"), {"radius": RADIUS, "num_features": NUM_FEATURES})
    w = load_npz(str(tmp_path / "w.npz"))
    rng = np.random.default_rng(1)
    own = rng.integers(0, NUM_FEATURES, 7).tolist()
    opp = rng.integers(0, NUM_FEATURES, 5).tolist()
    hand = rng.integers(0, 3, 16).tolist()
    values = rng.integers(0, 30, NUM_SCALARS).tolist() if scalars else None  # some clip
    pad = lambda f: torch.tensor([f + [model.pad] * (28 - len(f))])  # noqa: E731
    s = torch.tensor([values]) if values else None
    with torch.no_grad():
        expected = model(pad(own), pad(opp), torch.tensor([hand], dtype=torch.int8), s).item()
    assert w.scalars == scalars
    assert abs(evaluate(w, own, opp, hand, values) - expected) < 1e-3
