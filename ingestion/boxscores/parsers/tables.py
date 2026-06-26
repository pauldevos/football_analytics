"""
One function per PFR boxscore table.

Every function signature:
    parse_<table>(soup, game_id, season, home_abbrev, vis_abbrev)
    → (pd.DataFrame | None, found: bool)

`found` is True even when the table exists but produces zero data rows,
so the manifest can distinguish "table not on page" from "table empty".
"""

from __future__ import annotations

import re
import pandas as pd
from bs4 import BeautifulSoup

from .base import (
    first_table,
    parse_standard_table,
    parse_key_value_table,
    parse_weather,
    _to_snake,
)


# ---------------------------------------------------------------------------
# player_offense  (double-decker: Passing | Rushing | Receiving | Fumbles)
# ---------------------------------------------------------------------------

def parse_player_offense(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "player_offense")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# player_defense  (double-decker: Def Interceptions | Tackles | Fumbles)
# ---------------------------------------------------------------------------

def parse_player_defense(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "player_defense")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# returns  (double-decker: Kick Returns | Punt Returns)
# ---------------------------------------------------------------------------

def parse_returns(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "returns")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# kicking  (double-decker: Scoring | Punting)
# ---------------------------------------------------------------------------

def parse_kicking(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "kicking")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# scoring  (single-header; score cols use data-stat vis_team_score/home_team_score)
# ---------------------------------------------------------------------------

def parse_scoring(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "scoring")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# game_info  (key-value + weather decomposition)
# ---------------------------------------------------------------------------

def parse_game_info(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "game_info")
    if not tbl:
        return None, False

    df = parse_key_value_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    if df is None:
        return None, True

    # Decompose raw weather string into structured columns
    if "weather" in df.columns:
        weather_raw = df.at[0, "weather"]
        w = parse_weather(weather_raw)
        df["weather_raw"]   = w["weather_raw"]
        df["temp_f"]        = w["temp_f"]
        df["humidity_pct"]  = w["humidity_pct"]
        df["wind_mph"]      = w["wind_mph"]
        df["is_indoor"]     = w["is_indoor"]
        df["precip_type"]   = w["precip_type"]
        df.drop(columns=["weather"], inplace=True)

    # Normalize attendance: '69,012' → 69012 (int-friendly string, keep as str)
    if "attendance" in df.columns:
        df["attendance"] = df["attendance"].str.replace(",", "", regex=False)

    return df, True


# ---------------------------------------------------------------------------
# officials  (key-value)
# ---------------------------------------------------------------------------

def parse_officials(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "officials")
    if not tbl:
        return None, False
    df = parse_key_value_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# team_stats  (key-value; vis_stat/home_stat data-stats already normalized)
# ---------------------------------------------------------------------------

def parse_team_stats(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "team_stats")
    if not tbl:
        return None, False

    # team_stats is long-format rows: stat_name | vis_value | home_value
    # Keep it long so new stats added by PFR don't require schema changes.
    rows = []
    tbody = tbl.find("tbody")
    if not tbody:
        return None, True

    for tr in tbody.find_all("tr"):
        cls = " ".join(tr.get("class", []))
        if "thead" in cls:
            continue
        cells = {td.get("data-stat", ""): td for td in tr.find_all(["th", "td"])}
        stat_td  = cells.get("stat")
        vis_td   = cells.get("vis_stat")
        home_td  = cells.get("home_stat")
        if not stat_td:
            continue
        stat_name = stat_td.get_text(" ", strip=True)
        if not stat_name:
            continue
        rows.append({
            "game_id":     game_id,
            "season":      season,
            "home_abbrev": home_abbrev,
            "vis_abbrev":  vis_abbrev,
            "stat_name":   stat_name,
            "vis_value":   vis_td.get_text(strip=True)  if vis_td  else None,
            "home_value":  home_td.get_text(strip=True) if home_td else None,
        })

    if not rows:
        return None, True

    return pd.DataFrame(rows), True


# ---------------------------------------------------------------------------
# expected_points  (double-decker: Offense | Defense | Special Teams)
# ---------------------------------------------------------------------------

def parse_expected_points(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "expected_points")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# Advanced tables  (all single-header, same parse logic)
# ---------------------------------------------------------------------------

def parse_passing_advanced(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "passing_advanced")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


def parse_rushing_advanced(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "rushing_advanced")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


def parse_receiving_advanced(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "receiving_advanced")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


def parse_defense_advanced(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "defense_advanced")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# starters  (home_starters / vis_starters — parsed separately, team_side added)
# ---------------------------------------------------------------------------

