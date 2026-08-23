#!/usr/bin/env python3
"""
Build the REAL, verified per-team-per-season solo:assist tackle ratio table,
directly from PFR's official per-game player_defense.csv boxscore files --
NOT from gold.player_game_stats (which this session confirmed is actually
PFR pbp.csv PLAY-BY-PLAY TEXT parsed into a table, not official box-score
data, and undercounts assist tackles by ~2.6x on a real 2025 HOU spot check
-- see docs/deferred/tackle_ratio_verification_20260822.md for the full
writeup and scripts/build_tackle_opportunity_ratio.py's own docstring for
where that flawed source was first found).

WHAT THIS READS (both confirmed present locally, no scraping):
  ~/data/pfref/raw/boxscores/{year}/{game_id}/player_defense.csv
      real per-game per-player defensive box score rows, one row per
      player per game, with a `team` column giving that player's team as
      an era-specific PFR short code (e.g. "ARI", "HOU", "STL" -- these
      change with relocations/renames even though the franchise doesn't).
  ~/data/pfref/raw/season/team/defense/team_stats/team_stats_{year}.csv
      one row per team per season; despite living under a generically-named
      "team_stats" path, this is PFR's Team Defense page's OPPONENT-stats
      section (points/yards/plays *allowed*, confirmed by a direct spot
      check: Denver Broncos 2001 plays_offense=960 matches PFR's own
      "Opp. Stats > Ply" column for that Broncos season exactly). So
      plays_offense here is real -- the opponent's own offensive plays run
      against that team's defense that season -- and is used as the
      tackle-opportunity denominator.
  ~/data/pfref/franchise_year_abbrev.csv
      (year, team_name, abbrev) for every franchise back to 1920 -- the
      SAME stable lowercase abbrev convention as
      scripts/build_tackle_opportunity_ratio.py's FID_TO_TEAM dict (e.g.
      "crd" for the Cardinals regardless of St. Louis/Phoenix/Arizona era,
      "oti" for the Oilers/Titans franchise, "htx" for the separate Texans
      expansion franchise). Used twice: once to translate team_stats.csv's
      full team_name into the stable code, and once (via a small explicit
      dict below, TEAM_CODE_TO_STABLE) to translate player_defense.csv's
      era-specific short code into the same stable code.

WHY player_defense.csv's own short code needs its own translation dict
instead of reusing franchise_year_abbrev.csv directly: that code is NOT
always a case-insensitive match of the stable abbrev (e.g. Cardinals rows
say team="ARI" while the stable code is "crd" -- a historical PFR URL
artifact, not a typo). The one genuinely year-conditional case is HOU:
it means the Houston Oilers (stable code "oti") in 1994-1996, and the
Houston Texans expansion franchise (stable code "htx", unrelated to the
Oilers/Titans lineage) from 2002 on -- confirmed by checking which years
"HOU" vs "TEN" actually appear in the data (HOU never overlaps with TEN;
TEN takes over from HOU in 1997, matching the real Oilers->Titans rename,
then HOU reappears in 2002 as the unrelated Texans franchise). Every other
code is a fixed, franchise-stable translation regardless of year.

RELIABILITY FINDING (see docstring at bottom of main() / the written-up
doc for the full evidence): tackles_combined/tackles_solo/tackles_assists
are ALL BLANK in player_defense.csv for every season before 1994 (checked
1950/1960/1970/1980/1985/1990/1993 directly) -- PFR's box scores literally
did not carry a solo/assist split before 1994, this isn't a sparse-data
problem, the columns don't exist as populated data at all. 1994 on, the
columns are populated. So this script processes 1994-2025 (the full
range the data can support), not just 2001-2025.

Output: data_output/tackle_ratio_by_team_season.csv
  columns: season, team, team_name, comb_tackles, solo_tackles, ast_tackles,
  n_games, plays_offense, tackle_share_denominator, solo_ratio, ast_ratio,
  solo_to_ast_ratio
  -- tackle_share_denominator is just plays_offense named per the task's
  own spec; kept as two columns (plays_offense unchanged from source,
  tackle_share_denominator as the explicit derived-use name) so nothing is
  silently renamed away from its source meaning.

Usage: python3 build_verified_tackle_ratio.py
  (plain pandas/numpy -- no football_db/.venv dependency, this step never
  touches Postgres, unlike build_tackle_opportunity_ratio.py which still
  needs it for the "opportunities" denominator on the 1967-2000 side)
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

PFREF_DIR = Path.home() / "data" / "pfref"
BOXSCORES_DIR = PFREF_DIR / "raw" / "boxscores"
TEAM_STATS_DIR = PFREF_DIR / "raw" / "season" / "team" / "defense" / "team_stats"
FRANCHISE_YEAR_ABBREV = PFREF_DIR / "franchise_year_abbrev.csv"

OUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data_output" / "tackle_ratio_by_team_season.csv"
)

FIRST_SOLO_AST_YEAR = 1994  # see docstring RELIABILITY FINDING
LAST_YEAR = 2025

# player_defense.csv "team" short code -> stable franchise abbrev
# (same convention as franchise_year_abbrev.csv / build_tackle_opportunity_
# ratio.py's FID_TO_TEAM). HOU is the one year-conditional entry -- see
# module docstring. Built + verified against the full 1994-2025 distinct
# code list (37 codes) pulled directly from the corpus.
TEAM_CODE_TO_STABLE = {
    "ARI": "crd", "ATL": "atl", "BAL": "rav", "BUF": "buf", "CAR": "car",
    "CHI": "chi", "CIN": "cin", "CLE": "cle", "DAL": "dal", "DEN": "den",
    "DET": "det", "GNB": "gnb", "IND": "clt", "JAX": "jax", "KAN": "kan",
    "LAC": "sdg", "LAR": "ram", "LVR": "rai", "MIA": "mia", "MIN": "min",
    "NOR": "nor", "NWE": "nwe", "NYG": "nyg", "NYJ": "nyj", "OAK": "rai",
    "PHI": "phi", "PIT": "pit", "RAI": "rai", "RAM": "ram", "SDG": "sdg",
    "SEA": "sea", "SFO": "sfo", "STL": "ram", "TAM": "tam", "TEN": "oti",
    "WAS": "was",
}


def stable_code(team_code: str, season: int) -> str | None:
    if team_code == "HOU":
        return "oti" if season <= 1996 else "htx"
    return TEAM_CODE_TO_STABLE.get(team_code)


def load_franchise_year_abbrev() -> pd.DataFrame:
    df = pd.read_csv(FRANCHISE_YEAR_ABBREV)
    df["abbrev"] = df["abbrev"].str.lower()
    return df


def sum_player_defense_by_game() -> tuple[pd.DataFrame, dict]:
    """Scan every player_defense.csv for FIRST_SOLO_AST_YEAR..LAST_YEAR,
    summing tackles_combined/solo/assists per (season, stable team code,
    game_id) -- PER-GAME, not yet collapsed to a season total. Collapsing
    happens later in trim_to_regular_season(), which needs per-game
    granularity to drop playoff games chronologically (see that function's
    docstring for why: the boxscore folder tree includes playoff games,
    but team_stats.csv's plays_offense/g columns are regular-season-only,
    and mixing the two scopes silently overstates the tackle numerator
    relative to the denominator -- caught via a real HOU 2025 check:
    19 raw game folders vs team_stats.csv's own g=17).

    Also tracks, per season, how many player-rows had a non-blank
    tackles_solo value vs total rows (completeness signal), for the
    reliability report."""
    game_rows: dict[tuple[int, str, str], dict] = {}
    completeness: dict[int, dict] = {}
    unmapped_codes: set[tuple[str, int]] = set()

    for year in range(FIRST_SOLO_AST_YEAR, LAST_YEAR + 1):
        year_dir = BOXSCORES_DIR / str(year)
        if not year_dir.exists():
            continue
        comp = completeness.setdefault(year, {"rows": 0, "solo_populated": 0, "games": set()})
        for game_dir in sorted(year_dir.iterdir()):
            f = game_dir / "player_defense.csv"
            if not f.exists():
                continue
            with open(f, newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    season = int(row["season"])
                    team_code = row["team"]
                    code = stable_code(team_code, season)
                    if code is None:
                        unmapped_codes.add((team_code, season))
                        continue
                    comp["rows"] += 1
                    comp["games"].add(game_dir.name)
                    solo_raw = row.get("tackles_solo", "")
                    ast_raw = row.get("tackles_assists", "")
                    comb_raw = row.get("tackles_combined", "")
                    if solo_raw not in ("", None):
                        comp["solo_populated"] += 1
                    solo = float(solo_raw) if solo_raw not in ("", None) else 0.0
                    ast = float(ast_raw) if ast_raw not in ("", None) else 0.0
                    comb = float(comb_raw) if comb_raw not in ("", None) else 0.0
                    key = (season, code, game_dir.name)
                    d = game_rows.setdefault(key, {"comb": 0.0, "solo": 0.0, "ast": 0.0})
                    d["comb"] += comb
                    d["solo"] += solo
                    d["ast"] += ast

    rows = []
    for (season, code, game_id), d in game_rows.items():
        rows.append({
            "season": season, "team": code, "game_id": game_id,
            "comb_tackles": d["comb"], "solo_tackles": d["solo"],
            "ast_tackles": d["ast"],
        })
    out = pd.DataFrame(rows)
    if unmapped_codes:
        print(f"WARNING: {len(unmapped_codes)} unmapped (team_code, season) pairs skipped: "
              f"{sorted(unmapped_codes)[:20]}")
    return out, completeness


def trim_to_regular_season(game_df: pd.DataFrame, ts_all: pd.DataFrame) -> pd.DataFrame:
    """The boxscore folder tree has no explicit season-type field, but
    game_id's leading 8 digits are YYYYMMDD, so games sort chronologically
    within a season, and playoff games always come after every regular-
    season game on the calendar. team_stats.csv's own `g` column is the
    real regular-season game count per team-season (PFR's own scope for
    plays_offense too), so: per (season, team), sort games chronologically
    and keep exactly the first g games, dropping the rest as playoffs.
    Confirmed necessary via HOU 2025: 19 raw game folders vs g=17 -- the 2
    extra were playoff games whose tackle totals would otherwise inflate
    the numerator against a denominator that never counted them."""
    g_lookup = ts_all.set_index(["season", "team"])["g"].to_dict()
    game_df = game_df.copy()
    game_df["game_date"] = game_df["game_id"].str[:8]
    game_df = game_df.sort_values(["season", "team", "game_date"])

    kept_parts = []
    dropped_playoff_games = 0
    for (season, team), grp in game_df.groupby(["season", "team"], sort=False):
        g = g_lookup.get((season, team))
        if g is None:
            kept_parts.append(grp)  # no team_stats row to trim against -- keep as-is
            continue
        g = int(g)
        kept_parts.append(grp.iloc[:g])
        dropped_playoff_games += max(0, len(grp) - g)
    trimmed = pd.concat(kept_parts, ignore_index=True) if kept_parts else game_df

    print(f"trim_to_regular_season: dropped {dropped_playoff_games} playoff-game rows "
          f"across all team-seasons (kept count matches team_stats.csv's own g column).")

    season_totals = trimmed.groupby(["season", "team"], as_index=False).agg(
        comb_tackles=("comb_tackles", "sum"),
        solo_tackles=("solo_tackles", "sum"),
        ast_tackles=("ast_tackles", "sum"),
        n_games=("game_id", "nunique"),
    )
    return season_totals


def build_team_stats_coded(fya: pd.DataFrame) -> pd.DataFrame:
    """Read every season's team_stats_{year}.csv and translate its full
    team_name to the stable franchise code via franchise_year_abbrev.csv.
    Returns one row per (season, team) with team_name, plays_offense, and
    g (real regular-season game count -- used both as the trim target in
    trim_to_regular_season() and reported directly in the output)."""
    ts_rows = []
    for year in range(FIRST_SOLO_AST_YEAR, LAST_YEAR + 1):
        f = TEAM_STATS_DIR / f"team_stats_{year}.csv"
        if not f.exists():
            continue
        ts = pd.read_csv(f)
        ts = ts[["season", "team", "g", "plays_offense"]].rename(columns={"team": "team_name"})
        ts_rows.append(ts)
    ts_all = pd.concat(ts_rows, ignore_index=True)

    fya_year = fya[["year", "team_name", "abbrev"]].rename(
        columns={"year": "season", "abbrev": "team"}
    )
    ts_coded = ts_all.merge(fya_year, on=["season", "team_name"], how="left")

    # franchise_year_abbrev.csv tops out at 2024 (not yet updated for the
    # season in progress at build time). For any (season, team_name) that
    # didn't match directly -- expected to be exactly the current season's
    # teams whose name hasn't changed since their last listed year -- fall
    # back to that team_name's most recent known abbrev (team_name itself
    # already encodes any rename, so same-name = same franchise = safe).
    unmatched_mask = ts_coded["team"].isna()
    if unmatched_mask.any():
        latest_by_name = (
            fya.sort_values("year").groupby("team_name")["abbrev"].last()
        )
        fallback = ts_coded.loc[unmatched_mask, "team_name"].map(latest_by_name)
        ts_coded.loc[unmatched_mask, "team"] = fallback
        still_unmatched = ts_coded[ts_coded["team"].isna()]
        if len(still_unmatched):
            print(f"WARNING: {len(still_unmatched)} team_stats rows failed to match a stable "
                  f"code even via name-fallback: "
                  f"{list(zip(still_unmatched['season'], still_unmatched['team_name']))[:20]}")
        else:
            print(f"Note: {unmatched_mask.sum()} team_stats rows (season not yet listed in "
                  f"franchise_year_abbrev.csv) matched via team_name fallback instead of "
                  f"exact (season, team_name).")
    return ts_coded


def main() -> None:
    print(f"Scanning player_defense.csv for {FIRST_SOLO_AST_YEAR}-{LAST_YEAR}...")
    game_df, completeness = sum_player_defense_by_game()
    print(f"Built {len(game_df)} (season, team, game) rows from "
          f"{sum(len(c['games']) for c in completeness.values())} game-files.")

    print("\nSolo-column completeness by season (rows with non-blank tackles_solo):")
    for year in sorted(completeness):
        c = completeness[year]
        pct = c["solo_populated"] / c["rows"] * 100 if c["rows"] else 0.0
        print(f"  {year}: {c['solo_populated']}/{c['rows']} rows ({pct:.1f}%), "
              f"{len(c['games'])} games")

    fya = load_franchise_year_abbrev()
    ts_coded = build_team_stats_coded(fya)

    tackle_df = trim_to_regular_season(game_df, ts_coded)

    full = tackle_df.merge(
        ts_coded[["season", "team", "team_name", "g", "plays_offense"]],
        on=["season", "team"], how="left",
    )

    full["tackle_share_denominator"] = full["plays_offense"]
    full["solo_ratio"] = full["solo_tackles"] / full["comb_tackles"]
    full["ast_ratio"] = full["ast_tackles"] / full["comb_tackles"]
    full["solo_to_ast_ratio"] = full["solo_tackles"] / full["ast_tackles"]

    full = full.sort_values(["team", "season"]).reset_index(drop=True)
    cols = ["season", "team", "team_name", "g", "n_games", "comb_tackles", "solo_tackles",
            "ast_tackles", "plays_offense", "tackle_share_denominator",
            "solo_ratio", "ast_ratio", "solo_to_ast_ratio"]
    full = full[cols]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    full.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(full)} team-seasons to {OUT_PATH}")

    # --- Denver 2001 validation against the user's pasted PFR numbers ---
    den2001 = full[(full["team"] == "den") & (full["season"] == 2001)]
    print("\n=== Denver Broncos 2001 validation (user pasted Comb=951 Solo=803 Ast=148, plays_offense=960) ===")
    if len(den2001):
        r = den2001.iloc[0]
        print(f"  Computed: comb={r['comb_tackles']:.0f} solo={r['solo_tackles']:.0f} "
              f"ast={r['ast_tackles']:.0f} plays_offense={r['plays_offense']:.0f} "
              f"n_games={r['n_games']:.0f}")
    else:
        print("  NOT FOUND")

    # --- distribution report (2001-2025, the modern-era window) ---
    modern = full[(full["season"] >= 2001) & full["solo_ratio"].notna()]
    print("\n=== solo:ast distribution, 2001-2025 team-seasons (n={}) ===".format(len(modern)))
    print(f"  solo_ratio: mean={modern['solo_ratio'].mean():.4f} std={modern['solo_ratio'].std():.4f} "
          f"min={modern['solo_ratio'].min():.4f} max={modern['solo_ratio'].max():.4f}")
    print(f"  ast_ratio:  mean={modern['ast_ratio'].mean():.4f} std={modern['ast_ratio'].std():.4f} "
          f"min={modern['ast_ratio'].min():.4f} max={modern['ast_ratio'].max():.4f}")
    print(f"  solo:ast (solo_tackles/ast_tackles): mean={modern['solo_to_ast_ratio'].mean():.4f} "
          f"std={modern['solo_to_ast_ratio'].std():.4f} "
          f"min={modern['solo_to_ast_ratio'].min():.4f} max={modern['solo_to_ast_ratio'].max():.4f}")

    by_season = modern.groupby("season").agg(
        solo=("solo_tackles", "sum"), ast=("ast_tackles", "sum")
    )
    by_season["solo_to_ast"] = by_season["solo"] / by_season["ast"]
    print("\n  League-pooled solo:ast by season:")
    print(by_season[["solo_to_ast"]].to_string())

    # also report full 1994-2025 window (pre-2001 sanity) for context
    all_years = full[full["solo_ratio"].notna()]
    by_season_all = all_years.groupby("season").agg(
        solo=("solo_tackles", "sum"), ast=("ast_tackles", "sum")
    )
    by_season_all["solo_to_ast"] = by_season_all["solo"] / by_season_all["ast"]
    print("\n  League-pooled solo:ast by season, full 1994-2025 window:")
    print(by_season_all[["solo_to_ast"]].to_string())


if __name__ == "__main__":
    main()
