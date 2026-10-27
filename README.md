# tocandira

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo/tocandira-dark.svg"><img src="docs/logo/tocandira-light.svg" alt="tocandira logo" width="140" align="right"></picture>
Hive engine with a learned evaluation, built on nokamute's rules and search framework
(named after the bullet ant; in Hive the ant is the piece that goes anywhere). Fork of
[nokamute](https://github.com/edre/nokamute) by Eric Roshan Eisner (MIT).
Target: beat nokamute 1.0.3 at equal time per move. Status: done; v1.0.0 (2026-10-27)
scores 97.8% [96.5, 98.6] (+660 Elo) over 800 games at 1 s per move, tocandira vs
nokamute 1.0.3; see [docs/benchmarks.md](docs/benchmarks.md).

To play it: a [release](https://github.com/abstratovcm/tocandira/releases) (Linux,
Windows) is one UHP engine binary with the net inside; set it as MzingaViewer's Engine.

## Roadmap

1. **Learned evaluation inside nokamute's search.** **Done:** +34 with the first net
   (2026-10-14), +650 by 2026-10-20; the labels are in their third generation, each best
   net's own search ([docs/pipeline.md](docs/pipeline.md)). Still the largest lever.
2. **Own search**, grown from the vendored `minimax`. **In progress, one measured option at
   a time:** null move pruning, late move reductions, partial iterations, killer moves,
   reverse futility pruning adopted; five more tested and off. Next: the same additions in
   the parallel search (the release plays one thread until then).
3. **Own board representation**, if incremental net updates ask for it. **Not needed so
   far:** what the net asked for went into nokamute's board in place.

Claims read "tocandira (nokamute's rules and search framework, with the tocandira evaluation
and search additions) vs nokamute 1.0.3, equal time per move"; speed and move generation
are nokamute's, not ours.

## Lineage

The engine answers UHP's `info` as `tocandira 1.0.0 (nokamute <version>)` and keeps
nokamute's MIT notice.

| nokamute's (Eric Roshan-Eisner) | tocandira's |
|---|---|
| rules, board, move generation, notation, UHP, perft | learned evaluation (`src/nnue.rs`), 12 strategy scalars (`src/scalars.rs`) |
| the search framework (`minimax`, vendored from his crate) | search additions, each an option measured in matches ([docs/pipeline.md](docs/pipeline.md)) |
| the hand tuned evaluation, generation 0's labeler | labels, data, training, the nets, and everything in this repository |

## Layout

- `engine/nokamute/`: the engine fork (submodule, branch `tocandira`).
- `tocandira/`: Python lab: `hive-tournament` (matches over UHP, paired openings, Wilson
  interval, Elo, SPRT), `hive-label` (self play, labels), `hive-encode` (sparse features),
  `hive-train` and `hive-export` (the net, torch: `uv sync --group train`).
- `nets/` and `scripts/build_release.sh`: the release's net and its build;
  `scripts/build_reference.sh`: the frozen opponent, upstream `v1.0.3`.
- `colab/`: the round's notebooks (self play, labels, matches), two copies for two runtimes.
- `docs/`: [benchmarks](docs/benchmarks.md), [pipeline](docs/pipeline.md) (how a round
  goes), [encoding](docs/encoding.md), `releases/`. `runs/`: data and records (gitignored).

## Setup

```bash
git submodule update --init
(cd engine/nokamute && cargo build --release)   # LTO is set in its Cargo.toml
scripts/build_reference.sh
uv sync
```

## Use

```bash
uv run hive-tournament --a seconds=1 --b cmd=ref,seconds=1 --games 400    # the real question
uv run hive-label --games 1000 --depth 4 --random-move-prob 0.1           # -> runs/labels-*.jsonl
uv run hive-train <npz folder> <out> target=net5 hidden=128 l2=16 scalars=true lam=0.9
```

Player specs are in `tocandira/uhp.py`; every command of a round in [docs/pipeline.md](docs/pipeline.md).

## Development

```bash
uv run ruff format && uv run ruff check --fix && uv run mypy && uv run pytest -q   # as CI does; conventions in CONTRIBUTING.md
```

Code and documentation written with Claude and Gemini.
