#!/usr/bin/env python3
"""
fit_idi_additive_weights.py — derive REAL, empirically-fit weights for the
six-stat additive defensive value formula the user asked for on 2026-08-23:

    score = w1*tackle_total + w2*sacks + w3*pfr_tfl + w4*ff + w5*fr + w6*int

using RAW season counts (not z-scores, not shares), fit via logistic
regression against real AP All-Pro recognition. This REPLACES the hand-picked
version documented in docs/DPVS_G_FORMULA_REFERENCE.md's "reweighted test
variant" section (FF=0.133/INT=0.150/etc, tuned by eye on 3 team-seasons) with
coefficients derived from data, per the user's explicit request: "I don't want
it hand-picked... I want it fit properly."

WHY 1999-2024 AND WHY THIS SOURCE (not football_db's Postgres per-game
tables): dpvs/idi.py's own Postgres path (gold.player_game_stats /
silver.player_game_stats_pfr) is, for the ENTIRE 1978-2025 range including
1999-2024, sourced from gamebooks_boxscores/parse_pfr_pbp.py parsing PFR's
pbp.csv PLAY-BY-PLAY TEXT -- not PFR's official box-score columns. This is a
CONFIRMED, measured undercount even in the modern era (docs/experiments/
2026-08-20_pfr_pbp_vs_gamebook_completeness/README.md found real sacks
missing from the pbp.csv narrative entirely for J.J. Watt 2012 [-4.0],
Aaron Donald 2018 [-2.0], DeMarcus Ware 2008 [-3.0], Von Miller 2012 [-1.0] --
confirmed by a background-agent investigation this session that traced
`data_tier='pfr_pbp_derived_1999_2025'` in silver.player_game_stats_pfr back
to the exact same pbp.csv-text-parsing code path as the explicitly-flagged
`pfr_pbp_undercount_1978_1998` tier; the "_derived" vs "_undercount" naming
difference reflects officiating/scorekeeping getting MORE consistent after
1999, not a switch to an officially-sourced pathway).

The task brief's premise -- "this era has fully reliable, official PFR season
totals... so the weight-derivation itself isn't contaminated" -- does NOT
hold for that Postgres path. It DOES hold for PFR's actual official
season-defense tables, which exist on disk and are NOT the same data:
    ~/data/pfref/raw/season/player/defense/defense_{year}.csv
one row per player-season, scraped directly from PFR's own season defense
stat page (not play-by-play text). tackles_solo/tackles_assists populated
from 1994, tackles_loss (TFL) from 1999 -- confirmed via the same 2026-08-20
experiment's "Finding 1" -- which is exactly why 1999 is this fit's start
year: it's the first season ALL SIX stats (tackle, sack, pfr_tfl, ff, fr, int)
are simultaneously available from PFR's own official per-player season
table. This script reads those CSVs directly; it does not touch
football_db's per-game stat tables at all for the modern-era fit.

Multi-team players: PFR's own file already includes a "2TM"/"3TM" aggregate
row summing the full season alongside the per-team split rows -- kept the
aggregate, dropped the per-team splits, so no double-counting.

Position filter: dpvs/positions.py's map_position() (this project's existing,
single position-group mapper) != 'unknown' -- i.e. any of DE/OLB/DT/NT/MLB/
ILB/CB/S/etc, whatever this project already treats as defense anywhere else.
This is a DATA-CLEANING filter only (excluding offense/special-teams from the
pool) -- the fit itself is fully position-blind, one set of six weights, no
position interaction terms, per the user's standing rule this session
("we don't care about position group at all").

Label: AP 1st-Team or 2nd-Team All-Pro that season (gold.player_awards,
org='AP'), restricted to defensive positions on the award side too (same
DEF_POS set build_top15_award_overlap.py already uses) as a belt-and-suspenders
check against a rare offense/defense-both-sides player id collision.

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    PYTHONPATH=~/github/football/football_db/src python3 \
        scripts/fit_idi_additive_weights.py

Outputs:
    data_output/idi_additive_fit_dataset_1999_2024.csv   -- the fitting pool itself
    data_output/idi_additive_fit_weights.json            -- fitted coefficients + intercept
    data_output/idi_additive_top30_validation.csv        -- per-season hit-rate table
    data_output/idi_additive_dpoy_check.csv              -- per-season #1-vs-DPOY table
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dpvs.positions import map_position  # noqa: E402

PFREF_DEFENSE_DIR = Path.home() / "data/pfref/raw/season/player/defense"
DPOY_PATH = Path.home() / "data/pfref/ap_dpoy_voting.csv"
DATA_OUT = Path(__file__).resolve().parent.parent / "data_output"

SEASON_LO, SEASON_HI = 1999, 2024
MULTITEAM_RE = re.compile(r"^\d+TM$")

DEF_POS = {
    "CB", "DB", "DE", "DL", "DT", "EDGE", "FS", "ILB", "LB", "LCB", "LDE",
    "LDE/RDT", "LDT", "LE", "LILB", "LLB", "LOLB", "MLB", "NT", "OLB",
    "RCB", "RCB/SS", "RDE", "RDT", "RDT/LDE", "RILB", "RLB", "RLB/MLB",
    "ROLB", "ROLB/RILB", "S", "SAF", "SS",
}

# "pfr_tfl", not "run_stuff": this is PFR's own official, sack-inclusive
# tackles_loss stat (their raw CSV column is literally "tfl" -- the bronze
# scrape layer stays untouched per gamebooks_boxscores/docs/RUN_STUFFS_RENAME_PLAN.md
# SS7a point 2), a genuinely different number from this project's own
# non-sack "run_stuff" convention used everywhere else in this repo. Do not
# rename this to run_stuff -- it would misrepresent which stat is being fit.
STAT_COLS = ["tackle_total", "sacks", "pfr_tfl", "ff", "fr", "int"]


# 1999-2005 scrapes use an older, shorter PFR column-naming convention than
# 2006+ (confirmed: all 7 years share the exact same old header). Both
# conventions carry the same six raw stats -- this just normalizes column
# names so one loader handles both eras. Old format also repeats "yds" for
# both int_yards and fr_yards; pandas auto-suffixes the second occurrence
# ("yds.1"), which is fine since neither is used here (only fr count, not
# fr_yards, feeds the fit).
_OLD_FORMAT_RENAME = {
    "team": "team_abbrev", "player": "player_name", "pos": "position",
    "g": "games", "sk": "sack", "comb": "comb_tackles",
    "solo": "solo_tackles", "ast": "ast_tackles",
}


def load_season_defense(season: int) -> pd.DataFrame:
    path = PFREF_DEFENSE_DIR / f"defense_{season}.csv"
    df = pd.read_csv(path)
    if "team_abbrev" not in df.columns and "team" in df.columns:
        df = df.rename(columns=_OLD_FORMAT_RENAME)
    df = df[df["player_id"].notna()].copy()  # drop repeated header rows

    # Keep the season-aggregate row for traded players ("2TM"/"3TM"), drop
    # the per-team split rows for the same player_id -- the aggregate row
    # already sums the full season.
    df["_is_multiteam_agg"] = df["team_abbrev"].astype(str).str.match(MULTITEAM_RE)
    has_agg = df.groupby("player_id")["_is_multiteam_agg"].transform("any")
    df = df[df["_is_multiteam_agg"] | ~has_agg].copy()
    assert not df["player_id"].duplicated().any(), f"{season}: duplicate player_id after multi-team dedup"

    # 1999-2005 (old-format) numeric columns come back as object dtype --
    # some non-numeric artifact elsewhere in the raw CSV forces the whole
    # column to object on read, which then makes "+" on solo_tackles/
    # ast_tackles silently do STRING concatenation ("65"+"14"->"6514")
    # instead of addition. Force real numeric dtype before any arithmetic.
    for col in ("solo_tackles", "ast_tackles", "sack", "tfl", "ff", "fr", "int", "games"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["season"] = season
    df["tackle_total"] = df["solo_tackles"].fillna(0) + df["ast_tackles"].fillna(0)
    df["sacks"] = df["sack"].fillna(0)
    df["pfr_tfl"] = df["tfl"].fillna(0)  # PFR's own raw column is "tfl" -- see STAT_COLS comment above
    df["ff"] = df["ff"].fillna(0)
    df["fr"] = df["fr"].fillna(0)
    df["int"] = df["int"].fillna(0)
    df["position_group"] = df["position"].apply(map_position)
    df = df[df["position_group"] != "unknown"].copy()

    return df[["season", "player_id", "player_name", "position", "position_group",
               "games", "tackle_total", "sacks", "pfr_tfl", "ff", "fr", "int"]]


def build_fit_dataset() -> pd.DataFrame:
    frames = [load_season_defense(s) for s in range(SEASON_LO, SEASON_HI + 1)]
    df = pd.concat(frames, ignore_index=True)

    conn = psycopg2.connect(dbname="football")
    ap = pd.read_sql("""
        SELECT pa.season, pa.designation, pa.position, x.source_player_id AS player_id
        FROM gold.player_awards pa
        JOIN internal.player_xref x ON x.player_id = pa.player_id AND x.source_system = 'pfr'
        WHERE pa.org = 'AP' AND pa.designation IN ('1st Tm', '2nd Tm')
          AND pa.season BETWEEN %(lo)s AND %(hi)s
    """, conn, params={"lo": SEASON_LO, "hi": SEASON_HI})
    conn.close()
    ap = ap[ap["position"].isin(DEF_POS)]
    ap_keys = set(zip(ap["season"], ap["player_id"]))

    df["all_pro"] = [
        1 if (s, pid) in ap_keys else 0
        for s, pid in zip(df["season"], df["player_id"])
    ]
    return df


def fit_logistic(df: pd.DataFrame) -> tuple[dict, float]:
    X = df[STAT_COLS].to_numpy(dtype=float)
    y = df["all_pro"].to_numpy(dtype=int)

    # Standardize for solver stability/convergence only -- coefficients are
    # unscaled back to raw-count units immediately below before reporting.
    # Reporting the SCALED coefficients as-is would misrepresent them as
    # "points per raw unit" when they're actually "points per std-dev" --
    # exactly what the task brief says not to do.
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    clf = LogisticRegression(max_iter=5000, penalty=None)
    clf.fit(Xs, y)

    coef_scaled = clf.coef_[0]
    coef_raw = coef_scaled / scaler.scale_
    intercept_raw = clf.intercept_[0] - float(np.sum(coef_scaled * scaler.mean_ / scaler.scale_))

    weights = dict(zip(STAT_COLS, coef_raw.tolist()))
    return weights, intercept_raw


def score_df(df: pd.DataFrame, weights: dict) -> pd.Series:
    return sum(df[c] * w for c, w in weights.items())


def validate_top30(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    df = df.copy()
    df["score"] = score_df(df, weights)
    rows = []
    for season, g in df.groupby("season"):
        g = g.sort_values("score", ascending=False)
        real_ap = set(g[g["all_pro"] == 1]["player_id"])
        n_real_ap = len(real_ap)
        top30_ids = set(g.head(30)["player_id"])
        hit = len(top30_ids & real_ap)
        rows.append({
            "season": season,
            "n_defensive_player_seasons": len(g),
            "n_real_ap_1st_2nd": n_real_ap,
            "n_in_model_top30": hit,
            "hit_rate_of_real_ap": hit / n_real_ap if n_real_ap else np.nan,
        })
    return pd.DataFrame(rows)


def validate_dpoy(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    df = df.copy()
    df["score"] = score_df(df, weights)
    dpoy = pd.read_csv(DPOY_PATH)
    dpoy = dpoy[(dpoy["season"] >= SEASON_LO) & (dpoy["season"] <= SEASON_HI)]

    rows = []
    for season, g in df.groupby("season"):
        g = g.sort_values("score", ascending=False).reset_index(drop=True)
        model_top1 = g.iloc[0]
        model_top1_rank_among_all = 1

        winner_row = dpoy[(dpoy["season"] == season) & (dpoy["dpoy_voting_rank"] == 1)]
        winner_id = winner_row.iloc[0]["player_id"] if not winner_row.empty else None
        winner_name = winner_row.iloc[0]["player_name"] if not winner_row.empty else None

        model_rank_of_winner = None
        if winner_id is not None and winner_id in set(g["player_id"]):
            model_rank_of_winner = int(g.index[g["player_id"] == winner_id][0]) + 1

        rows.append({
            "season": season,
            "model_top1_player_id": model_top1["player_id"],
            "model_top1_player_name": model_top1["player_name"],
            "model_top1_score": round(model_top1["score"], 3),
            "real_dpoy_winner": winner_name,
            "real_dpoy_player_id": winner_id,
            "model_agrees_with_dpoy": (winner_id == model_top1["player_id"]) if winner_id else None,
            "model_rank_of_real_dpoy_winner": model_rank_of_winner,
        })
    return pd.DataFrame(rows)


def main():
    DATA_OUT.mkdir(exist_ok=True)

    print(f"Building fit dataset {SEASON_LO}-{SEASON_HI} from PFR official season-defense tables...")
    df = build_fit_dataset()
    print(f"  {len(df)} defensive player-seasons, {df['all_pro'].sum()} AP 1st/2nd Team labels "
          f"({100*df['all_pro'].mean():.2f}%)")
    df.to_csv(DATA_OUT / "idi_additive_fit_dataset_1999_2024.csv", index=False)

    print("\nFitting logistic regression (raw counts, unscaled coefficients)...")
    weights, intercept = fit_logistic(df)
    print("Fitted weights (points per raw unit):")
    for k, v in weights.items():
        print(f"  {k:15s} {v:+.4f}")
    print(f"  intercept       {intercept:+.4f}")

    with open(DATA_OUT / "idi_additive_fit_weights.json", "w") as f:
        json.dump({"weights": weights, "intercept": intercept,
                   "fit_seasons": [SEASON_LO, SEASON_HI],
                   "n_player_seasons": len(df), "n_all_pro": int(df["all_pro"].sum())}, f, indent=2)

    print("\nValidating: top-30-by-score vs real AP 1st/2nd Team, per season...")
    top30 = validate_top30(df, weights)
    top30.to_csv(DATA_OUT / "idi_additive_top30_validation.csv", index=False)
    print(top30.to_string(index=False))
    print(f"\nAggregate hit rate (real AP defenders landing in model's own top-30): "
          f"{top30['n_in_model_top30'].sum()}/{top30['n_real_ap_1st_2nd'].sum()} = "
          f"{100*top30['n_in_model_top30'].sum()/top30['n_real_ap_1st_2nd'].sum():.1f}%")
    print(f"Mean per-season hit rate: {100*top30['hit_rate_of_real_ap'].mean():.1f}%")

    print("\nValidating: model's own #1 defender vs real DPOY winner, per season...")
    dpoy_check = validate_dpoy(df, weights)
    dpoy_check.to_csv(DATA_OUT / "idi_additive_dpoy_check.csv", index=False)
    print(dpoy_check.to_string(index=False))
    n_agree = dpoy_check["model_agrees_with_dpoy"].sum()
    n_total = dpoy_check["model_agrees_with_dpoy"].notna().sum()
    print(f"\nModel #1 == real DPOY winner: {n_agree}/{n_total} seasons ({100*n_agree/n_total:.1f}%)")
    print(f"Wrote outputs to {DATA_OUT}")


if __name__ == "__main__":
    main()
