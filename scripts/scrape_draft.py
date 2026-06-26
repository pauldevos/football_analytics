#!/usr/bin/env python3
"""
Scrape NFL draft picks from Pro Football Reference.

Source: https://www.pro-football-reference.com/years/{year}/draft.htm
Output: ~/data/pfref/raw/season/draft/draft_{year}.csv

NFL drafts begin in 1936.  Already-pulled years are skipped unless --force is given.

Usage:
  python scripts/scrape_draft.py                        # 1936–2025 (full history)
  python scripts/scrape_draft.py --years 2025           # single year
  python scripts/scrape_draft.py --years 2020-2025      # inclusive range
  python scripts/scrape_draft.py --years 2023,2024,2025 # comma-separated list
  python scripts/scrape_draft.py --force                # re-pull even if file exists
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from ingestion.pfref.draft import scrape_draft


def _parse_years(spec: str) -> list[int]:
    """Parse '2025', '2020-2025', or '2023,2024,2025' into a sorted list."""
    if "," in spec:
        return sorted(int(y.strip()) for y in spec.split(","))
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


def main():
    ap = argparse.ArgumentParser(
        description="Scrape NFL draft picks from PFR (1936–2025).\n"
                    "Output: ~/data/pfref/raw/season/draft/draft_{year}.csv"
    )
    ap.add_argument(
        "--years",
        default="1936-2025",
        help="Year(s) to pull: single year, range (2020-2025), or comma list. "
             "Default: 1936-2025 (full history).",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-pull years that already have a file on disk.",
    )
    args = ap.parse_args()

    years = _parse_years(args.years)
    print(f"Pulling draft data for {len(years)} year(s): {years[0]}–{years[-1]}")

    scrape_draft(years=years, skip_existing=not args.force)


if __name__ == "__main__":
    main()
