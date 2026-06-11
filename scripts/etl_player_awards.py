#!/usr/bin/env python3
"""
ETL: all_pro/*.csv → player_awards table.

Normalizes multi-org award rows (AP, FW, SN, PFF, PFWA) into a single
award_class per row, resolves pfr_player_id from the short id, and upserts.

award_class values:
  ALL_PRO_1   AP 1st Tm
  ALL_PRO_2   AP 2nd Tm
  ALL_CONF    Conference all-star (FW "1st Tm All-Conf." / "2nd Tm All-Conf.")
  PFF_1       PFF 1st Tm
  PFF_2       PFF 2nd Tm
  SN_1        Sporting News 1st Tm
  SN_2        Sporting News 2nd Tm
  PRO_BOWL    Any Pro Bowl designation
  OTHER       Anything that doesn't match the above patterns

Usage:
  python scripts/etl_player_awards.py              # all seasons
  python scripts/etl_player_awards.py --season 2012
  python scripts/etl_player_awards.py --season 2012 --org AP
"""

import argparse
import csv
import sys
from pathlib import Path

PFREF    = Path("/Users/devos/data/pfref")
ALLP_DIR = PFREF / "all_pro"

sys.path.insert(0, str(Path(__file__).parent))
from db import get_engine
from sqlalchemy import text


def _pfr_player_id(short_id: str) -> str | None:
    """Convert short PFR player id (e.g. 'MannPe00') to full path ('/players/M/MannPe00.htm')."""
    if not short_id or len(short_id) < 2:
        return None
    # PFR directory = first letter of the surname part (first 4 chars)
    first_letter = short_id[0].upper()
    return f"/players/{first_letter}/{short_id}.htm"


def _award_class(org: str, designation: str) -> str:
    org, des = (org or "").upper().strip(), (designation or "").lower().strip()
    if "pro bowl" in des:
        return "PRO_BOWL"
    if org == "AP":
        if "1st" in des:   return "ALL_PRO_1"
        if "2nd" in des:   return "ALL_PRO_2"
    if org in ("FW", "PFWA"):
        if "all-conf" in des or "all conf" in des:
            return "ALL_CONF"
        if "1st" in des:   return "ALL_PRO_1"
        if "2nd" in des:   return "ALL_PRO_2"
    if org == "PFF":
        if "1st" in des:   return "PFF_1"
        if "2nd" in des:   return "PFF_2"
    if org == "SN":
        if "1st" in des:   return "SN_1"
        if "2nd" in des:   return "SN_2"
    return "OTHER"


def process_season(season: int, engine, filter_org: str | None = None) -> int:
    path = ALLP_DIR / f"all_pro_{season}.csv"
    if not path.exists():
        return 0

    upsert_sql = text("""
        INSERT INTO player_awards (
            pfr_short_id, pfr_player_id, player_name,
            season, team_abbrev, position,
            org, designation, award_class
        ) VALUES (
            :pfr_short_id, :pfr_player_id, :player_name,
            :season, :team_abbrev, :position,
            :org, :designation, :award_class
        )
        ON CONFLICT (pfr_short_id, season, org, designation) DO UPDATE SET
            pfr_player_id = COALESCE(EXCLUDED.pfr_player_id, player_awards.pfr_player_id),
            player_name   = EXCLUDED.player_name,
            team_abbrev   = EXCLUDED.team_abbrev,
            position      = EXCLUDED.position,
            award_class   = EXCLUDED.award_class
    """)

    written = 0
    with open(path) as f, engine.begin() as conn:
        for row in csv.DictReader(f):
            short_id    = (row.get("player_id") or "").strip()
            player_name = (row.get("player_name") or "").strip()
            org         = (row.get("org") or "").strip().upper()
            designation = (row.get("designation") or "").strip()
            team        = (row.get("team") or "").strip().upper()
            position    = (row.get("pos") or "").strip()

            if not player_name or not org or not designation:
                continue
            if filter_org and org != filter_org.upper():
                continue

            conn.execute(upsert_sql, {
                "pfr_short_id":  short_id or player_name,
                "pfr_player_id": _pfr_player_id(short_id) if short_id else None,
                "player_name":   player_name,
                "season":        season,
                "team_abbrev":   team,
                "position":      position,
                "org":           org,
                "designation":   designation,
                "award_class":   _award_class(org, designation),
            })
            written += 1

    return written


def main():
    ap = argparse.ArgumentParser(description="Load player awards from all_pro CSVs")
    ap.add_argument("--season", type=int, help="Process a single season year")
    ap.add_argument("--org",    help="Only load rows for this org (e.g. AP, PFF)")
    args = ap.parse_args()

    engine = get_engine()
    total  = 0

    if args.season:
        seasons = [args.season]
    else:
        seasons = sorted(
            int(p.stem.replace("all_pro_", ""))
            for p in ALLP_DIR.glob("all_pro_*.csv")
        )

    for season in seasons:
        n = process_season(season, engine, filter_org=args.org)
        if n:
            print(f"  {season}: {n} award rows written")
        total += n

    print(f"\nDone. Total award rows written/updated: {total}")


if __name__ == "__main__":
    main()
