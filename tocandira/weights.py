"""Engine side weight files and a numpy reference of the net's forward pass.

    hive-export runs/models/c/r6-lam1-h256/weights.npz   # -> weights.bin next to it

The binary is what the Rust fork loads (`--nnue weights.bin`): "TOCA", u32 version, u32
radius, u32 num_features, u32 hidden, u32 l2, f32 scale, (version 2 only: u32 number of
strategy scalars), then little endian float32 arrays in the order ft [num_features, hidden],
hand_w [hidden, 16], hand_b [hidden], l1_w [l2, 2 * hidden + scalars], l1_b [l2],
l2_w [l2, l2], l2_b [l2], out_w [l2], out_b [1]. Nets without scalars are written as
version 1. `evaluate` reproduces the net without torch, for cross checking the engine.

Strategy scalars (the engine's `scalars` command, side to move first): bugs that can move,
pinned bugs, free hexes around the queen, immovable bugs next to the queen, placeable
hexes, queen covered; each for the side to move and the opponent. As net inputs they are
divided by `SCALAR_MAX` and clipped to 1.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

MAGIC = b"TOCA"
HEADER = "<4sIIIIIf"
NUM_SCALARS = 12
SCALAR_MAX = (14, 14, 14, 14, 6, 6, 6, 6, 24, 24, 1, 1)  # same as the engine's scalars.rs
ORDER = ("ft", "hand_w", "hand_b", "l1_w", "l1_b", "l2_w", "l2_b", "out_w", "out_b")

Array = npt.NDArray[np.float32]


@dataclass
class Weights:
    """The net's parameters plus the geometry they were trained for."""

    radius: int
    num_features: int
    hidden: int
    l2: int
    scale: float
    arrays: dict[str, Array]
    scalars: int = 0  # strategy scalars fed to the first layer: 0 or NUM_SCALARS

    def shapes(self) -> dict[str, tuple[int, ...]]:
        """Expected shape of every array, in file order."""
        h, l2 = self.hidden, self.l2
        return {
            "ft": (self.num_features, h),
            "hand_w": (h, 16),
            "hand_b": (h,),
            "l1_w": (l2, 2 * h + self.scalars),
            "l1_b": (l2,),
            "l2_w": (l2, l2),
            "l2_b": (l2,),
            "out_w": (l2,),
            "out_b": (1,),
        }


def load_npz(path: str) -> Weights:
    """Weights from `tocandira.nnue.export_weights` output."""
    with np.load(path) as d:
        arrays = {k: np.asarray(d[k], dtype=np.float32) for k in ORDER}
        arrays["out_w"] = arrays["out_w"].reshape(-1)
        ft = arrays["ft"]
        # Files from before the radius was recorded: infer it from the table size.
        radius = int(d["radius"]) if "radius" in d else _radius_for(int(ft.shape[0]))
        return Weights(
            radius=radius,
            num_features=int(ft.shape[0]),
            hidden=int(ft.shape[1]),
            l2=int(arrays["l1_w"].shape[0]),
            scale=float(d["scale"]),
            arrays=arrays,
            scalars=int(arrays["l1_w"].shape[1]) - 2 * int(ft.shape[1]),
        )


def _radius_for(num_features: int) -> int:
    for radius in range(1, 32):
        if (3 * radius * radius + 3 * radius + 1) * 64 == num_features:
            return radius
    raise ValueError(f"{num_features} features is not a radius geometry")


def write_bin(w: Weights, path: str) -> None:
    """Write the engine file."""
    for name, shape in w.shapes().items():
        if tuple(w.arrays[name].shape) != shape:
            raise ValueError(f"{name}: shape {w.arrays[name].shape}, expected {shape}")
    if w.scalars not in (0, NUM_SCALARS):
        raise ValueError(f"{w.scalars} scalars, expected 0 or {NUM_SCALARS}")
    version = 2 if w.scalars else 1
    with open(path, "wb") as f:
        f.write(
            struct.pack(HEADER, MAGIC, version, w.radius, w.num_features, w.hidden, w.l2, w.scale)
        )
        if w.scalars:
            f.write(struct.pack("<I", w.scalars))
        for name in ORDER:
            f.write(np.ascontiguousarray(w.arrays[name], dtype="<f4").tobytes())


def read_bin(path: str) -> Weights:
    """Read an engine file back (for tests and inspection)."""
    with open(path, "rb") as f:
        buf = f.read()
    magic, version, radius, num_features, hidden, l2, scale = struct.unpack_from(HEADER, buf)
    if magic != MAGIC or version not in (1, 2):
        raise ValueError(f"{path}: not a version 1 or 2 tocandira weights file")
    pos = struct.calcsize(HEADER)
    scalars = 0
    if version == 2:
        (scalars,) = struct.unpack_from("<I", buf, pos)
        pos += 4
    w = Weights(radius, num_features, hidden, l2, scale, {}, scalars)
    for name, shape in w.shapes().items():
        n = int(np.prod(shape))
        w.arrays[name] = np.frombuffer(buf, dtype="<f4", count=n, offset=pos).reshape(shape)
        pos += 4 * n
    if pos != len(buf):
        raise ValueError(f"{path}: trailing bytes")
    return w


