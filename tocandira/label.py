"""Self play position labeling.

    hive-label --games 1000 --depth 4 --random-move-prob 0.1

One nokamute process per game plays itself from a random opening. Every position gets the
engine's root score at the given depth (from the side to move's perspective) and the best
move; with probability --random-move-prob a random legal move is played instead of the best
one, for diversity (the position is still labeled with the search result). The final game
outcome is attached to every position as well.

Output: one JSON object per game:
  {"id", "game_type", "result", "moves": [...], "positions": [
      {"ply", "score", "best", "played", "random", "pvlen", "outcome"}]}
where ply is the number of moves already played (the position is reproduced by replaying
moves[:ply]) and outcome is +1 / 0 / -1 from the side to move's perspective.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from multiprocessing import Pool
from typing import Any

from .game import random_opening
from .uhp import Engine, PlayerSpec, game_state

RUNS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")
TERMINAL = ("Draw", "WhiteWins", "BlackWins")

Game = dict[str, Any]
Task = tuple[int, PlayerSpec, int, float, str, int, int]


def label_game(
    game_id: int,
    spec: PlayerSpec,
    opening_plies: int,
    eps: float,
    game_type: str,
    ply_cap: int,
    seed: int,
) -> Game:
    """Play one labeled self play game; see the module docstring for the record format."""
    rng = random.Random(seed)
    with Engine(spec) as eng:
        moves, state = random_opening(eng, opening_plies, rng, game_type)
        positions: list[dict[str, Any]] = []
        while len(moves) < ply_cap and state not in TERMINAL:
            best, score, pvlen = eng.search()
            played = best
            is_random = False
            if eps and rng.random() < eps:
                legal = eng.validmoves()
                if len(legal) > 1:
                    played, is_random = rng.choice(legal), True
            positions.append(
                {
                    "ply": len(moves),
                    "score": score,
                    "best": best,
                    "played": played,
                    "random": is_random,
                    "pvlen": pvlen,
                }
            )
            state = game_state(eng.play(played))
            moves.append(played)
        result = state if state in TERMINAL else "PlyCap"
    white_outcome = {"WhiteWins": 1, "BlackWins": -1}.get(result, 0)
    for pos in positions:
        pos["outcome"] = white_outcome if pos["ply"] % 2 == 0 else -white_outcome
    return {
        "id": game_id,
        "game_type": game_type,
        "result": result,
        "moves": moves,
        "positions": positions,
    }


def _label(task: Task) -> Game:
    return label_game(*task)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--games", type=int, default=100)
    p.add_argument("--depth", type=int, default=4, help="search depth for labels and moves played")
    p.add_argument("--seconds", type=float, help="time per search instead of depth (nokamute only)")
    p.add_argument("--random-move-prob", type=float, default=0.1)
    p.add_argument("--opening-plies", type=int, default=4)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--game-type", default="Base+MLP")
    p.add_argument("--ply-cap", type=int, default=300)
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    p.add_argument("--engine-options", default="", help="extra spec items, e.g. Aggression=5")
    p.add_argument("--out", help="jsonl output (default runs/labels-<timestamp>.jsonl)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Label the requested number of games; returns the process exit code."""
    args = _parse_args(argv)
    limit = f"seconds={args.seconds}" if args.seconds else f"depth={args.depth}"
    spec = PlayerSpec.parse(",".join(filter(None, [limit, args.engine_options])))
    os.makedirs(RUNS, exist_ok=True)
    out = args.out or os.path.join(RUNS, f"labels-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl")
    tasks: list[Task] = [
        (
            i,
            spec,
            args.opening_plies,
            args.random_move_prob,
            args.game_type,
            args.ply_cap,
            args.seed * 1_000_003 + i,
        )
        for i in range(args.games)
    ]
    print(
        f"{args.games} games, {spec.name}, eps {args.random_move_prob}, "
        f"{args.workers} workers -> {out}",
        file=sys.stderr,
    )

    n_pos = 0
    results: dict[str, int] = {}
    t0 = time.perf_counter()
    with open(out, "w") as f, Pool(args.workers) as pool:
        for n, game in enumerate(pool.imap_unordered(_label, tasks), 1):
            n_pos += len(game["positions"])
            results[game["result"]] = results.get(game["result"], 0) + 1
            f.write(json.dumps(game) + "\n")
            if n % 10 == 0 or n == args.games:
                elapsed = time.perf_counter() - t0
                print(
                    f"[{n}/{args.games} {elapsed:.0f}s] {n_pos} positions "
                    f"({n_pos / elapsed:.0f}/s) {results}",
                    file=sys.stderr,
                )
    elapsed = time.perf_counter() - t0
    print(
        f"done: {n_pos} positions from {args.games} games in {elapsed:.0f}s -> {out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
