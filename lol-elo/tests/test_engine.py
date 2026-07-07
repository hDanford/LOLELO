"""Sanity checks for the core properties. Run: python -m pytest (or python tests/test_engine.py)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lolelo import EloConfig, League, Match, expected_score, seed_offsets, updated_ratings


def test_expected_score_symmetry():
    assert abs(expected_score(1500, 1500) - 0.5) < 1e-9
    assert abs(expected_score(1600, 1500) + expected_score(1500, 1600) - 1.0) < 1e-9


def test_update_is_zero_sum():
    a, b = updated_ratings(1500, 1500, 1.0, 32)
    assert abs((a - 1500) + (b - 1500)) < 1e-9  # A's gain == B's loss


def test_seed_offsets_preserve_mean_sum_to_zero():
    offs = seed_offsets(8, 25, preserve_mean=True)
    assert abs(sum(offs)) < 1e-9
    assert offs[0] > offs[-1]  # best seed rated highest


def test_seed_offsets_upward_fan_inflates():
    offs = seed_offsets(8, 25, preserve_mean=False)
    assert sum(offs) > 0  # this mode injects points every season


def test_intra_region_conserves_region_rating():
    league = League(EloConfig())
    for i, r in enumerate([1550, 1500, 1450, 1400]):
        league.register_team(f"T{i}", "LCK", r)
    before = league.region_rating("LCK")
    league.process_all([Match("T0", "T3", "T3"), Match("T1", "T2", "T1")])
    assert abs(league.region_rating("LCK") - before) < 1e-9


def test_cross_region_moves_region_ratings():
    league = League(EloConfig())
    league.register_team("A", "LCK", 1500)
    league.register_team("B", "LEC", 1500)
    lck_before, lec_before = league.region_rating("LCK"), league.region_rating("LEC")
    league.process_match(Match("A", "B", "A", tier="international"))
    assert league.region_rating("LCK") > lck_before
    assert league.region_rating("LEC") < lec_before


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all passed")
