"""
Team Credit Share (TCS) — Layer 1 of DPVS-G.

Loads or rebuilds player_game_defense data, then aggregates to
player-season level:

  total_credit   = SUM(game_credit_share) across all games played
  games_played   = count of game rows
  per_game_credit = total_credit / games_played

The TDGS already embeds OQA (dual benchmark vs league avg + opponent avg),
so TCS automatically inherits opponent quality adjustment.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

SILVER_DIR = Path.home() / "data/silver"
PLAYER_GAME_DEF = SILVER_DIR / "player_game_defense.parquet"

# Column aliases: two generations of build_game_defense.py used different names
_CREDIT_ALIASES = ("team_credit_share", "game_credit_share")
_TDGS_ALIASES   = ("tdgs", "game_defense_score")


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename older-schema columns to canonical names."""
    col_map: dict[str, str] = {}
    if "game_defense_score" in df.columns and "tdgs" not in df.columns:
        col_map["game_defense_score"] = "tdgs"
    if "game_credit_share" in df.columns and "team_credit_share" not in df.columns:
        col_map["game_credit_share"] = "team_credit_share"
    if "games_started" in df.columns and "games_in" not in df.columns:
        col_map["games_started"] = "games_in"
    if col_map:
        df = df.rename(columns=col_map)
    return df


GAME_DEF_PARQUET = SILVER_DIR / "game_defense.parquet"


def load_or_build_player_game(
    seasons: list[int],
    teams: list[str] | None = None,
    rebuild: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Return (game_df, player_game_df) for the requested seasons.

    game_df        — one row per game × defending team (TDGS, OQA)
    player_game_df — one row per game × defensive participant

    Uses the cached parquets when they cover the requested seasons.
    Calls build_game_defense.build() otherwise (or when rebuild=True).

    teams: lowercase PFR abbreviations filter (e.g. ['min', 'pit']).
           None = all teams.
    """
    target_seasons = set(seasons)

    # Check parquet coverage for BOTH files
    if PLAYER_GAME_DEF.exists() and GAME_DEF_PARQUET.exists() and not rebuild:
        cached_p = _normalise_columns(pd.read_parquet(PLAYER_GAME_DEF))
        cached_g = pd.read_parquet(GAME_DEF_PARQUET)
        if "game_defense_score" in cached_g.columns and "tdgs" not in cached_g.columns:
            cached_g = cached_g.rename(columns={"game_defense_score": "tdgs"})
        cached_p_seasons = set(cached_p["season"].unique())
        cached_g_seasons = set(cached_g["season"].unique())
        if target_seasons.issubset(cached_p_seasons) and target_seasons.issubset(cached_g_seasons):
            pdf = cached_p[cached_p["season"].isin(target_seasons)].copy()
            gdf = cached_g[cached_g["season"].isin(target_seasons)].copy()
            # Filter to regular season only if the column is present
            if "is_regular_season" in pdf.columns:
                pdf = pdf[pdf["is_regular_season"]].copy()
            if "is_regular_season" in gdf.columns:
                gdf = gdf[gdf["is_regular_season"]].copy()
            if teams:
                pdf = pdf[pdf["team"].isin(teams)]
                gdf = gdf[gdf["team"].isin(teams)]
            return gdf, pdf

    # Need to (re)build
    print(f"  TCS: building game_defense for seasons {min(seasons)}–{max(seasons)} ...",
          file=sys.stderr)
    _analytics = Path(__file__).parent.parent
    sys.path.insert(0, str(_analytics / "scripts"))
    from build_game_defense import build as _build  # type: ignore[import]

    game_df, player_df = _build(seasons, team_filter=None)  # always build all teams
    player_df = _normalise_columns(player_df)
    if "game_defense_score" in game_df.columns and "tdgs" not in game_df.columns:
        game_df = game_df.rename(columns={"game_defense_score": "tdgs"})

    # Merge with cached parquets (append new seasons, drop rebuilt seasons)
    for out_path, new_df in [(PLAYER_GAME_DEF, player_df), (GAME_DEF_PARQUET, game_df)]:
        if out_path.exists():
            old = pd.read_parquet(out_path)
            if out_path == PLAYER_GAME_DEF:
                old = _normalise_columns(old)
            old = old[~old["season"].isin(target_seasons)]
            combined = pd.concat([old, new_df], ignore_index=True)
            combined.to_parquet(out_path, index=False)
        else:
            new_df.to_parquet(out_path, index=False)

    total_rows = len(player_df) + (
        len(pd.read_parquet(PLAYER_GAME_DEF)) - len(player_df)
    )
    print(f"  TCS: updated parquet → {len(pd.read_parquet(PLAYER_GAME_DEF)):,} total rows",
          file=sys.stderr)

    # Filter to regular season only
    if "is_regular_season" in player_df.columns:
        player_df = player_df[player_df["is_regular_season"]].copy()
    if "is_regular_season" in game_df.columns:
        game_df = game_df[game_df["is_regular_season"]].copy()

    # Return filtered view if teams were specified
    if teams:
        player_df = player_df[player_df["team"].isin(teams)]
        game_df   = game_df[game_df["team"].isin(teams)]
    return game_df, player_df


def aggregate_tcs(player_game_df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate game-level credit to player-season level.

    Returns DataFrame with columns:
      season, team, pfr_player_id, player_name, pos,
      games_played, total_credit, per_game_credit
    """
    required = {"game_id", "season", "team", "pfr_player_id",
                "player_name", "pos", "team_credit_share"}
    missing = required - set(player_game_df.columns)
    if missing:
        raise ValueError(f"player_game_defense is missing columns: {missing}")

    grp = player_game_df.groupby(
        ["season", "team", "pfr_player_id", "player_name", "pos"],
        as_index=False,
    ).agg(
        games_played=("game_id", "count"),
        total_credit=("team_credit_share", "sum"),
    )
    grp["per_game_credit"] = (
        grp["total_credit"] / grp["games_played"]
    ).round(5)
    grp["total_credit"] = grp["total_credit"].round(5)
    return grp
