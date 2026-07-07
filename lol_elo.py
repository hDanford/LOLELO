"""
lol_elo.py  --  Season-by-season Elo for League of Legends esports, in one file.

WHAT IT DOES
  * Loads real historical match data (Oracle's Elixir, 2014 -> now), auto-
    downloading when possible, and rates TIER-1 LEAGUES ONLY (with year windows
    so e.g. LJL/VCS/PCS stop counting once they became tier-2 under the LCP).
  * Rates SERIES, not individual games: a Bo5 is one update, and the score
    matters -- a 3-0 sweep swings ratings more than a 3-2 (margin weighting).
  * Two-tier Elo: team ratings reset each season, region ratings carry over,
    and region ratings only move at international events. International K is
    staged: each event has its own weight, knockout series weigh extra, and
    regions with little international history get a provisional K boost so
    they converge to their true level quickly instead of hugging 1500.
  * New regions born from mergers (LCP 2025) inherit the average Elo of their
    actual incoming teams. Defunct teams are dropped; new teams enter at the
    bottom-quartile seed of their league.
  * Reports region strength and top 20 teams for EVERY year, writes CSVs, and
    draws two charts.

HOW TO RUN
  1. pip install pandas matplotlib
  2. python lol_elo.py

DATA CREDIT
  Match data aggregated and freely provided by Tim "Magic" Sevenhuysen of
  Oracle's Elixir (oracleselixir.com). Not endorsed by Riot Games.
"""

import datetime
import os
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from statistics import mean

import pandas as pd

# ============================================================================
#  CONFIG  --  edit these, then re-run.
# ============================================================================

FIRST_YEAR = 2014
LAST_YEAR = 2026
DATA_DIR = "data"

# --- WHICH LEAGUES COUNT ----------------------------------------------------
# league code -> (region it counts toward, first tier-1 year, last tier-1 year)
# None = open bound. Games outside the window are ignored; leagues not listed
# at all (tier-2, academy, college, cups) are ignored completely.
LEAGUE_TO_REGION = {
    "LCK":    ("LCK",   None, None),
    "OGN":    ("LCK",   None, None),    # pre-2015 name of the LCK
    "LPL":    ("LPL",   None, None),
    "LEC":    ("LEC",   None, None),
    "EU LCS": ("LEC",   None, None),
    "LCS":    ("LCS",   None, None),
    "NA LCS": ("LCS",   None, None),
    "LTA N":  ("LCS",   2025, 2025),    # 2025 conference continuing the LCS line
    "CBLOL":  ("CBLOL", None, None),
    "LTA S":  ("CBLOL", 2025, 2025),
    "LCP":    ("LCP",   2025, None),    # merged APAC league
    "PCS":    ("PCS",   2020, 2024),    # tier-2 feeder after 2024
    "LMS":    ("LMS",   None, 2019),
    "VCS":    ("VCS",   None, 2024),    # tier-2 feeder after 2024
    "LJL":    ("LJL",   None, 2024),    # tier-2 feeder after 2024
}

# --- INTERNATIONAL EVENTS & STAGE WEIGHTS ------------------------------------
# Each international event gets its OWN base K -- Worlds moves ratings the
# most, minor events the least. Only games where both teams belong to a mapped
# tier-1 region are rated. Remove an event to stop counting it entirely.
INTERNATIONAL_K = {
    "WLDs": 44.0,   # World Championship
    "MSI":  36.0,   # Mid-Season Invitational
    "FST":  28.0,   # First Stand (2025-)
    "MSC":  28.0,   # Mid-Season Cup (2020)
    "EWC":  24.0,   # Esports World Cup (2024-)
    "IEM":  20.0,   # IEM Katowice era events
}
PLAYOFF_MULT = 1.25   # knockout/bracket series at internationals weigh this much
                      # extra (uses the data's `playoffs` flag)

# Provisional boost: while a REGION has played few career international
# series, its cross-region K is multiplied by up to PROVISIONAL_BOOST,
# decaying linearly to 1.0 by PROVISIONAL_SERIES. This is what lets a region
# with only a couple of international series per year (hi, CBLOL) fall/rise
# to its true level quickly instead of hovering near its 1500 starting point.
PROVISIONAL_SERIES = 40
PROVISIONAL_BOOST = 2.0

