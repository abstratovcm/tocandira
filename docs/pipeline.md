# Pipeline: data, labels, training, matches

How a round goes, what a label is, and the rules learned so far. Measured numbers live in
[benchmarks.md](benchmarks.md); this file says how to produce them.

## A round

| step | tool | where | time |
|---|---|---|---|
| 1. self play | `hive-label --games ... --depth 4 [--engine-options "cmd=<fork> --nnue <net>"]` | `colab/01_generate_instance{0,1}` | ~1 h per 60k games on two v6e-1 |
| 2. labels | `hive-label --relabel <games> --depths 3,4,5 [--nnue <net> --nnue-depths 5]` | `colab/01_relabel_instance{0,1}` | ~6-8 h per 2M positions per label kind, two v6e-1 |
| 3. scalars | `hive-label --relabel <labeled> --depths "" --scalars`, then `hive-encode --radius 6` | local | ~5 min per 4M positions |
| 4. training | `hive-train <npz folder> <out> target=net5 hidden=128 l2=16 scalars=true lam=0.9 patience=5 max_epochs=60`, two seeds | local GPU (ROCm) | ~5 s per epoch per 4M positions |
| 5. screen | `hive-tournament --a "cmd=<fork> --nnue <net>,depth=5" --b "cmd=<fork>,depth=5" --games 400` | local, 14 workers | ~7 min |
| 6. timed matches | `hive-tournament ... seconds=1 ... --games 800` | `colab/03_match_{a,b}` | ~30 min per 800 games on a v6e-1 |

Generation, labels and matches are CPU work (one search per core): the v6e-1 runtimes are
bought for their 44 vCPUs, the TPU stays idle. Training is the only GPU step.

Drive (`MyDrive/tocandira/`): `data/<set>` raw games (`shard-NNN.jsonl.gz`), `data/m` and
`data/mr6` relabeled games and their radius 6 encoding, `models/<sweep>/<name>/weights.npz`
(the notebooks export `weights.bin` next to it), `matches/` records and `summary.txt`.
Locally the same folders live under `runs/` (gitignored); `runs/data/msr6` is `mr6` with the
scalars added.

## What a label is

`score<d>` is the root value of a search at depth d from the side to move, by a fresh
engine for every position (`newgame` with the moves so far, one thread, 16 MiB table, root
moves in an order seeded by the position). It is a function of the position: the same
position gets the same score in any game, order, session or machine (checked: 1,353 scores
recomputed across machines, 0 differ). Speed work on the engine is bit exact, so it never
changes labels. `score_net<d>` is the same with a net's evaluation; the record's `labeler`
names the net file and its sha1, because those labels belong to that net.

## Label generations

A generation is one frozen labeler: engine commit, net file (sha1), depth.

| generation | labeler | data |
|---|---|---|
| 0 | nokamute's hand eval, depths 3, 4, 5 | d4 and d5 games (3.8M positions), n4 games |
| 1 (2026-10-16 to 2026-10-21) | net `i/d5-h128-l16-s`, depth 5 (`score_net5`) | n4 games (net self play, seeds 3000+, 3.1M), n4j (seeds 4000+, played by `j/n4-net5-s0`, 4.3M); 7.5M in all |
| 2 (since 2026-10-21) | net `l/lam09-s0` (sha1 698bd99a), depth 5 (`score_net5`) | n4j shards 0-19 relabeled (runs/data/m2s, A/B only); new games next |

Policy:
- Never relabel history. A round labels only its own new positions, with the current
  generation: constant cost per round, whatever the total.
- Old data is retired, not relabeled: train on a window of recent data weighted toward the
  newest generation; older generations fall out of the window.
- A new generation fills its window with new games, not relabeled old ones: playing the
  games costs little next to labeling them (about 1 h against 12-15 h for 3.8M positions on
  two v6e-1), and the positions come from the current net's play.
- Labels of the current generation only: generation 1 relabels with `DEPTHS = ""` and the
  net. Hand eval depths belong on the small reference set.
- A new generation only at a milestone (a new net clearly beats the labeler at equal
  time) and after an A/B test: same positions, both label kinds, two nets per label kind
  (two training seeds), screens, then a head to head of the best of each.
- A small fixed reference set may be relabeled by each generation, to compare them.
- `load_shards` keeps only the arrays every shard has: a target from one generation means
  training on that generation's shards.

## Search options

Search changes are opt-in (a flag or UHP option, default off), so the default search, the
one labels are defined with, never changes by accident; `hive-label` never passes them.
Matches and play use the options that won a timed match:

| option | since | evidence |
|---|---|---|
| `--null-move-pruning` | 2026-10-16 | +38 [+4, +73] at 1 s/move, 400 games |
| `--lmr` | 2026-10-16 | +20 [-5, +44] on top of null move, 800 games (best estimate, borderline) |
| `--partial-iteration` | 2026-10-16 | +50 [+15, +86] on top of both, SPRT stopped at 376 games |
| `--killers` | 2026-10-16 | +25 [+1, +49] on top of the three, 800 games |
| `--rfp=100` | 2026-10-18 | +67 [+22, +112] on top of the four, SPRT stopped at 235 games |

Tested and off: `--quiet-search` (fixed but about 5x slower, −243), `--aspiration-window=50`
(+10 [−24, +44]), `--lmr-scale=2.5` (+7 [−18, +31]), `--root-pvs` (+5 [−19, +29]), `--lmr-history` (+3 [−21, +27]). A switch joins a label definition only at a deliberate generation change.

## Rules learned the hard way

- Only one session encodes a given Drive folder at a time: two sessions encoding radius 6
  at once left byte identical copies that leaked the holdout (2026-10-14). `load_shards`
  now skips duplicate files.
- Only one session creates a Drive folder: two generate instances creating `n4j` at once
  made two folders of that name, each with half the shards (2026-10-16). In the notebooks
  instance 0 creates the folders and instance 1 waits for them.
- The holdout is by opening (same seeds give the same openings across game sets).
- Pearson does not rank nets: smaller nets and the cheap scalars looked equal offline and
  differed by 40-110 Elo per node. The depth 5 screen decides, the timed match confirms.
- Train on every position: keeping only the half whose evaluation changes least with depth
  (as Stockfish filters non-quiet positions) loses ~40 Elo per node (2026-10-18); the
  volatile half is where the net learns.
- Do not repeat them either: oversampling positions by surprise (KataGo style) loses 47-72
  (2026-10-20). Uniform over all positions.
- Blend in the outcome: lambda 0.9 beats 1.0 by ~43 per node (two seeds, 2026-10-18), and
  0.8 ties 0.9 (2026-10-20). Pearson had favoured 1.0; judge training settings by games.
- Training noise: the same recipe with another seed moves a screen by 24-36 Elo
  (2026-10-16). A difference of that size between two single trainings is not a result.
- The screen against the fork compresses at 85-90%: two nets at +370 and +392 there were 70
  Elo apart head to head (2026-10-16). Between top candidates, play them against each other
  at depth 5.
- No timed match on an engine that is about to change: finish the speed work first, then
  measure once. Fixed depth screens do not depend on speed.
- Speed is worth about +75 Elo per doubling at 1 s/move (measured with net c).
- Measure before building speed work: two of four attempts on 2026-10-15 were slower, a
  microbenchmark can mislead, the 20 position search time decides.
- Every speed change is bit exact: byte identical output on the 20 benchmark positions for
  net c, a scalars net and the hand eval.
