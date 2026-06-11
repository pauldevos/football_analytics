#!/usr/bin/env python3
"""
ETL: team-passing + team-rushing CSVs → team_offense_season table.

Joins passing and rushing season data per team per year, computes
pass/run ratio and within-season ranks (1 = best), then upserts
into team_offense_season.

Usage:
  python scripts/etl_team_offense_season.py              # all seasons
  python scripts/etl_team_offense_season.py --season 2012
  python scripts/etl_team_offense_season.py --season 2012 --qa-team min
"""

import argparse
import csv
import sys
from pathlib import Path

PFREF       = Path("/Users/devos/data/pfref")
PASSING_DIR = PFREF / "team-offense" / "team-passing"
RUSHING_DIR = PFREF / "team-offense" / "team-rushing"

sys.path.insert(0, str(Path(__file__).parent))
from db import get_engine

from sqlalchemy import text

# ── team name → PFR abbrev mapping ────────────────────────────────────────────
# Keys are exactly as they appear in the team-passing/team-rushing CSVs.
# All relocated franchises map to their current PFR abbrev.
TEAM_NAME_TO_ABBREV: dict[str, str] = {
    # AFC East
    "Buffalo Bills":              "buf",
    "Miami Dolphins":             "mia",
    "New England Patriots":       "nwe",
    "Boston Patriots":            "nwe",
    "New York Jets":              "nyj",
    "New York Titans":            "nyj",
    # AFC North
    "Baltimore Ravens":           "rav",
    "Cincinnati Bengals":         "cin",
    "Cleveland Browns":           "cle",
    "Pittsburgh Steelers":        "pit",
    # AFC South
    "Houston Texans":             "htx",
    "Indianapolis Colts":         "clt",
    "Baltimore Colts":            "clt",
    "Jacksonville Jaguars":       "jax",
    "Kansas City Chiefs":         "kan",
    "Dallas Texans":              "kan",  # AFL Dallas Texans → KC Chiefs
    # AFC West
    "Denver Broncos":             "den",
    "Las Vegas Raiders":          "rai",
    "Oakland Raiders":            "rai",
    "Los Angeles Raiders":        "rai",
    "Los Angeles Chargers":       "sdg",
    "San Diego Chargers":         "sdg",
    "Seattle Seahawks":           "sea",
    # NFC East
    "Dallas Cowboys":             "dal",
    "New York Giants":            "nyg",
    "Philadelphia Eagles":        "phi",
    "Washington Commanders":      "was",
    "Washington Football Team":   "was",
    "Washington Redskins":        "was",
    # NFC North
    "Chicago Bears":              "chi",
    "Decatur Staleys":            "chi",
    "Chicago Staleys":            "chi",
    "Detroit Lions":              "det",
    "Portsmouth Spartans":        "det",
    "Green Bay Packers":          "gnb",
    "Minnesota Vikings":          "min",
    # NFC South
    "Atlanta Falcons":            "atl",
    "Carolina Panthers":          "car",
    "New Orleans Saints":         "nor",
    "Tampa Bay Buccaneers":       "tam",
    # NFC West
    "Arizona Cardinals":          "crd",
    "Phoenix Cardinals":          "crd",
    "St. Louis Cardinals":        "crd",
    "Chicago Cardinals":          "crd",
    "Los Angeles Rams":           "ram",
    "St. Louis Rams":             "ram",
    "Cleveland Rams":             "ram",
    "San Francisco 49ers":        "sfo",
    # Tennessee/Houston
    "Tennessee Titans":           "oti",
    "Tennessee Oilers":           "oti",
    "Houston Oilers":             "oti",
    # AFC South cont.
    "Tennessee Titans":           "oti",
    # Two-city teams with ambiguous histories
    "Baltimore Colts (AFL)":      "clt",
}


def _safe(val, cast=float, default=None):
    try:
        v = str(val).strip()
        return cast(v) if v else default
    except (ValueError, TypeError):
        return default


