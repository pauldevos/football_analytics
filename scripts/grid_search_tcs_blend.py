#!/usr/bin/env python3
"""
Part 3 grid search: sweep the TCS position-weight tier-decay ratio AND the
outer TCS/IDI blend ratio, and score each combination on:
  (a) overlap % with the Part 2 "expected top-15" proxy pool
  (b) team-clustering (how many of a season's top-10 DPVS-G players share a team)
  (c) pooled YoY stability (season N -> season N+1 Pearson r)

Efficiency note: IDI (idi, idi_z, position_group) does NOT depend on the TCS
mechanism at all in this architecture (dpvs/idi.py computes it from
independent gold/gamebook/pbp sources, merged onto TCS only for its
season/team/pfr_player_id keys -- see build_dpvs_g.py Step 3). So idi_z is
IDENTICAL across every grid point and is reused as-is from the ALREADY-BUILT
~/data/silver/dpvs_g_player_season.parquet rather than recomputed 25 times.
Only tcs_z (from the new position-weighted total_credit) and the final
blend change per grid point -- this mirrors docs/deferred/01_tcs_idi_blend_
tuning.md's own stated optimization ("don't re-run the full pipeline for
every grid point").

Season sample: one per decade plus the session's known-important seasons
(see SAMPLE_SEASONS below) -- not the full 1967-2024 range, per the task's
own "use your judgment on a representative subset" allowance.

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    python3 scripts/grid_search_tcs_blend.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from dpvs.position_credit import compute_credit
from dpvs.composite import _zscore_within

SILVER_DIR = Path.home() / "data/silver"
INGREDIENTS_PATH = Path(__file__).parent.parent / "data_output" / "tcs_ingredients.parquet"
EXISTING_DPVS_G = SILVER_DIR / "dpvs_g_player_season.parquet"
PROXY_POOL_PATH = Path(__file__).parent.parent / "data_output" / "expected_top_pool.parquet"

DECAY_GRID = [0.5, 0.6, 0.65, 0.7, 0.8]
BLEND_GRID = [0.20, 0.25, 0.30, 0.35, 0.40]  # TCS weight; IDI = 1 - this
WINSOR = 4.0
MIN_GAMES = 6

# One season per decade + known-important seasons this session's spot-check
# roster and prior docs reference (Greene/Lambert 1974/1976, Shell 1978,
# Gradishar 1978, Watt 2012, Kuechly 2013, Donald 2018, Urlacher 2005,
# Lewis 2001/2003, Woodson 1994, Reed 2008, Singletary 1985/1988).
SAMPLE_SEASONS = sorted(set([
    1971, 1974, 1976, 1978,            # 1967-1977 gamebook era + Shell/Gradishar
    1985, 1988, 1994,                  # 1978-1998 pbp-derived era + Singletary/Woodson
    2001, 2003, 2005, 2008,            # 2001+ era: Lewis, Urlacher, Reed
    2012, 2013, 2018, 2024,            # Watt, Kuechly, Donald, most-recent
]))


def load_idi_scaffold() -> pd.DataFrame:
    df = pd.read_parquet(EXISTING_DPVS_G)
    df = df[df["season"].isin(SAMPLE_SEASONS)].copy()
    keep = ["season", "team", "pfr_player_id", "player_name", "pos", "position_group",
            "idi", "idi_z", "games_played"]
    return df[keep].drop_duplicates(subset=["season", "team", "pfr_player_id"])


def build_tcs_for_decay(ingredients: pd.DataFrame, decay: float) -> pd.DataFrame:
    credit_df = compute_credit(ingredients, decay=decay)
    grp = credit_df.groupby(
        ["season", "team", "pfr_player_id"], as_index=False
    ).agg(total_credit=("team_credit_share", "sum"), games_played_new=("game_id", "count"))
    grp["total_credit"] = grp["total_credit"].round(5)
    return grp


def zscore_tcs(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["tcs_z"] = np.nan
    for season, grp_idx in df.groupby(["season", "position_group"]).groups.items():
        mask = df.index.isin(grp_idx)
        df.loc[mask, "tcs_z"] = _zscore_within(df.loc[mask, "total_credit"]).clip(-WINSOR, WINSOR).values
    return df


def team_clustering(top10: pd.DataFrame) -> dict:
    """top10: season, team, ... rows (top-10 per season by composite).
    Returns {season: max_same_team_count}."""
    out = {}
    for season, grp in top10.groupby("season"):
        counts = grp["team"].value_counts()
        out[season] = int(counts.max()) if len(counts) else 0
    return out


def pooled_yoy_r(df: pd.DataFrame, col: str) -> float | None:
    d = df[["season", "pfr_player_id", col]].dropna()
    nxt = d.copy()
    nxt["season"] = nxt["season"] - 1
    nxt = nxt.rename(columns={col: f"{col}_next"})
    pairs = d.merge(nxt[["season", "pfr_player_id", f"{col}_next"]],
                     on=["season", "pfr_player_id"], how="inner")
    if len(pairs) < 10:
        return None
    return float(pairs[col].corr(pairs[f"{col}_next"]))


def proxy_overlap(top15: pd.DataFrame, proxy_pool: set[tuple[int, str]]) -> float:
    if not proxy_pool:
        return float("nan")
    hits = sum(1 for r in top15.itertuples()
               if (r.season, r.pfr_player_id) in proxy_pool)
    return 100.0 * hits / len(top15) if len(top15) else float("nan")


def main():
    print("Loading ingredients + IDI scaffold...")
    ingredients = pd.read_parquet(INGREDIENTS_PATH)
    ingredients = ingredients[ingredients["season"].isin(SAMPLE_SEASONS)].copy()
    idi_scaffold = load_idi_scaffold()
    print(f"  ingredients: {len(ingredients):,} rows (sample seasons only)")
    print(f"  idi scaffold: {len(idi_scaffold):,} player-seasons")

    proxy_pool = set()
    if PROXY_POOL_PATH.exists():
        pp = pd.read_parquet(PROXY_POOL_PATH)
        proxy_pool = set(zip(pp["season"], pp["pfr_player_id"]))
        print(f"  proxy pool: {len(proxy_pool):,} (season, pfr_player_id) entries")
    else:
        print("  WARNING: no proxy pool found -- run build_expected_top_pool.py first; overlap% will be NaN")

    results = []
    for decay in DECAY_GRID:
        tcs_new = build_tcs_for_decay(ingredients, decay)
        merged = idi_scaffold.merge(tcs_new, on=["season", "team", "pfr_player_id"], how="inner")
        merged = merged[merged["games_played_new"] >= MIN_GAMES].copy()
        merged = zscore_tcs(merged)

        for blend in BLEND_GRID:
            m = merged.dropna(subset=["tcs_z", "idi_z"]).copy()
            m["composite"] = blend * m["tcs_z"] + (1 - blend) * m["idi_z"]
            m["season_rank"] = m.groupby("season")["composite"].rank(ascending=False, method="min")

            top10 = m[m["season_rank"] <= 10]
            top15 = m[m["season_rank"] <= 15]

            clustering = team_clustering(top10)
            avg_cluster = np.mean(list(clustering.values())) if clustering else float("nan")
            max_cluster = max(clustering.values()) if clustering else 0
            n_4plus = sum(1 for v in clustering.values() if v >= 4)

            r_yoy = pooled_yoy_r(m, "composite")
            overlap = proxy_overlap(top15, proxy_pool)

            results.append({
                "decay": decay, "blend_tcs": blend,
                "avg_top10_cluster": round(avg_cluster, 2),
                "max_top10_cluster": max_cluster,
                "seasons_with_4plus_cluster": n_4plus,
                "n_seasons": len(clustering),
                "yoy_pooled_r": round(r_yoy, 3) if r_yoy is not None else None,
                "proxy_overlap_pct": round(overlap, 1) if not np.isnan(overlap) else None,
                "n_scored_player_seasons": len(m),
            })
            print(f"decay={decay:.2f} blend={blend:.2f}  "
                  f"avg_cluster={avg_cluster:.2f}  max={max_cluster}  4+={n_4plus}/{len(clustering)}  "
                  f"yoy_r={r_yoy}  proxy%={overlap:.1f}" if not np.isnan(overlap) else "")

    out = pd.DataFrame(results)
    out_path = Path(__file__).parent.parent / "data_output" / "tcs_grid_search_results.csv"
    out.to_csv(out_path, index=False)
    print(f"\nWrote {out_path}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
