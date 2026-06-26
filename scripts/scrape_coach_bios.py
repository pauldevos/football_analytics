#!/usr/bin/env python3
"""
Scrape biographical fields from PFR coach pages that are NOT in the 5 standard tables:
  - HOF status (Hall of Fame induction year)
  - Playing position(s)
  - College(s) attended
  - Playing career years (NFL, AFL, etc.)
  - Birthdate / birthplace

PFR coach page bio is in <div id="meta"> — a series of <p> and <li> elements
with text like:
    Position: Center
    College(s): Michigan
    Hall of Fame Induction: 1985
    Born: January 14, 1920, in Springfield, IL

Output:
  ~/data/pfref/raw/coaches/coach_bios.csv
      coach_id, coach_name, hof_year, playing_position, playing_college,
      playing_nfl_team, playing_career_years, born_date, birthplace

Usage:
    cd ~/github/football/football_analytics
    # Pull bios for all coaches already in manifest:
    .venv/bin/python scripts/scrape_coach_bios.py
    # Or for a single coach:
    .venv/bin/python scripts/scrape_coach_bios.py --coach GibbJo0
"""

import argparse
import csv
import pathlib
import re
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from bs4 import BeautifulSoup
from ingestion.pfref.coaches import COACHES_DIR, MANIFEST_PATH, _read_manifest
from ingestion.pfref.scraper_playwright import PlaywrightScraper

BASE_URL = "https://www.pro-football-reference.com"
OUTPUT_PATH = COACHES_DIR / "coach_bios.csv"

_OUTPUT_FIELDS = [
    "coach_id", "coach_name",
    "hof_year",              # Hall of Fame induction year (int or '')
    "playing_position",      # 'Quarterback', 'Linebacker', etc.
    "playing_college",       # 'Michigan', 'San Diego State', etc.
    "playing_nfl_team",      # First NFL/AFL team as player
    "playing_career_start",  # First year as professional player
    "playing_career_end",    # Last year as professional player
    "born_date",             # e.g. 'November 25, 1940'
    "birthplace",            # e.g. 'Mocksville, NC'
    "scraped_at",
]


def _parse_bio(soup: BeautifulSoup, coach_id: str) -> dict:
    """Extract bio fields from the meta div of a PFR coach page."""
    result = {k: "" for k in _OUTPUT_FIELDS}
    result["coach_id"] = coach_id

    meta = soup.find("div", id="meta")
    if not meta:
        return result

    # Name from h1
    h1 = soup.find("h1", itemprop="name") or soup.find("h1")
    if h1:
        result["coach_name"] = h1.get_text(strip=True)

    # Parse <p> and <li> elements in meta div
    for el in meta.find_all(["p", "li"]):
        text = el.get_text(" ", strip=True)
        text_lower = text.lower()

        # HOF
        if "hall of fame" in text_lower or "pro football hall of fame" in text_lower:
            # Look for a year
            year_match = re.search(r"\b(19|20)\d{2}\b", text)
            if year_match:
                result["hof_year"] = year_match.group(0)
            else:
                result["hof_year"] = "inducted"  # HOF but no year parsed

        # Position
        if text_lower.startswith("position"):
            parts = text.split(":", 1)
            if len(parts) > 1:
                result["playing_position"] = parts[1].strip()

        # College
        if text_lower.startswith("college") or "college(s)" in text_lower:
            parts = text.split(":", 1)
            if len(parts) > 1:
                result["playing_college"] = parts[1].strip()

        # Born
        if text_lower.startswith("born"):
            parts = text.split(":", 1)
            if len(parts) > 1:
                born_text = parts[1].strip()
                # Try to split date and birthplace (usually "Date, in City, State")
                in_match = re.search(r"\bin\b", born_text)
                if in_match:
                    result["born_date"] = born_text[:in_match.start()].strip().rstrip(",")
                    result["birthplace"] = born_text[in_match.end():].strip()
                else:
                    result["born_date"] = born_text

    # Look for playing career table (draft/playing info often in a separate table or section)
    # PFR coach pages sometimes have a playing career section with a table
    playing_header = soup.find(lambda tag: tag.name in ["h2", "h3"] and
                               "playing career" in tag.get_text(strip=True).lower())
    if playing_header:
        # Find the next table after this header
        for sibling in playing_header.find_next_siblings():
            if sibling.name == "table":
                rows = sibling.find("tbody").find_all("tr") if sibling.find("tbody") else []
                years = []
                teams = []
                for tr in rows:
                    cells = [td.get_text(strip=True) for td in tr.find_all(["td","th"])]
                    if cells:
                        years.append(cells[0])
                        if len(cells) > 1:
                            teams.append(cells[1])
                if years:
                    result["playing_career_start"] = years[0]
                    result["playing_career_end"] = years[-1]
                if teams:
                    result["playing_nfl_team"] = teams[0]
                break
            elif sibling.name in ["h2", "h3"]:
                break  # Hit next section

    # Fallback: look for career years in meta text patterns
    # e.g. "1961-1963" or "(1961-1963)"
    if not result["playing_career_start"]:
        meta_text = meta.get_text(" ", strip=True)
        year_range = re.search(r"\b(19\d{2})[\-–](19\d{2}|20\d{2})\b", meta_text)
        if year_range:
            result["playing_career_start"] = year_range.group(1)
            result["playing_career_end"] = year_range.group(2)

    from datetime import datetime
    result["scraped_at"] = datetime.now().isoformat()
    return result


