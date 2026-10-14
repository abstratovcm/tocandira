import math

from tocandira.stats import elo, sprt_bounds, sprt_llr, wilson


def test_wilson_contains_point_estimate():
    lo, hi = wilson(60, 100)
    assert lo < 0.6 < hi
    assert hi - lo < 0.25


def test_wilson_edges():
    assert wilson(0, 0) == (0.0, 1.0)
    lo, hi = wilson(100, 100)
    assert math.isclose(hi, 1.0) and lo > 0.95
    lo, hi = wilson(0, 100)
    assert math.isclose(lo, 0.0) and hi < 0.05


def test_wilson_symmetric():
    lo1, hi1 = wilson(30, 100)
    lo2, hi2 = wilson(70, 100)
    assert math.isclose(lo1, 1 - hi2) and math.isclose(hi1, 1 - lo2)


def test_elo():
    assert elo(0.5) == 0
    assert elo(0.75) > 0
    assert math.isclose(elo(0.75), -elo(0.25))
    assert math.isclose(elo(0.64), 100, rel_tol=0.02)


def test_sprt_llr_sign():
    assert sprt_llr(80, 10, 10, 0, 20) > 0
    assert sprt_llr(10, 10, 80, 0, 20) < 0
    assert sprt_llr(0, 0, 0, 0, 20) == 0
    assert sprt_llr(50, 0, 0, 0, 20) == 0  # undefined variance without both wins and losses


def test_sprt_bounds():
    lo, hi = sprt_bounds()
    assert math.isclose(lo, -hi)
    assert math.isclose(hi, math.log(0.95 / 0.05))
