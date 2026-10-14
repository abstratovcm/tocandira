"""Match statistics: Wilson interval, Elo difference, SPRT."""

from __future__ import annotations

import math


def wilson(score: float, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% interval for a proportion (draws count as half a win)."""
    if n == 0:
        return 0.0, 1.0
    p = score / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def elo(p: float) -> float:
    """Elo difference implied by a score fraction `p` (clamped away from 0 and 1)."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -400 * math.log10(1 / p - 1)


def sprt_llr(wins: int, draws: int, losses: int, elo0: float, elo1: float) -> float:
    """Log likelihood ratio of H1 (elo1) vs H0 (elo0), cutechess style trinomial approximation."""
    n = wins + draws + losses
    if n == 0 or wins == 0 or losses == 0:
        return 0.0
    pw, pd = wins / n, draws / n
    s = pw + pd / 2
    var = (pw + pd / 4) - s * s
    if var <= 0:
        return 0.0
    s0 = 1 / (1 + 10 ** (-elo0 / 400))
    s1 = 1 / (1 + 10 ** (-elo1 / 400))
    return (s1 - s0) * (2 * s - s0 - s1) / (2 * var / n)


def sprt_bounds(alpha: float = 0.05, beta: float = 0.05) -> tuple[float, float]:
    """(lower, upper) LLR thresholds: below accepts H0, above accepts H1."""
    return math.log(beta / (1 - alpha)), math.log((1 - beta) / alpha)


def summary(wins: int, draws: int, losses: int) -> str:
    """One line with W/D/L, score with its interval and the implied Elo."""
    n = wins + draws + losses
    if n == 0:
        return "no games"
    score = wins + draws / 2
    lo, hi = wilson(score, n)
    p = score / n
    return (
        f"W{wins} D{draws} L{losses} ({n} games)  score {100 * p:.1f}% "
        f"[{100 * lo:.1f}, {100 * hi:.1f}]  elo {elo(p):+.0f} [{elo(lo):+.0f}, {elo(hi):+.0f}]"
    )
