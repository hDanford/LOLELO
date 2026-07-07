"""
lol_elo.py  --  Season-by-season Elo for League of Legends esports, in one file.

WHAT IT DOES
  * Downloads real historical match data (Oracle's Elixir, 2014 -> now).
  * Runs a two-tier Elo: team ratings reset each season, region ratings carry
    over, and a region's rating only moves when its teams play internationally.
  * Prints final standings and writes CSVs (+ a chart if matplotlib is around).

HOW TO RUN
  1. pip install pandas          (matplotlib is optional, for the chart)
  2. python lol_elo.py
  The first run downloads the data into a local `data/` folder (a few minutes,
  once). Later runs reuse it. Works locally, in a GitHub Codespace, or pasted
  into a Google Colab cell.

EDITING
  Everything you'd want to change is in the CONFIG block right below. Change a
  number, save, re-run. You rarely need to touch anything under the "MACHINERY"
  divider further down.

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

FIRST_YEAR = 2014          # earliest year of data to include (2014 = earliest available)
LAST_YEAR = 2026           # latest year; the current year's file updates daily
DATA_DIR = "data"          # where downloaded CSVs are cached

# Which domestic leagues to include. None = every league found in the files.
# For a clean run focused on the big regions, uncomment the set below and make
# the codes match what gets printed under "Leagues found in the data:" -- Oracle's
# Elixir's exact spellings can differ (e.g. "LTA N" vs "LTA North"), so copy them
# from that printout rather than trusting these guesses.
LEAGUES = None
# LEAGUES = {"LCK", "LPL", "LEC", "LCS", "CBLOL", "LCP", "PCS", "LMS", "LTA N", "LTA S"}

# League codes that are INTERNATIONAL (cross-region) events. These are the only
# games that move a region's rating. Add any the printout shows you're missing.
INTERNATIONAL = {"WLDs", "Worlds", "MSI", "First Stand", "FST", "IEM", "WCS", "Rift Rivals"}

# Stitch renamed / merged leagues together so a region's history stays continuous.
# (In 2025 the Americas ran as "LTA North/South", continuing the LCS/CBLOL lines.)
# Left side = code in the data, right side = the region name you want it counted as.
REGION_ALIASES = {"LTA N": "LCS", "LTA S": "CBLOL"}

# --- Elo knobs -------------------------------------------------------------
INITIAL_RATING = 1500.0        # every region starts here in the first year
K_REGIONAL = 24.0              # how much a domestic game moves ratings
K_INTERNATIONAL = 40.0        # international games weigh more (only cross-region signal)
SEED_SPACING = 25.0           # rating gap between adjacent seeds at season start
PRESERVE_REGION_MEAN = True   # True: region strength carries over exactly (recommended)
                              # False: fan seeds upward from the region rating (inflates
                              #        every region a little each season -- your first sketch)

# ============================================================================
#  MACHINERY  --  you usually don't need to edit below here.
# ============================================================================

OE_BUCKET = "https://oracleselixir-downloadable-match-data.s3-us-west-2.amazonaws.com"
_UA = {"User-Agent": "Mozilla/5.0 (lol-elo)"}
NEEDED_COLS = ["gameid", "league", "year", "date", "side", "position", "teamname", "result"]


# ---- data download --------------------------------------------------------

def _candidate_urls(year):
    """URLs to try for a given year, best guess first."""
    # Undated canonical form (works for many years).
    yield f"{OE_BUCKET}/{year}_LoL_esports_match_data_from_OraclesElixir.csv"
    # Dated form, walking back from today -- catches the daily-updated current year.
    today = datetime.date.today()
    for d in range(0, 14):
        stamp = (today - datetime.timedelta(days=d)).strftime("%Y%m%d")
        yield f"{OE_BUCKET}/{year}_LoL_esports_match_data_from_OraclesElixir_{stamp}.csv"


def download_year(year):
    """Fetch one year's CSV into DATA_DIR, or explain how to grab it by hand."""
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
    """Return this year's team-summary rows (2 per game) as a slim DataFrame."""
    path = os.path.join(DATA_DIR, f"{year}.csv")
    if not (os.path.exists(path) and os.path.getsize(path) > 1000):
        path = download_year(year)
    if not path:
        return None
    df = pd.read_csv(path, low_memory=False)
    keep = [c for c in NEEDED_COLS if c in df.columns]
    df = df[keep]
    df = df[df["position"] == "team"]                       # 2 team rows per game
    df = df.dropna(subset=["teamname", "result", "gameid"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


# ---- Elo math -------------------------------------------------------------

def expected(a, b):
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def update(a, b, score_a, k):
    """New (a, b) after a result. Zero-sum: a's gain is exactly b's loss."""
    delta = k * (score_a - expected(a, b))
    return a + delta, b - delta


def seed_ratings(region_rating, ranked_teams):
    """Fan a region's teams around its carried rating, best seed first."""
    n = len(ranked_teams)
    if PRESERVE_REGION_MEAN:
        mid = (n - 1) / 2.0
        offsets = [(mid - i) * SEED_SPACING for i in range(n)]   # symmetric, sums to 0
    else:
        offsets = [(n - 1 - i) * SEED_SPACING for i in range(n)]  # fan upward from floor
    return {t: region_rating + off for t, off in zip(ranked_teams, offsets)}


def region_of(league):
    """Map a raw league code to the region name we count it under."""
    return REGION_ALIASES.get(league, league)


def in_scope(region):
    return LEAGUES is None or region in {region_of(x) for x in LEAGUES}


# ---- the season-by-season run --------------------------------------------

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

    team_rating = {}                     # team -> current Elo (persists across years)
    carried_region = {}                  # region -> rating carried into next season
    prev_end = {}                        # team -> rating at end of previous year (for seeding)
    region_history = []                  # (year, region, rating) rows for output
    match_history = []                   # per-match change log for output

    def rating_of(team):
        return team_rating.get(team, INITIAL_RATING)

    for y in sorted(per_year):
        df = per_year[y]
        dom = df[~df["league"].isin(INTERNATIONAL)]

        # Each team's region THIS year, from its domestic games (handles teams
        # that change leagues between years). Most common league wins.
        counts = defaultdict(Counter)
        for team, lg in zip(dom["teamname"], dom["league"]):
            counts[team][region_of(lg)] += 1
        team_region_y = {t: c.most_common(1)[0][0] for t, c in counts.items()}

        # This year's roster per region (only in-scope regions).
        roster = defaultdict(list)
        for team, reg in team_region_y.items():
            if in_scope(reg):
                roster[reg].append(team)

        # --- SEASON RESET: seed each region's teams around its carried rating,
        #     ordered by last season's final Elo (a stand-in for last year's finish).
        for reg, teams in roster.items():
            ranked = sorted(teams, key=lambda t: (prev_end.get(t, float("-inf")), t), reverse=True)
            carried = carried_region.get(reg, INITIAL_RATING)
            for team, r in seed_ratings(carried, ranked).items():
                team_rating[team] = r

        # --- PLAY the year's games in date order.
        games = []
        for gid, rows in df.groupby("gameid"):
            if len(rows) != 2:
                continue
            rows = rows.sort_values("side")
            a, b = rows.iloc[0], rows.iloc[1]
            games.append((a["date"], a["teamname"], b["teamname"],
                          a["teamname"] if a["result"] == 1 else b["teamname"], a["league"]))
        games.sort(key=lambda g: (pd.isna(g[0]), g[0]))

        for date, ta, tb, winner, league in games:
            ra_reg = team_region_y.get(ta)
            rb_reg = team_region_y.get(tb)
            is_intl = league in INTERNATIONAL
            cross = is_intl and ra_reg is not None and rb_reg is not None and ra_reg != rb_reg

            # Only rate games between in-scope teams.
            if is_intl:
                if not (ra_reg and rb_reg and in_scope(ra_reg) and in_scope(rb_reg)):
                    continue
            else:
                if not in_scope(region_of(league)):
                    continue

            k = K_INTERNATIONAL if cross else K_REGIONAL
            before_a, before_b = rating_of(ta), rating_of(tb)
            score_a = 1.0 if winner == ta else 0.0
            new_a, new_b = update(before_a, before_b, score_a, k)
            team_rating[ta], team_rating[tb] = new_a, new_b
            match_history.append({
                "year": y, "date": date.date() if not pd.isna(date) else None,
                "league": league, "cross_region": cross,
                "team_a": ta, "team_b": tb, "winner": winner,
                "a_before": round(before_a, 1), "a_after": round(new_a, 1),
                "b_before": round(before_b, 1), "b_after": round(new_b, 1),
            })

        # --- END OF SEASON: record each region's rating and carry it forward.
        for reg, teams in roster.items():
            r = mean(rating_of(t) for t in teams)
            carried_region[reg] = r
            region_history.append({"year": y, "region": reg, "rating": round(r, 1),
                                    "teams": len(teams)})
        prev_end = dict(team_rating)

    _report(region_history, match_history, team_rating, carried_region)


def _report(region_history, match_history, team_rating, carried_region):
    last_year = max(r["year"] for r in region_history)

    print(f"\nRegion strength at end of {last_year} (carried into next season):")
    for reg, rating in sorted(carried_region.items(), key=lambda kv: kv[1], reverse=True)[:15]:
        print(f"  {reg:<10} {rating:7.1f}")

    print("\nTop 20 teams by current Elo:")
    for team, r in sorted(team_rating.items(), key=lambda kv: kv[1], reverse=True)[:20]:
        print(f"  {team:<24} {r:7.1f}")

    reg_df = pd.DataFrame(region_history)
    reg_df.to_csv("region_ratings_by_year.csv", index=False)
    pd.DataFrame(match_history).to_csv("match_history.csv", index=False)
    print("\nWrote region_ratings_by_year.csv and match_history.csv")

    # Optional chart -- only if matplotlib is installed.
    try:
        import matplotlib.pyplot as plt

        top = (reg_df.groupby("region")["rating"].max()
               .sort_values(ascending=False).head(8).index)
        fig, ax = plt.subplots(figsize=(11, 6))
        for reg in top:
            sub = reg_df[reg_df["region"] == reg]
            ax.plot(sub["year"], sub["rating"], marker="o", label=reg)
        ax.set_title("Region Elo over time")
        ax.set_xlabel("Year")
        ax.set_ylabel("Region Elo (mean of teams)")
        ax.legend()
        fig.tight_layout()
        fig.savefig("region_ratings.png", dpi=130)
        print("Wrote region_ratings.png")
    except ImportError:
        print("(install matplotlib for a region_ratings.png chart)")


if __name__ == "__main__":
    run()
