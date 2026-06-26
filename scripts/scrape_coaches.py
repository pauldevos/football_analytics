#!/usr/bin/env python3
"""
Scrape coaching records from Pro Football Reference.

Phase 1 — Seed: pull /coaches/ index to build the manifest of all head coaches.
Phase 2 — Pull: fetch each coach's personal page (4 tables each).
Phase 3 — Tree: after phase 2, re-run pull to pick up coordinators/assistants
           discovered via 'worked for' / 'employed' links on HC pages.

Output:
  ~/data/pfref/raw/coaches/coach_manifest.csv
  ~/data/pfref/raw/coaches/{coach_id}/coaching_record.csv
  ~/data/pfref/raw/coaches/{coach_id}/team_ranks.csv
  ~/data/pfref/raw/coaches/{coach_id}/coaching_history.csv
  ~/data/pfref/raw/coaches/{coach_id}/worked_for.csv
  ~/data/pfref/raw/coaches/{coach_id}/employed.csv

Usage:
  python scripts/scrape_coaches.py --seed              # step 1: build manifest from HC index
  python scripts/scrape_coaches.py --pull              # step 2: pull all pending coaches
  python scripts/scrape_coaches.py --pull --hc-only   # step 2: only pull HCs (source=hc_index)
  python scripts/scrape_coaches.py --status            # show manifest summary
  python scripts/scrape_coaches.py --coach ShulDo0    # pull one specific coach
  python scripts/scrape_coaches.py --seed --pull       # seed then immediately pull
"""

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from ingestion.pfref.coaches import (
    seed_manifest,
    scrape_all_coaches,
    scrape_coach,
    manifest_summary,
    _read_manifest,
    _write_manifest,
    _add_to_manifest,
    _coach_id_from_href,
)
from ingestion.pfref.scraper_playwright import PlaywrightScraper


def main():
    ap = argparse.ArgumentParser(
        description="Scrape NFL coaching records from PFR.",
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--seed",   action="store_true", help="Build manifest from HC index page.")
    mode.add_argument("--pull",   action="store_true", help="Pull all pending coaches.")
    mode.add_argument("--status", action="store_true", help="Print manifest summary and exit.")
    mode.add_argument("--coach",  metavar="COACH_ID",  help="Pull a single coach by ID (e.g. ShulDo0).")

    ap.add_argument(
        "--hc-only",
        action="store_true",
        help="With --pull: only pull coaches sourced from the HC index (skip tree coaches).",
    )
    ap.add_argument(
        "--force-seed",
        action="store_true",
        help="With --seed: re-seed even if manifest already exists.",
    )
    args = ap.parse_args()

    if args.status:
        manifest_summary()
        return

    if args.coach:
        manifest = _read_manifest()
        if args.coach not in manifest:
            # Add it on the fly so scrape_coach can find it
            href = f"/coaches/{args.coach}.htm"
            _add_to_manifest(manifest, args.coach, href, source="manual")
            _write_manifest(manifest)
        scraper = PlaywrightScraper()
        try:
            scrape_coach(args.coach, scraper=scraper, manifest=manifest)
            _write_manifest(manifest)
        finally:
            scraper.close()
        return

    if args.seed:
        scraper = PlaywrightScraper()
        try:
            seed_manifest(scraper=scraper, force=args.force_seed)
        finally:
            scraper.close()

    if args.pull:
        source_filter = "hc_index" if args.hc_only else None
        scrape_all_coaches(skip_pulled=True, source_filter=source_filter)


if __name__ == "__main__":
    main()
