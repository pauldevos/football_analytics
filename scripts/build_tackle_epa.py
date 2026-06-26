#!/usr/bin/env python3
"""
build_tackle_epa.py
-------------------
Extract per-tackle EPA events from PFR play-by-play data (1978–2025).

For every play with tackle attribution ("tackle by Name") in pbp.csv:
  - Parse tackler name(s)
  - Compute defensive EPA = exp_pts_before - exp_pts_after
  - Resolve tackler → pfr_player_id via starters.csv / player_defense.csv
  - Classify play type (run / pass / sack / special)
  - Extract yards gained

Outputs:
  ~/data/silver/tackle_events.parquet      — play-level (1 row per tackle slot)
  ~/data/silver/tackle_epa_season.parquet  — player-season aggregations

Usage:
  python scripts/build_tackle_epa.py                      # all years
  python scripts/build_tackle_epa.py --seasons 1990-2000  # range
  python scripts/build_tackle_epa.py --seasons 1985       # single year

Notes:
  - Two-man tackles split EPA credit equally between tacklers.
  - ep_before / ep_after are from the OFFENSIVE team's perspective.
    epa_def = ep_before - ep_after  (positive = good for defense).
  - Plays without EP values are included but epa_def will be NaN.
  - Player name → pfr_player_id matching is fuzzy (strip trailing spaces,
    normalize). Unmatched tacklers get pfr_player_id = None.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

BOXSCORE_DIR = Path("/Users/devos/data/pfref/raw/boxscores")
SILVER_DIR   = Path("/Users/devos/data/silver")

# ---------------------------------------------------------------------------
# Position classification
# ---------------------------------------------------------------------------

DL_POS = {"DE", "DT", "NT", "LDE", "RDE", "LDT", "RDT", "NOSE", "DG",
           "LE", "RE", "LT", "RT"}   # LT/RT can be D-linemen in older notation
LB_POS = {"LB", "ILB", "OLB", "MLB", "SLB", "WLB",
           "LOLB", "ROLB", "LILB", "RILB", "RLB", "LLB",
           "LIB", "RIB", "LOB", "ROB"}
DB_POS = {"CB", "FS", "SS", "DB", "LCB", "RCB", "NCB", "S",
          "LC", "RC", "SCB", "WCB", "LS", "RS", "LFS", "RFS",
          "LHS", "RHS", "LHSS", "RHSS"}


def pos_group(pos: str) -> str:
    p = (pos or "").upper().strip()
    if p in DL_POS:
        return "DL"
    if p in LB_POS:
        return "LB"
    if p in DB_POS:
        return "DB"
    return "OTHER"


# ---------------------------------------------------------------------------
# Detail text parsers
# ---------------------------------------------------------------------------

_TACKLE_PAT  = re.compile(r"\(tackle by (.*?)\)", re.I)
_SACK_BY_PAT = re.compile(r"sacked by (.*?) for (-?\d+) yards?", re.I)
_YARDS_PAT   = re.compile(r"for (-?\d+) yards?", re.I)
_NO_GAIN     = re.compile(r"for no gain", re.I)
_INCOMPLETE  = re.compile(r"pass incomplete|incomplete intended", re.I)
_SACK_PAT    = re.compile(r"sacked", re.I)
_PASS_PAT    = re.compile(r"pass complete|pass incomplete|scrambles", re.I)
_SPECIAL_PAT = re.compile(r"punts|kicks off|field goal|extra point|kickoff", re.I)


def parse_tackles(detail: str) -> list[str]:
    """Return list of tackler full names from play detail."""
    m = _TACKLE_PAT.search(detail)
    if not m:
        return []
    inner = m.group(1).strip().rstrip()
    names = [n.strip() for n in re.split(r"\s+and\s+", inner)]
    return [n for n in names if n and not re.match(r"^\s*$", n)]


def parse_sackers(detail: str) -> tuple[list[str], int | None]:
    """
    Extract (sacker_names, yards_gained) from 'sacked by' play description.

    Handles both sign conventions:
      'sacked by LT for 11 yards'   → (['LT'], -11)  older PBP: positive = yards lost
      'sacked by Walker for -6 yards' → (['Walker'], -6)  modern PBP: already negative
    Returns ([], None) if pattern not found.
    """
    m = _SACK_BY_PAT.search(detail)
    if not m:
        return [], None
    names_raw = m.group(1).strip()
    yards_raw = int(m.group(2))
    # Sacks always lose yards; older PBP writes the loss as a positive magnitude
    yards = yards_raw if yards_raw <= 0 else -yards_raw
    names = [n.strip() for n in re.split(r"\s+and\s+", names_raw) if n.strip()]
    return names, yards


def parse_yards_gained(detail: str) -> int | None:
    if _NO_GAIN.search(detail):
        return 0
    if _INCOMPLETE.search(detail):
        return 0
    m = _YARDS_PAT.search(detail)
    if m:
        return int(m.group(1))
    return None


def classify_play_type(detail: str) -> str:
    d = detail.lower()
    if _SPECIAL_PAT.search(d):
        return "special"
    if _SACK_PAT.search(d):
        return "sack"
    if _PASS_PAT.search(d):
        return "pass"
    return "run"


def parse_location(loc: str) -> tuple[str, int]:
    """'TAM 23' → ('TAM', 23).  Returns ('', 0) on failure."""
    if not loc:
        return ("", 0)
    m = re.match(r"([A-Z]{2,4})\s+(\d+)", loc.strip())
    if m:
        return (m.group(1), int(m.group(2)))
    return ("", 0)


# ---------------------------------------------------------------------------
# Player ID resolution
# ---------------------------------------------------------------------------

def _norm_name(name: str) -> str:
    """Normalize player name for fuzzy matching."""
    return re.sub(r"\s+", " ", name.strip().lower())


def build_player_map(game_dir: Path) -> dict[str, tuple[str, str, str]]:
    """
    Build {norm_name: (pfr_player_id, pos, team)} from starters + player_defense.
    Returns empty dict if files are missing.
    """
    result: dict[str, tuple[str, str, str]] = {}

    def _load(path: Path, name_col: str, id_col: str,
               pos_col: str | None, team_col: str):
        if not path.exists():
            return
        try:
            df = pd.read_csv(path, dtype=str)
        except Exception:
            return
        for _, row in df.iterrows():
            nm = _norm_name(str(row.get(name_col, "") or ""))
            pid = str(row.get(id_col, "") or "").strip()
            pos = str(row.get(pos_col, "") or "").strip() if pos_col else ""
            team = str(row.get(team_col, "") or "").strip().lower()
            if nm and pid:
                result.setdefault(nm, (pid, pos, team))

    _load(game_dir / "starters.csv",
          "player", "pfr_player_id", "pos", "team_abbrev")
    _load(game_dir / "player_defense.csv",
          "player", "pfr_player_id", None, "team")
    return result


def resolve_tackler(name: str, player_map: dict) -> tuple[str, str, str]:
    """
    Look up (pfr_player_id, pos, team) for a tackler name.
    Returns ('', '', '') on miss.
    """
    key = _norm_name(name)
    return player_map.get(key, ("", "", ""))


# ---------------------------------------------------------------------------
# Single-game processing
# ---------------------------------------------------------------------------

def process_game(game_dir: Path) -> list[dict]:
    pbp_path = game_dir / "pbp.csv"
    if not pbp_path.exists():
        return []

    try:
        df = pd.read_csv(pbp_path, dtype=str)
    except Exception as e:
        print(f"  ERROR reading {pbp_path}: {e}", file=sys.stderr)
        return []

    if df.empty:
        return []

    player_map = build_player_map(game_dir)
    rows = []

    for _, play in df.iterrows():
        detail = str(play.get("detail", "") or "")
        if not detail or detail == "nan":
            continue

        tacklers = parse_tackles(detail)
        sackers, sack_yards = parse_sackers(detail)

        # Skip plays with neither a tackler nor a sacker
        if not tacklers and not sackers:
            continue

        # Parse EP — may be blank for early games or special plays
        def _float(v):
            try:
                return float(v) if v and str(v).strip() else None
            except ValueError:
                return None

        ep_before = _float(play.get("exp_pts_before"))
        ep_after  = _float(play.get("exp_pts_after"))
        epa_def   = (ep_before - ep_after) if (ep_before is not None and ep_after is not None) else None

        yards_gained = parse_yards_gained(detail)
        play_type    = classify_play_type(detail)

        loc_str = str(play.get("location", "") or "")
        if loc_str == "nan":
            loc_str = ""
        loc_team, loc_yard = parse_location(loc_str)

        # Common fields shared by tackle and sack rows
        common = {
            "game_id":    play.get("game_id", ""),
            "season":     play.get("season", ""),
            "home_team":  play.get("home_abbrev", ""),
            "vis_team":   play.get("vis_abbrev", ""),
            "quarter":    play.get("quarter", ""),
            "down":       play.get("down", ""),
            "yds_to_go":  play.get("yds_to_go", ""),
            "location":   loc_str,
            "loc_team":   loc_team,
            "loc_yard":   loc_yard,
            "score_away": play.get("pbp_score_aw", ""),
            "score_home": play.get("pbp_score_hm", ""),
            "ep_before":  ep_before,
            "ep_after":   ep_after,
            "epa_def":    epa_def,
            "play_detail": detail[:200],
        }

        # ── Regular tackle events (tackle by ...) ──────────────────────────
        if tacklers:
            n_tacklers = len(tacklers)
            epa_share  = (epa_def / n_tacklers) if epa_def is not None else None
            for i, name in enumerate(tacklers):
                pid, pos, team = resolve_tackler(name, player_map)
                rows.append({
                    **common,
                    "play_type":     play_type,
                    "yards_gained":  yards_gained,
                    "n_tacklers":    n_tacklers,
                    "tackle_slot":   i + 1,
                    "is_solo":       n_tacklers == 1,
                    "tackler_name":  name.strip(),
                    "pfr_player_id": pid,
                    "pos":           pos,
                    "pos_group":     pos_group(pos),
                    "team":          team,
                    "epa_def_share": epa_share,
                    "is_sack":       False,
                })

        # ── Sack events (sacked by X) ──────────────────────────────────────
        # Only emit when there is no (tackle by...) to avoid double-counting
        # the rare fumble-after-sack plays that have both patterns.
        if sackers and not tacklers:
            n_sackers = len(sackers)
            epa_share = (epa_def / n_sackers) if epa_def is not None else None
            for i, name in enumerate(sackers):
                pid, pos, team = resolve_tackler(name, player_map)
                rows.append({
                    **common,
                    "play_type":     "sack",
                    "yards_gained":  sack_yards,
                    "n_tacklers":    n_sackers,
                    "tackle_slot":   i + 1,
                    "is_solo":       n_sackers == 1,
                    "tackler_name":  name.strip(),
                    "pfr_player_id": pid,
                    "pos":           pos,
                    "pos_group":     pos_group(pos),
                    "team":          team,
                    "epa_def_share": epa_share,
                    "is_sack":       True,
                })

    return rows


# ---------------------------------------------------------------------------
# Aggregation: player-season summaries
# ---------------------------------------------------------------------------

def aggregate_seasons(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    ev = events.copy()
    ev["season"]   = ev["season"].astype(str)
    ev["down"]     = pd.to_numeric(ev["down"], errors="coerce")
    ev["yds_to_go"] = pd.to_numeric(ev["yds_to_go"], errors="coerce")

    agg_rows = []
    for (player, pid, season), g in ev.groupby(
            ["tackler_name", "pfr_player_id", "season"], dropna=False):
        n_games    = g["game_id"].nunique()
        n_solo     = int(g["is_solo"].sum())
        n_total    = len(g)
        n_assist   = n_total - n_solo
        n_run      = int((g["play_type"] == "run").sum())
        n_pass     = int((g["play_type"] == "pass").sum())
        n_sack     = int((g["play_type"] == "sack").sum())

        epa_total  = g["epa_def_share"].sum() if g["epa_def_share"].notna().any() else None
        epa_per_tk = (epa_total / n_total) if epa_total is not None else None

        avg_yards  = g["yards_gained"].mean() if g["yards_gained"].notna().any() else None

        # Most common pos/team (first non-empty)
        pos_vals  = g.loc[g["pos"] != "", "pos"]
        pg_vals   = g.loc[g["pos_group"] != "", "pos_group"]
        team_vals = g.loc[g["team"] != "", "team"]

        agg_rows.append({
            "tackler_name":       player,
            "pfr_player_id":      pid,
            "season":             season,
            "games":              n_games,
            "tackles_total":      n_total,
            "tackles_solo":       n_solo,
            "tackles_assist":     n_assist,
            "tackles_run":        n_run,
            "tackles_pass":       n_pass,
            "tackles_sack":       n_sack,
            "solo_rate":          round(n_solo / n_total, 3) if n_total else None,
            "run_rate":           round(n_run / n_total, 3) if n_total else None,
            "pass_rate":          round(n_pass / n_total, 3) if n_total else None,
            "avg_yards_allowed":  round(float(avg_yards), 2) if avg_yards is not None else None,
            "epa_def_total":      round(float(epa_total), 3) if epa_total is not None else None,
            "epa_def_per_tackle": round(float(epa_per_tk), 4) if epa_per_tk is not None else None,
            "pos":                pos_vals.iloc[0] if len(pos_vals) else "",
            "pos_group":          pg_vals.iloc[0] if len(pg_vals) else "",
            "team":               team_vals.iloc[0] if len(team_vals) else "",
        })

    return pd.DataFrame(agg_rows)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def parse_season_arg(arg: str) -> list[int]:
    """'1990-2000' → [1990..2000], '1985' → [1985], '1985,1990' → [1985,1990]"""
    if not arg:
        return list(range(1978, 2026))
    if "-" in arg and "," not in arg:
        parts = arg.split("-")
        return list(range(int(parts[0]), int(parts[1]) + 1))
    if "," in arg:
        return [int(x) for x in arg.split(",")]
    return [int(arg)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", default="",
                    help="Years to process: '1990-2000', '1985', or '1985,1990'")
    ap.add_argument("--events-out", default=str(SILVER_DIR / "tackle_events.parquet"))
    ap.add_argument("--season-out", default=str(SILVER_DIR / "tackle_epa_season.parquet"))
    args = ap.parse_args()

    seasons = parse_season_arg(args.seasons)
    print(f"Processing {len(seasons)} seasons: {seasons[0]}–{seasons[-1]}")

    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    all_events: list[dict] = []
    total_games = 0
    total_plays = 0

    for season in seasons:
        season_dir = BOXSCORE_DIR / str(season)
        if not season_dir.exists():
            continue
        game_dirs = [gd for gd in sorted(season_dir.iterdir()) if gd.is_dir()]
        if not game_dirs:
            continue

        season_events: list[dict] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(process_game, gd): gd for gd in game_dirs}
            for fut in as_completed(futures):
                season_events.extend(fut.result())

        all_events.extend(season_events)
        total_games += len(game_dirs)
        total_plays += len(season_events)
        n_sacks = sum(1 for e in season_events if e.get("is_sack"))
        print(f"  {season}: {len(game_dirs)} games → {len(season_events):,} events "
              f"(sacks: {n_sacks:,})")

    print(f"\nTotal: {total_games:,} games, {total_plays:,} tackle events")

    if not all_events:
        print("No events found — check season range and data paths.")
        return

    events_df = pd.DataFrame(all_events)

    # Tighten dtypes before saving
    for col in ["down", "yds_to_go", "n_tacklers", "tackle_slot", "loc_yard"]:
        events_df[col] = pd.to_numeric(events_df[col], errors="coerce")
    for col in ["yards_gained", "ep_before", "ep_after", "epa_def", "epa_def_share"]:
        events_df[col] = pd.to_numeric(events_df[col], errors="coerce")
    events_df["is_sack"] = events_df["is_sack"].astype(bool)

    events_df.to_parquet(args.events_out, index=False)
    print(f"Saved play-level events → {args.events_out}")
    print(f"  Rows: {len(events_df):,}  |  Seasons: {events_df['season'].nunique()}  "
          f"|  Players identified: {(events_df['pfr_player_id'] != '').sum():,} "
          f"({100*(events_df['pfr_player_id'] != '').mean():.0f}%)")

    print("\nBuilding season aggregations...")
    season_df = aggregate_seasons(events_df)
    season_df.to_parquet(args.season_out, index=False)
    print(f"Saved player-season aggregations → {args.season_out}  ({len(season_df):,} rows)")

    # Quick preview
    print("\nTop 15 tacklers by EPA (season aggregation, all years):")
    top = (season_df[season_df["tackles_total"] >= 30]
           .sort_values("epa_def_total", ascending=False)
           .head(15)[["tackler_name", "season", "team", "pos_group",
                       "tackles_total", "epa_def_total", "epa_def_per_tackle",
                       "avg_yards_allowed"]])
    print(top.to_string(index=False))


if __name__ == "__main__":
    main()
