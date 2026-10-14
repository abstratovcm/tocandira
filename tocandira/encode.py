"""NNUE style features for Hive positions.

    hive-encode runs/labels.jsonl --out runs/labels.npz [--radius 6]

One sparse feature per piece on the board, relative to an anchor (the perspective owner's
queen, falling back to the other queen, then to the first piece at (0, 0)):

    index = ((cell * 2 + colour_rel) * 8 + bug) * 4 + level

with `cell` the hex offset from the anchor within `radius` (3r² + 3r + 1 cells; farther
pieces are projected onto the ring), `colour_rel` 0 for the perspective owner's pieces,
`bug` in the order QABGSMLP and `level` the stack height bucket 0, 1, 2, 3+. Every position
is encoded twice, from the side to move's perspective (`own`) and the opponent's (`opp`),
plus 16 pieces in hand counts (side to move first). The first layer of the net is then a
sum of embeddings over at most 28 active features per perspective, cheap enough for CPU
search. The radius is a parameter (`Geometry`); 12 is the default, 6 covers 94% of pieces.

Hive's 12 symmetries about the anchor (6 rotations, 6 reflections) are index permutations,
see `Geometry.d6_tables()`, usable as free augmentation at training time.

Dataset layout (`np.savez_compressed`): `own`, `opp` int16 [N, 28] padded with -1,
`hand` int8 [N, 16], `score` int16, `static` int16 (the engine's hand tuned evaluation,
the baseline), `outcome` int8, `ply` int16, `game` int32, `random` bool, `opening` int64
(hash of the game's first 4 moves), `source` int8 (depth the game was played at, 0 if not
recorded), `meta` JSON (version, radius, num_features, depths, ...). Relabeled games
(`hive-label --relabel`) add one int16 array per searched depth: `score3`, `score4`, ...
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from functools import cache, partial
from multiprocessing import Pool
from typing import Any

import numpy as np
import numpy.typing as npt

from .board import BUGS, Board, Hex, hex_distance, other

RADIUS = 12
LEVELS = 4
FEATURES_PER_CELL = 2 * len(BUGS) * LEVELS
MAX_PIECES = 28
RUNS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")

Cube = tuple[int, int, int]


def _to_cube(h: Hex) -> Cube:
    # nokamute's axial to standard axial (q' = q - r), then cube with x + y + z = 0.
    x, z = h[0] - h[1], h[1]
    return x, -x - z, z


def _from_cube(c: Cube) -> Hex:
    x, _, z = c
    return x + z, z


def _rotate(c: Cube) -> Cube:
    x, y, z = c
    return -z, -x, -y


def _reflect(c: Cube) -> Cube:
    x, y, z = c
    return x, z, y


class Geometry:
    """The cells within `radius` of the anchor, their feature indices and the D6 tables."""

    def __init__(self, radius: int):
        self.radius = radius
        self.cells: list[Hex] = [
            (dq, dr)
            for dq in range(-radius, radius + 1)
            for dr in range(-radius, radius + 1)
            if hex_distance((dq, dr), (0, 0)) <= radius
        ]
        self.cell_index: dict[Hex, int] = {cell: i for i, cell in enumerate(self.cells)}
        self.num_cells = len(self.cells)
        self.num_features = self.num_cells * FEATURES_PER_CELL
        self._tables: npt.NDArray[np.int32] | None = None

    def feature_index(self, cell: Hex, colour_rel: int, bug: str, level: int) -> int:
        """Index of one (cell, relative colour, bug, stack level) feature."""
        within = (colour_rel * len(BUGS) + BUGS.index(bug)) * LEVELS + min(level, LEVELS - 1)
        return self.cell_index[cell] * FEATURES_PER_CELL + within

    def clamp(self, dq: int, dr: int) -> Hex:
        """The offset itself within the radius, otherwise its projection onto the ring."""
        d = hex_distance((dq, dr), (0, 0))
        if d <= self.radius:
            return dq, dr
        scale = self.radius / d
        fx, fy, fz = (v * scale for v in _to_cube((dq, dr)))
        rx, ry, rz = round(fx), round(fy), round(fz)
        ex, ey, ez = abs(rx - fx), abs(ry - fy), abs(rz - fz)
        if ex > ey and ex > ez:
            rx = -ry - rz
        elif ey > ez:
            ry = -rx - rz
        else:
            rz = -rx - ry
        return _from_cube((rx, ry, rz))

    def d6_tables(self) -> npt.NDArray[np.int32]:
        """12 feature permutations: rows 0 to 5 rotate by k * 60 degrees, 6 to 11 reflect first."""
        if self._tables is None:
            cell_perm = np.empty((12, self.num_cells), dtype=np.int32)
            for k in range(12):
                for i, cell in enumerate(self.cells):
                    c = _to_cube(cell)
                    if k >= 6:
                        c = _reflect(c)
                    for _ in range(k % 6):
                        c = _rotate(c)
                    cell_perm[k, i] = self.cell_index[_from_cube(c)]
            within = np.arange(FEATURES_PER_CELL, dtype=np.int32)
            tables = cell_perm[:, :, None] * FEATURES_PER_CELL + within[None, None, :]
            self._tables = tables.reshape(12, self.num_features)
        return self._tables


@cache
def geometry(radius: int = RADIUS) -> Geometry:
    """The shared `Geometry` for a radius."""
    return Geometry(radius)


def anchor(board: Board, colour: str) -> Hex:
    """That colour's queen, else the other queen, else the first piece's hex."""
    return board.queen(colour) or board.queen(other(colour)) or (0, 0)


def perspective(board: Board, colour: str, radius: int = RADIUS) -> list[int]:
    """Active features seen from `colour`'s queen, one per piece on the board."""
    g = geometry(radius)
    aq, ar = anchor(board, colour)
    return [
        g.feature_index(g.clamp(q - aq, r - ar), int(piece[0] != colour), piece[1], level)
        for piece, q, r, level in board.pieces()
    ]


