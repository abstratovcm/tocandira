"""NNUE style evaluation net and its training loop.

Needs torch (`uv sync --group train`; Colab has it preinstalled). The net:

    own, opp -> shared EmbeddingBag(num_features, H, sum) + hand projection -> clipped ReLU
    concat(2H) -> Linear(32) -> clipped ReLU -> Linear(32) -> clipped ReLU -> Linear(1)

The output is in nokamute score units. The loss compares sigmoid(pred / SCALE) with a blend
of sigmoid(score / SCALE) and the game outcome, as NNUE trainers do. The engine's hand tuned
`static` evaluation is scored with the same metrics: that is the baseline to beat.

Training habits (adapted from the Stockfish nnue-pytorch recipes to a finite dataset):
AdamW with a small weight decay, exponential learning rate decay per epoch, validation on
held out games every epoch, the best checkpoint kept, early stopping on patience.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import torch
from torch import Tensor, nn

from .encode import MAX_PIECES, geometry

SCALE = 400.0  # score units per logit: a +400 score is a 73% win probability
CLAMP = 3000  # scores beyond this (forced wins are ±32767) count as decisive
ARRAYS = ("own", "opp", "hand", "score", "static", "outcome", "ply", "game", "random")

Data = dict[str, npt.NDArray[Any]]
Meta = dict[str, Any]


def load_shards(paths: list[str]) -> tuple[Data, Meta]:
    """Concatenate npz shards of one radius; game ids are offset per shard so they stay unique."""
    parts: dict[str, list[npt.NDArray[Any]]] = {k: [] for k in ARRAYS}
    meta: Meta = {}
    for i, path in enumerate(sorted(paths)):
        with np.load(path) as d:
            m = json.loads(str(d["meta"]))
            if meta and m["radius"] != meta["radius"]:
                raise ValueError(f"{path}: radius {m['radius']} differs from {meta['radius']}")
            meta = {"radius": m["radius"], "num_features": m["num_features"], "shards": i + 1}
            for k in ARRAYS:
                arr = d[k].astype(np.int64) + i * 10_000_000 if k == "game" else d[k]
                parts[k].append(arr)
    return {k: np.concatenate(v) for k, v in parts.items()}, meta


def split_by_game(
    game: npt.NDArray[Any], holdout: float = 0.05, seed: int = 0
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """(train, validation) position indices; whole games are held out, never single positions."""
    games = np.unique(game)
    np.random.default_rng(seed).shuffle(games)
    held = np.isin(game, games[: max(1, int(len(games) * holdout))])
    return np.flatnonzero(~held), np.flatnonzero(held)


def win_prob(score: Tensor) -> Tensor:
    """Score units to a win probability."""
    return torch.sigmoid(score.clamp(-CLAMP, CLAMP) / SCALE)


def target(score: Tensor, outcome: Tensor, lam: float) -> Tensor:
    """Training target: `lam` of the search score, the rest from the final outcome."""
    return lam * win_prob(score) + (1 - lam) * (outcome + 1) / 2


class Nnue(nn.Module):
    """Two perspective accumulator net; see the module docstring."""

    def __init__(self, num_features: int, hidden: int = 256, l2: int = 32):
        super().__init__()
        self.num_features = num_features
        self.pad = num_features  # embedding row reserved for the -1 padding in the npz
        self.ft = nn.EmbeddingBag(num_features + 1, hidden, mode="sum", padding_idx=self.pad)
        nn.init.normal_(self.ft.weight, std=0.5 / MAX_PIECES**0.5)
        self.hand = nn.Linear(16, hidden)
        self.l1 = nn.Linear(2 * hidden, l2)
        self.l2 = nn.Linear(l2, l2)
        self.out = nn.Linear(l2, 1)

    def forward(self, own: Tensor, opp: Tensor, hand: Tensor) -> Tensor:
        """Score in nokamute units for the side to move; `own`/`opp` are [B, 28] long with pad."""
        hand = hand.float()
        swapped = torch.cat([hand[:, 8:], hand[:, :8]], dim=1)
        a = (self.ft(own) + self.hand(hand)).clamp(0, 1)
        b = (self.ft(opp) + self.hand(swapped)).clamp(0, 1)
        x = self.l1(torch.cat([a, b], dim=1)).clamp(0, 1)
        x = self.l2(x).clamp(0, 1)
        return self.out(x).squeeze(1) * SCALE


@dataclass
class Metrics:
    """How well a score predicts the search score and the outcome on held out games."""

    # loss: MSE in win probability space against the blended target.
    # pearson: correlation with the clamped search score.
    # sign_agreement: fraction of decided, non forced positions whose sign matches the outcome.
    loss: float
    pearson: float
    sign_agreement: float
    n: int

    def __str__(self) -> str:
        return (
            f"loss {self.loss:.4f}  pearson {self.pearson:.3f}  "
            f"sign agreement {100 * self.sign_agreement:.1f}%  (n={self.n})"
        )


def metrics(pred: Tensor, score: Tensor, outcome: Tensor, lam: float) -> Metrics:
    """Metrics of any score like prediction (the net's output or the static eval)."""
    loss = ((win_prob(pred) - target(score, outcome, lam)) ** 2).mean().item()
    clamped = score.clamp(-CLAMP, CLAMP)
    pearson = torch.corrcoef(torch.stack([pred.float(), clamped.float()]))[0, 1].item()
    decided = (outcome != 0) & (score.abs() < CLAMP)
    agree = (torch.sign(pred[decided]) == outcome[decided]).float().mean().item()
    return Metrics(loss, pearson, agree, int(decided.sum().item()))


@dataclass
class Config:
    """Training hyperparameters. `radius` selects the dataset in a sweep."""

    radius: int = 12
    hidden: int = 256
    l2: int = 32
    max_epochs: int = 30
    patience: int = 3  # stop after this many epochs without a better validation loss
    batch: int = 4096
    lr: float = 1e-3
    lr_gamma: float = 0.9  # exponential decay per epoch
    weight_decay: float = 1e-4
    lam: float = 0.75
    holdout: float = 0.05
    seed: int = 0
    augment: bool = True  # random D6 symmetry per batch


class Tensors:
    """The dataset as device tensors, indexable by position."""

    def __init__(self, data: Data, meta: Meta, device: torch.device):
        self.pad = int(meta["num_features"])
        self.own = torch.from_numpy(data["own"].astype(np.int32)).to(device)
        self.opp = torch.from_numpy(data["opp"].astype(np.int32)).to(device)
        self.hand = torch.from_numpy(data["hand"]).to(device)
        self.score = torch.from_numpy(data["score"].astype(np.float32)).to(device)
        self.static = torch.from_numpy(data["static"].astype(np.float32)).to(device)
        self.outcome = torch.from_numpy(data["outcome"].astype(np.float32)).to(device)
        tables = geometry(int(meta["radius"])).d6_tables()
        tables = np.concatenate([tables, np.full((12, 1), self.pad, dtype=np.int32)], axis=1)
        self.tables = torch.from_numpy(tables.astype(np.int64)).to(device)

    def features(self, idx: Tensor, sym: int | None) -> tuple[Tensor, Tensor]:
        """`own`, `opp` for the positions `idx` as long tensors with pad, optionally transformed."""
        own, opp = self.own[idx].long(), self.opp[idx].long()
        own = torch.where(own < 0, self.pad, own)
        opp = torch.where(opp < 0, self.pad, opp)
        if sym is not None:
            own, opp = self.tables[sym][own], self.tables[sym][opp]
        return own, opp


def evaluate(model: Nnue, t: Tensors, idx: Tensor, lam: float, batch: int = 16384) -> Metrics:
    """Metrics of the net on the positions `idx`."""
    model.eval()
    preds = []
    with torch.no_grad():
        for start in range(0, len(idx), batch):
            chunk = idx[start : start + batch]
            own, opp = t.features(chunk, None)
            preds.append(model(own, opp, t.hand[chunk]))
    return metrics(torch.cat(preds), t.score[idx], t.outcome[idx], lam)


def _run_epoch(
    model: Nnue,
    t: Tensors,
    train_idx: Tensor,
    cfg: Config,
    opt: torch.optim.Optimizer,
    gen: torch.Generator,
) -> float:
    """One pass over the training positions; returns the mean batch loss."""
    model.train()
    device = train_idx.device
    perm = train_idx[torch.randperm(len(train_idx), device=device, generator=gen)]
    total = 0.0
    n_batches = len(perm) // cfg.batch
    for b in range(n_batches):
        idx = perm[b * cfg.batch : (b + 1) * cfg.batch]
        sym = int(torch.randint(12, (1,), generator=gen, device=device)) if cfg.augment else None
        own, opp = t.features(idx, sym)
        pred = model(own, opp, t.hand[idx])
        loss = ((win_prob(pred) - target(t.score[idx], t.outcome[idx], cfg.lam)) ** 2).mean()
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        total += loss.item()
    return total / max(1, n_batches)


@dataclass
class TrainResult:
    """What `train` returns: the best model and how it and the baseline scored."""

    model: Nnue
    best_epoch: int
    best: Metrics
    baseline: Metrics
    epochs_run: int


def train(
    data: Data,
    meta: Meta,
    cfg: Config,
    out_dir: str,
    log: Callable[[str], None] = print,
) -> TrainResult:
    """Train with early stopping; `nnue.pt`, `weights.npz` and `log.jsonl` land in `out_dir`.

    The checkpoint and the weights are those of the best validation epoch, not the last.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(cfg.seed)
    os.makedirs(out_dir, exist_ok=True)
    cfg.radius = int(meta["radius"])
    t = Tensors(data, meta, device)
    train_np, val_np = split_by_game(data["game"], cfg.holdout, cfg.seed)
    train_idx = torch.from_numpy(train_np).to(device)
    val_idx = torch.from_numpy(val_np).to(device)
    log(f"{len(train_idx)} training positions, {len(val_idx)} held out, device {device}")
    baseline = metrics(t.static[val_idx], t.score[val_idx], t.outcome[val_idx], cfg.lam)
    log(f"baseline (static eval): {baseline}")

    model = Nnue(int(meta["num_features"]), cfg.hidden, cfg.l2).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = torch.optim.lr_scheduler.ExponentialLR(opt, cfg.lr_gamma)
    gen = torch.Generator(device=device).manual_seed(cfg.seed)
    ckpt_path = os.path.join(out_dir, "nnue.pt")
    best: Metrics | None = None
    best_epoch = since_best = epoch = 0
    with open(os.path.join(out_dir, "log.jsonl"), "w") as logf:
        head = {"config": asdict(cfg), "meta": meta, "baseline": asdict(baseline)}
        logf.write(json.dumps(head) + "\n")
        for epoch in range(1, cfg.max_epochs + 1):
            t0 = time.perf_counter()
            train_loss = _run_epoch(model, t, train_idx, cfg, opt, gen)
            sched.step()
            val = evaluate(model, t, val_idx, cfg.lam)
            improved = best is None or val.loss < best.loss
            if improved:
                best, best_epoch, since_best = val, epoch, 0
                state = {"config": asdict(cfg), "meta": meta, "epoch": epoch, "val": asdict(val)}
                torch.save({**state, "state": model.state_dict()}, ckpt_path)
                export_weights(model, os.path.join(out_dir, "weights.npz"), meta)
            else:
                since_best += 1
            line = {"epoch": epoch, "train_loss": train_loss, "best": improved}
            logf.write(json.dumps({**line, **asdict(val)}) + "\n")
            logf.flush()
            elapsed = time.perf_counter() - t0
            mark = " *" if improved else ""
            log(f"epoch {epoch}: train loss {train_loss:.4f}  val {val}  {elapsed:.0f}s{mark}")
            if since_best >= cfg.patience:
                log(f"no improvement for {cfg.patience} epochs, stopping")
                break
        assert best is not None
        tail = {"best_epoch": best_epoch, "best": asdict(best), "epochs_run": epoch}
        logf.write(json.dumps(tail) + "\n")
    log(f"best epoch {best_epoch}: {best}")
    model.load_state_dict(torch.load(ckpt_path, map_location=device)["state"])
    return TrainResult(model, best_epoch, best, baseline, epoch)


def sweep(
    datasets: dict[int, tuple[Data, Meta]],
    configs: list[tuple[str, Config]],
    out_root: str,
    log: Callable[[str], None] = print,
) -> dict[str, TrainResult]:
    """Train each config into `out_root/<name>/` on the dataset of its radius; prints a table."""
    results: dict[str, TrainResult] = {}
    for name, cfg in configs:
        log(f"\n=== {name}: {asdict(cfg)}")
        data, meta = datasets[cfg.radius]
        results[name] = train(data, meta, cfg, os.path.join(out_root, name), log)
    first = next(iter(results.values()))
    rows = [("static eval", "", first.baseline)] + [
        (name, str(r.best_epoch), r.best) for name, r in results.items()
    ]
    log(f"\n{'run':<14}{'epoch':>6}  {'loss':>7}  {'pearson':>8}  {'sign':>6}")
    for name, epoch, m in rows:
        log(
            f"{name:<14}{epoch:>6}  {m.loss:7.4f}  {m.pearson:8.3f}  {100 * m.sign_agreement:5.1f}%"
        )
    return results


def export_weights(model: Nnue, path: str, meta: Meta) -> None:
    """Plain float32 arrays for an engine side loader (no torch needed to read)."""
    sd = {k: v.detach().cpu().numpy().astype(np.float32) for k, v in model.state_dict().items()}
    np.savez(
        path,
        ft=sd["ft.weight"][: model.num_features],  # drop the padding row
        hand_w=sd["hand.weight"],
        hand_b=sd["hand.bias"],
        l1_w=sd["l1.weight"],
        l1_b=sd["l1.bias"],
        l2_w=sd["l2.weight"],
        l2_b=sd["l2.bias"],
        out_w=sd["out.weight"],
        out_b=sd["out.bias"],
        scale=np.float32(SCALE),
        radius=np.int32(meta["radius"]),
        num_features=np.int32(meta["num_features"]),
    )
