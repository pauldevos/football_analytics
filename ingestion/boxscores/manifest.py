"""
Per-year manifest: one row per game recording which tables were found.

File: ~/data/pfref/manifest/page_manifest_{year}.csv

Columns:
    game_id, season, scraped_at, home_abbrev, vis_abbrev,
    had_player_offense, had_player_defense, had_returns, had_kicking,
    had_scoring, had_game_info, had_officials, had_team_stats,
    had_expected_points, had_passing_advanced, had_rushing_advanced,
    had_receiving_advanced, had_defense_advanced, had_starters,
    had_snap_counts, had_drives, had_pbp, error

Rows are upserted by game_id (re-scraping a game updates its manifest row).
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_DIR = Path.home() / "data" / "pfref" / "manifest"

_TABLE_FLAGS = [
    "player_offense", "player_defense", "returns", "kicking",
    "scoring", "game_info", "officials", "team_stats",
    "expected_points", "passing_advanced", "rushing_advanced",
    "receiving_advanced", "defense_advanced",
    "starters", "snap_counts", "drives", "pbp",
]

_COLUMNS = (
    ["game_id", "season", "scraped_at", "home_abbrev", "vis_abbrev"]
    + [f"had_{t}" for t in _TABLE_FLAGS]
    + ["error"]
)


def _manifest_path(season: int) -> Path:
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    return MANIFEST_DIR / f"page_manifest_{season}.csv"


def load_manifest(season: int) -> dict[str, dict]:
    """Return {game_id: row_dict} for an existing manifest file."""
    path = _manifest_path(season)
    if not path.exists():
        return {}
    with open(path, newline="") as f:
        return {row["game_id"]: row for row in csv.DictReader(f)}


def write_manifest_row(
    season: int,
    game_id: str,
    home_abbrev: str,
    vis_abbrev: str,
    found_tables: dict[str, bool],   # table_name → found bool
    error: str | None = None,
) -> None:
    """Upsert one game row into the season manifest CSV."""
    path = _manifest_path(season)

    existing = load_manifest(season)

    row: dict = {
        "game_id":     game_id,
        "season":      season,
        "scraped_at":  datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_abbrev": home_abbrev,
        "vis_abbrev":  vis_abbrev,
        "error":       error or "",
    }
    for t in _TABLE_FLAGS:
        row[f"had_{t}"] = "1" if found_tables.get(t, False) else "0"

    existing[game_id] = row

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing.values())


def scraped_game_ids(season: int) -> set[str]:
    """Return set of game_ids already successfully scraped this season."""
    manifest = load_manifest(season)
    return {gid for gid, row in manifest.items() if not row.get("error")}
