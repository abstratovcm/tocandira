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

The radius is a parameter (`hive-encode --radius`, `tocandira.encode.geometry(r)`):

| radius | cells | features | pieces covered (round 2 data) |
|---|---|---|---|
| 6 | 127 | 8,128 | 93.6% |
| 8 | 217 | 13,888 | 99.0% |
| 12 | 469 | 30,016 | 99.9% |

At radius 12 only 9,365 features ever fired in 2.3M positions. At most 28 features are
active per perspective (one per piece in Base+MLP). A position is encoded from both
perspectives: `own` (side to move) and `opp`, plus 16 pieces in hand counts (side to
move's 8 bugs first).

## Possible next inputs

What strong players attend to, per Ingersoll's *Play Hive Like a Champion* (three keys:
mobility, tempo, strength; formations gate, door, ring, elbow, pocket; tactics pin, cover,
block, fill, bug counting) and the KTH strategy comparison (defensive circling beats a
naive attack): counts of movable bugs per side, pinned bugs, free hexes around each queen,
placeable hexes per side, a beetle on or next to a queen. The queen relative features see
the geometry of these; mobility needs move generation, so these would be a few dense
scalars emitted by the engine at labeling time, an experiment arm after the first match.

## Symmetries

Hive is invariant under the 12 symmetries of the hexagon about the anchor (6 rotations,
6 reflections). `tocandira.encode.geometry(r).d6_tables()` gives 12 permutations of the feature
indices; applying one to `own` and `opp` is a free augmentation at training time.

## Dataset layout

`hive-encode` writes `np.savez_compressed` with `own`, `opp` (int16 [N, 28], padded with
-1), `hand` (int8 [N, 16]), `score` (int16, root negamax value from the side to move,
±32767 forced), `static` (int16, nokamute's hand tuned evaluation of the same position,
the baseline a learned evaluation has to beat), `outcome` (int8, +1/0/-1 for the side to
move), `ply` (int16), `game` (int32), `random` (bool, an epsilon random move was played
from this position), `opening` (int64, hash of the game's first 4 moves), `source` (int8,
the depth the game was played at, 0 if not recorded) and `meta` (JSON: version, radius,
levels, num_features, bug order, source file, depths).

Version 3 adds, for relabeled games (`hive-label --relabel`), one int16 array per searched
depth: `score3`, `score4`, `score5`. These labels are a function of the position only: a
fresh engine (one thread, 16 MiB table, root moves in an order seeded by the position)
searches each position at each depth, so the same position always gets the same score.
The trainer's `target` picks one depth (`"d5"`) or the mean of several in win probability
space (`"d45"`); holding out by `opening` keeps the depth 4 and depth 5 games that share an
opening (same seeds) on the same side of the split.