# --- SERIES & MARGIN ----------------------------------------------------------
# Games between the same two teams in the same league on the same day are one
# series, rated once. The margin multiplier scales the update by how lopsided
# the series was:  mult = MARGIN_MIN + (1 - MARGIN_MIN) * (W - L) / W
#   3-0 -> 1.00      3-1 -> 0.80      3-2 -> 0.60      (with MARGIN_MIN = 0.4)
#   2-0 -> 1.00      2-1 -> 0.70      1-0 -> 1.00 (a Bo1 is all the info we get)
MARGIN_MIN = 0.4

# --- Elo knobs ------------------------------------------------------------------
INITIAL_RATING = 1500.0
K_REGIONAL = 28.0            # per domestic SERIES (series are rarer than games,
                             # so this sits a bit above the old per-game 24)
SEED_SPACING = 25.0
PRESERVE_REGION_MEAN = True
NEW_TEAM_QUANTILE = 0.25
TOP_N = 20

# ============================================================================
#  MACHINERY  --  you usually don't need to edit below here.
# ============================================================================

OE_BUCKET = "https://oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com"
_UA = {"User-Agent": "Mozilla/5.0 (lol-elo)"}
NEEDED_COLS = ["gameid", "league", "year", "date", "side", "position",
               "teamname", "result", "playoffs"]


def region_for(league, year):
    if league not in LEAGUE_TO_REGION:
        return None
    region, first, last = LEAGUE_TO_REGION[league]
    if first is not None and year < first:
        return None
    if last is not None and year > last:
        return None
    return region


# ---- data download -----------------------------------------------------------

def _candidate_urls(year):
    yield f"{OE_BUCKET}/{year}_LoL_esports_match_data_from_OraclesElixir.csv"
    today = datetime.date.today()
    for d in range(0, 14):
        stamp = (today - datetime.timedelta(days=d)).strftime("%Y%m%d")
        yield f"{OE_BUCKET}/{year}_LoL_esports_match_data_from_OraclesElixir_{stamp}.csv"


def download_year(year):
    os.makedirs(DATA_DIR, exist_ok=True)
    dest = os.path.join(DATA_DIR, f"{year}.csv")
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return dest
    for url in _candidate_urls(year):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = resp.read()
            with open(dest, "wb") as f:
                f.write(data)
            print(f"  downloaded {year}")
            return dest
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            continue
    print(f"  !! couldn't auto-download {year}. Get it from")
    print(f"     https://oracleselixir.com/tools/downloads  and save it as  {dest}")
    return None