def scalar_inputs(scalars: list[int]) -> Array:
    """Strategy scalars as the net's inputs: each divided by its SCALAR_MAX, clipped to 1."""
    return np.minimum(np.asarray(scalars, np.float32) / np.asarray(SCALAR_MAX, np.float32), 1)


def evaluate(
    w: Weights, own: list[int], opp: list[int], hand: list[int], scalars: list[int] | None = None
) -> float:
    """The net's score for the side to move, in score units (numpy reference)."""
    a = w.arrays
    h = np.asarray(hand, dtype=np.float32)
    swapped = np.concatenate([h[8:], h[:8]])

    def acc(features: list[int], hand_vec: Array) -> Array:
        total = a["ft"][features].sum(axis=0) if features else np.zeros(w.hidden, np.float32)
        return np.clip(total + a["hand_w"] @ hand_vec + a["hand_b"], 0, 1)

    x = np.concatenate([acc(own, h), acc(opp, swapped), _scalars(w, scalars, scalar_inputs)])
    x = np.clip(a["l1_w"] @ x + a["l1_b"], 0, 1)
    x = np.clip(a["l2_w"] @ x + a["l2_b"], 0, 1)
    return float((a["out_w"] @ x + a["out_b"][0]) * w.scale)


ACT_SCALE = 127
WEIGHT_SCALE = 64
WEIGHT_SHIFT = 6


def _scalars(w: Weights, scalars: list[int] | None, convert: Any) -> npt.NDArray[Any]:
    if not w.scalars:
        return np.asarray(convert([0] * NUM_SCALARS))[:0]  # empty, of the path's dtype
    if scalars is None or len(scalars) != w.scalars:
        raise ValueError(f"this net takes {w.scalars} scalars")
    return np.asarray(convert(scalars))


def _scalar_activations(scalars: list[int]) -> npt.NDArray[np.int64]:
    # The engine's scalar_input: value * 127 / max, rounded half up, clipped at 127.
    v, m = np.asarray(scalars, np.int64), np.asarray(SCALAR_MAX, np.int64)
    return np.asarray(np.minimum((v * ACT_SCALE + m // 2) // m, ACT_SCALE), dtype=np.int64)


def evaluate_quantized(
    w: Weights, own: list[int], opp: list[int], hand: list[int], scalars: list[int] | None = None
) -> float:
    """What the engine computes: int16 accumulators, int8 layer weights, same rounding.

    Rows and biases carry ACT_SCALE per unit, layer weights WEIGHT_SCALE per unit; activations
    are clipped to 0..127 and layer sums shifted back by WEIGHT_SHIFT. The output layer is f32.
    """
    a = w.arrays

    def q16(x: npt.NDArray[Any], s: float) -> npt.NDArray[np.int32]:
        return np.clip(np.rint(x.astype(np.float64) * s), -32767, 32767).astype(np.int32)

    def q8(x: npt.NDArray[Any], s: float) -> npt.NDArray[np.int32]:
        return np.clip(np.rint(x.astype(np.float64) * s), -127, 127).astype(np.int32)

    ft, hand_w, hand_b = q16(a["ft"], ACT_SCALE), a["hand_w"], q16(a["hand_b"], ACT_SCALE)
    counts = np.asarray(hand, dtype=np.int64)
    swapped = np.concatenate([counts[8:], counts[:8]])

    def acc(features: list[int], hand_vec: npt.NDArray[np.int64]) -> npt.NDArray[np.int32]:
        total = hand_b.copy()
        for f in features:
            total = total + ft[f]
        for slot in range(16):
            total = total + q16(hand_w[:, slot] * min(int(hand_vec[slot]), 3), ACT_SCALE)
        return np.clip(total, 0, ACT_SCALE)

    x = np.concatenate(
        [acc(own, counts), acc(opp, swapped), _scalars(w, scalars, _scalar_activations)]
    )
    l1 = q8(a["l1_w"], WEIGHT_SCALE) @ x + q16(a["l1_b"], ACT_SCALE * WEIGHT_SCALE)
    x = np.clip(l1 >> WEIGHT_SHIFT, 0, ACT_SCALE)
    l2 = q8(a["l2_w"], WEIGHT_SCALE) @ x + q16(a["l2_b"], ACT_SCALE * WEIGHT_SCALE)
    y = np.clip(l2 >> WEIGHT_SHIFT, 0, ACT_SCALE).astype(np.float32) / ACT_SCALE
    return float((a["out_w"] @ y + a["out_b"][0]) * w.scale)


def main(argv: list[str] | None = None) -> int:
    """Convert a weights.npz into the engine's binary format."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("npz", help="weights.npz written by training")
    p.add_argument("--out", help="output path (default: weights.bin next to the npz)")
    args = p.parse_args(argv)
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.npz)), "weights.bin")
    w = load_npz(args.npz)
    write_bin(w, out)
    size = os.path.getsize(out) / 1e6
    print(
        f"radius {w.radius}, {w.num_features} features, hidden {w.hidden}, {w.scalars} scalars"
        f" -> {out} ({size:.1f} MB)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
