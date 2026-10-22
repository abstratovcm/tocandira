# Pipeline: data, labels, training, matches

How a round goes, what a label is, and the rules learned so far. Measured numbers live in
[benchmarks.md](benchmarks.md); this file says how to produce them.

## A round

| step | tool | where | time |
|---|---|---|---|
| 1. self play | `hive-label --games ... --depth 4 --opening-plies 6 --engine-options "cmd=<fork> --nnue <net> <match switches>"` | `colab/01_generate_instance{0,1}` | ~1 h per 60k games on two runtimes |
| 2. labels | `hive-label --relabel <games> --depths "" --nnue <labeler> --nnue-depths 5 --nnue-options "<switches>" --scalars`, then `hive-encode --radius 6` | `colab/01_relabel_instance{0,1}` or local | plain depth 5: ~53 positions/s per Colab runtime (v5e-1 = v6e-1), 46/s on the Ryzen; with the switches about 3x faster |
| 3. scalars | `hive-label --relabel <labeled> --depths "" --scalars`, then `hive-encode --radius 6` (only for labels made without `--scalars`) | local | ~5 min per 4M positions |
| 4. training | `hive-train <npz folder> <out> target=net5 hidden=128 l2=16 scalars=true lam=0.9 patience=5 max_epochs=60`, two seeds | local GPU (ROCm) | ~5 s per epoch per 4M positions |
| 5. screen | `hive-tournament --a "cmd=<fork> --nnue <net>,depth=5" --b "cmd=<fork>,depth=5" --games 400` | local, 14 workers | ~7 min |
| 6. timed matches | `hive-tournament ... seconds=1 ... --games 800 [--sprt 0 20]` | local (6 workers, ~2.2 h) or `colab/03_match_{a,b}` (~40 min, ~4 units) | |

Generation, labels and matches are CPU work (one search per core); the TPU stays idle and
training is the only GPU step. A Colab runtime labels at about the Ryzen's speed (2026-10-21,
from shard times), so Colab buys parallel hours, not cheaper labels: v6e-1 ~4.6 units/h,
v5e-1 about half that at the same labeling speed, so the v5e-1 is the one to buy.

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
names the net file, its sha1 and the search options (`--nnue-options`), because those
labels belong to that net and that search. `load_shards` refuses to mix net labels of
different labelers. Deterministic search options (null move, LMR, killers, reverse
futility) keep a label a function of the position.

Before changing a label's definition, check it on ~100 positions against a deep reference
search (2026-10-21, `l/lam09-s0`): with the four switches, depth 6 costs 1.3x plain depth 5
and correlates 0.995 with plain depth 7 (plain depth 5: 0.980), depth 5 matches plain depth
5 at 0.3x the cost, depth 7 reaches 0.998 at 4.3x. Trained on the same 1.15M positions,
switched depth 6 labels gave nets no better than plain depth 5 (+19, -10 plain; +25, -22
with the switches): a deeper search with the same net changes the labels little (0.982),
so the definition is chosen by cost: switched depth 5, which also trained better than plain
depth 5 on the same positions (+45, +32 plain; +37, +3 switched).

## Label generations

A generation is one frozen labeler: engine commit, net file (sha1), depth.

| generation | labeler | data |
|---|---|---|
| 0 | nokamute's hand eval, depths 3, 4, 5 | d4 and d5 games (3.8M positions), n4 games |
| 1 (2026-10-16 to 2026-10-21) | net `i/d5-h128-l16-s`, depth 5 (`score_net5`) | n4 games (net self play, seeds 3000+, 3.1M), n4j (seeds 4000+, played by `j/n4-net5-s0`, 4.3M); 7.5M in all |
| 2 (since 2026-10-21; best net `n/g2-warm-s0`) | net `l/lam09-s0` (sha1 698bd99a) with `--null-move-pruning --lmr --killers --rfp=100`, depth 5 (`score_net5`, options in the labeler); the A/B used plain depth 5 | n4j shards 0-19 (plain depth 5 for the A/B, switched depths 5 and 6 for E1); n4l (seeds 5000+, played by `l/lam09-s0` with the match switches, 6 random plies, 60 shards) |

Policy:
- A label costs the same on old or new positions, locally or on Colab: relabel what an
  experiment or the window needs, but keep the labeled total per round bounded; the
  window of recent data replaces relabeling everything every round.
- New positions come from the current best player with the match switches (the games only
  choose positions); whether that beats older positions at equal size is measured (E2).
  (Until 2026-10-21 the rule was "never relabel history, fill with new games", from Colab
  labels looking expensive next to games.)
- Labels of the current generation only: generation 1 relabels with `DEPTHS = ""` and the
  net. Hand eval depths belong on the small reference set.
- A new generation only at a milestone (a new net clearly beats the labeler at equal
  time) and after an A/B test: same positions, both label kinds, two nets per label kind
  (two training seeds), screens, then a head to head of the best of each.
- A small fixed reference set may be relabeled by each generation, to compare them.
- `load_shards` keeps only the arrays every shard has: a target from one generation means
  training on that generation's shards.

## Search options

Search changes are opt-in (a flag or UHP option, default off), so the default search never
changes by accident. Labels use options only as part of a generation's definition
(`--nnue-options`, recorded in the labeler); self play passes the match options. Matches
and play use the options that won a timed match:

