r"""Hive board rebuilt from UHP move strings, no engine needed.

Coordinates follow nokamute's grid: axial (q, r) with E (+1, 0), W (-1, 0), NE (0, -1),
SW (0, +1), NW (-1, -1), SE (+1, +1), so hex distance is max(|dq|, |dr|, |dq - dr|).

Move strings: a glyph before the reference piece puts the moved piece to its NW (`\wA1`),
W (`-wA1`) or SW (`/wA1`); a glyph after it, to its NE (`wA1/`), E (`wA1-`) or SE (`wA1\`);
no glyph (`wB1 bQ`) means on top of it. The first move of a game is a bare piece, placed at
(0, 0). `pass` only advances the ply. Legality is not checked beyond what the notation needs.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

BUGS = "QABGSMLP"  # index order used by the encoder
Hex = tuple[int, int]
DIRS: dict[str, Hex] = {
    "E": (1, 0),
    "W": (-1, 0),
    "NE": (0, -1),
    "SW": (0, 1),
    "NW": (-1, -1),
    "SE": (1, 1),
}
ON_TOP: Hex = (0, 0)
_GLYPH_BEFORE = {"\\": DIRS["NW"], "-": DIRS["W"], "/": DIRS["SW"]}
_GLYPH_AFTER = {"/": DIRS["NE"], "-": DIRS["E"], "\\": DIRS["SE"]}
_BASE_HAND = {"Q": 1, "A": 3, "G": 3, "B": 2, "S": 2}


def hex_distance(a: Hex, b: Hex) -> int:
    """Number of steps between two hexes."""
    dq, dr = a[0] - b[0], a[1] - b[1]
    return max(abs(dq), abs(dr), abs(dq - dr))


def other(colour: str) -> str:
    """The opponent of `w` or `b`."""
    return "b" if colour == "w" else "w"


def hand_for(game_type: str) -> dict[str, int]:
    """Pieces per colour at the start: Base plus M, L, P for the expansions in `game_type`."""
    base, _, expansions = game_type.partition("+")
    if base != "Base" or any(letter not in "MLP" for letter in expansions):
        raise ValueError(f"unknown game type: {game_type!r}")
    hand = dict(_BASE_HAND)
    for letter in expansions:
        hand[letter] = 1
    return hand


def parse_move(move: str) -> tuple[str, str | None, Hex]:
    """Split a move string into (piece, reference piece, offset from the reference).

    The reference is None for a bare first move; the offset is ON_TOP for stacking.
    """
    tokens = move.split()
    if len(tokens) == 1:
        return tokens[0], None, ON_TOP
    piece, ref = tokens[0], tokens[1]
    if ref[0] in _GLYPH_BEFORE:
        return piece, ref[1:], _GLYPH_BEFORE[ref[0]]
    if ref[-1] in _GLYPH_AFTER:
        return piece, ref[:-1], _GLYPH_AFTER[ref[-1]]
    return piece, ref, ON_TOP


@dataclass
class Board:
    """Piece positions and stacks after a sequence of move strings."""

    game_type: str = "Base+MLP"
    stacks: dict[Hex, list[str]] = field(default_factory=dict)  # bottom to top
    where: dict[str, Hex] = field(default_factory=dict)
    hand: dict[str, dict[str, int]] = field(init=False)
    ply: int = 0

    def __post_init__(self) -> None:
        self.hand = {"w": hand_for(self.game_type), "b": hand_for(self.game_type)}

    @classmethod
    def replay(cls, moves: list[str], game_type: str = "Base+MLP") -> Board:
        """Board after playing `moves` from the start."""
        board = cls(game_type)
        for move in moves:
            board.apply(move)
        return board

    @property
    def to_move(self) -> str:
        """`w` on even plies, `b` on odd ones."""
        return "wb"[self.ply % 2]

    def top(self, hex: Hex) -> str | None:
        """Piece on top of the stack at `hex`, if any."""
        stack = self.stacks.get(hex)
        return stack[-1] if stack else None

    def level(self, piece: str) -> int:
        """0 for a piece on the ground, 1 for one sitting on a single piece, and so on."""
        return self.stacks[self.where[piece]].index(piece)

    def queen(self, colour: str) -> Hex | None:
        """Where that colour's queen is, if placed."""
        return self.where.get(colour + "Q")

    def pieces(self) -> Iterator[tuple[str, int, int, int]]:
        """Every piece on the board as (piece, q, r, level)."""
        for (q, r), stack in self.stacks.items():
            for level, piece in enumerate(stack):
                yield piece, q, r, level

    def apply(self, move: str) -> None:
        """Play one move string (placement, movement or `pass`)."""
        if move == "pass":
            self.ply += 1
            return
        piece, ref, offset = parse_move(move)
        if ref is None:
            if self.stacks:
                raise ValueError(f"bare move string after the first move: {move!r}")
            dest: Hex = (0, 0)
        else:
            if ref not in self.where:
                raise ValueError(f"reference piece {ref} is not on the board: {move!r}")
            rq, rr = self.where[ref]
            dest = (rq + offset[0], rr + offset[1])
        if piece in self.where:
            old = self.where[piece]
            stack = self.stacks[old]
            if stack[-1] != piece:
                raise ValueError(f"{piece} is covered and cannot move: {move!r}")
            stack.pop()
            if not stack:
                del self.stacks[old]
        else:
            colour, bug = piece[0], piece[1]
            if self.hand[colour].get(bug, 0) <= 0:
                raise ValueError(f"no {bug} left in hand for {colour}: {move!r}")
            self.hand[colour][bug] -= 1
        self.stacks.setdefault(dest, []).append(piece)
        self.where[piece] = dest
        self.ply += 1
