"""
DPVS-G composite score and z-score normalization.

All three components are z-scored within season only (full league, all
position groups together, as of the 2026-08-23 §22 fix -- see
z_score_components()'s docstring for why the earlier season × position_group
version was a real bug, not a design choice). This makes the final number
directly interpretable:

  DPVS-G = 0   → league average that season
  DPVS-G = +2  → two standard deviations above average — historically elite

Three metric variants are computed:

  DPVS-G  — original: team context equally credited to all positions
    No-WOWY:  0.60 × TCS_z + 0.40 × IDI_z
    With-WOWY: 0.50 × TCS_z + 0.30 × IDI_z + 0.20 × WOWY_z

  DPVS-A  — individual-weighted: doubles IDI, reduces team context
    No-WOWY:  (0.25 × TCS_z + 0.50 × IDI_z) / 0.75
    With-WOWY: 0.25 × TCS_z + 0.50 × IDI_z + 0.25 × WOWY_z

  DPVS-P  — positional: run/pass defensive credit split by position responsibility
    PTCS_z replaces TCS_z; run-stoppers credit more from run D, coverage more from pass D
    No-WOWY:  0.60 × PTCS_z + 0.40 × IDI_z
    With-WOWY: 0.50 × PTCS_z + 0.30 × IDI_z + 0.20 × WOWY_z

Confidence flags:
  'high'    — TCS + IDI (gamebook tackles) + WOWY
  'medium'  — TCS + IDI (gamebook tackles) only; or TCS + IDI + WOWY without gamebook
  'low'     — TCS only; or missing-season flags (1982, 1987 strikes)
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from .positions import map_position

# ── weights ────────────────────────────────────────────────────────────────────

# DPVS-G
# 2026-08-23 TCS rebuild (position-weighted run/pass credit split, replacing
# the flat tdgs/n_parts equal split -- see dpvs/position_credit.py and
# docs/framework_decisions.md's TCS rebuild section): outer TCS/IDI blend
# re-tuned via a 5x5 grid search (decay ratio x blend ratio, see
# scripts/grid_search_tcs_blend.py and its data_output/tcs_grid_search_
# results.csv) over docs/deferred/01_tcs_idi_blend_tuning.md's originally
# scoped 0.20-0.40 TCS range. 0.25 TCS / 0.75 IDI chosen: team-clustering
# and pooled YoY stability both degrade monotonically as TCS weight rises
# (0.20 was marginally best on both, 0.25 a close second with meaningfully
# better proxy-pool overlap -- see the grid results), and the decay ratio
# itself showed low sensitivity across 0.5-0.8, so it's left at the user's
# original 0.65 production value.
#
# WOWY is EXCLUDED from the primary DPVS-G composite entirely, not just
# down-weighted -- per the user's explicit instruction this pass (pooled
# YoY r=0.023 for wowy_z, near pure noise; see TCS_MECHANISM_EXPLAINED
# §4.3-4.4). _compute_dpvs_g_row() below always uses the no-WOWY formula
# now, regardless of whether wowy_z is available for a row -- there is no
# more per-row WOWY/no-WOWY branch for DPVS-G specifically. _W_FULL is kept
# only as a documented historical reference / for any future revisit; it is
# no longer read by _compute_dpvs_g_row().
_W_FULL    = {"tcs_z": 0.50, "idi_z": 0.30, "wowy_z": 0.20}  # historical, unused by DPVS-G as of 2026-08-23
_W_NO_WOWY = {"tcs_z": 0.25, "idi_z": 0.75}

# DPVS-A (individual-weighted)
_WA_FULL    = {"tcs_z": 0.25, "idi_z": 0.50, "wowy_z": 0.25}
_WA_NO_WOWY = {"tcs_z": 0.25, "idi_z": 0.50}  # rescaled ÷0.75 at compute time

# DPVS-P (positional run/pass split); outer formula weights same as DPVS-G
_WP_FULL    = {"ptcs_z": 0.50, "idi_z": 0.30, "wowy_z": 0.20}
_WP_NO_WOWY = {"ptcs_z": 0.60, "idi_z": 0.40}

# Position-group fractions of run/pass team credit (empirically derived from
# AP1 selection correlations with team run_def_z / pass_def_z, 1970-1977).
# Original intuitive values: run_stopper 0.65/0.10, pass_rusher 0.20/0.50,
# coverage 0.15/0.40 — data shows weights are far more balanced than intuition.
_POS_RUN_CREDIT  = {"run_stopper": 0.411, "pass_rusher": 0.326, "coverage": 0.263}
_POS_PASS_CREDIT = {"run_stopper": 0.321, "pass_rusher": 0.308, "coverage": 0.370}

_STRIKE_YEARS = {1982, 1987}


# ── z-score helper ─────────────────────────────────────────────────────────────

def _zscore_within(series: pd.Series) -> pd.Series:
    mu = series.mean()
    sigma = series.std(ddof=1)
    if sigma == 0 or pd.isna(sigma):
        return pd.Series(0.0, index=series.index)
    return (series - mu) / sigma


_WINSOR_SIGMA = 4.0  # clip extreme z-scores (e.g., card_back INT outliers)


def compute_run_pass_context(game_df: pd.DataFrame) -> pd.DataFrame:
    """
    From per-game team defense data, compute per-team-season run/pass
    defensive quality z-scores (positive = better than league average).

    Returns DataFrame: season, team, run_def_z, pass_def_z
    """
    df = game_df.copy()
    if "is_regular_season" in df.columns:
        df = df[df["is_regular_season"]]
    df = df.dropna(subset=["rush_yds_allowed", "rush_att_vs",
                            "pass_yds_allowed", "att_vs"])
    agg = df.groupby(["season", "team"], as_index=False).agg(
        rush_yds=("rush_yds_allowed", "sum"),
        rush_att=("rush_att_vs", "sum"),
        pass_yds=("pass_yds_allowed", "sum"),
        pass_att=("att_vs", "sum"),
    )
    agg["rush_ypa"] = agg["rush_yds"] / agg["rush_att"].replace(0, np.nan)
    agg["pass_ypa"] = agg["pass_yds"] / agg["pass_att"].replace(0, np.nan)

    agg["run_def_z"] = np.nan
    agg["pass_def_z"] = np.nan
    for season, idx in agg.groupby("season").groups.items():
        mask = agg.index.isin(idx)
        # Negate: fewer yards per attempt allowed → positive z-score
        agg.loc[mask, "run_def_z"]  = -_zscore_within(agg.loc[mask, "rush_ypa"]).values
        agg.loc[mask, "pass_def_z"] = -_zscore_within(agg.loc[mask, "pass_ypa"]).values

    return agg[["season", "team", "run_def_z", "pass_def_z"]]


def z_score_components(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add tcs_z, idi_z, wowy_z columns to df by z-scoring within season only
    (full league, all position groups together). Z-scores are winsorized at
    ±4σ to prevent single-player outliers (e.g., a card_back-sourced INT
    spike) from compressing the entire distribution.

    2026-08-23 (§22): changed from (season × position_group) to season-only.
    The old position-grouped z-scoring reproduced the exact Donnie Shell
    sack_component_z=4.0 bug one layer up: coverage has the smallest idi
    standard deviation of the three position groups in 58/58 measurable
    seasons (structural -- DBs rarely record sack/TFL/FF/FR), so the same
    absolute gap-above-mean produced a much larger idi_z there than for
    run_stopper/pass_rusher, and that's what actually put Shell's 1978 at
    #2 overall (idi=0.750, a real, correctly-computed, position-blind
    number, 2.5x lower than #1 Randy White's idi=1.833). Per the user's
    explicit rule -- "There shouldn't be ANY z-score by position at all for
    these stats... we don't care about position group at all" -- this
    applies to the composite's outer z-scoring exactly as much as it did to
    IDI's internal rate/count z-scoring (already fixed in idi.py, §20).
    Position-group awareness stays confined to TCS's credit-ALLOCATION step
    (dividing team defensive value among participants by position
    responsibility, dpvs/position_credit.py) -- that's a different
    mechanism the user has explicitly endorsed ("we assign game weights tho
    for value that team players get from that group"), not a ranking
    normalization step.

    df must already have: total_credit, idi, wowy_delta, position_group.
    """
    df = df.copy()
    for season, grp in df.groupby("season"):
        idx = grp.index
        df.loc[idx, "tcs_z"] = _zscore_within(grp["total_credit"]).clip(
            -_WINSOR_SIGMA, _WINSOR_SIGMA
        ).values
        df.loc[idx, "idi_z"] = _zscore_within(grp["idi"]).clip(
            -_WINSOR_SIGMA, _WINSOR_SIGMA
        ).values
        wo = grp["wowy_delta"].dropna()
        if len(wo) >= 3:
            # Only z-score WOWY if there are enough valid entries this season
            df.loc[idx, "wowy_z"] = _zscore_within(grp["wowy_delta"]).clip(
                -_WINSOR_SIGMA, _WINSOR_SIGMA
            ).values
        # else leave wowy_z NaN → composite will use no-wowy weights

    return df


