import numpy as np
import pytest

torch = pytest.importorskip("torch")

from tocandira.encode import NUM_FEATURES  # noqa: E402
from tocandira.nnue import PAD, Config, Nnue, load_shards, split_by_game, train  # noqa: E402

VOCAB = 300  # a small feature vocabulary, so features recur often enough to be learned


def _synthetic(n: int, seed: int) -> dict:
    """Positions whose score is a fixed linear function of their features, so it is learnable."""
    rng = np.random.default_rng(seed)
    weights = np.zeros(NUM_FEATURES)
    weights[:VOCAB] = rng.normal(0, 300, VOCAB)
    own = rng.integers(0, VOCAB, (n, 28)).astype(np.int16)
    opp = rng.integers(0, VOCAB, (n, 28)).astype(np.int16)
    own[:, 20:] = -1
    opp[:, 20:] = -1
    score = (weights[own[:, :20]].sum(1) - weights[opp[:, :20]].sum(1)) / 20
    return {
        "own": own,
        "opp": opp,
        "hand": rng.integers(0, 3, (n, 16)).astype(np.int8),
        "score": score.astype(np.int16),
        "static": rng.normal(0, 300, n).astype(np.int16),  # uninformative baseline
        "outcome": np.sign(score).astype(np.int8),
        "ply": np.full(n, 10, dtype=np.int16),
        "game": (np.arange(n) // 50).astype(np.int32),
        "random": np.zeros(n, dtype=bool),
    }


def test_forward_shape_and_padding():
    model = Nnue(hidden=16, l2=8)
    own = torch.full((3, 28), PAD, dtype=torch.long)
    hand = torch.zeros(3, 16, dtype=torch.int8)
    out = model(own, own, hand)
    assert out.shape == (3,)
    assert torch.allclose(out[0], out[1])  # identical inputs, identical scores


def test_split_holds_out_whole_games():
    game = np.repeat(np.arange(40), 25)
    train_idx, val_idx = split_by_game(game, holdout=0.1)
    assert len(train_idx) + len(val_idx) == 1000
    assert not set(game[train_idx]) & set(game[val_idx])
    assert len(set(game[val_idx])) == 4


def test_load_shards_keeps_game_ids_unique(tmp_path):
    data = _synthetic(100, seed=1)
    for i in range(2):
        np.savez(tmp_path / f"shard{i}.npz", **data)
    merged = load_shards([str(tmp_path / "shard0.npz"), str(tmp_path / "shard1.npz")])
    assert len(merged["score"]) == 200
    assert len(np.unique(merged["game"])) == 4


@pytest.mark.slow
def test_training_beats_uninformative_baseline(tmp_path):
    data = _synthetic(4000, seed=2)
    cfg = Config(hidden=32, l2=8, epochs=10, batch=64, lr=3e-3, augment=False)
    lines: list[str] = []
    train(data, cfg, str(tmp_path), log=lines.append)
    assert (tmp_path / "weights.npz").exists()
    first, last = lines[2], lines[-1]
    assert "epoch 1" in first and f"epoch {cfg.epochs}" in last
    pearson = float(last.split("pearson ")[1].split()[0])
    assert pearson > 0.5