def _load_passing(season: int) -> dict[str, dict]:
    """
    Return {team_name_raw: {pass_att, pass_comp, ...}} for the season.

    PFR's team-passing CSV has two columns both named 'sack_yards':
      index 6  = total passing yards
      index 18 = yards lost to sacks
    csv.DictReader only keeps the last occurrence, so we use positional
    parsing via csv.reader for this file to capture both values.
    """
    path = PASSING_DIR / f"team-passing-{season}.csv"
    if not path.exists():
        return {}

    out = {}
    with open(path) as f:
        reader = csv.reader(f)
        headers = next(reader)

        # Build a name→index map for non-duplicate columns
        hmap = {h: i for i, h in enumerate(headers)}

        # The duplicate 'sack_yards' columns — find both by scanning
        sack_yards_indices = [i for i, h in enumerate(headers) if h == "sack_yards"]
        pass_yds_idx    = sack_yards_indices[0] if len(sack_yards_indices) > 0 else None
        sack_yds_idx    = sack_yards_indices[1] if len(sack_yards_indices) > 1 else None

        def _col(row: list, key: str, idx_override=None):
            idx = idx_override if idx_override is not None else hmap.get(key)
            if idx is None or idx >= len(row):
                return None
            return row[idx] or None

        for row in reader:
            if not row:
                continue
            team = _col(row, "team")
            if not team or team.strip() == "":
                continue
            team = team.strip()

            out[team] = {
                "pass_comp":     _safe(_col(row, "comp"),          int),
                "pass_att":      _safe(_col(row, "att"),           int),
                "pass_yds":      _safe(_col(row, None, pass_yds_idx),  int),
                "pass_td":       _safe(_col(row, "td"),            int),
                "pass_int":      _safe(_col(row, "int"),           int),
                "comp_pct":      _safe(_col(row, "cmp_pct"),       float),
                "qb_rating":     _safe(_col(row, "qb_rating"),     float),
                "sacks_taken":   _safe(_col(row, "sack"),          int),
                "sack_yds_lost": _safe(_col(row, None, sack_yds_idx), int),
                "sack_pct":      _safe(_col(row, "sack_pct"),      float),
                "games":         _safe(_col(row, "games"),         int),
            }
    return out


def _load_rushing(season: int) -> dict[str, dict]:
    """Return {team_name_raw: {rush_att, rush_yds, rush_ypc, rush_td}} for the season."""
    path = RUSHING_DIR / f"team-rushing-{season}.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            team = row.get("team", "").strip()
            if not team:
                continue
            out[team] = {
                "rush_att": _safe(row.get("att"),           int),
                "rush_yds": _safe(row.get("yards"),         int),
                "rush_td":  _safe(row.get("td"),            int),
                "rush_ypc": _safe(row.get("yards_per_att"), float),
            }
    return out


def _rank_asc(rows: list[dict], key: str) -> dict[str, int]:
    """Rank teams 1=best for a stat where lower is better (e.g. sacks_taken)."""
    valid = [(r["abbrev"], r[key]) for r in rows if r[key] is not None]
    valid.sort(key=lambda x: x[1])
    return {abbrev: i + 1 for i, (abbrev, _) in enumerate(valid)}


def _rank_desc(rows: list[dict], key: str) -> dict[str, int]:
    """Rank teams 1=best for a stat where higher is better (e.g. pass_yds)."""
    valid = [(r["abbrev"], r[key]) for r in rows if r[key] is not None]
    valid.sort(key=lambda x: x[1], reverse=True)
    return {abbrev: i + 1 for i, (abbrev, _) in enumerate(valid)}