# ── composite ─────────────────────────────────────────────────────────────────

def _compute_dpvs_g_row(row: pd.Series) -> float:
    """DPVS-G primary composite. WOWY is deliberately never used here as of
    the 2026-08-23 TCS rebuild -- see _W_NO_WOWY's comment above."""
    tcs_z  = row.get("tcs_z", np.nan)
    idi_z  = row.get("idi_z", np.nan)

    if pd.isna(tcs_z):
        return np.nan
    idi_z_safe = float(idi_z) if pd.notna(idi_z) else 0.0

    return (
        _W_NO_WOWY["tcs_z"] * float(tcs_z)
        + _W_NO_WOWY["idi_z"] * idi_z_safe
    )


def _compute_dpvs_a_row(row: pd.Series) -> float:
    tcs_z  = row.get("tcs_z", np.nan)
    idi_z  = row.get("idi_z", np.nan)
    wowy_z = row.get("wowy_z", np.nan)

    if pd.isna(tcs_z):
        return np.nan
    idi_z_safe = float(idi_z) if pd.notna(idi_z) else 0.0

    if pd.notna(wowy_z):
        return (
            _WA_FULL["tcs_z"]  * float(tcs_z)
            + _WA_FULL["idi_z"]  * idi_z_safe
            + _WA_FULL["wowy_z"] * float(wowy_z)
        )
    # No WOWY: rescale 0.25/0.50 weights to sum to 1.0
    return (
        _WA_NO_WOWY["tcs_z"] * float(tcs_z)
        + _WA_NO_WOWY["idi_z"] * idi_z_safe
    ) / 0.75


