"""lolelo -- a two-tier Elo system for League of Legends esports.

Team ratings reset each season; region ratings carry over. Region strength is
derived as the mean of a region's teams, so intra-region games leave it fixed
and only international games move it. See model.py and season.py for the why.
"""

from .config import EloConfig
from .engine import expected_score, updated_ratings
from .model import League, Match
from .season import reset_for_new_season, seed_new_season, seed_offsets

__all__ = [
    "EloConfig",
    "expected_score",
    "updated_ratings",
    "League",
    "Match",
    "reset_for_new_season",
    "seed_new_season",
    "seed_offsets",
]
