#!/usr/bin/env python3
"""
Scrape defensive coordinator coach IDs from PFR team season pages.

For each row in team_schemes.csv that has a DC name but no coach_id, fetch
https://www.pro-football-reference.com/teams/{team}/{season}.htm and extract
the Defensive Coordinator link to get their PFR coach ID.

The page structure is:
    <p><strong>Defensive Coordinator:</strong> <a href="/coaches/ID.htm">Name</a></p>

Output:
  Writes coordinator_season_links.csv:
      team, season, dc_name, dc_id, oc_name, oc_id, hc_name, hc_id
  Updates team_schemes.csv with dc_coach_id column (filled where found).
  Adds any new coach IDs to coach_manifest.csv as source="team_season_page".

Usage:
    cd ~/github/football/football_analytics
    # Dry run — print what would be scraped:
    .venv/bin/python scripts/scrape_team_season_coordinators.py --dry-run

    # Run for all unmatched rows (slow — ~1000 pages at 5s each = ~90 min):
    .venv/bin/python scripts/scrape_team_season_coordinators.py

    # Run for a specific team:
    .venv/bin/python scripts/scrape_team_season_coordinators.py --team phi

    # Run for a specific year range:
    .venv/bin/python scripts/scrape_team_season_coordinators.py --from-year 1967 --to-year 1985
"""

import argparse
import csv
import pathlib
import sys
import time

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import pandas as pd
from ingestion.pfref.coaches import (
    COACHES_DIR, MANIFEST_PATH, _read_manifest, _write_manifest, _add_to_manifest,
)
from ingestion.pfref.scraper_playwright import PlaywrightScraper

BASE_URL = "https://www.pro-football-reference.com"
SCHEMES_PATH = pathlib.Path.home() / "data" / "pfref" / "team_schemes.csv"
LINKS_OUTPUT = COACHES_DIR / "coordinator_season_links.csv"

LINKS_FIELDS = ["team", "season", "hc_name", "hc_id", "oc_name", "oc_id", "dc_name", "dc_id"]

ROLE_LABELS = {
    "head coach": "hc",
    "offensive coordinator": "oc",
    "defensive coordinator": "dc",
}


def _extract_coordinators(soup) -> dict[str, tuple[str, str]]:
    """
    Parse the coaching staff section of a team season page.

    Returns dict: role_key -> (coach_name, coach_id)
    role_key is one of 'hc', 'oc', 'dc'
    """
    result = {}
    for strong in soup.find_all("strong"):
        label = strong.get_text(strip=True).rstrip(":").lower()
        role_key = ROLE_LABELS.get(label)
        if role_key is None:
            continue
        # The coach name/link is the next sibling
        a = strong.find_next_sibling("a")
        if a and "/coaches/" in a.get("href", ""):
            coach_id = pathlib.Path(a["href"]).stem
            coach_name = a.get_text(strip=True)
            result[role_key] = (coach_name, coach_id)
        else:
            # No link — might be text only (no PFR page for this person)
            sibling = strong.next_sibling
            if sibling:
                name = str(sibling).strip().lstrip(": ")
                if name:
                    result[role_key] = (name, "")
    return result


def build_scrape_queue(
    schemes: pd.DataFrame,
    existing_links: set[tuple[str, int]],
    team_filter: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
) -> list[tuple[str, int]]:
    """Return list of (team, season) pairs that still need scraping."""
    queue = set()
    for _, row in schemes.iterrows():
        team = str(row["team"]).lower()
        season = int(row["season"])
        dc_name = row.get("defensive_coordinator")

        # Skip HC-as-DC rows (no DC name)
        if pd.isna(dc_name) or not str(dc_name).strip():
            continue

        # Skip if dc_coach_id already filled (from team_ranks join or prior scrape)
        existing_id = row.get("dc_coach_id")
        if not pd.isna(existing_id) and str(existing_id).strip():
            continue

        # Skip if already have link data in coordinator_season_links.csv
        if (team, season) in existing_links:
            continue

        if team_filter and team != team_filter.lower():
            continue
        if from_year and season < from_year:
            continue
        if to_year and season > to_year:
            continue

        queue.add((team, season))

    return sorted(queue)


