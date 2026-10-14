# Benchmarks and results

Dated records. Newest first. Machine unless stated: Ryzen 7 5700G, 16 threads, Linux.

## 2026-10-14: 800 game matches (Colab v5e-1, fair worker count) and the depth 5 nets

Net c (`c/r6-lam1-h256`, incremental engine), 800 games each, one game per two vCPUs on the
clock:

| match | score | Elo |
|---|---|---|
| vs fork, depth 4 | 60.4% [57.0, 63.8] | +74 [+49, +98] |
| vs fork, depth 5 | 55.1% [51.6, 58.5] | +35 [+11, +59] |
| vs fork, 1 s/move | 52.7% [49.2, 56.1] | +19 [−5, +43] |
| **vs nokamute 1.0.3, 1 s/move** | **54.8% [51.3, 58.2]** | **+34 [+9, +58]** |

The per node edge is real at both depths and shrinks with depth (the net imitates a depth 4
search). At equal time the net is ahead of 1.0.3 with an interval that excludes zero, and
about level with the current code. Roadmap item 1 holds, by a modest margin.

Depth 5 data, sweeps g and h (radius 6 unless noted, lambda 1.0, 30 epochs max; all were
still improving at the cap):

| run | hidden | Pearson vs depth 5 score |
|---|---|---|
| static eval | | 0.272 |
| g/d5-r6-lam1-h256 | 256 | **0.731** |
| g/d5-r6-lam1-h128 | 128 | 0.729 |
| h/d5-r8-lam1-h256 (radius 8) | 256 | 0.698 |
| h/d5-r6-lam1-h256-lr5e-4 | 256 | 0.722 |

Width 128 matches 256 again and evaluates in 0.42 µs instead of 0.52. Next: these two nets
in the same matches.

## 2026-10-14: depth 5 dataset

`hive-label --depth 5`, 30 shards on two Colab sessions (v6e-1 44 vCPUs / v5e-1 24): 30,000
games, 1,460,396 positions. Depth 5 self play is more decisive than depth 4: 49 positions per
game (vs 77), median ply 28 (vs 43), draws and ply caps 2% (vs 20%), forced labels 9.1% (vs
4.2%). The static eval predicts the depth 5 score with Pearson 0.275 (0.324 for depth 4).
The depth 4 net (c) scores 0.638 on held out depth 5 games without ever seeing one, so most
of what depth 5 knows is already in the depth 4 imitation; the training round on this data
(sweeps g and h) measures what the rest is worth.

## 2026-10-14: Colab matches (two v5e-1, 24 vCPUs each), incremental engine

| match | games | score | Elo |
|---|---|---|---|
| net vs 1.0.3, 1 s/move | 400 | 51.5% [46.6, 56.4] | +10 [−24, +44] |
| net vs fork, 1 s/move | 400 | 53.8% [48.9, 58.6] | +26 [−8, +60] |
| net vs fork, 3 s/move | 200 | 51.7% [44.9, 58.6] | +12 [−36, +60] |
| net vs fork, depth 5 | 200 | 48.0% [41.2, 54.9] | −14 [−62, +34] |

Two caveats. The time controlled matches ran one game per vCPU (24 workers on 24
hyperthreads), so the two engines of a game shared a core with another game's engines; the
net's AVX2 evaluation is the kind of load that suffers most from a busy sibling thread, which
biases these numbers against it relative to the local run (+70 at 7 games on 8 cores). The
notebook now defaults to one game per two vCPUs for time controlled matches. Second, the
depth 5 result is a tie where depth 4 gave +63 and +83; with 200 games its interval still
reaches +34, so the honest reading is "the per node edge shrinks with depth, by an amount
not yet measured". Both need bigger, cleaner samples: fixed depth matches are exact and
cheap on Colab (800 games of depth 4 and 5), time controlled ones with the corrected worker
count.

## 2026-10-14: equal time with the incremental engine: the net wins

`hive-tournament --a "cmd=<fork> --nnue c/r6-lam1-h256/weights.bin,seconds=1" --b
"cmd=<fork>,seconds=1" --games 400 --workers 7`, one evaluation at 0.52 µs.

**60.0% [55.1, 64.7], about +70 Elo [+36, +105]**, W230 D20 L150, 47 plies per game, 38 min.
As white 68%, as black 52%. Same code and rules on both sides; the evaluator is the only
difference. The three equal time matches of the day, same net: f32 forward pass −144,
quantized AVX2 −28, incremental accumulators +70.

## 2026-10-14: equal time with the quantized net

`hive-tournament --a "cmd=<fork> --nnue c/r6-lam1-h256/weights.bin,seconds=1" --b
"cmd=<fork>,seconds=1" --games 400 --workers 7`, the net at 1.6 µs per evaluation.

**46.0% [41.2, 50.9], about −28 Elo [−62, +6]**, W174 D20 L206 (50 plies per game, 40 min).
As white 50%, as black 42%. From −144 with the f32 net to a statistical tie: the speed work
bought ~115 Elo at equal time. Still short of a win; the remaining levers are the
incremental accumulators (removes the 44 row adds per perspective), a narrower net
(hidden 128 is 1.1 µs) and more training data.

## 2026-10-14: making the net cheap (fork, `benches/nnue.rs`, radius 6, hidden 256)

Microbenchmark of one evaluation on a mid game position, Ryzen 7 5700G:

