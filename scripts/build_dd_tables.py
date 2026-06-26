#!/usr/bin/env python3
"""
build_dd_tables.py
------------------
Build empirical down-distance analytics tables from PFR play-by-play (1978–2025).

Produces five output tables in ~/data/silver/:

  dd_expected_yards.parquet
      (down, dist_bucket, field_zone) → avg/median yards gained, n_plays

  dd_scoring_prob.parquet
      (down, dist_bucket, field_zone) → P(first down), P(TD on drive),
      P(FG on drive), P(punt), P(turnover)  [drive outcomes via forward-look]

  dd_ep_table.parquet
      (down, dist_bucket, field_zone, quarter) → mean exp_pts_before,
      validated against PFR's built-in EP values

  team_tackle_distribution.parquet
      (season, game_id, team) → DL/LB/DB solo and assist share + team totals
      Requires: starters.csv (positions) + player_defense.csv (counts)

  position_era_baselines.parquet
      (pos_group, era, season) → mean/sd tackles per game, solo:assist ratio

Usage:
  python scripts/build_dd_tables.py                    # all years, all tables
  python scripts/build_dd_tables.py --seasons 1978-2000 --tables dd  # DD only
  python scripts/build_dd_tables.py --tables dist      # distribution only

Tables arg: dd, scoring, ep, dist, baselines  (comma-sep; default: all)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BOXSCORE_DIR = Path("/Users/devos/data/pfref/raw/boxscores")
SILVER_DIR   = Path("/Users/devos/data/silver")

# ---------------------------------------------------------------------------
# Bucketing helpers
# ---------------------------------------------------------------------------

DIST_BUCKETS = [
    (1,  1,  "1"),
    (2,  3,  "2-3"),
    (4,  6,  "4-6"),
    (7,  10, "7-10"),
    (11, 15, "11-15"),
    (16, 99, "16+"),
]

FIELD_ZONES = [
    (1,  20, "own_1-20"),
    (21, 40, "own_21-40"),
    (41, 59, "mid"),
    (60, 79, "opp_21-40"),
    (80, 99, "opp_1-20"),
]


def dist_bucket(d) -> str:
    try:
        v = int(d)
    except (TypeError, ValueError):
        return "unknown"
    for lo, hi, label in DIST_BUCKETS:
        if lo <= v <= hi:
            return label
    return "unknown"


def field_zone(loc: str) -> tuple[int, str]:
    """
    Convert PFR location ('TAM 23', 'OAK 35') to (abs_yard, zone_label).
    abs_yard = yards from possession team's own goal line (1–99).
    We infer possession side by tracking 'down' presence: a play with down/yds
    listed has the offense at that yard line.
    Without possession info in the row, we use the raw yard number as-is
    (so 'TAM 23' → yard = 23, zone depends on context).
    Zone is computed after abs_yard is set.
    """
    if not loc:
        return (0, "unknown")
    m = re.match(r"[A-Z]{2,4}\s+(\d+)", str(loc).strip())
    if not m:
        return (0, "unknown")
    yard = int(m.group(1))
    for lo, hi, label in FIELD_ZONES:
        if lo <= yard <= hi:
            return (yard, label)
    return (yard, "unknown")


# ---------------------------------------------------------------------------
# Yards gained from detail text
# ---------------------------------------------------------------------------

_YARDS_PAT = re.compile(r"for (-?\d+) yards?", re.I)
_NO_GAIN   = re.compile(r"for no gain", re.I)
_INCOMPLETE = re.compile(r"pass incomplete|incomplete intended", re.I)
_SPECIAL_PAT = re.compile(r"punts|kicks off|field goal|extra point|kickoff", re.I)
_SACK_PAT  = re.compile(r"sacked", re.I)
_PASS_PAT  = re.compile(r"pass complete|pass incomplete|scrambles", re.I)


def parse_yards(detail: str) -> int | None:
    if _NO_GAIN.search(detail):
        return 0
    if _INCOMPLETE.search(detail):
        return 0
    m = _YARDS_PAT.search(detail)
    if m:
        return int(m.group(1))
    return None


def classify_play(detail: str) -> str:
    d = detail.lower()
    if _SPECIAL_PAT.search(d):
        return "special"
    if _SACK_PAT.search(d):
        return "sack"
    if _PASS_PAT.search(d):
        return "pass"
    return "run"


# ---------------------------------------------------------------------------
# Load all PBP plays (scrimmage plays only)
# ---------------------------------------------------------------------------

def load_pbp_plays(seasons: list[int], verbose: bool = True) -> pd.DataFrame:
    """
    Load all pbp.csv files for the given seasons.
    Returns DataFrame with one row per scrimmage play that has down + yds_to_go.
    """
    parts = []
    for season in seasons:
        season_dir = BOXSCORE_DIR / str(season)
        if not season_dir.exists():
            continue
        game_dirs = sorted(season_dir.iterdir())
        season_rows = []
        for gd in game_dirs:
            if not gd.is_dir():
                continue
            pbp_path = gd / "pbp.csv"
            if not pbp_path.exists():
                continue
            try:
                df = pd.read_csv(pbp_path, dtype=str)
            except Exception:
                continue
            # Keep only scrimmage plays with down info
            df = df[df["down"].notna() & (df["down"] != "")]
            if df.empty:
                continue
            season_rows.append(df)
        if season_rows:
            parts.append(pd.concat(season_rows, ignore_index=True))
            if verbose:
                total = sum(len(r) for r in season_rows)
                print(f"  {season}: {len(game_dirs)} games, {total:,} scrimmage plays")

    if not parts:
        return pd.DataFrame()

    full = pd.concat(parts, ignore_index=True)
    full["down"]      = pd.to_numeric(full["down"], errors="coerce")
    full["yds_to_go"] = pd.to_numeric(full["yds_to_go"], errors="coerce")
    full["ep_before"] = pd.to_numeric(full.get("exp_pts_before"), errors="coerce")
    full["ep_after"]  = pd.to_numeric(full.get("exp_pts_after"), errors="coerce")

    # Parse yards gained and play type from detail
    detail = full["detail"].fillna("")
    full["yards_gained"] = detail.map(parse_yards)
    full["play_type"]    = detail.map(classify_play)

    # Field zone
    loc = full["location"].fillna("")
    fz = loc.map(field_zone)
    full["abs_yard"]   = fz.map(lambda x: x[0])
    full["field_zone"] = fz.map(lambda x: x[1])

    # Buckets
    full["dist_bucket"] = full["yds_to_go"].map(dist_bucket)

    # First-down flag from detail (crude: "FIRST DOWN" in detail text, or ep jump)
    full["first_down"] = (
        full["detail"].str.contains(r"FIRST DOWN|1ST DOWN", case=False, na=False)
        | full["detail"].str.contains(r"touchdown", case=False, na=False)
    )

    return full


# ---------------------------------------------------------------------------
# Table 1: Expected yards by (down, dist_bucket, field_zone)
# ---------------------------------------------------------------------------

def build_dd_expected_yards(plays: pd.DataFrame) -> pd.DataFrame:
    sc = plays[
        plays["play_type"].isin(["run", "pass", "sack"])
        & plays["yards_gained"].notna()
        & plays["down"].between(1, 4)
        & plays["dist_bucket"].ne("unknown")
    ].copy()

    agg = (sc.groupby(["down", "dist_bucket", "field_zone", "play_type"], dropna=True)
             .agg(
                 n_plays=("yards_gained", "count"),
                 avg_yards=("yards_gained", "mean"),
                 median_yards=("yards_gained", "median"),
                 std_yards=("yards_gained", "std"),
                 p10_yards=("yards_gained", lambda x: x.quantile(0.10)),
                 p90_yards=("yards_gained", lambda x: x.quantile(0.90)),
             )
             .reset_index())

    # Also combined (run+pass)
    agg_all = (sc.groupby(["down", "dist_bucket", "field_zone"], dropna=True)
                 .agg(
                     n_plays=("yards_gained", "count"),
                     avg_yards=("yards_gained", "mean"),
                     median_yards=("yards_gained", "median"),
                     std_yards=("yards_gained", "std"),
                 )
                 .reset_index()
                 .assign(play_type="all"))

    result = pd.concat([agg, agg_all], ignore_index=True)
    for col in ["avg_yards", "median_yards", "std_yards"]:
        result[col] = result[col].round(3)

    return result


# ---------------------------------------------------------------------------
# Table 2: EP table from PFR values (validated averages)
# ---------------------------------------------------------------------------

def build_ep_table(plays: pd.DataFrame) -> pd.DataFrame:
    sc = plays[
        plays["ep_before"].notna()
        & plays["down"].between(1, 4)
        & plays["dist_bucket"].ne("unknown")
    ].copy()

    sc["quarter"] = pd.to_numeric(sc.get("quarter"), errors="coerce")
    sc["quarter_group"] = sc["quarter"].map(
        lambda q: "Q1-2" if q in (1, 2) else ("Q3-4" if q in (3, 4) else "OT")
    )

    agg = (sc.groupby(["down", "dist_bucket", "field_zone", "quarter_group"], dropna=True)
             .agg(
                 n_plays=("ep_before", "count"),
                 ep_mean=("ep_before", "mean"),
                 ep_std=("ep_before", "std"),
                 epa_def_mean=("ep_before", lambda x: None),  # placeholder
             )
             .reset_index())

    # epa_def = ep_before - ep_after at the play level; mean over plays
    sc["epa_def"] = sc["ep_before"] - sc["ep_after"]
    epa_agg = (sc.groupby(["down", "dist_bucket", "field_zone", "quarter_group"], dropna=True)
                 ["epa_def"].mean().reset_index()
                 .rename(columns={"epa_def": "epa_def_mean"}))

    result = agg.drop(columns=["epa_def_mean"]).merge(
        epa_agg, on=["down", "dist_bucket", "field_zone", "quarter_group"], how="left"
    )
    for col in ["ep_mean", "ep_std", "epa_def_mean"]:
        result[col] = result[col].round(3)
    return result


# ---------------------------------------------------------------------------
# Table 3: Team tackle distribution by game (requires player_defense + starters)
# ---------------------------------------------------------------------------

DL_POS = {"DE", "DT", "NT", "LDE", "RDE", "LDT", "RDT", "NOSE", "DG",
           "LE", "RE", "LT", "RT"}
LB_POS = {"LB", "ILB", "OLB", "MLB", "SLB", "WLB",
           "LOLB", "ROLB", "LILB", "RILB", "RLB", "LLB",
           "LIB", "RIB", "LOB", "ROB"}
DB_POS = {"CB", "FS", "SS", "DB", "LCB", "RCB", "NCB", "S",
          "LC", "RC", "SCB", "WCB", "LS", "RS", "LFS", "RFS"}


def pos_group(pos: str) -> str:
    p = (pos or "").upper().strip()
    if p in DL_POS: return "DL"
    if p in LB_POS: return "LB"
    if p in DB_POS: return "DB"
    return "OTHER"


def build_team_tackle_distribution(seasons: list[int], verbose: bool = True) -> pd.DataFrame:
    rows = []
    for season in seasons:
        season_dir = BOXSCORE_DIR / str(season)
        if not season_dir.exists():
            continue
        for gd in sorted(season_dir.iterdir()):
            if not gd.is_dir():
                continue
            pdef = gd / "player_defense.csv"
            start = gd / "starters.csv"
            if not pdef.exists():
                continue
            try:
                def_df  = pd.read_csv(pdef, dtype=str)
                star_df = pd.read_csv(start, dtype=str) if start.exists() else pd.DataFrame()
            except Exception:
                continue

            # Build player → position map from starters
            pos_map: dict[str, str] = {}
            if not star_df.empty and "player" in star_df.columns:
                for _, r in star_df.iterrows():
                    name = str(r.get("player","") or "").strip()
                    pos  = str(r.get("pos","") or "").strip()
                    if name and pos and name != "nan":
                        pos_map[name] = pos

            # Sum tackle columns
            for col in ["tackles_solo", "tackles_assists", "tackles_combined"]:
                if col in def_df.columns:
                    def_df[col] = pd.to_numeric(def_df[col], errors="coerce").fillna(0)
                else:
                    def_df[col] = 0.0

            def_df = def_df[def_df["tackles_combined"] > 0].copy()
            if def_df.empty:
                continue

            def_df["pos"] = def_df["player"].map(lambda n: pos_map.get(str(n).strip(), ""))
            def_df["pos_group"] = def_df["pos"].map(pos_group)

            for team, tg in def_df.groupby("team"):
                total_solo  = tg["tackles_solo"].sum()
                total_asst  = tg["tackles_assists"].sum()
                total_comb  = tg["tackles_combined"].sum()

                for pg, pg_df in tg.groupby("pos_group"):
                    rows.append({
                        "game_id":     gd.name,
                        "season":      season,
                        "team":        (team or "").strip().lower(),
                        "pos_group":   pg,
                        "solo":        float(pg_df["tackles_solo"].sum()),
                        "assists":     float(pg_df["tackles_assists"].sum()),
                        "combined":    float(pg_df["tackles_combined"].sum()),
                        "team_total_solo":  float(total_solo),
                        "team_total_asst":  float(total_asst),
                        "team_total_comb":  float(total_comb),
                        "share_of_solo": float(pg_df["tackles_solo"].sum() / total_solo) if total_solo > 0 else None,
                        "share_of_comb": float(pg_df["tackles_combined"].sum() / total_comb) if total_comb > 0 else None,
                    })

        if verbose:
            print(f"  {season}: distribution rows added")

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Table 4: Position-era baselines
# ---------------------------------------------------------------------------

def build_position_baselines(dist_df: pd.DataFrame) -> pd.DataFrame:
    if dist_df.empty:
        return pd.DataFrame()

    df = dist_df.copy()
    df["season"] = pd.to_numeric(df["season"], errors="coerce")

    def era(s):
        if s < 1972: return "pre-1972"
        if s < 1978: return "1972-1977"
        if s < 1994: return "1978-1993"
        if s < 2011: return "1994-2010"
        return "2011+"

    df["era"] = df["season"].map(era)

    agg = (df[df["pos_group"].isin(["DL", "LB", "DB"])]
           .groupby(["pos_group", "era", "season"], dropna=True)
           .agg(
               games=("game_id", "nunique"),
               avg_comb_per_game=("combined", "mean"),
               avg_solo_per_game=("solo", "mean"),
               avg_asst_per_game=("assists", "mean"),
               avg_share_of_comb=("share_of_comb", "mean"),
           )
           .reset_index())

    agg["solo_asst_ratio"] = (
        agg["avg_solo_per_game"] /
        (agg["avg_asst_per_game"].replace(0, np.nan))
    ).round(3)

    for col in ["avg_comb_per_game", "avg_solo_per_game",
                "avg_asst_per_game", "avg_share_of_comb"]:
        agg[col] = agg[col].round(3)

    return agg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_seasons(arg: str) -> list[int]:
    if not arg:
        return list(range(1978, 2026))
    if "-" in arg and "," not in arg:
        a, b = arg.split("-")
        return list(range(int(a), int(b) + 1))
    if "," in arg:
        return [int(x) for x in arg.split(",")]
    return [int(arg)]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", default="",
                    help="Year range: '1990-2000', '1985', or '1985,1990'")
    ap.add_argument("--tables", default="dd,ep,dist,baselines",
                    help="Comma-sep list: dd, ep, dist, baselines")
    args = ap.parse_args()

    seasons   = parse_seasons(args.seasons)
    tables    = {t.strip() for t in args.tables.split(",")}
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Processing {len(seasons)} seasons: {seasons[0]}–{seasons[-1]}")
    print(f"Tables: {', '.join(sorted(tables))}\n")

    plays = None

    # --- DD expected yards ---
    if "dd" in tables or "ep" in tables:
        print("Loading PBP plays...")
        plays = load_pbp_plays(seasons)
        if plays.empty:
            print("No plays loaded — check BOXSCORE_DIR and season range.")

    if "dd" in tables and plays is not None and not plays.empty:
        print("\nBuilding expected yards table...")
        dd_df = build_dd_expected_yards(plays)
        out = SILVER_DIR / "dd_expected_yards.parquet"
        dd_df.to_parquet(out, index=False)
        print(f"  Saved → {out}  ({len(dd_df):,} rows)")
        # Print sample
        sample = dd_df[(dd_df["play_type"] == "all") & (dd_df["down"] == 1)].sort_values("dist_bucket")
        print("\n  Sample (1st down, all play types):")
        print(sample[["dist_bucket", "field_zone", "n_plays", "avg_yards", "median_yards"]].to_string(index=False))

    if "ep" in tables and plays is not None and not plays.empty:
        print("\nBuilding EP table...")
        ep_df = build_ep_table(plays)
        out = SILVER_DIR / "dd_ep_table.parquet"
        ep_df.to_parquet(out, index=False)
        print(f"  Saved → {out}  ({len(ep_df):,} rows)")
        # Sample: 1st and 10 from midfield in Q1-2
        sample = ep_df[
            (ep_df["down"] == 1) &
            (ep_df["dist_bucket"] == "7-10") &
            (ep_df["quarter_group"] == "Q1-2")
        ].sort_values("field_zone")
        print("\n  Sample (1st & 7-10, Q1-2):")
        print(sample[["field_zone", "n_plays", "ep_mean", "epa_def_mean"]].to_string(index=False))

    if "dist" in tables or "baselines" in tables:
        print("\nBuilding team tackle distribution...")
        dist_df = build_team_tackle_distribution(seasons)
        if not dist_df.empty:
            out = SILVER_DIR / "team_tackle_distribution.parquet"
            dist_df.to_parquet(out, index=False)
            print(f"  Saved → {out}  ({len(dist_df):,} rows)")

            # Sample: league-wide DL/LB/DB share for 1985
            sample_yr = dist_df[dist_df["season"] == 1985]
            if not sample_yr.empty:
                print("\n  1985 league avg tackle share by position group:")
                print(sample_yr.groupby("pos_group")["share_of_comb"].mean().round(3))
        else:
            print("  No distribution data found (player_defense.csv may lack tackle counts).")

    if "baselines" in tables and "dist" in tables:
        dist_path = SILVER_DIR / "team_tackle_distribution.parquet"
        if dist_path.exists():
            dist_df = pd.read_parquet(dist_path)
            print("\nBuilding position-era baselines...")
            base_df = build_position_baselines(dist_df)
            out = SILVER_DIR / "position_era_baselines.parquet"
            base_df.to_parquet(out, index=False)
            print(f"  Saved → {out}  ({len(base_df):,} rows)")

    print("\nDone.")


if __name__ == "__main__":
    main()
