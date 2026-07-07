"""The two-tier state: individual team ratings, with region ratings derived.

The key design decision: a region's rating is NOT tracked as a separate number.
It's *defined* as the mean rating of that region's teams, computed on demand.
That one choice gives you the whole spec for free:

  * Intra-region game  -> zero-sum, so the region mean is unchanged. This is
    exactly "region-wide Elo doesn't move during the domestic season."
  * Cross-region game   -> one team (region X) gains, the other (region Y) loses,
    so X's mean rises and Y's falls. This is exactly "the region rating changes
    only at international events."

No special-casing needed. The only place regions are handled explicitly is the
season reset (season.py), where you re-seed teams around the carried mean.
"""

from dataclasses import dataclass, field
from statistics import mean

from .config import EloConfig
from .engine import updated_ratings


@dataclass
class Match:
    """One decided contest between two teams.

    By default this represents a whole series (one Elo update per series). To
    rate per game instead, just feed each game in as its own Match.
    """

    team_a: str
    team_b: str
    winner: str  # must equal team_a or team_b
    tier: str = "regional"  # "regional" or "international"
    date: str | None = None
    k_override: float | None = None  # bypass config K for this match

    def __post_init__(self) -> None:
        if self.winner not in (self.team_a, self.team_b):
            raise ValueError(
                f"winner {self.winner!r} must be {self.team_a!r} or {self.team_b!r}"
            )


@dataclass
class League:
    config: EloConfig = field(default_factory=EloConfig)
    ratings: dict[str, float] = field(default_factory=dict)  # team -> rating
    team_region: dict[str, str] = field(default_factory=dict)  # team -> region
    history: list[dict] = field(default_factory=list)  # per-match change log

    # --- setup -----------------------------------------------------------
    def register_team(self, team: str, region: str, rating: float) -> None:
        self.ratings[team] = rating
        self.team_region[team] = region

    # --- derived views ---------------------------------------------------
    def regions(self) -> list[str]:
        return sorted(set(self.team_region.values()))

    def teams_in(self, region: str) -> list[str]:
        return [t for t, r in self.team_region.items() if r == region]

    def region_rating(self, region: str) -> float:
        """A region's strength = the mean rating of its current teams."""
        members = [self.ratings[t] for t in self.teams_in(region)]
        return mean(members) if members else float("nan")

    def standings(self, region: str) -> list[str]:
        """Teams in a region, best-rated first (for next-season seeding)."""
        return sorted(self.teams_in(region), key=lambda t: self.ratings[t], reverse=True)

    # --- the loop --------------------------------------------------------
    def process_match(self, m: Match) -> None:
        ra, rb = self.ratings[m.team_a], self.ratings[m.team_b]
        score_a = 1.0 if m.winner == m.team_a else 0.0
        k = m.k_override if m.k_override is not None else self.config.k_for(m.tier)
        new_a, new_b = updated_ratings(ra, rb, score_a, k)
        self.ratings[m.team_a], self.ratings[m.team_b] = new_a, new_b

        self.history.append(
            {
                "date": m.date,
                "tier": m.tier,
                "cross_region": self.team_region[m.team_a] != self.team_region[m.team_b],
                "team_a": m.team_a,
                "team_b": m.team_b,
                "winner": m.winner,
                "a_before": round(ra, 2),
                "a_after": round(new_a, 2),
                "b_before": round(rb, 2),
                "b_after": round(new_b, 2),
            }
        )

    def process_all(self, matches: list[Match]) -> None:
        for m in matches:
            self.process_match(m)