def load_year(year):
    path = os.path.join(DATA_DIR, f"{year}.csv")
    if not (os.path.exists(path) and os.path.getsize(path) > 1000):
        path = download_year(year)
    if not path:
        return None
    df = pd.read_csv(path, low_memory=False)
    df = df[[c for c in NEEDED_COLS if c in df.columns]]
    df = df[df["position"] == "team"]
    df = df.dropna(subset=["teamname", "result", "gameid"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "playoffs" not in df.columns:
        df["playoffs"] = 0
    return df


# ---- Elo math -------------------------------------------------------------------

def expected(a, b):
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def margin_mult(w, l):
    """Update multiplier from series score: sweeps full weight, close ones less."""
    if w <= 0:
        return MARGIN_MIN
    return MARGIN_MIN + (1.0 - MARGIN_MIN) * (w - l) / w


def seed_fan(n, center):
    if PRESERVE_REGION_MEAN:
        mid = (n - 1) / 2.0
        return [center + (mid - i) * SEED_SPACING for i in range(n)]
    return [center + (n - 1 - i) * SEED_SPACING for i in range(n)]


def build_series(df):
    """Fold this year's games into series: same league + same day + same two
    teams = one series. Returns rows sorted by date. (Rare quirk: a same-day
    tiebreaker vs the same opponent merges into that day's series.)"""
    agg = {}
    for gid, rows in df.groupby("gameid"):
        if len(rows) != 2:
            continue
        rows = rows.sort_values("side")
        a, b = rows.iloc[0], rows.iloc[1]
        day = a["date"].date() if not pd.isna(a["date"]) else None
        t1, t2 = sorted([a["teamname"], b["teamname"]])
        key = (a["league"], day, t1, t2)
        s = agg.setdefault(key, {"league": a["league"], "date": a["date"],
                                 "team_a": t1, "team_b": t2,
                                 "wins_a": 0, "wins_b": 0, "playoffs": False})
        winner = a["teamname"] if a["result"] == 1 else b["teamname"]
        s["wins_a" if winner == t1 else "wins_b"] += 1
        try:
            s["playoffs"] = s["playoffs"] or int(a.get("playoffs", 0) or 0) == 1
        except (TypeError, ValueError):
            pass
        if not pd.isna(a["date"]) and (pd.isna(s["date"]) or a["date"] < s["date"]):
            s["date"] = a["date"]
    out = list(agg.values())
    out.sort(key=lambda s: (pd.isna(s["date"]), s["date"]))
    return out


# ---- the season-by-season run ------------------------------------------------------

def run():
    years = list(range(FIRST_YEAR, LAST_YEAR + 1))
    print(f"Loading match data for {FIRST_YEAR}-{LAST_YEAR} ...")
    per_year = {}
    for y in years:
        df = load_year(y)
        if df is not None and len(df):
            per_year[y] = df
    if not per_year:
        print("\nNo data loaded. Download at least one year's CSV into the data/ folder.")
        return

    all_leagues = sorted({lg for df in per_year.values() for lg in df["league"].dropna().unique()})
    print("\nLeagues found in the data:")
    print("  " + ", ".join(all_leagues))

    team_rating = {}
    carried_region = {}
    prev_end = {}
    intl_series_count = defaultdict(int)   # region -> career rated intl series
    region_history = []
    series_history = []
    yearly_top = {}

    def provisional(reg):
        n = intl_series_count[reg]
        frac = max(0.0, 1.0 - n / PROVISIONAL_SERIES)
        return 1.0 + (PROVISIONAL_BOOST - 1.0) * frac

    for y in sorted(per_year):
        df = per_year[y]

        counts = defaultdict(Counter)
        for team, lg in zip(df["teamname"], df["league"]):
            reg = region_for(lg, y)
            if reg:
                counts[team][reg] += 1
        team_region_y = {t: c.most_common(1)[0][0] for t, c in counts.items()}

        roster = defaultdict(list)
        for team, reg in team_region_y.items():
            roster[reg].append(team)

        # --- SEASON RESET ------------------------------------------------------
        for reg, teams in roster.items():
            carried = carried_region.get(reg)
            if carried is None:                       # region debut (e.g. LCP 2025):
                incoming = [prev_end[t] for t in teams if t in prev_end]
                carried = mean(incoming) if incoming else INITIAL_RATING
                carried_region[reg] = carried
            returning = sorted((t for t in teams if t in prev_end),
                               key=lambda t: prev_end[t], reverse=True)
            newcomers = [t for t in teams if t not in prev_end]
            if not returning:
                for t in teams:
                    team_rating[t] = carried
                continue
            fan = seed_fan(len(teams), carried)
            for t, r in zip(returning, fan):
                team_rating[t] = r
            q_idx = round((1.0 - NEW_TEAM_QUANTILE) * (len(teams) - 1))
            for t in newcomers:
                team_rating[t] = fan[q_idx]

        active = set(team_region_y)
        team_rating = {t: r for t, r in team_rating.items() if t in active}

        # --- PLAY the year's SERIES in date order --------------------------------
        for s in build_series(df):
            league, ta, tb = s["league"], s["team_a"], s["team_b"]
            wa, wb = s["wins_a"], s["wins_b"]
            if region_for(league, y):                                # tier-1 domestic
                cross = False
                k = K_REGIONAL
            elif league in INTERNATIONAL_K:                          # international
                ra, rb = team_region_y.get(ta), team_region_y.get(tb)
                if ra is None or rb is None:                         # unmapped guest
                    continue
                cross = ra != rb
                k = INTERNATIONAL_K[league]
                if s["playoffs"]:
                    k *= PLAYOFF_MULT
                if cross:
                    k *= (provisional(ra) + provisional(rb)) / 2.0
                    intl_series_count[ra] += 1
                    intl_series_count[rb] += 1
            else:
                continue                                             # everything else

            if wa == wb:                        # rare data oddity: treat as a draw
                score_a, mult = 0.5, MARGIN_MIN
            else:
                score_a = 1.0 if wa > wb else 0.0
                mult = margin_mult(max(wa, wb), min(wa, wb))

            k_eff = k * mult
            before_a, before_b = team_rating[ta], team_rating[tb]
            delta = k_eff * (score_a - expected(before_a, before_b))
            team_rating[ta] = before_a + delta
            team_rating[tb] = before_b - delta
            series_history.append({
                "year": y, "date": s["date"].date() if not pd.isna(s["date"]) else None,
                "league": league, "playoffs": s["playoffs"], "cross_region": cross,
                "team_a": ta, "team_b": tb, "score": f"{wa}-{wb}",
                "k_eff": round(k_eff, 2),
                "a_before": round(before_a, 1), "a_after": round(team_rating[ta], 1),
                "b_before": round(before_b, 1), "b_after": round(team_rating[tb], 1),
            })

        # --- END OF SEASON ---------------------------------------------------------
        for reg, teams in roster.items():
            r = mean(team_rating[t] for t in teams)
            carried_region[reg] = r
            region_history.append({"year": y, "region": reg,
                                   "rating": round(r, 1), "teams": len(teams)})
        yearly_top[y] = sorted(((t, team_rating[t], team_region_y[t]) for t in active),
                               key=lambda x: x[1], reverse=True)
        prev_end = dict(team_rating)

    _report(region_history, series_history, yearly_top)


def _report(region_history, series_history, yearly_top):
    reg_df = pd.DataFrame(region_history)

    for y in sorted(yearly_top):
        print(f"\n{'='*24}  {y}  {'='*24}")
        yr = reg_df[reg_df["year"] == y].sort_values("rating", ascending=False)
        print("Region strength: " + " | ".join(
            f"{r.region} {r.rating:.0f}" for r in yr.itertuples()))
        print(f"Top {TOP_N} teams:")
        for i, (team, rating, reg) in enumerate(yearly_top[y][:TOP_N], 1):
            print(f"  {i:>2}. {team:<28} {rating:7.1f}  ({reg})")

    reg_df.to_csv("region_ratings_by_year.csv", index=False)
    pd.DataFrame(series_history).to_csv("series_history.csv", index=False)
    team_rows = [{"year": y, "rank": i, "team": t, "region": reg, "rating": round(r, 1)}
                 for y in sorted(yearly_top)
                 for i, (t, r, reg) in enumerate(yearly_top[y], 1)]
    pd.DataFrame(team_rows).to_csv("team_ratings_by_year.csv", index=False)
    print("\nWrote region_ratings_by_year.csv, team_ratings_by_year.csv, series_history.csv")

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("(install matplotlib for the charts)")
        return

    fig, ax = plt.subplots(figsize=(11, 6))
    for reg in sorted(reg_df["region"].unique()):
        sub = reg_df[reg_df["region"] == reg]
        ax.plot(sub["year"], sub["rating"], marker="o", label=reg)
    ax.set_title("Region Elo over time (tier-1 only)")
    ax.set_xlabel("Year"); ax.set_ylabel("Region Elo (mean of teams)")
    ax.legend(); fig.tight_layout()
    fig.savefig("region_ratings.png", dpi=130)

    last = max(yearly_top)
    focus = [t for t, _, _ in yearly_top[last][:TOP_N]]
    series = {t: {} for t in focus}
    for y, rows in yearly_top.items():
        for t, r, _ in rows:
            if t in series:
                series[t][y] = r
    fig, ax = plt.subplots(figsize=(13, 7))
    cmap = plt.get_cmap("tab20")
    for i, t in enumerate(focus):
        yrs = sorted(series[t])
        ax.plot(yrs, [series[t][y] for y in yrs], marker="o", ms=3,
                color=cmap(i % 20), label=t)
    ax.set_title(f"Top {TOP_N} teams of {last}: Elo over the years")
    ax.set_xlabel("Year"); ax.set_ylabel("End-of-season Elo")
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize=8)
    fig.tight_layout()
    fig.savefig("top_teams.png", dpi=130)
    print("Wrote region_ratings.png and top_teams.png")


if __name__ == "__main__":
    run()
