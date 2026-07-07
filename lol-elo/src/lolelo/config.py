"""Tunable knobs for the Elo model.

Everything you might want to experiment with lives here so the engine itself
stays clean. Defaults are reasonable starting points, not gospel -- Elo tuning
is empirical, so expect to sweep K and the seed spacing once you have real data.
"""

from dataclasses import dataclass


@dataclass
class EloConfig:
    # Rating every region starts at in the very first modeled season, before any
    # history exists. Arbitrary (Elo is relative); 1500 is the classic anchor.
    initial_region_rating: float = 1500.0

    # K-factor controls how much a single result moves ratings. Higher = more
    # reactive/volatile, lower = more inertia. International games are the ONLY
    # signal that separates regions from each other, so they're weighted more.
    k_regional: float = 24.0
    k_international: float = 40.0

    # Points between adjacent seeds at the start of a season. With 8 teams and
    # spacing 25 you get a 175-point spread from 1st to 8th seed.
    seed_spacing: float = 25.0

    # Seeding mode -- see season.py for the full explanation.
    #   True  -> seeds are symmetric around the carried region rating (sum of
    #            offsets = 0), so the region's strength carries over *exactly*.
    #   False -> seeds fan upward from the region rating as a floor (this is the
    #            scheme in your original sketch). Simpler to picture, but it
    #            quietly inflates every region by (n-1)*spacing/2 each season.
    preserve_region_mean: bool = True

    def k_for(self, tier: str) -> float:
        """K-factor for a match given its tier ('regional' or 'international')."""
        return self.k_international if tier == "international" else self.k_regional
