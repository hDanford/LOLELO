# lolelo

A two-tier Elo rating system for League of Legends esports.

## Start here: `lol_elo.py`

Everything in one editable file. It downloads all available historical match
data (Oracle's Elixir, 2014 → now), runs the two-tier Elo season by season, and
writes results + a chart.

```bash
pip install pandas matplotlib
python lol_elo.py
```

All the knobs (years, leagues, K-factors, seed spacing) are in the CONFIG block
at the top of the file — change a number, save, re-run. If the auto-download
ever fails, the script prints exactly which file to grab by hand from
oracleselixir.com/tools/downloads and where to put it. `make_test_data.py`
generates fake data in the same format if you want to experiment offline.

The `src/lolelo` package below is the same engine as a clean library, for when
the project grows past one file.

**Team ratings reset each season. Region ratings carry over.** And a region's
rating only moves when its teams play *other* regions internationally — never
during domestic play.

## The idea

The trick that makes the whole thing simple: **a region's rating is not tracked
separately.** It's *defined* as the average rating of that region's teams. From
that one choice, your entire spec falls out for free, because Elo updates are
zero-sum (whatever the winner gains, the loser loses):

- **Domestic games are within a region.** Zero-sum → the region's average is
  unchanged. That *is* "region Elo doesn't move during the season."
- **International games are between regions.** The winner (region X) gains and
  the loser (region Y) loses, so X's average rises and Y's falls. That *is*
  "region Elo changes only at international events."

So there's no special code for the two tiers — it emerges. Regions are only
handled explicitly at the season reset, where each region's carried average is
used to re-seed its teams.

## Seeding (and a fix to the original sketch)

At season start, teams are fanned out around their region's carried rating,
ordered by last season's finish. Two modes (`EloConfig.preserve_region_mean`):

- **Symmetric (default).** Offsets sum to zero, e.g. for 8 teams at 25-point
  spacing: `+87.5 … −87.5`. The seeded roster keeps the same average as the
  carried rating, so region strength carries over *exactly*.
- **Upward fan.** Offsets run `+175 … +0` from the region rating as a floor.
  This is the version in the original sketch (top 4 above the anchor, bottom 4
  at/below it). It's easy to picture, but the seeded average ends up
  `(n−1)·spacing/2` above the carried rating — so **every region inflates by
  that much every season**. Since it hits all regions equally, it adds nothing
  but drift. Use the symmetric mode unless you only ever compare within a season.

## Quick start

```bash
python examples/demo.py      # synthetic walkthrough, no data needed
python tests/test_engine.py  # sanity checks
```

The demo prints region ratings staying flat through a domestic season, diverging
after internationals, and carrying into the next season while teams re-seed.

## Using real data

The engine takes a list of `Match` objects and doesn't care where they come
from. Recommended source: **[Oracle's Elixir](https://oracleselixir.com/tools/downloads)**
— one clean CSV per year (2014→now), with a `league` column that makes
regional-vs-international classification basically free.

```python
from lolelo import EloConfig, League
from lolelo.ingest.oracles_elixir import load_matches

matches, region_of = load_matches("2024_LoL_esports.csv")
league = League(EloConfig())
for team, region in region_of.items():
    league.register_team(team, region, EloConfig().initial_region_rating)
league.process_all(matches)
```

Verify the international `league` codes against your file first — see the note
in `ingest/oracles_elixir.py`. (Leaguepedia's Cargo API is a fine alternative
source; just write a second adapter that emits `Match` objects.)

## Open decisions

Things worth pinning down before a serious run:

- **K-factors** (`k_regional`, `k_international`). International games are the
  only cross-region signal, so they're weighted higher by default. Sweep these.
- **Series vs. games.** A `Match` is one series by default (one update, win/loss).
  Feed individual games as separate `Match`es to rate per game, or pass a
  fractional `score` if you'd rather score a Bo5 by games won.
- **Region merges & splits.** LCK/LPL/LEC are stable, but the Americas merged
  (LCS+CBLOL+LLA → LTA in 2025) and split back (LTA → LCS+CBLOL in 2026). The
  reset does **not** handle this automatically. Options: treat the LTA North/
  South conferences as the continuation of LCS/CBLOL; average the merged
  regions' ratings on merge and copy the parent's rating on split; or just start
  your model in one era and sidestep it. Set the new region's carried rating
  yourself before calling `reset_for_new_season`.

## Layout

```
src/lolelo/
  engine.py    # pure Elo math (expected score, zero-sum update)
  model.py     # League/Match state; region rating = mean of teams
  season.py    # carry-over + seeding
  config.py    # K-factors, seed spacing, seeding mode
  ingest/      # data-source adapters (Oracle's Elixir included)
examples/demo.py
tests/test_engine.py
```

## Next: the viewer

A web front-end (the HTML layer you mentioned — that'd be JavaScript, not Java)
comes after the ratings pipeline is wired to real data. `league.history` is
already a per-match change log ready to plot as region and team rating curves
over time.