| step | per eval | vs hand eval (373 ns) |
|---|---|---|
| first version: f32, allocations, plain sums | 13.3 µs | 36x |
| no allocations, hand counts as precomputed rows, lane chunked sums | 4.3 µs | 11x |
| int16 accumulators, int8 layer weights (scalar) | 3.5 µs | 9x |
| **AVX2 (16 lane adds, u8 x i8 multiply-add pairs), runtime detected** | **1.57 µs** | 4.2x |
| same at hidden 128 | 1.13 µs | 3.0x |
| **accumulators kept in the board, updated on every piece insert/remove and hand change** | **0.52 µs** | 1.5x |
| same at hidden 128 | 0.42 µs | 1.2x |

Keeping the accumulators in step costs 164 ns per apply+undo pair (168 → 332 ns). A queen
appearing or leaving refreshes both perspectives from scratch (the anchors move). The
board's accumulators are checked against a from scratch evaluation after every move of
random games with undos (Rust test) and against the numpy reference over UHP (Python test).

A table small enough for L2 was no faster, so the cost is arithmetic, not memory. The
quantization (127 per unit for accumulators, 64 for layer weights, output layer in f32)
is mirrored in numpy (`tocandira.weights.evaluate_quantized`) and the engine matches it
exactly on random games; the deviation from the f32 net stays under 2% of a logit.


## 2026-10-14: equal time, and what a ply is worth

All with the sweep c net (`c/r6-lam1-h256`) and the fork; 200 games unless noted.

| match | score | Elo |
|---|---|---|
| fork plain vs 1.0.3, depth 4 | 53.0% [46.1, 59.8] | +21 [-27, +69] (same strength) |
| net vs fork plain, depth 4 | 59.0% [52.1, 65.6] | **+63** [+14, +112] |
| net vs fork plain, 1 s/move (143 games, stopped) | 30.4% [23.5, 38.4] | **−144** [−205, −82] |
| plain depth 4 vs depth 3 | 82.8% | +272 per ply |
| plain depth 5 vs depth 4 | 86.0% | +315 per ply |
| net depth 3 vs plain depth 4 | 40.0% [33.5, 46.9] | −70 [−119, −21] |

Reading: the learned evaluation is worth about +200 Elo at a fixed depth (a one ply
handicap costs it 70 instead of 272), but its forward pass costs ~10x the hand eval per
node, which is about one ply at any time control, and a ply is worth ~300. Equal time
therefore loses until the net gets at least 4 to 5x cheaper per node. That is engineering
(no allocations, SIMD, quantization, incremental accumulators, a smaller net), not learning.

## 2026-10-14: first match, equal depth

`hive-tournament --a "cmd=<fork> --nnue a/r6-h256/weights.bin,depth=4" --b cmd=ref,depth=4
--games 200 --workers 7` (the sweep a net: radius 6, lambda 0.75, Pearson 0.579).

**Net 60.8% [53.8, 67.3], about +76 Elo [+27, +125] over nokamute 1.0.3 at depth 4**,
W107 D29 L64, 336 s of wall clock. As white 68%, as black 54%. The net side took 10.2 s of
search per game, the hand eval 1.0 s (the ~10x per node cost). One game was a rules version
disagreement: the fork declared a repetition draw (the post 1.0.3 six ply cycle fix) where
1.0.3 played on; the harness now records such games as `Disagree`, scored as a draw.

Same match with the sweep c net (radius 6, lambda 1.0, Pearson 0.662): **61.8% [54.9, 68.2],
about +83 Elo [+34, +133]**, W105 D37 L58, 321 s.

This is the per node answer: the learned evaluation beats the hand tuned one when both
search the same tree. Equal time is the next test.

## 2026-10-14: sweeps c and d, the recipe combined (Colab, L4)

Radius 6, lambda 1.0, patience 5, same data and holdout.

| run | hidden | best epoch | Pearson |
|---|---|---|---|
| static eval | | | 0.324 |
| c/r6-lam1-h256 | 256 | 12 of 17 | **0.662** |
| d/r6-lam1-h512 | 512 | 10 of 15 | 0.659 |

The engine candidate is `c/r6-lam1-h256` (8,128 x 256 table, 8.4 MB as `weights.bin`).

Cost in the engine (`--nnue`, forward pass from scratch per node, no quantization): a mid
game `bestmove` takes 0.35 s at depth 4 and 1.7 s at depth 5 with the net vs 0.03 s and
0.40 s with the hand eval, about 10x per node. Equal time therefore means about one ply less
for the net.

## 2026-10-14: round 3 sweeps, radius and target (Colab, L4)

Same 2.3M positions, same 5% held out games, new trainer (AdamW, weight decay 1e-4, lr
1e-3 decaying 0.9 per epoch, best epoch kept, patience 3). Pearson is against the depth 4
score and is comparable across targets; loss is not (the target changes with lambda).

| run | radius | lambda | best epoch | loss | Pearson |
|---|---|---|---|---|---|
| static eval | | | | | 0.324 |
| a/r12-h256 | 12 | 0.75 | 3 of 6 | 0.0170 | 0.571 |
| a/r8-h256 | 8 | 0.75 | 3 of 6 | 0.0169 | 0.578 |
| a/r6-h256 | 6 | 0.75 | 3 of 6 | 0.0167 | 0.579 |
| b/lam1.0 | 12 | 1.0 | 12 of 15 | 0.0063 | **0.644** |
| b/lam0.5 | 12 | 0.5 | 1 of 4 | 0.0500 | 0.435 |
| b/wd1e-3 | 12 | 0.75, wd 1e-3 | 2 of 5 | 0.0171 | 0.562 |

Radius 6 is as good as 12 with 3.7x fewer features (8,128). The game outcome in the target
is what makes the nets overfit: lambda 0.5 peaks at epoch 1, lambda 1.0 (pure search score,
the Stockfish pretraining setting) keeps improving for 12 epochs and reaches Pearson 0.64.
Extra weight decay does nothing. Decision for the engine: radius 6, lambda 1.0.

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
