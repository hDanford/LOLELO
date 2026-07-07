"""End-to-end demo on synthetic data -- no downloads, no network.

Run:  python examples/demo.py

It walks through the three properties the model is built around:
  1. Intra-region games leave each region's rating unchanged.
  2. International games make region ratings diverge.
  3. A season reset carries the region rating over and re-seeds the teams.
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lolelo import EloConfig, League, Match, reset_for_new_season, seed_new_season


def banner(text: str) -> None:
    print("\n" + text)
    print("-" * len(text))


def show_regions(league: League) -> None:
    for region in league.regions():
        teams = ", ".join(
            f"{t} {league.ratings[t]:.0f}" for t in league.standings(region)
        )
        print(f"  {region}: rating {league.region_rating(region):.1f}   [{teams}]")


def main() -> None:
    config = EloConfig()  # defaults: K 24 regional / 40 international, spacing 25

    # --- Season 1 setup: two regions, 4 teams each, all seeded around 1500 ---
    league = League(config=config)
    for region in ("LCK", "LEC"):
        seeded = seed_new_season(1500.0, [f"{region}{i}" for i in range(1, 5)], config)
        for team, rating in seeded.items():
            league.register_team(team, region, rating)

    banner("Season 1 start -- both regions seeded around 1500")
    show_regions(league)

    # --- Domestic round-robin (intra-region only) ---
    # Stronger seeds tend to win; outcomes are fixed so output is reproducible.
    domestic = [
        Match("LCK1", "LCK4", "LCK1"), Match("LCK1", "LCK3", "LCK1"),
        Match("LCK2", "LCK4", "LCK2"), Match("LCK2", "LCK3", "LCK3"),
        Match("LCK1", "LCK2", "LCK1"), Match("LCK3", "LCK4", "LCK4"),
        Match("LEC1", "LEC4", "LEC1"), Match("LEC1", "LEC3", "LEC3"),
        Match("LEC2", "LEC4", "LEC2"), Match("LEC2", "LEC3", "LEC2"),
        Match("LEC1", "LEC2", "LEC2"), Match("LEC3", "LEC4", "LEC3"),
    ]
    league.process_all(domestic)

    banner("After the domestic season -- note region ratings are UNCHANGED")
    show_regions(league)
    print("  (intra-region games are zero-sum, so each region's mean can't move)")

    # --- International event (cross-region), LCK the stronger region here ---
    intl = [
        Match("LCK1", "LEC1", "LCK1", tier="international"),
        Match("LCK2", "LEC2", "LCK2", tier="international"),
        Match("LCK1", "LEC2", "LEC2", tier="international"),
        Match("LCK2", "LEC1", "LCK2", tier="international"),
    ]
    league.process_all(intl)

    banner("After internationals -- region ratings now DIVERGE")
    show_regions(league)
    print("  (LCK won the cross-region games, so its mean rose and LEC's fell)")

    # --- Season reset: carry region rating, reset teams ---
    league2 = reset_for_new_season(league)

    banner("Season 2 start -- region ratings carried over, teams re-seeded")
    show_regions(league2)
    print("  (each region's mean matches where it ended season 1; teams fanned")
    print("   back out by final standing. Team Elo reset, region Elo carried.)")

    # --- Write the full per-match rating history to CSV ---
    out = Path(__file__).resolve().parent / "ratings_history.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(league.history[0].keys()))
        writer.writeheader()
        writer.writerows(league.history)
    print(f"\nWrote per-match history -> {out.name} ({len(league.history)} rows)")


if __name__ == "__main__":
    main()
