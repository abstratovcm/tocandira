"""Replay recorded games with tocandira.board.Board and dump the positions as JSON.

The output is the cross-check fixture for tanajura's TypeScript port of the board model
(its board.test.ts replays the same moves and compares). Games come from match records
(runs/matches/*.jsonl or runs/match-*.jsonl, one GameRecord per line).

Usage: uv run python scripts/dump_board_fixtures.py <out.json> [records.jsonl ...] [--games N]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tocandira.board import Board


def main() -> None:
    """Replay the games and write the JSON fixture."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out")
    parser.add_argument("records", nargs="*")
    parser.add_argument("--games", type=int, default=40, help="games per record file")
    args = parser.parse_args()
    files = args.records or sorted(glob.glob("runs/matches/*.jsonl"))[:3]
    games = []
    for path in files:
        with open(path) as f:
            for n, line in enumerate(f):
                if n >= args.games:
                    break
                record = json.loads(line)
                board = Board(record["game_type"])
                positions = []
                for move in record["moves"]:
                    board.apply(move)
                    positions.append(sorted(board.pieces()))
                games.append(
                    {
                        "game_type": record["game_type"],
                        "moves": record["moves"],
                        "result": record["result"],
                        "positions": positions,
                        "hand": board.hand,
                    }
                )
    with open(args.out, "w") as f:
        json.dump(games, f, separators=(",", ":"))
    print(f"{len(games)} games, {sum(len(g['moves']) for g in games)} plies -> {args.out}")


if __name__ == "__main__":
    main()
