"""Engine vs engine match runner.

    hive-tournament --a depth=4 --b depth=4,Aggression=5 --games 200
    hive-tournament --a depth=4 --b depth=3 --games 1000 --sprt 0 20   # stop early once decided

Games are played in pairs: each random opening is played with both colour assignments.
All counts and Elo are from A's point of view.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from dataclasses import asdict
from multiprocessing import Pool

from .game import GameRecord, play_game, random_opening
from .stats import sprt_bounds, sprt_llr, summary
from .uhp import Engine, PlayerSpec

RUNS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")

Task = tuple[int, bool, PlayerSpec, PlayerSpec, list[str], str, int]


def _play(task: Task) -> tuple[int, bool, GameRecord]:
    idx, a_white, a, b, opening, game_type, ply_cap = task
    white, black = (a, b) if a_white else (b, a)
    return idx, a_white, play_game(white, black, opening, game_type, ply_cap)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--a", required=True, help="player spec for engine A (see tocandira.uhp)")
    p.add_argument("--b", required=True, help="player spec for engine B")
    p.add_argument("--games", type=int, default=100, help="total games (rounded up to even)")
    p.add_argument("--opening-plies", type=int, default=4)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--game-type", default="Base+MLP")
    p.add_argument(
        "--ply-cap", type=int, default=300, help="adjudicate a draw after this many plies"
    )
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    p.add_argument(
        "--sprt",
        nargs=2,
        type=float,
        metavar=("ELO0", "ELO1"),
        help="stop early with a sequential test",
    )
    p.add_argument(
        "--out", help="jsonl of game records (default runs/tournament-<timestamp>.jsonl)"
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the match described by the command line; returns the process exit code."""
    args = _parse_args(argv)
    a, b = PlayerSpec.parse(args.a), PlayerSpec.parse(args.b)
    n_pairs = (args.games + 1) // 2
    rng = random.Random(args.seed)
    with Engine(PlayerSpec(depth=1)) as oracle:
        openings = [
            random_opening(oracle, args.opening_plies, rng, args.game_type)[0]
            for _ in range(n_pairs)
        ]

    os.makedirs(RUNS, exist_ok=True)
    out = args.out or os.path.join(RUNS, f"tournament-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl")
    tasks: list[Task] = [
        (i, aw, a, b, openings[i], args.game_type, args.ply_cap)
        for i in range(n_pairs)
        for aw in (True, False)
    ]
    print(f"A: {a.name}\nB: {b.name}", file=sys.stderr)
    print(
        f"{len(tasks)} games, {args.workers} workers, "
        f"openings of {args.opening_plies} plies -> {out}",
        file=sys.stderr,
    )

    wins = draws = losses = forfeits = 0
    lower, upper = sprt_bounds()
    t0 = time.perf_counter()
    with open(out, "w") as f, Pool(args.workers) as pool:
        for n, (idx, a_white, rec) in enumerate(pool.imap_unordered(_play, tasks), 1):
            s = rec.score_for_white() if a_white else 1 - rec.score_for_white()
            wins += s == 1
            draws += s == 0.5
            losses += s == 0
            forfeits += rec.result.startswith("Forfeit")
            f.write(json.dumps({"pair": idx, "a_white": a_white, **asdict(rec)}) + "\n")
            f.flush()
            elapsed = time.perf_counter() - t0
            line = f"[{n}/{len(tasks)} {elapsed:.0f}s] {summary(wins, draws, losses)}"
            if args.sprt:
                llr = sprt_llr(wins, draws, losses, *args.sprt)
                line += f"  LLR {llr:+.2f} ({lower:.2f}, {upper:.2f})"
                if llr < lower or llr > upper:
                    print(line, file=sys.stderr)
                    verdict = "H1 accepted (A is better)" if llr > upper else "H0 accepted"
                    print(f"SPRT: {verdict}", file=sys.stderr)
                    pool.terminate()
                    break
            print(line, file=sys.stderr)
    print(f"\nA = {a.name}  vs  B = {b.name}\n{summary(wins, draws, losses)}", file=sys.stderr)
    print(
        f"forfeits/illegal moves: {forfeits}   "
        f"wall {time.perf_counter() - t0:.0f}s   records: {out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
