"""Self play position labeling.

    hive-label --games 1000 --depth 4 --random-move-prob 0.1

One nokamute process per game plays itself from a random opening. Every position gets the
engine's root score at the given depth (from the side to move's perspective), its static
evaluation (the hand tuned baseline a learned eval must beat) and the best move; with
probability --random-move-prob a random legal move is played instead of the best one, for
diversity (the position is still labeled with the search result). The final game outcome
is attached to every position as well.

Output: one JSON object per game:
  {"id", "game_type", "result", "moves": [...], "positions": [
      {"ply", "score", "static", "best", "played", "random", "pvlen", "outcome"}]}
where ply is the number of moves already played (the position is reproduced by replaying
moves[:ply]) and outcome is +1 / 0 / -1 from the side to move's perspective.

    hive-label --relabel runs/labels.jsonl.gz --depths 3,4,5 --source-depth 4

Labels the positions of existing games again, as a function of the position only: for
every labeled ply and every depth, a fresh player (no transposition table or history from
earlier searches, `newgame` with the moves so far) searches with one thread and a
16 MiB table. The engine orders the root moves by a seed taken from the position, so the
same position gets the same score in any game, order or machine. The records come back
with "depth" (the depth the games were played at) and, per position,
"scores": {"3": ..., "4": ..., "5": ...}; "score" is left as recorded. Scores already in the
records are kept, so depths can be added later.

    hive-label --relabel runs/relabeled.jsonl.gz --depths "" --scalars

adds the engine's 12 strategy scalars per position ("scalars"), which need no search.
`--nnue weights.bin --nnue-depths 5` also searches each position with that net, the same
way (fresh engine, one thread, 16 MiB table), under "net5"; the record names the net and
the sha1 of its file ("labeler"), since those labels belong to that net.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import random
import sys
import time
from multiprocessing import Pool
from typing import Any

from .encode import read_games
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
            static = eng.eval()
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
                    "static": static,
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


LABEL_OPTIONS = "TableSizeMiB=16"  # part of the label's definition, like the depth


def game_string(game_type: str, moves: list[str]) -> str:
    """UHP game string for `newgame` (nokamute ignores the state and turn fields)."""
    return ";".join([game_type, "InProgress", "White[1]", *moves])


def label_position(
    eng: Engine, game_type: str, moves: list[str], depths: list[int], prefix: str = ""
) -> dict[str, int | None]:
    """Root score at each depth of the position after `moves`, each from a fresh player."""
    scores: dict[str, int | None] = {}
    for depth in depths:
        eng.newgame(game_string(game_type, moves))
        scores[f"{prefix}{depth}"] = eng.search(depth)[1]
    return scores


def labeler(nnue: str) -> dict[str, str]:
    """What identifies net search labels: the net's file name and the sha1 of its bytes."""
    with open(nnue, "rb") as f:
        return {"net": os.path.basename(nnue), "sha1": hashlib.sha1(f.read()).hexdigest()}


def relabel_game(
    game: Game,
    depths: list[int],
    source_depth: int | None = None,
    scalars: bool = False,
    nnue: str | None = None,
    nnue_depths: tuple[int, ...] = (),
) -> Game:
    """`game` with `depth`, and per position `scores` (and `scalars`) added.

    See the module docstring; `source_depth` defaults to the depth recorded in the game.
    """
    positions = []
    with Engine(PlayerSpec.parse(f"depth=1,{LABEL_OPTIONS}")) as eng:
        for p in game["positions"]:
            scores = label_position(eng, game["game_type"], game["moves"][: p["ply"]], depths)
            positions.append({**p, "scores": {**p.get("scores", {}), **scores}})
        if scalars:
            # No search involved, so one replay of the game serves every position.
            at_ply = {p["ply"]: p for p in positions}
            eng.newgame(game["game_type"])
            for ply in range(len(game["moves"]) + 1):
                if ply in at_ply:
                    at_ply[ply]["scalars"] = eng.scalars()
                if ply < len(game["moves"]):
                    eng.play(game["moves"][ply])
    extra: Game = {}
    if nnue and nnue_depths:
        spec = PlayerSpec.parse(f"cmd={PlayerSpec().cmd} --nnue {nnue},depth=1,{LABEL_OPTIONS}")
        with Engine(spec) as net:
            for p in positions:
                moves = game["moves"][: p["ply"]]
                p["scores"].update(
                    label_position(net, game["game_type"], moves, list(nnue_depths), "net")
                )
        extra["labeler"] = labeler(nnue)
    depth = source_depth if source_depth is not None else game.get("depth")
    return {**game, **extra, "depth": depth, "positions": positions}


def _label(task: Task) -> Game:
    return label_game(*task)


def _relabel(
    task: tuple[Game, list[int], int | None, bool, str | None, tuple[int, ...]],
) -> Game:
    return relabel_game(*task)


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
    p.add_argument("--relabel", metavar="GAMES", help="label these games' positions again")
    p.add_argument("--depths", default="3,4,5", help="with --relabel: depths to search")
    p.add_argument("--scalars", action="store_true", help="with --relabel: add strategy scalars")
    p.add_argument("--nnue", help="with --relabel: also search with this net (weights.bin)")
    p.add_argument("--nnue-depths", default="5", help="with --nnue: depths, stored as net<d>")
    p.add_argument(
        "--source-depth", type=int, help="with --relabel: depth the games were played at"
    )
    return p.parse_args(argv)


def relabel(args: argparse.Namespace) -> int:
    """The --relabel mode of `main`."""
    depths = [int(d) for d in args.depths.split(",") if d]
    games = read_games(args.relabel)
    if args.source_depth is None and any(g.get("depth") is None for g in games):
        raise SystemExit("--relabel needs --source-depth for games without a recorded depth")
    out = args.out or os.path.join(RUNS, f"relabel-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl")
    print(f"{len(games)} games, depths {depths}, {args.workers} workers -> {out}", file=sys.stderr)
    nnue_depths = tuple(int(d) for d in args.nnue_depths.split(",") if d)
    tasks = [(g, depths, args.source_depth, args.scalars, args.nnue, nnue_depths) for g in games]
    n_pos = 0
    t0 = time.perf_counter()
    with open(out, "w") as f, Pool(args.workers) as pool:
        for n, game in enumerate(pool.imap(_relabel, tasks, chunksize=4), 1):
            n_pos += len(game["positions"])
            f.write(json.dumps(game) + "\n")
            if n % 10 == 0 or n == len(games):
                elapsed = time.perf_counter() - t0
                rate = n_pos / elapsed
                print(
                    f"[{n}/{len(games)} {elapsed:.0f}s] {n_pos} positions ({rate:.0f}/s)",
                    file=sys.stderr,
                )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Label the requested number of games; returns the process exit code."""
    args = _parse_args(argv)
    os.makedirs(RUNS, exist_ok=True)
    if args.relabel:
        return relabel(args)
    limit = f"seconds={args.seconds}" if args.seconds else f"depth={args.depth}"
    spec = PlayerSpec.parse(",".join(filter(None, [limit, args.engine_options])))
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
