# Contributing

## README

The README answers three questions for a stranger: what is this, how do I run it, what
should I believe about it right now. Budget: one screen, under 80 lines. Before adding a
line, move one out.

- Dated facts (measurements, match results, throughput) go to docs/benchmarks.md with the
  date and machine. The README links, it does not repeat.
- Rationale and formulas (why an encoding, why a search change) go to docs/<topic>.md.
- History goes in commit messages, not in the README.

## Tests

Add a test when it:
- pins something that would break silently and be noticed late (move notation, feature
  indices, dataset layout, statistics);
- is a contract someone else relies on (player spec syntax, npz layout, UHP extensions);
- reproduces a bug that actually happened.

Do not add tests that restate the implementation, test glue (argparse defaults,
forwarding functions), duplicate existing coverage, or assert exact human readable strings.

A test failing on a legitimate change means it pinned the wrong thing: fix or delete it,
never just update the expected value.

The default suite stays under a few seconds. Anything slower (playing games, encoding a
dataset, training) is marked `@pytest.mark.slow`; run `pytest -m "not slow"` locally, CI
runs everything.

## Code

ruff for lint and format, mypy strict, google style docstrings on public functions. The
config is in pyproject.toml; `uv run ruff format && uv run ruff check && uv run mypy &&
uv run pytest` is what CI runs.
