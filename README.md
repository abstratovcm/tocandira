# tocandira

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo/tocandira-dark.svg"><img src="docs/logo/tocandira-light.svg" alt="tocandira logo" width="140" align="right"></picture>
Hive engine with a learned evaluation, built on nokamute's rules and search framework
(named after the bullet ant; in Hive the ant is the piece that goes anywhere). Fork of
[nokamute](https://github.com/edre/nokamute) by Eric Roshan Eisner (MIT).
Target: beat nokamute 1.0.3 at equal time per move. Status (2026-10-20): done, 97.7%
[96.4, 98.5] (+650 Elo) over 800 games at 1 s per move, tocandira vs nokamute 1.0.3; see
[docs/benchmarks.md](docs/benchmarks.md).

## Roadmap

1. **Learned evaluation inside nokamute's search.** Label positions with the engine's own
   search, train a small net, put it back in place of `eval.rs`. Does it beat the hand
   tuned evaluation at equal time per move? Nobody had shown a neural Hive engine that does.
   **Done:** +34 with the first net (2026-10-14), +650 now; the labels are in their third
   generation (the hand eval's search, then each best net's own search,
   [docs/pipeline.md](docs/pipeline.md)), and this is still the largest lever.
2. If 1 works: **own search**, tuned for the learned evaluation (grows from the vendored `minimax`).
   **In progress, one measured option at a time** rather than a rewrite: adopted after
   timed matches, null move pruning +38, late move reductions +20, partial iterations +50,
   killer moves +25, reverse futility pruning +67; five more tested and off. No part of the
   profile is large enough for a rewrite to pay; one is planned only if a measurement asks
   for it.
3. If needed: **own board representation**, when incremental net updates ask for it.
   **Not needed so far:** what the net asked for (neighbour masks, an accumulator stack,
   prefetch, kept cut vertexes) went into nokamute's board in place.

Claims read "tocandira (nokamute's rules and search framework, with the tocandira evaluation
and search additions) vs nokamute 1.0.3, equal time per move"; speed and move generation
are nokamute's, not ours.

## Lineage

The engine answers UHP's `info` as `tocandira 0.1.0 (nokamute <version>)`: built on
[nokamute](https://github.com/edre/nokamute), whose MIT notice it keeps.

| nokamute's (Eric Roshan-Eisner) | tocandira's |
|---|---|
| rules, board, move generation, notation, UHP, perft | learned evaluation (`src/nnue.rs`) and the 12 strategy scalars (`src/scalars.rs`) |
| the search framework (`minimax`, vendored from his crate) | search additions, each an option measured in matches: partial iterations, killers, reverse futility, LMR exceptions, a seeded root order ([docs/pipeline.md](docs/pipeline.md)) |
| the hand tuned evaluation, generation 0's labeler | labels, data, training, the nets, and everything in this repository |

By lines, about a quarter of the engine's Rust (2026-10-21); most of the measured strength
comes from the evaluation.

## Layout

- `engine/nokamute/`: the engine fork (submodule, branch `tocandira`): the `search` UHP
  command ([edre/nokamute#13](https://github.com/edre/nokamute/pull/13)), `--nnue`, and a
  vendored `minimax` whose root move order is seeded by the position (deterministic search),
  with the search options of [docs/pipeline.md](docs/pipeline.md).
- `tocandira/`: Python lab (numpy is the only runtime dependency).
  - `hive-tournament`: engine vs engine matches over UHP, parallel games, paired random
    openings with colours swapped, Wilson interval, Elo, optional SPRT early stop.
  - `hive-label`: self play, and relabeling of positions (search scores, scalars): the data.
  - `hive-encode`: turns a labels file into NNUE style sparse features (npz).
- `scripts/build_reference.sh`: builds the frozen opponent, upstream `v1.0.3`, into
  `reference/nokamute-1.0.3`. Never taken from the fork.
- `tocandira/nnue.py`: the evaluation net and its training loop (torch, `uv sync --group train`).
- `colab/`: two copies per round, one per Colab session: `01_generate_instance{0,1}`
  (self play), `01_relabel_instance{0,1}` (labels by any labeler, hand eval depths or a net,
  into output folders given as parameters), `02_train_{a,b}` (a sweep each; unused since
  training moved to a local GPU), `03_match_{a,b}` (match lists against our previous best
  and the 1.0.3 reference).
- `docs/`: dated [benchmarks](docs/benchmarks.md), [encoding](docs/encoding.md) design,
  [pipeline](docs/pipeline.md) (how a round goes), `logo/`.
- `runs/`: match records and datasets (gitignored).

## Setup

```bash
git submodule update --init
(cd engine/nokamute && cargo build --release)   # LTO is set in its Cargo.toml
scripts/build_reference.sh
uv sync
```

## Use

```bash
uv run hive-tournament --a depth=4 --b depth=4,Aggression=5 --games 200   # development, fixed depth
uv run hive-tournament --a seconds=1 --b cmd=ref,seconds=1 --games 400    # the real question
uv run hive-label --games 1000 --depth 4 --random-move-prob 0.1           # -> runs/labels-*.jsonl
uv run hive-label --relabel runs/labels-<stamp>.jsonl --source-depth 4    # + scores at depths 3,4,5
uv run hive-label --relabel <games> --depths "" --nnue <weights.bin> --scalars  # net labels (net5), scalars
uv run hive-encode runs/labels-<stamp>.jsonl --radius 6                   # -> runs/labels-<stamp>.npz
uv run hive-train <npz folder> <out> target=net5 hidden=128 l2=16 scalars=true lam=0.9  # torch
uv run hive-export <out>/weights.npz                                      # -> weights.bin for --nnue
```

A full round (games, labels, training, screens, timed matches) is in
[docs/pipeline.md](docs/pipeline.md).

Player spec: `depth=N` or `seconds=S`; `cmd=/path/to/uhp/engine` or `cmd=ref`; `name=...`;
any other `Key=Value` is sent as a UHP option (`Aggression`, `TableSizeMiB`, ...). All
match numbers are from A's point of view. Fixed depth is for development; the claim that
counts is at equal time, since a learned evaluation costs more per node.

Labels: one JSON object per game: moves and, per position, the root score (side to move's
view), best and played move, outcome; `--relabel` adds a score per depth.
Encoding: one sparse feature per piece relative to the queen, both perspectives, see
[docs/encoding.md](docs/encoding.md).

## Development

```bash
uv run ruff format && uv run ruff check --fix   # format and lint (config in pyproject.toml)
uv run mypy                                     # strict type check of tocandira/
uv run pytest -q                                # engine tests skip until engine/nokamute is built
```

CI runs the same four on every push; conventions in [CONTRIBUTING.md](CONTRIBUTING.md).
