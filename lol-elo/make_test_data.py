"""Generate fake data files in the exact Oracle's Elixir schema (the columns
lol_elo.py uses, incl. player rows + team rows) to test the whole pipeline
without network access. Covers 2023-2025 including a league rename (LTA N)
to exercise REGION_ALIASES, plus MSI/Worlds international games."""

import csv
import os
import random

random.seed(42)

os.makedirs("data", exist_ok=True)

LEAGUES = {
    2023: {"LCK": ["T1", "GenG", "KT", "DK"],
           "LEC": ["G2", "FNC", "MAD", "BDS"],
           "LCS": ["C9", "FLY", "TL", "100T"]},
    2024: {"LCK": ["T1", "GenG", "KT", "DK"],
           "LEC": ["G2", "FNC", "MAD", "BDS"],
           "LCS": ["C9", "FLY", "TL", "100T"]},
    2025: {"LCK": ["T1", "GenG", "KT", "DK"],
           "LEC": ["G2", "FNC", "MAD", "BDS"],
           "LTA N": ["C9", "FLY", "TL", "DSG"]},  # LCS renamed -> tests aliasing
}

# Hidden "true strength" so results aren't pure coin flips; LCK strongest.
STRENGTH = {"T1": 1650, "GenG": 1620, "KT": 1520, "DK": 1500,
            "G2": 1580, "FNC": 1520, "MAD": 1470, "BDS": 1430,
            "C9": 1540, "FLY": 1510, "TL": 1470, "100T": 1430, "DSG": 1400}

HEADER = ["gameid", "league", "year", "split", "playoffs", "date", "game",
          "side", "position", "teamname", "result"]

def p_win(a, b):
    return 1 / (1 + 10 ** ((STRENGTH[b] - STRENGTH[a]) / 400))

def rows_for_game(gid, league, year, date, ta, tb):
    win_a = random.random() < p_win(ta, tb)
    out = []
    for side, team, res in (("Blue", ta, int(win_a)), ("Red", tb, int(not win_a))):
        for pos in ("top", "jng", "mid", "bot", "sup"):   # player rows (ignored by parser)
            out.append([gid, league, year, "", 0, date, 1, side, pos, team, res])
        out.append([gid, league, year, "", 0, date, 1, side, "team", team, res])
    return out

for year, leagues in LEAGUES.items():
    rows, gid = [], 0
    # Domestic: double round robin per league
    for lg, teams in leagues.items():
        for rep in range(2):
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    gid += 1
                    date = f"{year}-{random.randint(1,6):02d}-{random.randint(1,28):02d} 12:00:00"
                    rows += rows_for_game(f"{year}g{gid}", lg, year, date, teams[i], teams[j])
    # MSI: top team per league, round robin
    tops = [teams[0] for teams in leagues.values()]
    for i in range(len(tops)):
        for j in range(i + 1, len(tops)):
            gid += 1
            rows += rows_for_game(f"{year}g{gid}", "MSI", year,
                                  f"{year}-07-{random.randint(1,15):02d} 12:00:00", tops[i], tops[j])
    # Worlds: top two per league, single round robin
    w = [t for teams in leagues.values() for t in teams[:2]]
    for i in range(len(w)):
        for j in range(i + 1, len(w)):
            gid += 1
            rows += rows_for_game(f"{year}g{gid}", "WLDs", year,
                                  f"{year}-10-{random.randint(1,28):02d} 12:00:00", w[i], w[j])
    with open(f"data/{year}.csv", "w", newline="") as f:
        wtr = csv.writer(f)
        wtr.writerow(HEADER)
        wtr.writerows(rows)
    print(f"data/{year}.csv: {gid} games, {len(rows)} rows")
