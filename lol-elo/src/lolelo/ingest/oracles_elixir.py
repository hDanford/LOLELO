"""Adapter for Oracle's Elixir match data.

Oracle's Elixir publishes one CSV per year (2014 -> present), updated daily,
from https://oracleselixir.com/tools/downloads . Each *game* is 12 rows: 5
players + 1 team-summary row per side. We only need the team-summary rows
(`position == "team"`), two per game, to know who played and who won.

Relevant columns we use: gameid, league, year, split, date, playoffs,
teamname, result, position.

IMPORTANT -- verify before trusting: the exact `league` codes for international
events change as Riot restructures. Historically domestic leagues appear as
"LCK", "LPL", "LEC", "LCS", "CBLOL", etc., and international events under codes
like "MSI" and "WLDs"/"Worlds". Newer events (e.g. "First Stand") and the
2025-only "LTA N"/"LTA S" conference codes may differ from what's below. Print
`df['league'].unique()` on your actual file and adjust INTERNATIONAL_LEAGUES.

This module is written against the documented schema; the demo uses synthetic
data so nothing here needs a network connection to try the engine out.
"""

from __future__ import annotations

from ..model import Match

# League codes that represent cross-region (international) events. Extend/adjust
# after inspecting your CSV -- see the note above.
INTERNATIONAL_LEAGUES = {"MSI", "WLDs", "Worlds", "WCS", "First Stand", "FST", "IEM"}


def _tier(league_code: str) -> str:
    return "international" if league_code in INTERNATIONAL_LEAGUES else "regional"


def build_team_region_map(df) -> dict[str, str]:
    """Learn each team's home region from its domestic (non-international) games.

    International events list teams but not their region, so we infer region from
    where a team plays its domestic games. If a team appears in more than one
    domestic league across the file, the most frequent one wins.
    """
    from collections import Counter

    team_leagues: dict[str, Counter] = {}
    domestic = df[~df["league"].isin(INTERNATIONAL_LEAGUES)]
    for team, league in zip(domestic["teamname"], domestic["league"]):
        team_leagues.setdefault(team, Counter())[league] += 1
    return {team: counts.most_common(1)[0][0] for team, counts in team_leagues.items()}


def load_matches(csv_path: str, leagues: set[str] | None = None) -> list[Match]:
    """Read a season CSV into an ordered list of series-level Match objects.

    `leagues` optionally restricts to specific domestic leagues (international
    events involving those teams are included automatically). Matches are sorted
    by date so they can be fed to League.process_all in chronological order.

    Requires pandas (`pip install pandas`).
    """
    import pandas as pd

    df = pd.read_csv(csv_path)
    df = df[df["position"] == "team"].copy()  # 2 rows per game
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    region_of = build_team_region_map(df)

    matches: list[Match] = []
    for gameid, rows in df.groupby("gameid"):
        if len(rows) != 2:
            continue  # skip malformed/incomplete games
        rows = rows.sort_values("side")  # Blue, Red
        a, b = rows.iloc[0], rows.iloc[1]

        if leagues is not None:
            in_scope = region_of.get(a["teamname"]) in leagues or (
                region_of.get(b["teamname"]) in leagues
            )
            if not in_scope:
                continue

        winner = a["teamname"] if a["result"] == 1 else b["teamname"]
        matches.append(
            Match(
                team_a=a["teamname"],
                team_b=b["teamname"],
                winner=winner,
                tier=_tier(a["league"]),
                date=str(a["date"].date()) if not pd.isna(a["date"]) else None,
            )
        )

    matches.sort(key=lambda m: (m.date or ""))
    return matches, region_of