def _compute_dpvs_p_row(row: pd.Series) -> float:
    ptcs_z = row.get("ptcs_z", np.nan)
    idi_z  = row.get("idi_z", np.nan)
    wowy_z = row.get("wowy_z", np.nan)

    if pd.isna(ptcs_z):
        return np.nan
    idi_z_safe = float(idi_z) if pd.notna(idi_z) else 0.0

    if pd.notna(wowy_z):
        return (
            _WP_FULL["ptcs_z"]  * float(ptcs_z)
            + _WP_FULL["idi_z"]  * idi_z_safe
            + _WP_FULL["wowy_z"] * float(wowy_z)
        )
    return (
        _WP_NO_WOWY["ptcs_z"] * float(ptcs_z)
        + _WP_NO_WOWY["idi_z"] * idi_z_safe
    )


def _confidence(row: pd.Series) -> str:
    if row.get("season") in _STRIKE_YEARS:
        return "low"
    has_gamebook = bool(row.get("idi_has_tackles", False))
    has_wowy = pd.notna(row.get("wowy_z"))
    if has_gamebook and has_wowy:
        return "high"
    if has_gamebook or has_wowy:
        return "medium"
    return "low"


def _dedup_positions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Some players appear in multiple rows per season when starters.csv lists
    them at different positions in different games (e.g., Alan Page at LDT
    in game 1 and RDT in games 2-14).

    Strategy: pick the position with the most games_played; sum total_credit
    and games_played across all rows for that player-season; keep the max
    wowy_delta.
    """
    key = ["season", "team", "pfr_player_id"]
    dups = df.duplicated(subset=key, keep=False)
    if not dups.any():
        return df

    singles = df[~dups].copy()
    multi = df[dups].copy()

    merged_rows: list[pd.DataFrame] = []
    for _, grp in multi.groupby(key):
        # Primary position = the one with most games
        primary = grp.loc[grp["games_played"].idxmax()].copy()
        primary["games_played"] = int(grp["games_played"].sum())
        primary["total_credit"] = float(grp["total_credit"].sum())
        primary["per_game_credit"] = (
            primary["total_credit"] / primary["games_played"]
            if primary["games_played"] > 0 else 0.0
        )
        # Best WOWY (most positive, ignoring NaN)
        wo = grp["wowy_delta"].dropna()
        if not wo.empty:
            primary["wowy_delta"] = float(wo.max())
        merged_rows.append(primary.to_frame().T)

    if merged_rows:
        return pd.concat([singles] + merged_rows, ignore_index=True)
    return singles


def build_composite(
    df: pd.DataFrame,
    min_games: int = 6,
    run_pass_ctx: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Given a merged DataFrame with tcs, idi, and wowy columns, produce
    the final player-season table with DPVS-G, DPVS-A, and DPVS-P scores.

    run_pass_ctx: output of compute_run_pass_context(game_df) — per-team-season
    run_def_z and pass_def_z.  Required to compute DPVS-P; if None, dpvs_p is NaN.

    Steps:
      0. Deduplicate multi-position rows (same player, different pos code)
      1. Filter to min_games played (removes backup appearances on great teams)
      2. Assign position_group from pos column
      3. Z-score TCS, IDI, WOWY within season only (not position_group -- §22)
      4. Compute PTCS_z (positional run/pass context) if run_pass_ctx provided
      5. Compute DPVS-G, DPVS-A, DPVS-P
      6. Rank within season × position_group (by DPVS-G)
      7. Add confidence flag
    """
    df = df.copy()

    # Dedup multi-position rows before anything else
    df = _dedup_positions(df)

    # Minimum games filter — removes backup cameos that inflate career peaks
    if min_games > 0 and "games_played" in df.columns:
        df = df[df["games_played"] >= min_games].copy()

    # Position group — prefer TCS (starters-derived) pos; fall back to gold parquet pos
    # for seasons where starters.csv is absent (2001-2018, pre-1967).
    if "gold_pos" in df.columns:
        empty_pos = df["pos"].isna() | (df["pos"].str.strip() == "")
        df.loc[empty_pos, "pos"] = df.loc[empty_pos, "gold_pos"].fillna("")
        df.drop(columns=["gold_pos"], inplace=True, errors="ignore")

    df["position_group"] = df["pos"].apply(map_position)
    # Drop players where we still can't assign a group after fallback
    df = df[df["position_group"] != "unknown"].copy()

    # Ensure numeric
    for col in ("total_credit", "idi", "wowy_delta"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Z-scores for TCS, IDI, WOWY (within season only, winsorized -- §22)
    df = z_score_components(df)

    # DPVS-G
    df["dpvs_g"] = df.apply(_compute_dpvs_g_row, axis=1).round(4)

    # DPVS-A (individual-weighted)
    df["dpvs_a"] = df.apply(_compute_dpvs_a_row, axis=1).round(4)

    # DPVS-P (positional run/pass context)
    df["ptcs_z"] = np.nan
    if run_pass_ctx is not None and not run_pass_ctx.empty:
        df = df.merge(run_pass_ctx, on=["season", "team"], how="left")

        # ptcs_raw = run_def_z × pos_run_wt + pass_def_z × pos_pass_wt
        def _ptcs_raw(row: pd.Series) -> float:
            pg = row.get("position_group", "")
            run_w  = _POS_RUN_CREDIT.get(pg, 1/3)
            pass_w = _POS_PASS_CREDIT.get(pg, 1/3)
            r = row.get("run_def_z")
            p = row.get("pass_def_z")
            return run_w * (float(r) if pd.notna(r) else 0.0) \
                 + pass_w * (float(p) if pd.notna(p) else 0.0)

        df["_ptcs_raw"] = df.apply(_ptcs_raw, axis=1)

        # Z-score ptcs_raw within season across ALL players (not within pos group)
        for season, idx in df.groupby("season").groups.items():
            mask = df.index.isin(idx)
            df.loc[mask, "ptcs_z"] = _zscore_within(
                df.loc[mask, "_ptcs_raw"]
            ).clip(-_WINSOR_SIGMA, _WINSOR_SIGMA).values

        df.drop(columns=["_ptcs_raw"], inplace=True, errors="ignore")

    df["dpvs_p"] = df.apply(_compute_dpvs_p_row, axis=1).round(4)

    # Season rank within position group (by DPVS-G — primary metric)
    df["season_pos_rank"] = df.groupby(["season", "position_group"])["dpvs_g"].rank(
        ascending=False, method="min", na_option="bottom"
    ).astype("Int64")

    # Season rank overall (all defenders, by DPVS-G)
    df["season_overall_rank"] = df.groupby("season")["dpvs_g"].rank(
        ascending=False, method="min", na_option="bottom"
    ).astype("Int64")

    # Confidence
    df["data_confidence"] = df.apply(_confidence, axis=1)

    return df.sort_values(["season", "dpvs_g"], ascending=[True, False])


# ── career summary ─────────────────────────────────────────────────────────────

def career_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute career DPVS-G summary per player.

    peak_dpvs_g        best single-season score
    peak_season        year of peak
    prime_dpvs_g       mean of top-3 seasons (by dpvs_g)
    career_avg_dpvs_g  games-played-weighted average
    seasons_above_avg  seasons with dpvs_g > 0
    total_games        sum of games_played
    primary_team       team with most games
    primary_pos_group  most common position group
    """
    rows: list[dict] = []
    for pid, grp in df.groupby("pfr_player_id"):
        grp = grp.dropna(subset=["dpvs_g"])
        if grp.empty:
            continue
        peak_row = grp.loc[grp["dpvs_g"].idxmax()]
        top3 = grp.nlargest(3, "dpvs_g")["dpvs_g"]
        games = grp.get("games_played", pd.Series([1] * len(grp)))
        weighted_avg = float(np.average(grp["dpvs_g"], weights=games.fillna(1)))
        primary_team = (
            grp.groupby("team")["games_played"].sum().idxmax()
            if "games_played" in grp.columns else grp["team"].mode().iloc[0]
        )
        rows.append({
            "pfr_player_id":    pid,
            "player_name":      grp["player_name"].iloc[0],
            "primary_team":     primary_team,
            "primary_pos_group": grp["position_group"].mode().iloc[0],
            "seasons_in_data":  len(grp),
            "total_games":      int(games.sum()) if "games_played" in grp.columns else None,
            "peak_dpvs_g":      round(float(peak_row["dpvs_g"]), 4),
            "peak_season":      int(peak_row["season"]),
            "prime_dpvs_g":     round(float(top3.mean()), 4),
            "career_avg_dpvs_g": round(weighted_avg, 4),
            "seasons_above_avg": int((grp["dpvs_g"] > 0).sum()),
        })

    result = pd.DataFrame(rows).sort_values("peak_dpvs_g", ascending=False)
    # Qualifier flag: ≥5 seasons in data, ≥3 seasons above average, and career_avg ≥ 0.30.
    # Requires 5 seasons minimum to prevent small-sample outliers (e.g. a NT on one
    # historically dominant defense inflating career avg over 4 seasons).
    result["qualified_career"] = (
        (result["seasons_in_data"] >= 5)
        & (result["seasons_above_avg"] >= 3)
        & (result["career_avg_dpvs_g"] >= 0.30)
    )
    return result
