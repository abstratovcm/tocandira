# Position encoding

## Why sparse features

The evaluation has to run on CPU inside alpha beta, hundreds of thousands of times per
second. A dense hex grid CNN cannot do that per node; NNUE can: one binary feature per
piece on the board, a wide first layer that becomes a sum of embeddings over the active
features, then a tiny MLP. Chess anchors its features on the king; Hive's anchor is the
queen, the piece whose surroundings decide the game.

## Coordinates

Axial (q, r) following nokamute's grid, so the Rust side can compute identical features:
E (+1, 0), W (-1, 0), NE (0, -1), SW (0, +1), NW (-1, -1), SE (+1, +1). Hex distance is
max(|dq|, |dr|, |dq - dr|). Boards are rebuilt from UHP move strings by `tocandira.board`
(a glyph before the reference piece means NW `\`, W `-`, SW `/`; after it NE `/`, E `-`,
SE `\`; no glyph means on top; the first move lands on (0, 0)). The tracker is cross
checked against the engine's `validmoves` in the test suite.

## Features

For one perspective (a colour), the anchor is that colour's queen, else the other queen,
else (0, 0). Each piece on the board yields one feature:

    index = ((cell * 2 + colour_rel) * 8 + bug) * 4 + level

- `cell`: offset from the anchor within hex radius 12, enumerated into 469 cells. Farther
  pieces are projected onto the ring (rare; nokamute's grid had to grow to 32 for spans
  of ~15).
- `colour_rel`: 0 for the perspective owner's pieces, 1 for the opponent's.
- `bug`: index into `QABGSMLP`.
- `level`: stack height bucket 0, 1, 2, 3+.

469 × 2 × 8 × 4 = 30,016 possible features, at most 28 active (one per piece in Base+MLP).
A position is encoded from both perspectives: `own` (side to move) and `opp`, plus 16
pieces in hand counts (side to move's 8 bugs first).

## Symmetries

Hive is invariant under the 12 symmetries of the hexagon about the anchor (6 rotations,
6 reflections). `tocandira.encode.d6_tables()` gives 12 permutations of the feature
indices; applying one to `own` and `opp` is a free augmentation at training time.

## Dataset layout

`hive-encode` writes `np.savez_compressed` with `own`, `opp` (int16 [N, 28], padded with
-1), `hand` (int8 [N, 16]), `score` (int16, root negamax value from the side to move,
±32767 forced), `outcome` (int8, +1/0/-1 for the side to move), `ply` (int16), `game`
(int32), `random` (bool, an epsilon random move was played from this position) and
`meta` (JSON: version, radius, levels, num_features, bug order, source file).
