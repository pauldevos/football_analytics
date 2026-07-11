"""
WOWY — With Or Without You — Layer 3 of DPVS-G.

Computes per-player-season WOWY delta from game-level data:

  wowy_delta = avg_TDGS(games player IN) − avg_TDGS(games player OUT)

When a player appeared in all games (games_out = 0), wowy_delta = None
and the composite formula drops this layer, rebalancing to TCS + IDI only.

Requires player_game_defense data (output of build_game_defense.py).
"""

from __future__ import annotations

import pandas as pd
import numpy as np


def compute_wowy(
    player_game_df: pd.DataFrame,
    game_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compute WOWY delta per player-season.

    player_game_df: from tcs.load_or_build_player_game()
                    needs: game_id, season, team, pfr_player_id, player_name, tdgs
    game_df:        team-game level, needs: game_id, season, team, tdgs

    Returns DataFrame with wowy_delta per player-season (None if no missed games).
    """
    if "tdgs" not in player_game_df.columns:
        # Legacy schema
        if "game_defense_score" in player_game_df.columns:
            player_game_df = player_game_df.rename(columns={"game_defense_score": "tdgs"})
        else:
            raise ValueError("player_game_df has no 'tdgs' or 'game_defense_score' column")

    if "tdgs" not in game_df.columns:
        raise ValueError("game_df has no 'tdgs' column")

    rows: list[dict] = []
    for (season, pid, name, team), grp in player_game_df.groupby(
        ["season", "pfr_player_id", "player_name", "team"]
    ):
        games_in = set(grp["game_id"])
        avg_tdgs_in = float(grp["tdgs"].mean())

        team_games = game_df[(game_df["season"] == season) & (game_df["team"] == team)]
        out_games = team_games[~team_games["game_id"].isin(games_in)]
        n_out = len(out_games)

        avg_tdgs_out: float | None = None
        wowy_delta: float | None = None
        if n_out > 0:
            avg_tdgs_out = float(out_games["tdgs"].mean())
            wowy_delta = round(avg_tdgs_in - avg_tdgs_out, 4)

        rows.append({
            "season":        season,
            "team":          team,
            "pfr_player_id": pid,
            "player_name":   name,
            "games_in":      len(games_in),
            "games_out":     n_out,
            "tdgs_with":     round(avg_tdgs_in, 4),
            "tdgs_without":  round(avg_tdgs_out, 4) if avg_tdgs_out is not None else None,
            "wowy_delta":    wowy_delta,
        })

    return pd.DataFrame(rows)


def load_wowy_parquet(path) -> pd.DataFrame | None:
    """
    Load the cached player_season_wowy.parquet if it exists.
    Handles both old schema (team_gds_with) and new schema (tdgs_with).
    """
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    col_map: dict[str, str] = {}
    if "team_gds_with" in df.columns and "tdgs_with" not in df.columns:
        col_map["team_gds_with"] = "tdgs_with"
    if "team_gds_without" in df.columns and "tdgs_without" not in df.columns:
        col_map["team_gds_without"] = "tdgs_without"
    if col_map:
        df = df.rename(columns=col_map)
    if "wowy_delta" not in df.columns and "tdgs_with" in df.columns:
        df["wowy_delta"] = df.apply(
            lambda r: round(r["tdgs_with"] - r["tdgs_without"], 4)
            if pd.notna(r.get("tdgs_without")) else None,
            axis=1,
        )
    return df
