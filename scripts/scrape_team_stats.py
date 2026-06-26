#!/usr/bin/env python3
"""
Scrape season-level team statistics from Pro Football Reference.

Fetches the offense and/or defense season page for each year and saves
EVERY table found on the page — no hardcoded table ID list required.

Offense page: https://www.pro-football-reference.com/years/{year}/
Defense page: https://www.pro-football-reference.com/years/{year}/opp.htm

Output:
  ~/data/pfref/raw/season/team/offense/{table_id}/{table_id}_{year}.csv
  ~/data/pfref/raw/season/team/defense/{table_id}/{table_id}_{year}.csv

Years default to newest-first (2025→1950) so the most useful data arrives
first and you can interrupt without losing recent seasons.

Usage:
  python scripts/scrape_team_stats.py                    # both sides, 2025→1950
  python scripts/scrape_team_stats.py --side offense     # offense only
  python scripts/scrape_team_stats.py --side defense     # defense only
  python scripts/scrape_team_stats.py --years 2025       # one year, both sides
  python scripts/scrape_team_stats.py --years 2025-2020  # range (newest-first)
  python scripts/scrape_team_stats.py --years 2023,2024,2025
  python scripts/scrape_team_stats.py --force            # re-pull existing years
  python scripts/scrape_team_stats.py --list-tables 2025 --side offense
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from ingestion.pfref.team_stats import scrape_offense, scrape_defense, scrape_all, list_page_tables


def _parse_years(spec: str) -> list[int]:
    """Parse '2025', '2025-2020', or '2023,2024,2025' into a list (preserving order)."""
    if "," in spec:
        return [int(y.strip()) for y in spec.split(",")]
    if "-" in spec:
        parts = spec.split("-")
        lo, hi = int(parts[0]), int(parts[1])
        # Descend if lo > hi, ascend if lo < hi
        return list(range(lo, hi - 1, -1)) if lo > hi else list(range(lo, hi + 1))
    return [int(spec)]


def main():
    ap = argparse.ArgumentParser(
        description="Scrape season team stats from PFR — saves all tables found on each page.\n"
                    "Output: ~/data/pfref/raw/season/team/{offense|defense}/{table_id}/"
    )
    ap.add_argument(
        "--side",
        choices=["offense", "defense", "all"],
        default="all",
        help="Which page to scrape (default: all).",
    )
    ap.add_argument(
        "--years",
        default="2025-1950",
        help="Year(s): single (2025), range (2025-1950 = newest-first), or comma list. "
             "Default: 2025-1950.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-pull years already marked as done in metadata.",
    )
    ap.add_argument(
        "--list-tables",
        metavar="YEAR",
        type=int,
        help="Fetch one page and print all table IDs found (no data saved). "
             "Combine with --side to specify which page.",
    )
    args = ap.parse_args()

    if args.list_tables:
        side = "offense" if args.side == "all" else args.side
        list_page_tables(args.list_tables, side)
        return

    years = _parse_years(args.years)
    print(f"Side  : {args.side}")
    print(f"Years : {years[0]}→{years[-1]} ({len(years)} year(s))")
    print(f"Force : {args.force}")
    print()

    skip = not args.force
    if args.side == "offense":
        scrape_offense(years=years, skip_existing=skip, force=args.force)
    elif args.side == "defense":
        scrape_defense(years=years, skip_existing=skip, force=args.force)
    else:
        scrape_all(years=years, skip_existing=skip, force=args.force)


if __name__ == "__main__":
    main()
