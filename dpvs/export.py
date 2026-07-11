"""
Export DPVS-G data for web / API consumers.

Produces:
  ~/data/gold/dpvs_export/
      season_rankings_{year}.csv    — all players for a season, ranked
      all_time_leaderboard.csv      — top seasons all-time
      player_{pfr_id}.json          — full career for one player
      leaderboards.json             — top 25 per position group per season (compact)

JSON schema for player files matches what PFR / ESPN player pages expect:
  {
    "player_id": "PageAl00",
    "player_name": "Alan Page",
    "primary_team": "min",
    "primary_pos_group": "run_stopper",
    "career": { "peak_dpvs_g": ..., "peak_season": ..., ... },
    "seasons": [
      {
        "season": 1971, "team": "min", "pos": "RDT",
        "position_group": "run_stopper",
        "games_played": 14,
        "tcs": 0.xxx, "tcs_z": x.xx,
        "idi": 0.xxx, "idi_z": x.xx,
        "wowy_delta": x.xx, "wowy_z": x.xx,
        "dpvs_g": x.xx,
        "season_pos_rank": 1, "season_overall_rank": 2,
        "data_confidence": "high",
        "tackle_source": "gamebook"
      }
    ]
  }
"""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
import numpy as np

EXPORT_DIR = Path.home() / "data/gold/dpvs_export"

_SEASON_COLS = [
    "season", "team", "pfr_player_id", "player_name", "pos", "position_group",
    "games_played",
    "total_credit", "tcs_z",
    "idi", "idi_z", "idi_has_tackles",
    "wowy_delta", "wowy_z",
    "dpvs_g", "season_pos_rank", "season_overall_rank",
    "data_confidence", "tackle_source",
]


def _clean_val(v):
    """Convert numpy/pandas scalars to JSON-serialisable Python types."""
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, float) and np.isnan(v):
        return None
    if pd.isna(v):
        return None
    return v


def export_season_rankings(
    player_season_df: pd.DataFrame,
    seasons: list[int] | None = None,
    out_dir: Path = EXPORT_DIR,
) -> None:
    """Write season_rankings_{year}.csv for each season."""
    out_dir.mkdir(parents=True, exist_ok=True)
    available_cols = [c for c in _SEASON_COLS if c in player_season_df.columns]
    df = player_season_df[available_cols].copy()
    if seasons:
        df = df[df["season"].isin(seasons)]

    for season, grp in df.groupby("season"):
        path = out_dir / f"season_rankings_{season}.csv"
        grp.sort_values("dpvs_g", ascending=False).to_csv(path, index=False)

    print(f"  Season rankings written to {out_dir}/season_rankings_*.csv")


def export_all_time_leaderboard(
    player_season_df: pd.DataFrame,
    top_n: int = 250,
    out_dir: Path = EXPORT_DIR,
) -> None:
    """Write all_time_leaderboard.csv — top N player-seasons by DPVS-G."""
    out_dir.mkdir(parents=True, exist_ok=True)
    available_cols = [c for c in _SEASON_COLS if c in player_season_df.columns]
    top = (
        player_season_df[available_cols]
        .dropna(subset=["dpvs_g"])
        .nlargest(top_n, "dpvs_g")
    )
    path = out_dir / "all_time_leaderboard.csv"
    top.to_csv(path, index=False)
    print(f"  All-time leaderboard ({len(top)} rows) → {path}")


def export_player_json(
    player_season_df: pd.DataFrame,
    career_df: pd.DataFrame,
    player_ids: list[str] | None = None,
    out_dir: Path = EXPORT_DIR,
) -> None:
    """Write player_{pfr_id}.json for each player (or a specified subset)."""
    players_dir = out_dir / "players"
    players_dir.mkdir(parents=True, exist_ok=True)

    if player_ids:
        targets = player_season_df[player_season_df["pfr_player_id"].isin(player_ids)]
    else:
        targets = player_season_df

    available_season_cols = [c for c in _SEASON_COLS if c in player_season_df.columns]

    for pid, grp in targets.groupby("pfr_player_id"):
        career_row = career_df[career_df["pfr_player_id"] == pid]
        career_dict = (
            {k: _clean_val(v) for k, v in career_row.iloc[0].to_dict().items()}
            if not career_row.empty else {}
        )

        seasons_list = []
        for _, row in grp[available_season_cols].sort_values("season").iterrows():
            seasons_list.append({k: _clean_val(v) for k, v in row.to_dict().items()})

        payload = {
            "player_id":        pid,
            "player_name":      grp["player_name"].iloc[0],
            "primary_team":     career_dict.get("primary_team"),
            "primary_pos_group": career_dict.get("primary_pos_group"),
            "career":           career_dict,
            "seasons":          seasons_list,
        }

        safe_id = str(pid).replace("/", "_").replace("\\", "_")
        path = players_dir / f"player_{safe_id}.json"
        path.write_text(json.dumps(payload, indent=2))

    print(f"  Player JSON files written to {players_dir}/")


def export_leaderboards_json(
    player_season_df: pd.DataFrame,
    top_n: int = 25,
    out_dir: Path = EXPORT_DIR,
) -> None:
    """
    Write leaderboards.json — compact top-N per position group per season.
    Suitable for a leaderboard page that loads a single file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {}

    for (season, pg), grp in player_season_df.groupby(["season", "position_group"]):
        top = grp.nlargest(top_n, "dpvs_g")[
            ["pfr_player_id", "player_name", "team", "pos", "dpvs_g",
             "season_pos_rank", "data_confidence"]
        ]
        result.setdefault(str(season), {})[pg] = [
            {k: _clean_val(v) for k, v in row.to_dict().items()}
            for _, row in top.iterrows()
        ]

    path = out_dir / "leaderboards.json"
    path.write_text(json.dumps(result, indent=2))
    print(f"  Leaderboards JSON → {path}")


def export_all(
    player_season_df: pd.DataFrame,
    career_df: pd.DataFrame,
    seasons: list[int] | None = None,
    player_ids: list[str] | None = None,
    out_dir: Path = EXPORT_DIR,
) -> None:
    """Run all four export functions in sequence."""
    print(f"Exporting DPVS-G data to {out_dir} ...")
    export_season_rankings(player_season_df, seasons=seasons, out_dir=out_dir)
    export_all_time_leaderboard(player_season_df, out_dir=out_dir)
    export_player_json(player_season_df, career_df,
                       player_ids=player_ids, out_dir=out_dir)
    export_leaderboards_json(player_season_df, out_dir=out_dir)
    print("Export complete.")
