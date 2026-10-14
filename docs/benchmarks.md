# Benchmarks and results

Dated records. Newest first. Machine unless stated: Ryzen 7 5700G, 16 threads, Linux.

## 2026-10-14: first full run, 2.3M positions (Colab)

Data: 30 shards, 30,000 games, 2,310,987 positions at depth 4 (round 1 on two TPU v5e-1
runtimes, 24 vCPUs each, ~170 s per 1000 game shard, ~4 units). Training: `Nnue(256)` and
`Nnue(512)`, 20 epochs, batch 4096, lambda 0.75, on L4 (round 2, two runtimes). 5% of
games held out (115,290 positions). Raw files under `runs/data/d4` and `runs/models/`.

Held out, best epoch (4 to 5) vs nokamute's static eval:

| | loss | Pearson vs depth 4 score | sign agreement |
|---|---|---|---|
| static eval (baseline) | 0.0205 | 0.32 | 60.6% |
| h256, epoch 5 | 0.0171 | 0.56 | 63.0% |
| h512, epoch 4 | 0.0172 | 0.56 | 63.3% |

Ceiling: the depth 4 score's own sign matches the final outcome on 63.2% of decided, non
forced positions, so sign agreement is saturated and uninformative; loss and Pearson are
the metrics. Both nets overfit after epoch 5 (train loss keeps falling, validation rises to
0.0180 / 0.0185 by epoch 20); the saved checkpoints are epoch 20, not the best. Width 512
gains nothing over 256: data limited, not capacity limited.

By phase, epoch 20 models (static / h256), loss and Pearson:
opening 0-10: 0.0167 r0.56 / 0.0144 r0.57; 10-20: 0.0148 r0.53 / 0.0147 r0.47;
20-40: 0.0193 r0.31 / 0.0172 r0.57; 40-70: 0.0321 r0.35 / 0.0244 r0.62;
70+: 0.0161 r0.37 / 0.0160 r0.53. The gain is in the middlegame; the endgame is a tie.

Feature usage: 9,365 of 30,016 features ever active; 93.6% of pieces lie within 6 hexes
of the anchor queen, 99.0% within 8. Radius 12 is oversized.

## 2026-10-13: first net vs the static baseline, 500 games only

`runs/labels-d4-500-static.npz` (36,640 positions, 2,004 held out by game), `Nnue(hidden=128)`,
12 epochs on CPU. nokamute's static eval as a predictor of its own depth 4 score: loss 0.0195,
Pearson 0.31, sign agreement 63.9%. The net at epoch 4: loss 0.0197, Pearson 0.27, sign
agreement 67.9%; after that it overfits (train loss 0.008, validation rising). Ties the
hand eval with 1% of the planned data; the rest is a data problem.

## 2026-10-13: Aggression 3 vs 5 at depth 4

`hive-tournament --a depth=4 --b depth=4,Aggression=5 --games 200 --workers 7`

nokamute's default `Aggression=3` beats `Aggression=5`: 57.5% [50.6, 64.1], about +53 Elo
[+4, +101], 200 games, 102 s of wall clock. First measured fact about the engine's dial.

## 2026-10-13: nokamute throughput, one thread per game

Self play over UHP, Base+MLP, random first two plies (`docs/throughput_bench.py`).

| Depth | Per move | Per game (median) | 100k games on 16 threads |
|---|---|---|---|
| 1 | 0.06 ms | 0.11 s | minutes |
| 2 | 0.3 ms | 0.14 s | minutes |
| 3 | 5 ms | 0.4 s | ~40 min |
| 4 | 27 ms | 2 s | ~3.5 h |
| 5 | 290 ms | 10 s | ~18 h |
| 6 | 1.35 s | 69 s | ~5 days |

Games run 40 to 130 plies; depth 5 and 6 games vary a lot (2 s to 100 s), so time
controls, not fixed depth, are the right limit above depth 4.

## 2026-10-13: labeling and encoding

`hive-label --games 500 --depth 4 --workers 7`: 38,761 positions (78 per game) in 177 s,
~220 positions/s. 4% of labels are forced win/loss (±32767); the sign of the depth 4 score
agrees with the final outcome in 63% of decided positions.

`hive-encode` on that file: 0.6 s, 0.7 MB npz. Mean active features per perspective: 6 in
the first 10 plies, 28 after ply 60.