def scrape_coach_bio(coach_id: str, scraper: PlaywrightScraper, manifest: dict) -> dict:
    """Fetch one coach page and return bio dict."""
    if coach_id not in manifest:
        href = f"/coaches/{coach_id}.htm"
    else:
        href = manifest[coach_id].get("href", f"/coaches/{coach_id}.htm")

    url = f"{BASE_URL}{href}"
    print(f"  [{coach_id}] {url}")
    soup = scraper.fetch_and_sleep(url, strip_comments=True)
    return _parse_bio(soup, coach_id)


def scrape_all_bios(coach_ids: list[str] | None = None, skip_existing: bool = True) -> None:
    """
    Scrape bio data for all (or a subset of) coaches in the manifest.

    Args:
        coach_ids:      If provided, only scrape these IDs.
        skip_existing:  Skip coaches already in coach_bios.csv.
    """
    manifest = _read_manifest()

    # Load existing bios to skip
    existing: set[str] = set()
    if skip_existing and OUTPUT_PATH.exists():
        with open(OUTPUT_PATH, newline="") as f:
            existing = {row["coach_id"] for row in csv.DictReader(f)}

    targets = coach_ids or list(manifest.keys())
    targets = [c for c in targets if c not in existing]
    print(f"Coaches to bio-scrape: {len(targets)} (skipping {len(existing)} already done)")

    write_header = not OUTPUT_PATH.exists() or OUTPUT_PATH.stat().st_size == 0

    scraper = PlaywrightScraper(sleep_min=4, sleep_max=7)
    try:
        COACHES_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_PATH, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_OUTPUT_FIELDS)
            if write_header:
                writer.writeheader()

            for i, coach_id in enumerate(targets):
                print(f"\n[{i+1}/{len(targets)}] {coach_id}")
                try:
                    bio = scrape_coach_bio(coach_id, scraper, manifest)
                    writer.writerow(bio)
                    f.flush()
                    print(f"  → HOF={bio['hof_year']} pos={bio['playing_position']} "
                          f"college={bio['playing_college']}")
                except Exception as e:
                    print(f"  ERROR: {e}")
    finally:
        scraper.close()

    print(f"\nDone. Results in {OUTPUT_PATH}")


def main():
    ap = argparse.ArgumentParser(description="Scrape HOF/bio fields from PFR coach pages.")
    ap.add_argument("--coach", metavar="COACH_ID", help="Scrape one coach only.")
    ap.add_argument("--no-skip", action="store_true", help="Re-scrape coaches already in output.")
    args = ap.parse_args()

    if args.coach:
        manifest = _read_manifest()
        scraper = PlaywrightScraper()
        try:
            bio = scrape_coach_bio(args.coach, scraper, manifest)
            for k, v in bio.items():
                if v:
                    print(f"  {k}: {v}")
        finally:
            scraper.close()
    else:
        scrape_all_bios(skip_existing=not args.no_skip)


if __name__ == "__main__":
    main()