| option | since | evidence |
|---|---|---|
| `--null-move-pruning` | 2026-10-16 | +38 [+4, +73] at 1 s/move, 400 games |
| `--lmr` | 2026-10-16 | +20 [-5, +44] on top of null move, 800 games (best estimate, borderline) |
| `--partial-iteration` | 2026-10-16 | +50 [+15, +86] on top of both, SPRT stopped at 376 games |
| `--killers` | 2026-10-16 | +25 [+1, +49] on top of the three, 800 games |
| `--rfp=100` | 2026-10-18 | +67 [+22, +112] on top of the four, SPRT stopped at 235 games |
| `--rfp=115` with `n/g2-warm-s0` | 2026-10-22 | +21 [−3, +45] over 100, 800 games (best estimate): the margin is 100 x the net's output std / 469 (`l/lam09-s0`'s) |

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
- Volume and the labeler matter, the games' source barely: new games by the best player,
  more opening plies or mixed sources never beat older positions at equal size (2026-10-21,
  2026-10-22), while twice the positions gave +57 and a better labeler +46. Spend on
  positions with labels, cheaply (switched depth 5).
- Start from the previous best's weights (`init=`): +35 per node over training from
  scratch on generation 2's data (2026-10-22).
- Blend in the outcome: lambda 0.9 beats 1.0 by ~43 per node (two seeds, 2026-10-18), and
  0.8 ties 0.9 (2026-10-20). Pearson had favoured 1.0; judge training settings by games.
- Training noise: the same recipe with another seed moves a screen by 24-36 Elo
  (2026-10-16). A difference of that size between two single trainings is not a result.
- The screen against the fork compresses at 85-90%: two nets at +370 and +392 there were 70
  Elo apart head to head (2026-10-16). Between top candidates, play them against each other
  at depth 5.
- No timed match on an engine that is about to change: finish the speed work first, then
  measure once.
- Decide candidates with the match switches on. Plain depth 5 head to heads measure the
  evaluation alone; reverse futility and null move compare the evaluation with fixed
  margins, and the nets' output spread grows each generation (std on the same positions:
  i 332, j 449, l 469, the generation 2 A/B net 544; 2026-10-21). The decision is a timed
  match; a net whose output std is >15% off `l`'s gets its `--rfp` margin checked.
- Speed was worth about +75 Elo per doubling at 1 s/move with net c and the old engine
  (depth ~5); stale now that the search reaches depth 7-8, measure again before speed work.
- Measure before building speed work: two of four attempts on 2026-10-15 were slower, a
  microbenchmark can mislead, the 20 position search time decides.
- Every speed change is bit exact: byte identical output on the 20 benchmark positions for
  net c, a scalars net and the hand eval.

## Contributions ledger

Every lever measured so far, newest first per kind, with how it was measured. Details and
dates in [benchmarks.md](benchmarks.md). "Per node": head to head at fixed depth; "time":
1 s per move; Elo against the previous best of its kind unless stated.

| lever | kind | gain | how | kept |
|---|---|---|---|---|
| new games (l, switches, 6 random plies) vs older positions (j's games), same labels and size | data | -19 (-60, +1 / -3, -15) | per node, 2 seeds | no effect |
| 2.34M vs 1.15M generation 2 positions | data | +57 (+62, +53) | per node, 2 seeds | yes |
| warm start from the previous best's weights vs from scratch | training | +35 (+44, +26) | per node, 2 seeds | yes |
| generation 2 net (`n/g2-warm-s0`) vs `l/lam09-s0`, both with the five switches | net | +104 [+46, +161] | time, SPRT 152 games | yes |
| reverse futility margin scaled to the net's spread (115 vs 100) | search | +21 [-3, +45] | time, 800 games | yes (best estimate) |
| switched depth 5 vs plain depth 5 labels, same net and 1.15M positions | labels | +29 (+45, +32 / +37, +3), at 0.3x the cost | per node, 2 seeds, plain and switched | yes |
| switched depth 6 vs plain depth 5 labels, same net and 1.15M positions | labels | +3 (+19, -10 / +25, -22) | per node, 2 seeds, plain and switched | no (cost) |
| generation 2 labels (`l`'s search) vs generation 1 (`i`'s), same 1.1M positions | labels | +39, +53 | per node, 2 seeds | yes |
| generation 1 labels (`i`'s search) vs hand eval, same 3.1M positions | labels | +94 | per node, 2 seeds | yes |
| hand depth 5 vs depth 4 labels | labels | +55 | per node, from screens vs the fork | yes |
| outcome blend lambda 0.9 vs 1.0 | training | +43 (0.8 ties 0.9) | per node, 2 seeds | yes |
| 7.5M vs 3.1M generation 1 positions | data | +20 | per node, 2 seeds | yes |
| 6.9M vs 3.1M generation 0 positions (three game sources) | data | +128 | per node, from screens vs the fork | yes |
| three game sources vs one, equal size | data | +10 (-13, +34) | per node, 2 seeds | no effect |
| dropping the volatile half / oversampling it | data | -39 / -60 | per node, 2 seeds | no |
| hidden 256 vs 128 | net | -11 | per node | no |
| strategy scalars | net | +137 | time | yes |
| reverse futility (`--rfp=100`) | search | +67 | time, SPRT | yes |
| partial iterations | search | +50 | time, SPRT | yes |
| null move pruning | search | +38 | time | yes |
| killer moves | search | +25 | time | yes |
| late move reductions (fixed) | search | +20 | time | yes |
| LMR table, LMR by history, root null window, aspiration windows | search | +7, +3, +5, +10 | time | no |
| quiescence search | search | -243 | time | no |
| ordering by the net | search | slower to depth | node counts | no |
| speed work up to 2026-10-14 (1.6x) | speed | +52 | time, net c | yes |
| history sort, LTO | speed | -8% time at match conditions, 2-5% | bit exact benchmark | yes |
