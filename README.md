# tocandira

Hive engine: nokamute's search with a learned evaluation. Fork of
[nokamute](https://github.com/edre/nokamute) by Eric Roshan Eisner (MIT).
Target: beat nokamute 1.0.3 at equal time per move. Work in progress, no results yet.

Named after the bullet ant (*Paraponera clavata*, "tocandira" in Tupi). In Hive the ant is
the piece that goes anywhere.

## Roadmap

1. **Learned evaluation inside nokamute's search.** Label positions with the engine's own
   search, train a small net, put it back in place of `eval.rs`. The open question: does it
   beat the hand tuned evaluation at equal time per move? Nobody has shown a neural Hive
   engine that does.
2. If 1 works: **own search**, tuned for the learned evaluation (replaces the generic
   `minimax` crate nokamute uses).
3. If needed: **own board representation**, when incremental net updates ask for it.

Until step 2, every strength claim reads "nokamute's search with the tocandira evaluation
vs nokamute 1.0.3". Speed and move generation are nokamute's, not ours.

## Layout

- `engine/nokamute/`: the engine fork (submodule, branch `tocandira`), with a `search` UHP
  command that returns the root score (sent upstream as
  [edre/nokamute#13](https://github.com/edre/nokamute/pull/13)).
- `tocandira/`: Python lab, no runtime dependencies.
  - `hive-tournament`: engine vs engine matches over UHP, parallel games, paired random
    openings with colours swapped, Wilson interval, Elo, optional SPRT early stop.
  - `hive-label`: self play that records the engine's search score and the final outcome
    for every position, i.e. training data for the evaluation.
- `scripts/build_reference.sh`: builds the frozen opponent, upstream `v1.0.3`, into
  `reference/nokamute-1.0.3`. Never taken from the fork.
- `runs/`: match records and datasets (jsonl, gitignored).

## Setup

```bash
git submodule update --init
(cd engine/nokamute && CARGO_PROFILE_RELEASE_LTO=true CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 cargo build --release)
scripts/build_reference.sh
uv sync
```

## Tournament

```bash
uv run hive-tournament --a depth=4 --b depth=4,Aggression=5 --games 200   # development, fixed depth
uv run hive-tournament --a seconds=1 --b cmd=ref,seconds=1 --games 400    # the real question
uv run hive-tournament --a depth=4 --b depth=3 --games 2000 --sprt 0 20   # stops once decided
```

Player spec: `depth=N` or `seconds=S`; `cmd=/path/to/uhp/engine` or `cmd=ref`; `name=...`;
any other `Key=Value` is sent as a UHP option (`Aggression`, `TableSizeMiB`, ...). All
numbers are from A's point of view. One JSON line per game lands in `runs/`.

Fixed depth comparisons are for development only. A learned evaluation costs more per node,
so the claim that counts is at equal time per move.

## Labeling

```bash
uv run hive-label --games 1000 --depth 4 --random-move-prob 0.1
```

One JSON object per game: `moves` (full move list) and `positions`, each with `ply` (replay
`moves[:ply]` to rebuild it), `score` (root negamax value at that depth from the side to
move's perspective, ±32767 = forced win/loss), `best`, `played`, `random` (an epsilon random
move was played instead of `best`), `pvlen` and `outcome` (+1/0/-1 for the side to move).

## Measured throughput (Ryzen 7 5700G, 16 threads, one thread per game)

| Depth | Per move | Per game (median) | 100k games on 16 threads |
|---|---|---|---|
| 1 | 0.06 ms | 0.11 s | minutes |
| 2 | 0.3 ms | 0.14 s | minutes |
| 3 | 5 ms | 0.4 s | ~40 min |
| 4 | 27 ms | 2 s | ~3.5 h |
| 5 | 290 ms | 10 s | ~18 h |
| 6 | 1.35 s | 69 s | ~5 days |

Labeling at depth 4 runs at ~220 positions/s on 7 workers (~80 positions per game).
Script: `docs/throughput_bench.py`.

## First result

200 games at depth 4: nokamute's default `Aggression=3` beats `Aggression=5`, 57.5%
[50.6, 64.1], about +53 Elo, in 102 s of wall clock.

## Development

```bash
uv run ruff format && uv run ruff check --fix   # format and lint (config in pyproject.toml)
uv run mypy                                     # strict type check of tocandira/
uv run pytest -q                                # engine tests skip until engine/nokamute is built
```

CI runs the same four on every push.
