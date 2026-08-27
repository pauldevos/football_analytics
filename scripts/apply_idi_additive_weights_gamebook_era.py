#!/usr/bin/env python3
"""
apply_idi_additive_weights_gamebook_era.py — apply the fitted additive
weights from fit_idi_additive_weights.py (real, logistic-regression-derived,
1999-2024) OUT OF SAMPLE to 1971 Minnesota, 1972 Pittsburgh, and 1974
Pittsburgh -- the three team-seasons already spot-checked by hand this
session with the hand-picked version of this formula (docs/
DPVS_G_FORMULA_REFERENCE.md's "reweighted test variant" section). This is a
genuine out-of-sample check: these three team-seasons were never part of the
fitting pool (which is 1999-2024 only), so nothing here was tuned to produce
any particular Ham/White or Greene/Holmes ordering.

Six raw stats needed per player, three different sourcing strategies:

  sacks, int, fr — pulled DIRECTLY from PFR's own official season-defense
    table (~/data/pfref/raw/season/player/defense/defense_{season}.csv, same
    file the modern-era fit uses) for the target team. No proration: per the
    task brief, these are treated as reliable enough as-is for this era (fr
    especially -- fumble recoveries are a simple, unambiguous box-score
    count, not a text-narrative-dependent one the way tackle/run stuff/FF are).

  run_stuff, ff, tackle_total — PRORATED from gamebooks_boxscores' own
    completeness-ratio-gated corpus (silver.player_game_stats_gamebook,
    completeness_qualified=true rows only -- exactly the source dpvs/idi.py's
    own "Layer 0" tackle/run stuff handling already uses for this era, see that
    module's docstring). Method (identical for all three stats, per the task
    brief): for each player, sum the raw stat across the team-side's
    qualified games only; divide by the TEAM's summed opponent-opportunities
    (opponent rush_attempts + pass_completions + times_sacked, from
    gold.team_game_stats) across those SAME qualified games, giving a
    per-player rate; multiply by the team's FULL-SEASON opponent-
    opportunities (all regular-season games, qualified or not) to prorate to
    a season estimate. This is the same "rate x full-season opportunity"
    idea dpvs/idi.py's own tackle_opportunity_ratio mechanism (Layer 2b)
    embodies, applied directly to the real completeness-qualified per-player
    game rows already in Postgres for this era (Layer 0's own source)
    instead of Layer 2b's own lookup table (TACKLE_OPPORTUNITY_ADJ_CORPUS),
    which is calibrated for the DIFFERENT pathway idi.py falls back to only
    when no gamebook data exists at all (not the case for any of these three
    team-seasons, which all have real completeness-qualified gamebook
    coverage -- see this script's own printed qualified-game counts).

Player identity across the two sources: silver.player_game_stats_gamebook's
player_id is a real gold.players FK, joined to its PFR id via
internal.player_xref (source_system='pfr') -- the exact same bare id format
PFR's season-defense CSV already uses as its own player_id column, so the
two sources merge directly on that id with no name-matching step needed.

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    PYTHONPATH=~/github/football/football_db/src python3 \
        scripts/apply_idi_additive_weights_gamebook_era.py

Outputs (printed, plus one CSV per team-season):
    data_output/additive_score_1971_min.csv
    data_output/additive_score_1972_pit.csv
    data_output/additive_score_1974_pit.csv
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import psycopg2

PFREF_DEFENSE_DIR = Path.home() / "data/pfref/raw/season/player/defense"
DATA_OUT = Path(__file__).resolve().parent.parent / "data_output"
WEIGHTS_PATH = DATA_OUT / "idi_additive_fit_weights.json"

# (franchise_id, season, PFR team abbrev as used in defense_{season}.csv)
TARGETS = [
    (32, 1971, "MIN"),
    (29, 1972, "PIT"),
    (29, 1974, "PIT"),
]


def load_official_sack_int_fr(season: int, team_abbrev: str) -> pd.DataFrame:
    """sacks/int/fr straight from PFR's official season-defense table --
    same source and same columns the 1999-2024 fit used, just applied to an
    earlier season. No multi-team dedup needed here (none of Ham/White/
    Greene/Holmes were traded mid-season in these three team-seasons)."""
    df = pd.read_csv(PFREF_DEFENSE_DIR / f"defense_{season}.csv")
    if "team_abbrev" not in df.columns and "team" in df.columns:
        df = df.rename(columns={"team": "team_abbrev", "player": "player_name",
                                 "pos": "position", "sk": "sack"})
    df = df[df["player_id"].notna() & (df["team_abbrev"] == team_abbrev)].copy()
    for col in ("sack", "fr", "int"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df[["player_id", "player_name", "position", "sack", "fr", "int"]].rename(
        columns={"sack": "sacks_official", "fr": "fr_official", "int": "int_official"}
    )


def load_prorated_run_stuff_ff_tackles(conn, franchise_id: int, season: int) -> tuple[pd.DataFrame, dict]:
    """Qualified-games rate x full-season-opportunities proration for
    run_stuff/ff/tackle_total. Returns (per-player frame, diagnostics dict)."""
    # Per-game opponent opportunities + whether this franchise's own side
    # was completeness_qualified that game (bool_or across that game's rows
    # for this franchise -- confirmed uniform per (franchise_id, game_id),
    # not mixed, so bool_or is just reading the one real value, not voting).
    games = pd.read_sql("""
        SELECT g.game_id,
               tgs.rush_attempts, tgs.pass_completions, tgs.times_sacked,
               COALESCE(bool_or(gb.completeness_qualified), false) AS qualified
        FROM gold.games g
        LEFT JOIN gold.team_game_stats tgs
               ON tgs.game_id = g.game_id
              AND tgs.franchise_id = CASE WHEN g.home_franchise_id = %(fid)s
                                           THEN g.away_franchise_id ELSE g.home_franchise_id END
        LEFT JOIN silver.player_game_stats_gamebook gb
               ON gb.game_id = g.game_id AND gb.franchise_id = %(fid)s
        WHERE g.season = %(season)s AND g.game_type = 'regular'
          AND (g.home_franchise_id = %(fid)s OR g.away_franchise_id = %(fid)s)
        GROUP BY g.game_id, tgs.rush_attempts, tgs.pass_completions, tgs.times_sacked
    """, conn, params={"fid": franchise_id, "season": season})
    games["opportunities"] = (games["rush_attempts"].fillna(0)
                               + games["pass_completions"].fillna(0)
                               + games["times_sacked"].fillna(0))
    full_season_opp = games["opportunities"].sum()
    qualified_opp = games.loc[games["qualified"], "opportunities"].sum()
    n_qualified_games = int(games["qualified"].sum())
    n_total_games = len(games)

    players = pd.read_sql("""
        SELECT gb.player_id, p.full_name AS player_name, x.source_player_id AS pfr_id,
               SUM(gb.run_stuff) FILTER (WHERE gb.completeness_qualified) AS run_stuff_qual_sum,
               SUM(gb.ff) FILTER (WHERE gb.completeness_qualified) AS ff_qual_sum,
               SUM(COALESCE(gb.solo_tackle, 0) + COALESCE(gb.ast_tackle, 0))
                   FILTER (WHERE gb.completeness_qualified) AS tackle_qual_sum
        FROM silver.player_game_stats_gamebook gb
        JOIN gold.games g ON g.game_id = gb.game_id
        JOIN gold.players p ON p.player_id = gb.player_id
        LEFT JOIN internal.player_xref x ON x.player_id = gb.player_id AND x.source_system = 'pfr'
        WHERE gb.franchise_id = %(fid)s AND g.season = %(season)s AND g.game_type = 'regular'
        GROUP BY gb.player_id, p.full_name, x.source_player_id
    """, conn, params={"fid": franchise_id, "season": season})

    for c in ("run_stuff_qual_sum", "ff_qual_sum", "tackle_qual_sum"):
        players[c] = players[c].fillna(0)

    rate_denom = qualified_opp if qualified_opp else float("nan")
    players["run_stuff"] = players["run_stuff_qual_sum"] / rate_denom * full_season_opp
    players["ff"] = players["ff_qual_sum"] / rate_denom * full_season_opp
    players["tackle_total"] = players["tackle_qual_sum"] / rate_denom * full_season_opp

    diag = {
        "n_total_games": n_total_games, "n_qualified_games": n_qualified_games,
        "full_season_opportunities": float(full_season_opp),
        "qualified_opportunities": float(qualified_opp),
    }
    return players, diag


def main():
    weights_blob = json.loads(WEIGHTS_PATH.read_text())
    weights = weights_blob["weights"]
    # fit_idi_additive_weights.py's fitted weight is keyed "pfr_tfl" (PFR's
    # own official, sack-inclusive season stat -- see that script's STAT_COLS
    # comment). This script has no PFR official tackle-for-loss data for
    # 1971/1972/1974 (predates PFR's 1999+ tackles_loss column entirely), so
    # it deliberately applies that same fitted weight, out-of-sample, to its
    # own prorated "run_stuff" proxy (gamebooks_boxscores' non-sack
    # convention) as the best available stand-in for this era -- a
    # pre-existing cross-era approximation, not a naming bug. Remap the key
    # here rather than rename this script's own column to "pfr_tfl", since
    # the data underneath genuinely IS this project's run_stuff convention.
    weights = {("run_stuff" if k == "pfr_tfl" else k): v for k, v in weights.items()}
    intercept = weights_blob["intercept"]
    print(f"Loaded fitted weights (from {weights_blob['fit_seasons']}, "
          f"n={weights_blob['n_player_seasons']}, all_pro={weights_blob['n_all_pro']}):")
    for k, v in weights.items():
        print(f"  {k:15s} {v:+.4f}")
    print(f"  intercept       {intercept:+.4f}\n")

    conn = psycopg2.connect(dbname="football")

    for fid, season, abbrev in TARGETS:
        print(f"\n{'='*70}\n{season} {abbrev} (franchise_id={fid})\n{'='*70}")
        official = load_official_sack_int_fr(season, abbrev)
        prorated, diag = load_prorated_run_stuff_ff_tackles(conn, fid, season)
        print(f"  qualified games: {diag['n_qualified_games']}/{diag['n_total_games']}  "
              f"qualified_opportunities={diag['qualified_opportunities']:.0f}  "
              f"full_season_opportunities={diag['full_season_opportunities']:.0f}")

        merged = prorated.merge(official, left_on="pfr_id", right_on="player_id",
                                 how="outer", suffixes=("", "_off"))
        merged["player_name"] = merged["player_name"].fillna(merged["player_name_off"])
        for c in ("run_stuff", "ff", "tackle_total"):
            merged[c] = merged[c].fillna(0)
        for c in ("sacks_official", "fr_official", "int_official"):
            merged[c] = merged[c].fillna(0)
        merged = merged.rename(columns={"sacks_official": "sacks", "fr_official": "fr", "int_official": "int"})

        merged["score"] = sum(merged[c] * w for c, w in weights.items())
        merged["prob_all_pro"] = 1 / (1 + pd.Series(
            [pow(2.718281828, -(s + intercept)) for s in merged["score"]]
        ))

        out_cols = ["player_name", "position", "tackle_total", "sacks", "run_stuff", "ff", "fr", "int", "score", "prob_all_pro"]
        out = merged[out_cols].sort_values("score", ascending=False).reset_index(drop=True)
        out.insert(0, "rank", out.index + 1)
        print(out.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

        fname = f"additive_score_{season}_{abbrev.lower()}.csv"
        out.to_csv(DATA_OUT / fname, index=False)
        print(f"  wrote {DATA_OUT / fname}")

    conn.close()


if __name__ == "__main__":
    main()