def process_season(season: int, engine, qa_team: str | None = None) -> int:
    passing = _load_passing(season)
    rushing = _load_rushing(season)

    all_team_names = set(passing) | set(rushing)
    if not all_team_names:
        print(f"  {season}: no data files found, skipping")
        return 0

    rows = []
    unmapped = []
    for team_name in sorted(all_team_names):
        abbrev = TEAM_NAME_TO_ABBREV.get(team_name)
        if abbrev is None:
            unmapped.append(team_name)
            continue

        p = passing.get(team_name, {})
        r = rushing.get(team_name, {})

        pass_att  = p.get("pass_att")
        rush_att  = r.get("rush_att")
        total     = (pass_att or 0) + (rush_att or 0)

        rows.append({
            "abbrev":      abbrev,
            "season":      season,
            "games":       p.get("games") or r.get("games"),  # same value either way
            "pass_comp":   p.get("pass_comp"),
            "pass_att":    pass_att,
            "pass_yds":    p.get("pass_yds"),
            "pass_td":     p.get("pass_td"),
            "pass_int":    p.get("pass_int"),
            "comp_pct":    p.get("comp_pct"),
            "qb_rating":   p.get("qb_rating"),
            "sacks_taken": p.get("sacks_taken"),
            "sack_yds_lost": p.get("sack_yds_lost"),
            "sack_pct":    p.get("sack_pct"),
            "rush_att":    rush_att,
            "rush_yds":    r.get("rush_yds"),
            "rush_td":     r.get("rush_td"),
            "rush_ypc":    r.get("rush_ypc"),
            "total_plays": total if total > 0 else None,
            "pass_run_ratio": round(pass_att / total, 4) if (pass_att and total) else None,
        })

    if unmapped:
        print(f"  {season}: WARN unmapped teams: {unmapped}", file=sys.stderr)

    # Compute ranks
    rank_pass_yds     = _rank_desc(rows, "pass_yds")
    rank_rush_ypc     = _rank_desc(rows, "rush_ypc")
    rank_rush_yds     = _rank_desc(rows, "rush_yds")
    rank_sacks_taken  = _rank_asc(rows, "sacks_taken")   # fewer sacks = better rank

    upsert_sql = text("""
        INSERT INTO team_offense_season (
            team_abbrev, season, games,
            pass_comp, pass_att, pass_yds, pass_td, pass_int,
            comp_pct, qb_rating,
            sacks_taken, sack_yds_lost, sack_pct,
            rush_att, rush_yds, rush_td, rush_ypc,
            total_plays, pass_run_ratio,
            pass_yds_rank, rush_ypc_rank, sacks_taken_rank, rush_yds_rank
        ) VALUES (
            :team_abbrev, :season, :games,
            :pass_comp, :pass_att, :pass_yds, :pass_td, :pass_int,
            :comp_pct, :qb_rating,
            :sacks_taken, :sack_yds_lost, :sack_pct,
            :rush_att, :rush_yds, :rush_td, :rush_ypc,
            :total_plays, :pass_run_ratio,
            :pass_yds_rank, :rush_ypc_rank, :sacks_taken_rank, :rush_yds_rank
        )
        ON CONFLICT (team_abbrev, season) DO UPDATE SET
            games           = EXCLUDED.games,
            pass_comp       = EXCLUDED.pass_comp,
            pass_att        = EXCLUDED.pass_att,
            pass_yds        = EXCLUDED.pass_yds,
            pass_td         = EXCLUDED.pass_td,
            pass_int        = EXCLUDED.pass_int,
            comp_pct        = EXCLUDED.comp_pct,
            qb_rating       = EXCLUDED.qb_rating,
            sacks_taken     = EXCLUDED.sacks_taken,
            sack_yds_lost   = EXCLUDED.sack_yds_lost,
            sack_pct        = EXCLUDED.sack_pct,
            rush_att        = EXCLUDED.rush_att,
            rush_yds        = EXCLUDED.rush_yds,
            rush_td         = EXCLUDED.rush_td,
            rush_ypc        = EXCLUDED.rush_ypc,
            total_plays     = EXCLUDED.total_plays,
            pass_run_ratio  = EXCLUDED.pass_run_ratio,
            pass_yds_rank   = EXCLUDED.pass_yds_rank,
            rush_ypc_rank   = EXCLUDED.rush_ypc_rank,
            sacks_taken_rank = EXCLUDED.sacks_taken_rank,
            rush_yds_rank   = EXCLUDED.rush_yds_rank
    """)

    written = 0
    with engine.begin() as conn:
        for row in rows:
            abbrev = row["abbrev"]
            if qa_team and abbrev != qa_team:
                continue
            conn.execute(upsert_sql, {
                "team_abbrev":      abbrev,
                "season":           row["season"],
                "games":            row["games"],
                "pass_comp":        row["pass_comp"],
                "pass_att":         row["pass_att"],
                "pass_yds":         row["pass_yds"],
                "pass_td":          row["pass_td"],
                "pass_int":         row["pass_int"],
                "comp_pct":         row["comp_pct"],
                "qb_rating":        row["qb_rating"],
                "sacks_taken":      row["sacks_taken"],
                "sack_yds_lost":    row["sack_yds_lost"],
                "sack_pct":         row["sack_pct"],
                "rush_att":         row["rush_att"],
                "rush_yds":         row["rush_yds"],
                "rush_td":          row["rush_td"],
                "rush_ypc":         row["rush_ypc"],
                "total_plays":      row["total_plays"],
                "pass_run_ratio":   row["pass_run_ratio"],
                "pass_yds_rank":    rank_pass_yds.get(abbrev),
                "rush_ypc_rank":    rank_rush_ypc.get(abbrev),
                "sacks_taken_rank": rank_sacks_taken.get(abbrev),
                "rush_yds_rank":    rank_rush_yds.get(abbrev),
            })
            written += 1

    return written


def main():
    ap = argparse.ArgumentParser(description="Load team offense season stats")
    ap.add_argument("--season", type=int, help="Process a single season year")
    ap.add_argument("--qa-team", help="Only write rows for this abbrev (e.g. min)")
    args = ap.parse_args()

    engine = get_engine()
    total  = 0

    if args.season:
        seasons = [args.season]
    else:
        seasons = sorted(
            int(p.stem.replace("team-passing-", ""))
            for p in PASSING_DIR.glob("team-passing-*.csv")
        )

    for season in seasons:
        n = process_season(season, engine, qa_team=args.qa_team)
        if n:
            print(f"  {season}: {n} teams written")
        total += n

    print(f"\nDone. Total rows written/updated: {total}")


if __name__ == "__main__":
    main()
