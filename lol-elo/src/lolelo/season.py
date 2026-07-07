"""Season boundaries: carry the region rating over, reset the teams.

Your rule is "team Elo resets each season, region Elo carries over." Here's how
that's implemented, and the one subtlety worth deciding on.

At the end of a season, each region has a rating (the mean of its teams). We
carry that number forward. Next season, we take the region's roster, order it by
last season's final standing, and fan the teams out around the carried rating.

The subtlety is where you center that fan.

  preserve_region_mean = True  (default)
      Offsets are symmetric, e.g. for 8 teams at spacing 25:
        +87.5, +62.5, +37.5, +12.5, -12.5, -37.5, -62.5, -87.5   (sums to 0)
      Because they sum to zero, the seeded roster has the SAME mean as the
      carried rating. The region's strength genuinely carries over. This is the
      version that makes your "carries over" rule literally true.

  preserve_region_mean = False  (your original sketch)
      Offsets fan upward from the region rating as a floor, e.g.:
        +175, +150, +125, +100, +75, +50, +25, +0
      Easy to picture, but the seeded mean is now (carried + 87.5), so every
      region drifts *up* by (n-1)*spacing/2 every single season. Over ten
      seasons at spacing 25 that's +875 of pure inflation, and since it hits all
      regions equally it adds nothing but noise. Fine if you only ever compare
      within one season; avoid it if you care about cross-season comparisons.

Promotion/relegation: a team that wasn't in the league last season has no prior
standing. `seed_new_season` just uses the order you hand it, so slot newcomers
wherever your rule says (bottom seed is the usual choice) -- or override their
seed rating directly afterward.
"""

from .config import EloConfig
from .model import League


def seed_offsets(n: int, spacing: float, preserve_mean: bool = True) -> list[float]:
    """Rating offsets for n seeds, best seed first."""
    if preserve_mean:
        mid = (n - 1) / 2.0
        return [(mid - i) * spacing for i in range(n)]
    return [(n - 1 - i) * spacing for i in range(n)]


def seed_new_season(
    prev_region_rating: float, ranked_teams: list[str], config: EloConfig
) -> dict[str, float]:
    """Seed ratings for one region's next season.

    `ranked_teams` is ordered best (1st place last season) to worst.
    Returns {team: seeded_rating}.
    """
    offs = seed_offsets(len(ranked_teams), config.seed_spacing, config.preserve_region_mean)
    return {team: prev_region_rating + off for team, off in zip(ranked_teams, offs)}


def reset_for_new_season(
    league: League, new_rosters: dict[str, list[str]] | None = None
) -> League:
    """Roll a finished League forward into a fresh season.

    Carries each region's current rating, then re-seeds its teams. Pass
    `new_rosters` ({region: [team, ...]}) to change who's in each league via
    promotion/relegation; teams are seeded in the order given, and any team not
    in last season's standings keeps that given order (so put newcomers last for
    a bottom seed). If omitted, the same rosters return, ranked by final rating.

    Region merges/splits (e.g. LCS+CBLOL -> LTA in 2025, or LTA -> LCS+CBLOL in
    2026) are NOT handled automatically -- that's a modeling choice. See the
    README for the options; the simplest is to set the new region's carried
    rating yourself before calling this.
    """
    fresh = League(config=league.config)

    for region in league.regions():
        carried = league.region_rating(region)
        if new_rosters and region in new_rosters:
            ranked = _reorder_by_standing(new_rosters[region], league.standings(region))
        else:
            ranked = league.standings(region)
        for team, rating in seed_new_season(carried, ranked, league.config).items():
            fresh.register_team(team, region, rating)

    return fresh


def _reorder_by_standing(roster: list[str], last_standing: list[str]) -> list[str]:
    """Order a new roster by last season's standing; unknowns keep input order."""
    rank = {team: i for i, team in enumerate(last_standing)}
    return sorted(roster, key=lambda t: rank.get(t, len(last_standing) + roster.index(t)))
