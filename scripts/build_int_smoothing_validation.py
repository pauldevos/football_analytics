#!/usr/bin/env python3
"""
Part B of the 2026-08-24 TCS/INT session: validates INT trailing-window
smoothing (dpvs/int_smoothing.py) by substituting the smoothed count into
scripts/fit_idi_additive_weights.py's already-fitted additive formula
(score = 0.0225*tackle + 0.2358*sacks + 0.1338*pfr_tfl + 0.1671*ff + 0.1227*fr
+ 0.6808*int) in place of the raw single-season int -- every other stat and
every weight (including INT's own 0.6808) held fixed, so this isolates the
smoothing's own effect rather than confounding it with a full refit.

Re-runs the SAME top-30-vs-AP-All-Pro and #1-vs-real-DPOY validation
fit_idi_additive_weights.py already used for the raw-int baseline
(data_output/idi_additive_top30_validation.csv /
idi_additive_dpoy_check.csv), for both N=5 and N=7 windows, 1999-2024.

Also prints the direct before/after for the case this task is named after
(Charlie West, MIN, 1971) and a real sustained-production control case in
the SAME team-season (Paul Krause, MIN FS, 1971 -- NFL's all-time career
INT leader) using the three gamebook-era spot-check team-seasons' own
additive-score tables (data_output/additive_score_1971_min.csv etc.,
already built by scripts/apply_idi_additive_weights_gamebook_era.py).

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    PYTHONPATH=~/github/football/football_db/src python3 \
        scripts/build_int_smoothing_validation.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import psycopg2  # noqa: E402
from dpvs.int_smoothing import load_int_history, add_trailing_int  # noqa: E402
from fit_idi_additive_weights import (  # noqa: E402
    validate_top30, validate_dpoy, STAT_COLS,
)
from apply_idi_additive_weights_gamebook_era import (  # noqa: E402
    load_official_sack_int_fr, load_prorated_run_stuff_ff_tackles, TARGETS,
)

# STAT_COLS (imported above) is keyed "pfr_tfl" -- PFR's own official,
# sack-inclusive season stat that fit_idi_additive_weights.py actually fit
# against. The gamebook-era section below has no PFR official tackle-for-loss
# data for 1971/1972/1974 (predates PFR's 1999+ tackles_loss column), so --
# same substitution apply_idi_additive_weights_gamebook_era.py's own main()
# makes -- it applies that fitted weight, out-of-sample, to
# load_prorated_run_stuff_ff_tackles()'s "run_stuff" column (this project's
# own non-sack proxy) as the best available stand-in for this era. This map
# is what actually performs that substitution when scoring `merged` below.
GAMEBOOK_STAT_COL = {c: ("run_stuff" if c == "pfr_tfl" else c) for c in STAT_COLS}

DATA_OUT = Path(__file__).resolve().parent.parent / "data_output"
WEIGHTS_PATH = DATA_OUT / "idi_additive_fit_weights.json"
FIT_DATASET_PATH = DATA_OUT / "idi_additive_fit_dataset_1999_2024.csv"

WINDOWS = (5, 7)


def build_smoothed_fit_dataset() -> pd.DataFrame:
    df = pd.read_csv(FIT_DATASET_PATH)
    # Need history well before 1999 to fill trailing windows for players
    # whose careers started earlier -- load the full 1950-2025 range once.
    hist = load_int_history(1950, 2025)
    hist = add_trailing_int(hist, windows=WINDOWS)
    hist = hist[["season", "player_id"] + [f"int_smooth{n}" for n in WINDOWS]]
    merged = df.merge(hist, on=["season", "player_id"], how="left")
    for n in WINDOWS:
        # A player missing from the history file entirely for some reason
        # (shouldn't happen -- same source as `int` itself) falls back to
        # their own raw int rather than a silent NaN/0.
        merged[f"int_smooth{n}"] = merged[f"int_smooth{n}"].fillna(merged["int"])
    return merged


def run_variant(df: pd.DataFrame, weights: dict, int_col: str, label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    # validate_top30/validate_dpoy compute "score" from STAT_COLS via the
    # literal column name "int" -- so build a frame where the "int" column
    # IS the (possibly smoothed) value being tested, every other stat and
    # every weight (including int's own 0.6808) unchanged.
    swapped = df.copy()
    swapped["int"] = swapped[int_col]
    top30 = validate_top30(swapped, weights)
    dpoy = validate_dpoy(swapped, weights)
    hit_rate = top30["n_in_model_top30"].sum() / top30["n_real_ap_1st_2nd"].sum()
    n_agree = dpoy["model_agrees_with_dpoy"].sum()
    n_total = dpoy["model_agrees_with_dpoy"].notna().sum()
    print(f"\n=== {label} ===")
    print(f"  Top-30 hit rate (real AP All-Pro landing in model top-30): "
          f"{top30['n_in_model_top30'].sum()}/{top30['n_real_ap_1st_2nd'].sum()} "
          f"= {100*hit_rate:.1f}%   (mean per-season: {100*top30['hit_rate_of_real_ap'].mean():.1f}%)")
    print(f"  Model #1 == real DPOY winner: {n_agree}/{n_total} ({100*n_agree/n_total:.1f}%)")
    return top30, dpoy


def gamebook_era_case(team_label: str, path: Path, target_names: list[str]):
    if not path.exists():
        print(f"  (missing {path}, skipping)")
        return
    df = pd.read_csv(path)
    for name in target_names:
        row = df[df["player_name"] == name]
        if row.empty:
            print(f"  {name}: not found in {path.name}")
            continue
        r = row.iloc[0]
        print(f"  {name:16s} rank={int(r['rank']):<3d} raw_int={r['int']:.1f}  "
              f"score(raw)={r['score']:.3f}")


def main():
    weights_blob = json.loads(WEIGHTS_PATH.read_text())
    weights = weights_blob["weights"]
    print("Loaded fitted weights (unchanged -- same weight applied to smoothed int):")
    for k, v in weights.items():
        print(f"  {k:15s} {v:+.4f}")

    print("\nBuilding smoothed 1999-2024 fit dataset (trailing INT windows N=5,7)...")
    df = build_smoothed_fit_dataset()
    df.to_csv(DATA_OUT / "idi_additive_fit_dataset_int_smoothed.csv", index=False)
    print(f"  {len(df):,} player-seasons")

    print("\n--- BASELINE (raw single-season int, from fit_idi_additive_weights.py) ---")
    top30_base, dpoy_base = run_variant(df, weights, "int", "Baseline (raw int)")

    results = {"baseline": (top30_base, dpoy_base)}
    for n in WINDOWS:
        t30, dp = run_variant(df, weights, f"int_smooth{n}", f"Trailing N={n}")
        results[f"n{n}"] = (t30, dp)

    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)
    print(f"{'variant':20s} {'top30_hit%':>12s} {'dpoy_agree%':>14s}")
    for label, (t30, dp) in results.items():
        hr = 100 * t30["n_in_model_top30"].sum() / t30["n_real_ap_1st_2nd"].sum()
        n_agree = dp["model_agrees_with_dpoy"].sum()
        n_total = dp["model_agrees_with_dpoy"].notna().sum()
        print(f"{label:20s} {hr:11.1f}% {100*n_agree/n_total:13.1f}%")

    # ── Charlie West 1971 / Paul Krause 1971 real before/after ────────────
    print("\n" + "=" * 70)
    print("1971 MIN -- Charlie West (the case this task is named after) vs.")
    print("Paul Krause (real sustained-production control, same team-season)")
    print("=" * 70)
    hist = load_int_history(1950, 2025)
    hist = add_trailing_int(hist, windows=WINDOWS)

    for pid, name in [("WestCh20", "Charlie West"), ("KrauPa00", "Paul Krause")]:
        trace = hist[(hist["player_id"] == pid) & (hist["season"] <= 1971)].sort_values("season")
        print(f"\n{name} ({pid}) -- real season-by-season int through 1971:")
        print(trace[["season", "int", "int_smooth5", "int_smooth7"]].to_string(index=False))
        row71 = trace[trace["season"] == 1971].iloc[0]
        raw_score_int_component = weights["int"] * row71["int"]
        smooth5_component = weights["int"] * row71["int_smooth5"]
        smooth7_component = weights["int"] * row71["int_smooth7"]
        print(f"  1971 raw int={row71['int']:.0f} -> INT-component of score: "
              f"raw={raw_score_int_component:.3f}  N5={smooth5_component:.3f}  N7={smooth7_component:.3f}")

    print("\n1971 MIN full team rank comparison (raw score already in "
          "data_output/additive_score_1971_min.csv) -- West/Krause raw ranks:")
    gamebook_era_case("1971 MIN", DATA_OUT / "additive_score_1971_min.csv",
                       ["Charlie West", "Paul Krause"])

    # ── Full team-season rank tables, raw vs. smoothed, all 3 gamebook-era
    #    spot-check team-seasons ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("FULL TEAM-SEASON RANK TABLES -- raw vs. N=5/N=7-smoothed int")
    print("=" * 70)
    conn = psycopg2.connect(dbname="football")
    for fid, season, abbrev in TARGETS:
        print(f"\n--- {season} {abbrev} ---")
        official = load_official_sack_int_fr(season, abbrev)
        prorated, diag = load_prorated_run_stuff_ff_tackles(conn, fid, season)
        merged = prorated.merge(official, left_on="pfr_id", right_on="player_id",
                                 how="outer", suffixes=("", "_off"))
        merged["player_name"] = merged["player_name"].fillna(merged["player_name_off"])
        for c in ("run_stuff", "ff", "tackle_total"):
            merged[c] = merged[c].fillna(0)
        for c in ("sacks_official", "fr_official", "int_official"):
            merged[c] = merged[c].fillna(0)
        merged = merged.rename(columns={"sacks_official": "sacks", "fr_official": "fr",
                                         "int_official": "int"})
        merged["_pid"] = merged["pfr_id"].fillna(merged["player_id"])

        trace_n = hist[hist["season"] <= season]
        latest = trace_n.sort_values("season").groupby("player_id").tail(1)
        latest = latest.set_index("player_id")[[f"int_smooth{n}" for n in WINDOWS]]
        merged = merged.merge(latest, left_on="_pid", right_index=True, how="left")
        for n in WINDOWS:
            merged[f"int_smooth{n}"] = merged[f"int_smooth{n}"].fillna(merged["int"])

        merged["score_raw"] = sum(merged[GAMEBOOK_STAT_COL[c]] * weights[c] for c in STAT_COLS)
        for n in WINDOWS:
            cols = {c: (f"int_smooth{n}" if c == "int" else GAMEBOOK_STAT_COL[c]) for c in STAT_COLS}
            merged[f"score_n{n}"] = sum(merged[cols[c]] * weights[c] for c in STAT_COLS)

        for score_col, label in [("score_raw", "RAW"), ("score_n5", "N=5"), ("score_n7", "N=7")]:
            ranked = merged.sort_values(score_col, ascending=False).reset_index(drop=True)
            ranked["rank"] = ranked.index + 1
            top5 = ranked.head(5)[["rank", "player_name", "int", score_col]]
            print(f"  {label} top-5: " + " | ".join(
                f"#{int(r['rank'])} {r['player_name']} ({r[score_col]:.2f})"
                for _, r in top5.iterrows()
            ))
    conn.close()

    print(f"\nWrote {DATA_OUT / 'idi_additive_fit_dataset_int_smoothed.csv'}")


if __name__ == "__main__":
    main()