@dataclass
class Encoded:
    """Sparse features of one position from both perspectives, plus pieces in hand."""

    own: list[int]
    opp: list[int]
    hand: list[int]


def encode(board: Board, radius: int = RADIUS) -> Encoded:
    """Encode the position for the side to move."""
    me, them = board.to_move, other(board.to_move)
    hand = [board.hand[colour].get(bug, 0) for colour in (me, them) for bug in BUGS]
    return Encoded(perspective(board, me, radius), perspective(board, them, radius), hand)


Row = tuple[list[int], list[int], list[int], int, int, int, bool, int]


def encode_game(game: dict[str, Any], radius: int = RADIUS) -> list[Row]:
    """Replay one labeled game and encode every labeled position."""
    board = Board(game["game_type"])
    moves: list[str] = game["moves"]
    positions = sorted(game["positions"], key=lambda p: int(p["ply"]))
    rows: list[Row] = []
    i = 0
    for ply in range(len(moves) + 1):
        while i < len(positions) and positions[i]["ply"] == ply:
            p = positions[i]
            enc = encode(board, radius)
            rows.append(
                (
                    enc.own,
                    enc.opp,
                    enc.hand,
                    p["score"] or 0,
                    p["outcome"],
                    ply,
                    bool(p["random"]),
                    p["static"],
                )
            )
            i += 1
        if ply < len(moves):
            board.apply(moves[ply])
    if i != len(positions):
        raise ValueError(f"game {game['id']}: labeled plies beyond the move list")
    return rows


OPENING_PLIES = 4  # hive-label's random opening length


def opening_key(moves: list[str]) -> int:
    """Stable int64 key of a game's opening: games sharing it are held out together."""
    digest = hashlib.sha1(";".join(moves[:OPENING_PLIES]).encode()).digest()
    return int.from_bytes(digest[:8], "little", signed=True)


def _pad(lists: list[list[int]]) -> npt.NDArray[np.int16]:
    arr = np.full((len(lists), MAX_PIECES), -1, dtype=np.int16)
    for i, feats in enumerate(lists):
        arr[i, : len(feats)] = feats
    return arr


def read_games(path: str) -> list[dict[str, Any]]:
    """Games from a labels file, plain or gzipped jsonl."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as f:
        return [json.loads(line) for line in f]


def encode_dataset(path: str, out: str, workers: int = 1, radius: int = RADIUS) -> int:
    """Encode a labels jsonl (optionally .gz) into a compressed npz; returns the position count."""
    games = read_games(path)
    encoder = partial(encode_game, radius=radius)
    if workers > 1:
        with Pool(workers) as pool:
            per_game = pool.map(encoder, games, chunksize=16)
    else:
        per_game = [encoder(g) for g in games]
    rows = [row for rows in per_game for row in rows]
    game_ids = [g["id"] for g, rows in zip(games, per_game, strict=True) for _ in rows]
    openings = [
        opening_key(g["moves"]) for g, rows in zip(games, per_game, strict=True) for _ in rows
    ]
    sources = [g.get("depth", 0) for g, rows in zip(games, per_game, strict=True) for _ in rows]
    # Rows follow each game's positions in ply order (`encode_game`).
    ordered = [p for g in games for p in sorted(g["positions"], key=lambda p: int(p["ply"]))]
    depths = sorted({int(d) for p in ordered for d in p.get("scores", {})})
    if any(sorted(int(d) for d in p.get("scores", {})) != depths for p in ordered):
        raise ValueError(f"{path}: positions searched at different depths")
    scores: dict[str, Any] = {
        f"score{d}": np.array([p["scores"][str(d)] or 0 for p in ordered], dtype=np.int16)
        for d in depths
    }
    meta = {
        "version": 3,
        "radius": radius,
        "levels": LEVELS,
        "num_features": geometry(radius).num_features,
        "bugs": BUGS,
        "max_pieces": MAX_PIECES,
        "source": os.path.basename(path),
        "depths": depths,
    }
    np.savez_compressed(
        out,
        own=_pad([r[0] for r in rows]),
        opp=_pad([r[1] for r in rows]),
        hand=np.array([r[2] for r in rows], dtype=np.int8).reshape(len(rows), 2 * len(BUGS)),
        score=np.array([r[3] for r in rows], dtype=np.int16),
        outcome=np.array([r[4] for r in rows], dtype=np.int8),
        ply=np.array([r[5] for r in rows], dtype=np.int16),
        game=np.array(game_ids, dtype=np.int32),
        random=np.array([r[6] for r in rows], dtype=bool),
        static=np.array([r[7] for r in rows], dtype=np.int16),
        opening=np.array(openings, dtype=np.int64),
        source=np.array(sources, dtype=np.int8),
        **scores,
        meta=np.array(json.dumps(meta)),
    )
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    """Encode a labels file; returns the process exit code."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("labels", help="jsonl or jsonl.gz written by hive-label")
    p.add_argument("--out", help="npz path (default runs/<labels stem>.npz)")
    p.add_argument("--radius", type=int, default=RADIUS, help="hex radius around the anchor queen")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    args = p.parse_args(argv)
    stem = os.path.basename(args.labels).split(".")[0]
    out = args.out or os.path.join(RUNS, stem + ".npz")
    t0 = time.perf_counter()
    n = encode_dataset(args.labels, out, args.workers, args.radius)
    size = os.path.getsize(out) / 1e6
    elapsed = time.perf_counter() - t0
    print(
        f"{n} positions (radius {args.radius}) in {elapsed:.1f}s -> {out} ({size:.1f} MB)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
