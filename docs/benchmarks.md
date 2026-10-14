# Benchmarks and results

Dated records. Newest first. Machine unless stated: Ryzen 7 5700G, 16 threads, Linux.

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
