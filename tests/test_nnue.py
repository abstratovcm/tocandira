import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from tocandira.encode import geometry  # noqa: E402
from tocandira.nnue import (  # noqa: E402
    Config,
    Nnue,
    load_shards,
    split_by_game,
    sweep,
    target_score,
    train,
)

RADIUS = 6
NUM_FEATURES = geometry(RADIUS).num_features
VOCAB = 300  # a small feature vocabulary, so features recur often enough to be learned
META = {"radius": RADIUS, "num_features": NUM_FEATURES}


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


def _save(path, data, meta=META):
    np.savez(path, **data, meta=np.array(json.dumps({**meta, "version": 2})))


def test_forward_shape_and_padding():
    model = Nnue(NUM_FEATURES, hidden=16, l2=8)
    own = torch.full((3, 28), model.pad, dtype=torch.long)
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


def test_load_shards_keeps_game_ids_unique_and_checks_radius(tmp_path):
    for i in range(2):
        _save(tmp_path / f"shard{i}.npz", _synthetic(100, seed=i))
    merged, meta = load_shards([str(tmp_path / "shard0.npz"), str(tmp_path / "shard1.npz")])
    assert len(merged["score"]) == 200
    assert len(np.unique(merged["game"])) == 4
    assert meta == {"radius": RADIUS, "num_features": NUM_FEATURES, "shards": 2, "duplicates": 0}
    _save(tmp_path / "other.npz", _synthetic(100, seed=1), {"radius": 12, "num_features": 30016})
    with pytest.raises(ValueError, match="radius"):
        load_shards([str(tmp_path / "shard0.npz"), str(tmp_path / "other.npz")])


def test_load_shards_skips_a_copy_of_a_shard(tmp_path):
    # Two Colab sessions encoded the same shards into one Drive folder (`shard-000.npz` and
    # `shard-000(1).npz`); with their own game ids the copies leaked into the holdout.
    _save(tmp_path / "shard-000.npz", _synthetic(100, seed=1))
    (tmp_path / "shard-000(1).npz").write_bytes((tmp_path / "shard-000.npz").read_bytes())
    merged, meta = load_shards([str(p) for p in tmp_path.iterdir()])
    assert len(merged["score"]) == 100
    assert (meta["shards"], meta["duplicates"]) == (1, 1)


def test_load_shards_carries_relabeled_arrays_and_rejects_a_mix(tmp_path):
    v3 = {**_synthetic(100, seed=1), "opening": np.arange(100, dtype=np.int64)}
    v3["score5"] = v3["score"] + 1
    _save(tmp_path / "a.npz", v3)
    _save(tmp_path / "b.npz", {**v3, "score5": v3["score"] + 2})
    merged, _ = load_shards([str(tmp_path / "a.npz"), str(tmp_path / "b.npz")])
    assert merged["score5"].tolist() == (v3["score"] + 1).tolist() + (v3["score"] + 2).tolist()
    assert len(merged["opening"]) == 200
    _save(tmp_path / "v2.npz", _synthetic(100, seed=2))
    with pytest.raises(ValueError, match="arrays"):
        load_shards([str(tmp_path / "a.npz"), str(tmp_path / "v2.npz")])


def test_target_score_averages_depths_in_win_probability():
    data = {
        "score": np.array([7, 0, 0], dtype=np.int16),
        "score4": np.array([100, 400, 32767], dtype=np.int16),
        "score5": np.array([100, -400, 32767], dtype=np.int16),
    }
    assert target_score(data, "score").tolist() == [7, 0, 0]
    d45 = target_score(data, "d45")
    assert d45[0] == pytest.approx(100, abs=0.01)  # equal depths: the score itself
    assert d45[1] == pytest.approx(0, abs=0.01)  # symmetric: an even game
    assert d45[2] == pytest.approx(3000, abs=0.5)  # forced wins count as decisive (CLAMP)
    assert target_score(data, "d5").tolist() == pytest.approx([100, -400, 3000], abs=0.5)
    with pytest.raises(ValueError):
        target_score(data, "deep")


@pytest.mark.slow
def test_training_keeps_the_best_epoch_and_stops_early(tmp_path):
    data = _synthetic(4000, seed=2)
    cfg = Config(hidden=32, l2=8, max_epochs=40, patience=2, batch=64, lr=3e-3, augment=False)
    result = train(data, META, cfg, str(tmp_path), log=lambda _: None)
    assert result.best.pearson > 0.5
    assert result.epochs_run < cfg.max_epochs  # patience stopped it
    with open(tmp_path / "log.jsonl") as f:
        lines = [json.loads(line) for line in f]
    best_logged = min(line["loss"] for line in lines[1:-1])
    assert result.best.loss == best_logged
    ckpt = torch.load(tmp_path / "nnue.pt", map_location="cpu")
    assert ckpt["epoch"] == result.best_epoch and ckpt["val"]["loss"] == best_logged
    weights = np.load(tmp_path / "weights.npz")
    assert weights["ft"].shape == (NUM_FEATURES, 32)
    assert int(weights["radius"]) == RADIUS


@pytest.mark.slow
def test_sweep_runs_each_config_into_its_folder(tmp_path):
    data = _synthetic(1000, seed=3)
    configs = [
        ("tiny", Config(radius=RADIUS, hidden=8, l2=4, max_epochs=2, batch=64, augment=False)),
        ("small", Config(radius=RADIUS, hidden=16, l2=4, max_epochs=2, batch=64, augment=False)),
    ]
    results = sweep({RADIUS: (data, META)}, configs, str(tmp_path), log=lambda _: None)
    assert set(results) == {"tiny", "small"}
    assert (tmp_path / "tiny" / "weights.npz").exists()
    assert (tmp_path / "small" / "nnue.pt").exists()