def parse_starters(soup, game_id, season, home_abbrev, vis_abbrev):
    results = {}
    for side, abbrev, tbl_id in [
        ("home", home_abbrev, "home_starters"),
        ("vis",  vis_abbrev,  "vis_starters"),
    ]:
        tbl = first_table(soup, tbl_id)
        if not tbl:
            results[side] = (None, False)
            continue
        df = parse_standard_table(
            tbl, game_id, season, home_abbrev, vis_abbrev, team_side=side
        )
        if df is not None:
            df["team_abbrev"] = abbrev
        results[side] = (df, True)

    # Combine into one DataFrame (home rows + vis rows)
    frames = [r[0] for r in results.values() if r[0] is not None]
    found  = any(r[1] for r in results.values())
    combined = pd.concat(frames, ignore_index=True) if frames else None
    return combined, found


# ---------------------------------------------------------------------------
# snap_counts  (double-decker: Off. | Def. | ST)
# ---------------------------------------------------------------------------

def parse_snap_counts(soup, game_id, season, home_abbrev, vis_abbrev):
    results = {}
    for side, abbrev, tbl_id in [
        ("home", home_abbrev, "home_snap_counts"),
        ("vis",  vis_abbrev,  "vis_snap_counts"),
    ]:
        tbl = first_table(soup, tbl_id)
        if not tbl:
            results[side] = (None, False)
            continue
        df = parse_standard_table(
            tbl, game_id, season, home_abbrev, vis_abbrev, team_side=side
        )
        if df is not None:
            df["team_abbrev"] = abbrev
        results[side] = (df, True)

    frames = [r[0] for r in results.values() if r[0] is not None]
    found  = any(r[1] for r in results.values())
    combined = pd.concat(frames, ignore_index=True) if frames else None
    return combined, found


# ---------------------------------------------------------------------------
# drives  (home_drives / vis_drives)
# ---------------------------------------------------------------------------

def parse_drives(soup, game_id, season, home_abbrev, vis_abbrev):
    results = {}
    for side, abbrev, tbl_id in [
        ("home", home_abbrev, "home_drives"),
        ("vis",  vis_abbrev,  "vis_drives"),
    ]:
        tbl = first_table(soup, tbl_id)
        if not tbl:
            results[side] = (None, False)
            continue
        df = parse_standard_table(
            tbl, game_id, season, home_abbrev, vis_abbrev, team_side=side
        )
        if df is not None:
            df["team_abbrev"] = abbrev
        results[side] = (df, True)

    frames = [r[0] for r in results.values() if r[0] is not None]
    found  = any(r[1] for r in results.values())
    combined = pd.concat(frames, ignore_index=True) if frames else None
    return combined, found


# ---------------------------------------------------------------------------
# pbp  (full play-by-play; score cols use data-stat pbp_score_aw/pbp_score_hm)
# ---------------------------------------------------------------------------

def parse_pbp(soup, game_id, season, home_abbrev, vis_abbrev):
    tbl = first_table(soup, "pbp")
    if not tbl:
        return None, False
    df = parse_standard_table(tbl, game_id, season, home_abbrev, vis_abbrev)
    return df, True


# ---------------------------------------------------------------------------
# Registry: table_name → parser function + output filename
# ---------------------------------------------------------------------------

TABLE_PARSERS: dict[str, tuple] = {
    # (parser_fn, output_filename)
    "player_offense":     (parse_player_offense,     "player_offense.csv"),
    "player_defense":     (parse_player_defense,     "player_defense.csv"),
    "returns":            (parse_returns,             "returns.csv"),
    "kicking":            (parse_kicking,             "kicking.csv"),
    "scoring":            (parse_scoring,             "scoring.csv"),
    "game_info":          (parse_game_info,           "game_info.csv"),
    "officials":          (parse_officials,           "officials.csv"),
    "team_stats":         (parse_team_stats,          "team_stats.csv"),
    "expected_points":    (parse_expected_points,     "expected_points.csv"),
    "passing_advanced":   (parse_passing_advanced,    "passing_advanced.csv"),
    "rushing_advanced":   (parse_rushing_advanced,    "rushing_advanced.csv"),
    "receiving_advanced": (parse_receiving_advanced,  "receiving_advanced.csv"),
    "defense_advanced":   (parse_defense_advanced,    "defense_advanced.csv"),
    "starters":           (parse_starters,            "starters.csv"),
    "snap_counts":        (parse_snap_counts,         "snap_counts.csv"),
    "drives":             (parse_drives,              "drives.csv"),
    "pbp":                (parse_pbp,                 "pbp.csv"),
}
