#!/usr/bin/env python3
"""
build_player_rankings.py
------------------------
Builds player-season tackle analytics and position-era z-score rankings.

Reads: ~/data/silver/tackle_events_enriched.parquet

Outputs:
  ~/data/silver/player_season_stats.parquet   — per player-season counts + EPA
  ~/data/silver/position_era_baselines.parquet— mean/SD by position × season
  ~/data/silver/player_season_rankings.parquet— z-scores vs position peers

Minimum tackles to qualify for z-score ranking: 20.
Only defensive positions (DL / LB / DB) are ranked.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SILVER_DIR  = Path("/Users/devos/data/silver")
EVENTS_PATH = SILVER_DIR / "tackle_events_enriched.parquet"

MIN_TACKLES     = 30   # minimum to qualify for z-score ranking
MIN_PEERS       = 10   # minimum peers in a position-season to compute z-score
QUALITY_PLAYS   = {"run", "pass", "sack"}  # exclude special teams from quality metrics

ERA_BREAKS = [1977, 1993, 2010]  # splits → 1978–1993, 1994–2010, 2011+

def assign_era(season: int) -> str:
    if season <= 1977: return "pre-1978"
    if season <= 1993: return "1978-1993"
    if season <= 2010: return "1994-2010"
    return "2011+"


def main():
    print("Loading tackle_events_enriched...")
    ev = pd.read_parquet(EVENTS_PATH)
    print(f"  {len(ev):,} rows, seasons {ev['season'].min()}–{ev['season'].max()}")

    ev["season"] = pd.to_numeric(ev["season"], errors="coerce").astype(int)
    ev["epa"]    = pd.to_numeric(ev["epa_def_share"], errors="coerce")
    ev["yards"]  = pd.to_numeric(ev["yards_gained"],  errors="coerce")
    ev["solo"]   = ev["is_solo"].astype(bool)

    # Restrict to defensive positions for ranking
    def_ev = ev[ev["pos_group_filled"].isin(["DL", "LB", "DB"])].copy()
    print(f"  Defensive events: {len(def_ev):,}")

    # Quality-only subset: run + pass + sack (excludes special teams)
    qual_ev = def_ev[def_ev["play_type"].isin(QUALITY_PLAYS)].copy()
    print(f"  Quality-play events (run/pass/sack): {len(qual_ev):,}")

    # ── Player-season stats ───────────────────────────────────────────────────
    print("\nAggregating player-season stats...")

    key_cols = ["pfr_player_id", "tackler_name", "season", "pos_group_filled", "team_filled"]

    # Total tackles from all plays (volume)
    grp_all = def_ev.groupby(key_cols, sort=False)
    stats = grp_all.agg(
        tackles      = ("epa",  "count"),
        solo_tackles = ("solo", "sum"),
        epa_total    = ("epa",  "sum"),
    ).reset_index()

    # Quality metrics only from run+pass+sack
    grp_q = qual_ev.groupby(key_cols, sort=False)
    q_stats = grp_q.agg(
        q_tackles    = ("epa",   "count"),
        epa_per_tack = ("epa",   "mean"),
        avg_yards    = ("yards", "mean"),
    ).reset_index()
    stats = stats.merge(q_stats, on=key_cols, how="left")

    # Run / pass breakdown (quality plays)
    for ptype, label in [("run", "run"), ("pass", "pass")]:
        sub = qual_ev[qual_ev["play_type"] == ptype].groupby(key_cols, sort=False).agg(
            n    = ("epa", "count"),
            epa  = ("epa", "mean"),
            yds  = ("yards", "mean"),
        ).reset_index().rename(columns={"n": f"{label}_n", "epa": f"{label}_epa", "yds": f"{label}_yds"})
        stats = stats.merge(sub, on=key_cols, how="left")

    stats["solo_rate"] = (stats["solo_tackles"] / stats["tackles"]).round(3)
    stats["era"]       = stats["season"].apply(assign_era)

    # W/L split from enriched
    wl = def_ev[def_ev["game_result"].isin(["W","L"])].groupby(
        ["pfr_player_id","tackler_name","season","pos_group_filled","team_filled","game_result"]
    ).agg(epa_wl=("epa","mean"), n_wl=("epa","count")).reset_index()
    wl_wide = wl.pivot_table(
        index=["pfr_player_id","tackler_name","season","pos_group_filled","team_filled"],
        columns="game_result", values=["epa_wl","n_wl"]
    )
    wl_wide.columns = ["_".join(c).strip() for c in wl_wide.columns]
    wl_wide = wl_wide.rename(columns={
        "epa_wl_W": "epa_in_wins", "epa_wl_L": "epa_in_losses",
        "n_wl_W":   "tackles_in_wins", "n_wl_L": "tackles_in_losses",
    }).reset_index()
    stats = stats.merge(wl_wide, on=["pfr_player_id","tackler_name","season","pos_group_filled","team_filled"], how="left")

    out1 = SILVER_DIR / "player_season_stats.parquet"
    stats.to_parquet(out1, index=False)
    print(f"  Saved {len(stats):,} player-seasons → {out1}")

    # ── Position × season baselines ──────────────────────────────────────────
    print("\nComputing position-era baselines...")
    qualified = stats[stats["tackles"] >= MIN_TACKLES]

    baselines = qualified.groupby(["pos_group_filled", "season"]).agg(
        n_players    = ("tackles",      "count"),
        epa_mean     = ("epa_per_tack", "mean"),
        epa_std      = ("epa_per_tack", "std"),
        epa_tot_mean = ("epa_total",    "mean"),
        epa_tot_std  = ("epa_total",    "std"),
        yards_mean   = ("avg_yards",    "mean"),
        yards_std    = ("avg_yards",    "std"),
        tackles_mean = ("tackles",      "mean"),
        tackles_std  = ("tackles",      "std"),
    ).reset_index()

    # Also compute era-level baselines (for seasons with few players)
    baselines["era"] = baselines["season"].apply(assign_era)
    era_base = qualified.groupby(["pos_group_filled", "era"]).agg(
        era_epa_mean  = ("epa_per_tack", "mean"),
        era_epa_std   = ("epa_per_tack", "std"),
        era_yards_mean= ("avg_yards",    "mean"),
        era_yards_std = ("avg_yards",    "std"),
    ).reset_index()

    out2 = SILVER_DIR / "position_era_baselines.parquet"
    baselines.to_parquet(out2, index=False)
    print(f"  Saved {len(baselines):,} position-season baselines → {out2}")

    # ── Z-score rankings ──────────────────────────────────────────────────────
    print("\nComputing z-scores...")
    ranked = qualified.copy()
    ranked = ranked.merge(
        baselines[["pos_group_filled","season","n_players","epa_mean","epa_std","yards_mean","yards_std","epa_tot_mean","epa_tot_std"]],
        on=["pos_group_filled","season"], how="left"
    )

    # Only compute z where enough peers exist
    enough = ranked["n_players"] >= MIN_PEERS

    ranked["epa_zscore"]   = np.where(
        enough & (ranked["epa_std"] > 0),
        (ranked["epa_per_tack"] - ranked["epa_mean"]) / ranked["epa_std"],
        np.nan
    )
    ranked["yards_zscore"] = np.where(
        enough & (ranked["yards_std"] > 0),
        # lower yards allowed = better → flip sign
        -1 * (ranked["avg_yards"] - ranked["yards_mean"]) / ranked["yards_std"],
        np.nan
    )
    ranked["vol_zscore"] = np.where(
        enough & (ranked["epa_tot_std"] > 0),
        (ranked["epa_total"] - ranked["epa_tot_mean"]) / ranked["epa_tot_std"],
        np.nan
    )
    # Composite: 60% EPA quality + 40% volume
    ranked["composite_score"] = (
        0.6 * ranked["epa_zscore"].fillna(0) +
        0.4 * ranked["vol_zscore"].fillna(0)
    )
    ranked.loc[ranked["epa_zscore"].isna() | ranked["vol_zscore"].isna(), "composite_score"] = np.nan

    out3 = SILVER_DIR / "player_season_rankings.parquet"
    ranked.to_parquet(out3, index=False)
    print(f"  Saved {len(ranked):,} ranked player-seasons → {out3}")

    # ── Top 10 per position per season ───────────────────────────────────────
    print("\nGenerating top-10 per position per season...")
    display_cols = ["tackler_name","season","team_filled","tackles",
                    "epa_per_tack","avg_yards","epa_zscore","yards_zscore","composite_score"]

    # Top 10 per position × season (for season tables)
    season_tops = (
        ranked[ranked["composite_score"].notna()]
        .sort_values("composite_score", ascending=False)
        .groupby(["pos_group_filled","season"])
        .head(10)
        .reset_index(drop=True)
    )
    out4 = SILVER_DIR / "top10_by_position_season.parquet"
    season_tops.to_parquet(out4, index=False)
    print(f"  Saved → {out4}")

    # ── All-time top 20 per position ──────────────────────────────────────────
    for pos in ["DL", "LB", "DB"]:
        sub = ranked[(ranked["pos_group_filled"] == pos) & ranked["composite_score"].notna()]
        print(f"\n{'='*60}")
        print(f"All-time top 20 {pos} seasons  (min {MIN_TACKLES} tackles, quality plays only)")
        print("="*60)
        top = sub.nlargest(20, "composite_score")[display_cols]
        top = top.round({"epa_per_tack":3,"avg_yards":2,"epa_zscore":2,"yards_zscore":2,"composite_score":2})
        print(top.to_string(index=False))

    # ── Era top-10 per position ────────────────────────────────────────────────
    for era in ["1978-1993","1994-2010","2011+"]:
        era_ranked = ranked[(ranked["era"] == era) & ranked["composite_score"].notna()]
        if era_ranked.empty:
            continue
        print(f"\n{'='*60}")
        print(f"Top 10 per position — {era}")
        print("="*60)
        for pos in ["DL","LB","DB"]:
            sub = era_ranked[era_ranked["pos_group_filled"] == pos].nlargest(10, "composite_score")
            if sub.empty: continue
            print(f"\n  {pos}:")
            print(sub[display_cols].round({"epa_per_tack":3,"avg_yards":2,"epa_zscore":2,"yards_zscore":2,"composite_score":2}).to_string(index=False))

    # ── Star player spotlight ─────────────────────────────────────────────────
    STARS = {
        "Lawrence Taylor":  "LB",
        "Reggie White":     "DL",
        "Ray Lewis":        "LB",
        "Derrick Thomas":   "LB",
        "Myles Garrett":    "DL",
        "Keith Millard":    "DL",
        "Ronnie Lott":      "DB",
        "Terrell Suggs":    "LB",
        "Bryant Young":     "DL",
        "Darren Woodson":   "DB",
        "Rod Woodson":      "DB",
        "Joey Browner":     "DB",
        "Scott Studwell":   "LB",
        "Aaron Donald":     "DL",
        "J.J. Watt":        "DL",
        "Von Miller":       "LB",
        "Brian Urlacher":   "LB",
        "Patrick Willis":   "LB",
        "Troy Polamalu":    "DB",
        "Ed Reed":          "DB",
    }

    print(f"\n{'='*60}")
    print("STAR PLAYER CAREER RANKINGS")
    print("="*60)
    print(f"{'Player':<22} {'Pos':<4} {'Seasons':<10} {'Best Z':<8} {'Best season':<12} {'Career avg Z'}")
    print("-"*70)

    star_rows = []
    for name, pos in sorted(STARS.items(), key=lambda x: x[1]+x[0]):
        mask = ranked["tackler_name"].str.contains(name, case=False, na=False)
        p_rows = ranked[mask & (ranked["pos_group_filled"] == pos) & ranked["composite_score"].notna()]
        if p_rows.empty:
            print(f"  {name:<22} {pos:<4}  NOT FOUND (below {MIN_TACKLES}-tackle threshold)")
            continue
        best = p_rows.loc[p_rows["composite_score"].idxmax()]
        n_seasons = len(p_rows)
        avg_z = p_rows["composite_score"].mean()
        print(f"  {name:<22} {pos:<4}  {n_seasons:<10} {best['composite_score']:<8.2f} {int(best['season']):<12} {avg_z:.2f}")
        star_rows.append(p_rows.assign(star=name))

    # Full season-by-season table for each star
    print(f"\n{'='*60}")
    print("SEASON-BY-SEASON DETAIL FOR STARS")
    print("="*60)
    detail_cols = ["tackler_name","season","team_filled","tackles","q_tackles",
                   "epa_per_tack","avg_yards","run_epa","pass_epa",
                   "epa_zscore","yards_zscore","composite_score"]
    for name, pos in sorted(STARS.items(), key=lambda x: x[1]+x[0]):
        mask = ranked["tackler_name"].str.contains(name, case=False, na=False)
        p_rows = ranked[mask & (ranked["pos_group_filled"] == pos)].sort_values("season")
        if p_rows.empty:
            continue
        print(f"\n── {name} ({pos}) ──")
        avail = [c for c in detail_cols if c in p_rows.columns]
        print(p_rows[avail].round({
            "epa_per_tack":3,"avg_yards":2,"run_epa":3,"pass_epa":3,
            "epa_zscore":2,"yards_zscore":2,"composite_score":2,
        }).to_string(index=False))

    print("\nDone.")


if __name__ == "__main__":
    main()