def load_existing_links() -> tuple[set[tuple[str, int]], list[dict]]:
    """Load already-scraped (team, season) pairs from coordinator_season_links.csv."""
    existing = set()
    rows = []
    if LINKS_OUTPUT.exists():
        with open(LINKS_OUTPUT, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    existing.add((row["team"], int(row["season"])))
                    rows.append(row)
                except (KeyError, ValueError):
                    pass
    return existing, rows


def scrape_queue(
    queue: list[tuple[str, int]],
    dry_run: bool = False,
) -> list[dict]:
    """Scrape all (team, season) pairs in queue and return link rows."""
    if dry_run:
        print(f"DRY RUN — would scrape {len(queue)} team-season pages")
        for team, season in queue[:20]:
            print(f"  {team} {season}")
        if len(queue) > 20:
            print(f"  ... and {len(queue) - 20} more")
        return []

    print(f"Scraping {len(queue)} team-season pages (~{len(queue) * 5 // 60} min at 5s/page)")
    manifest = _read_manifest()
    new_rows: list[dict] = []
    manifest_added = 0

    write_header = not LINKS_OUTPUT.exists() or LINKS_OUTPUT.stat().st_size == 0
    COACHES_DIR.mkdir(parents=True, exist_ok=True)

    scraper = PlaywrightScraper(sleep_min=4, sleep_max=7, page_load_wait=3)
    try:
        with open(LINKS_OUTPUT, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LINKS_FIELDS)
            if write_header:
                writer.writeheader()

            for i, (team, season) in enumerate(queue):
                url = f"{BASE_URL}/teams/{team}/{season}.htm"
                print(f"[{i+1}/{len(queue)}] {team} {season} ...", end=" ", flush=True)

                try:
                    soup = scraper.fetch_and_sleep(url, strip_comments=True)
                    staff = _extract_coordinators(soup)

                    row = {
                        "team": team, "season": season,
                        "hc_name": staff.get("hc", ("", ""))[0],
                        "hc_id": staff.get("hc", ("", ""))[1],
                        "oc_name": staff.get("oc", ("", ""))[0],
                        "oc_id": staff.get("oc", ("", ""))[1],
                        "dc_name": staff.get("dc", ("", ""))[0],
                        "dc_id": staff.get("dc", ("", ""))[1],
                    }
                    writer.writerow(row)
                    f.flush()
                    new_rows.append(row)

                    dc_id = row["dc_id"]
                    if dc_id:
                        href = f"/coaches/{dc_id}.htm"
                        if _add_to_manifest(manifest, dc_id, href,
                                            name=row["dc_name"], source="team_season_page"):
                            manifest_added += 1
                    print(f"DC={row['dc_name'] or '?'} ({dc_id or 'no-link'})")

                except Exception as e:
                    print(f"ERROR: {e}")

    finally:
        scraper.close()
        _write_manifest(manifest)

    print(f"\nScraped {len(new_rows)} pages. Added {manifest_added} new coaches to manifest.")
    return new_rows


def patch_team_schemes(all_link_rows: list[dict]) -> None:
    """Write dc_coach_id back into team_schemes.csv where found."""
    schemes = pd.read_csv(SCHEMES_PATH)
    links = pd.DataFrame(all_link_rows, columns=LINKS_FIELDS)
    links["season"] = links["season"].astype(int)

    # Build lookup: (team, season) -> dc_id
    dc_lookup = {
        (row["team"], row["season"]): row["dc_id"]
        for _, row in links.iterrows()
        if row["dc_id"]
    }

    if "dc_coach_id" not in schemes.columns:
        schemes["dc_coach_id"] = ""

    patched = 0
    for idx, row in schemes.iterrows():
        key = (str(row["team"]).lower(), int(row["season"]))
        if key in dc_lookup and (pd.isna(row.get("dc_coach_id")) or str(row.get("dc_coach_id", "")).strip() == ""):
            schemes.at[idx, "dc_coach_id"] = dc_lookup[key]
            patched += 1

    schemes.to_csv(SCHEMES_PATH, index=False)
    filled = (schemes["dc_coach_id"].notna() & (schemes["dc_coach_id"] != "")).sum()
    print(f"Patched {patched} rows. team_schemes now has {filled}/{len(schemes)} dc_coach_id values.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print queue without scraping.")
    ap.add_argument("--team", help="Only scrape this team abbreviation (e.g. phi).")
    ap.add_argument("--from-year", type=int, help="Start year (inclusive).")
    ap.add_argument("--to-year", type=int, help="End year (inclusive).")
    ap.add_argument("--patch-only", action="store_true",
                    help="Skip scraping; just patch team_schemes from existing coordinator_season_links.csv.")
    args = ap.parse_args()

    schemes = pd.read_csv(SCHEMES_PATH)
    existing_keys, existing_rows = load_existing_links()

    if args.patch_only:
        patch_team_schemes(existing_rows)
        return

    queue = build_scrape_queue(
        schemes, existing_keys,
        team_filter=args.team,
        from_year=args.from_year,
        to_year=args.to_year,
    )
    print(f"Queue: {len(queue)} team-season pages to scrape")

    if not queue:
        print("Nothing to scrape. Run with --dry-run to inspect filters, or check coordinator_season_links.csv.")
        return

    new_rows = scrape_queue(queue, dry_run=args.dry_run)

    if new_rows and not args.dry_run:
        all_rows = existing_rows + new_rows
        patch_team_schemes(all_rows)


if __name__ == "__main__":
    main()
