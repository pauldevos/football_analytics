#!/usr/bin/env python3
"""
DEPRECATED: PFR no longer hosts /friv/coordinators.fcgi (returns 404).

Use scrape_team_season_coordinators.py instead, which pulls coordinator
links directly from team season pages (/teams/{abbrev}/{year}.htm).

This script is kept for reference but should not be run.
"""
raise SystemExit("Use scrape_team_season_coordinators.py instead.")


import csv
import pathlib
import sys
import time
from datetime import datetime

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from bs4 import BeautifulSoup
from ingestion.pfref.coaches import (
    COACHES_DIR,
    MANIFEST_PATH,
    _read_manifest,
    _write_manifest,
    _add_to_manifest,
    _coach_id_from_href,
)
from ingestion.pfref.scraper_playwright import PlaywrightScraper

BASE_URL = "https://www.pro-football-reference.com"
COORDINATOR_INDEX_URL = f"{BASE_URL}/friv/coordinators.fcgi"
OUTPUT_PATH = COACHES_DIR / "coordinator_index.csv"

_OUTPUT_FIELDS = ["year", "team", "hc_name", "hc_id", "oc_name", "oc_id", "dc_name", "dc_id"]


def _extract_name_and_id(td) -> tuple[str, str]:
    """From a table cell, return (display_name, coach_id). coach_id is '' if no link."""
    name = td.get_text(" ", strip=True)
    a = td.find("a", href=True)
    if a and "/coaches/" in a["href"]:
        stem = pathlib.Path(a["href"]).stem
        if "_" not in stem:  # exclude _register pages
            return name, stem
    return name, ""


def scrape_coordinator_index() -> int:
    """
    Fetch the coordinator index and write coordinator_index.csv.
    Also adds any new coach IDs to the manifest as pending.

    Returns number of new coaches added to manifest.
    """
    manifest = _read_manifest()
    rows: list[dict] = []

    scraper = PlaywrightScraper(sleep_min=3, sleep_max=5)
    try:
        print(f"Fetching {COORDINATOR_INDEX_URL} ...")
        soup = scraper.fetch_and_sleep(COORDINATOR_INDEX_URL, strip_comments=True)

        # The page has one big table; we'll also handle multiple tables
        # PFR structure: table id="coordinators" or similar
        # Each row: Year | Tm | HC link | OC link | DC link
        tables = soup.find_all("table")
        print(f"  Found {len(tables)} table(s)")

        for table in tables:
            thead = table.find("thead")
            tbody = table.find("tbody")
            if not thead or not tbody:
                continue

            # Get column names from last header row
            header_cells = thead.find_all("tr")[-1].find_all(["th", "td"])
            col_names = [th.get("data-stat", th.get_text(strip=True).lower()) for th in header_cells]
            print(f"  Table cols: {col_names}")

            for tr in tbody.find_all("tr"):
                if "thead" in tr.get("class", []) or "divider" in tr.get("class", []):
                    continue
                cells = tr.find_all(["th", "td"])
                if len(cells) < 3:
                    continue

                row: dict = {}
                for col, td in zip(col_names, cells):
                    col = col.strip().lower()
                    if col in ("year", "year_id"):
                        row["year"] = td.get_text(strip=True)
                    elif col in ("tm", "team"):
                        row["team"] = td.get_text(strip=True)
                    elif col in ("hc", "head_coach", "coach"):
                        name, cid = _extract_name_and_id(td)
                        row["hc_name"] = name
                        row["hc_id"] = cid
                    elif col in ("oc", "off_coord", "offensive_coordinator"):
                        name, cid = _extract_name_and_id(td)
                        row["oc_name"] = name
                        row["oc_id"] = cid
                    elif col in ("dc", "def_coord", "defensive_coordinator"):
                        name, cid = _extract_name_and_id(td)
                        row["dc_name"] = name
                        row["dc_id"] = cid

                if row:
                    rows.append(row)

    finally:
        scraper.close()

    if not rows:
        print("No rows found — page may not have loaded correctly.")
        return 0

    # Write coordinator_index.csv
    COACHES_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in _OUTPUT_FIELDS})

    print(f"Wrote {len(rows)} rows to {OUTPUT_PATH}")

    # Add new coaches to manifest
    added = 0
    for row in rows:
        for name_key, id_key in [("hc_name", "hc_id"), ("oc_name", "oc_id"), ("dc_name", "dc_id")]:
            cid = row.get(id_key, "")
            name = row.get(name_key, "")
            if cid:
                href = f"/coaches/{cid}.htm"
                if _add_to_manifest(manifest, cid, href, name=name, source="coordinator_index"):
                    added += 1

    _write_manifest(manifest)
    print(f"Added {added} new coach(es) to manifest from coordinator index.")
    return added


if __name__ == "__main__":
    added = scrape_coordinator_index()
    print(f"\nDone. {added} new coaches queued. Run 'scrape_coaches.py --pull' to fetch their pages.")
