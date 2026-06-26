#!/usr/bin/env python3
"""
Scrape season-level player statistics from Pro Football Reference.

Sources: https://www.pro-football-reference.com/years/{year}/{stat}.htm
Output:  ~/data/pfref/raw/season/player/{stat}/{stat}_{year}.csv

Stat types: passing, rushing, receiving, defense, kicking, punting, returns, scoring
(scrimmage is intentionally excluded — rushing + receiving cover the same data)

Already-pulled years are skipped unless --force is given.
Files that exist on disk but lack a metadata entry are back-filled and skipped.

Usage:
  python scripts/scrape_player_stats.py                           # all types, 1950–2025
  python scripts/scrape_player_stats.py --types defense           # one type, all years
  python scripts/scrape_player_stats.py --types kicking,punting   # two types, all years
  python scripts/scrape_player_stats.py --years 2025              # all types, 2025 only
  python scripts/scrape_player_stats.py --types defense --years 2025
  python scripts/scrape_player_stats.py --force                   # ignore existing files
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from ingestion.pfref.player_stats import scrape_all

_VALID_TYPES = ["passing", "rushing", "receiving", "defense",
                "kicking", "punting", "returns", "scoring"]


def _parse_years(spec: str) -> list[int]:
    if "," in spec:
        return sorted(int(y.strip()) for y in spec.split(","))
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


def _parse_types(spec: str) -> list[str]:
    types = [t.strip() for t in spec.split(",")]
    invalid = [t for t in types if t not in _VALID_TYPES]
    if invalid:
        print(f"ERROR: unknown stat type(s): {invalid}")
        print(f"Valid types: {_VALID_TYPES}")
        sys.exit(1)
    return types


def main():
    ap = argparse.ArgumentParser(
        description="Scrape season player stats from PFR.\n"
                    "Output: ~/data/pfref/raw/season/player/{stat}/{stat}_{year}.csv"
    )
    ap.add_argument(
        "--types",
        default=",".join(_VALID_TYPES),
        help=f"Stat type(s) to pull, comma-separated. Default: all. "
             f"Valid: {', '.join(_VALID_TYPES)}",
    )
    ap.add_argument(
        "--years",
        default="1950-2025",
        help="Year(s): single (2025), range (2020-2025), or comma list. Default: 1950-2025.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-pull years that already exist on disk.",
    )
    args = ap.parse_args()

    years = _parse_years(args.years)
    types = _parse_types(args.types)

    print(f"Stat types : {types}")
    print(f"Years      : {years[0]}–{years[-1]} ({len(years)} year(s))")
    print(f"Force      : {args.force}")
    print()

    scrape_all(years=years, skip_existing=not args.force, stat_types=types)


if __name__ == "__main__":
    main()
