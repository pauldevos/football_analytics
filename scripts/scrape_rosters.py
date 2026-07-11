#!/usr/bin/env python3
"""
scrape_rosters.py
-----------------
Download PFR team roster pages for all active franchises, 1967–present.

Each roster page:  https://www.pro-football-reference.com/teams/{team}/{year}_roster.htm
Output:            ~/data/pfref/raw/season/rosters/{team}_{year}_roster.csv

Columns saved include player_link and player_id extracted from HTML <a> tags,
so every player resolves to a PFR ID.

Usage:
    python scripts/scrape_rosters.py                          # all missing
    python scripts/scrape_rosters.py --overwrite              # re-scrape all
    python scripts/scrape_rosters.py --team kan --years 1967-1969
    python scripts/scrape_rosters.py --teams-missing-ids      # only files with blank player_id
    python scripts/scrape_rosters.py --year 1967              # all teams for one year
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from pfref.scraper_nodriver import NoDriverScraper as FirefoxScraper
from pfref.team_rosters import extract_roster_table, parse_table_manual

ROSTER_DIR = Path.home() / "data/pfref/raw/season/rosters"
PFR_BASE   = "https://www.pro-football-reference.com"

# All active franchise codes (PFR team abbreviation → first NFL/AFL season)
# Pulled from https://www.pro-football-reference.com/teams/
ACTIVE_FRANCHISES: dict[str, int] = {
    "crd": 1920,  # Arizona Cardinals (was CHI/STL)
    "atl": 1966,
    "rav": 1996,  # Baltimore Ravens
    "buf": 1960,
    "car": 1995,
    "chi": 1920,
    "cin": 1968,
    "cle": 1946,
    "dal": 1960,
    "den": 1960,
    "det": 1930,
    "gnb": 1921,
    "htx": 2002,  # Houston Texans
    "clt": 1953,  # Indianapolis Colts (was Baltimore)
    "jax": 1995,
    "kan": 1960,
    "sdg": 1960,  # LA Chargers (was SD)
    "ram": 1937,  # LA Rams (was Cleveland/STL)
    "mia": 1966,
    "min": 1961,
    "nwe": 1960,
    "nor": 1967,
    "nyg": 1925,
    "nyj": 1960,
    "rai": 1960,  # Las Vegas Raiders (was OAK/LA)
    "phi": 1933,
    "pit": 1933,
    "sfo": 1946,
    "sea": 1976,
    "tam": 1976,
    "oti": 1960,  # Tennessee Titans (was HOU/TEN)
    "was": 1932,
    "jax": 1995,
}

FIRST_YEAR_OF_INTEREST = 1967


def build_season_urls(
    teams: list[str] | None = None,
    year_range: tuple[int, int] | None = None,
) -> list[tuple[str, int, str]]:
    """Return list of (team_code, year, roster_url) tuples."""
    start, end = year_range or (FIRST_YEAR_OF_INTEREST, 2025)
    result = []
    franchises = {t: f for t, f in ACTIVE_FRANCHISES.items() if teams is None or t in teams}
    for team, first_season in franchises.items():
        for year in range(max(start, first_season), end + 1):
            url = f"{PFR_BASE}/teams/{team}/{year}_roster.htm"
            result.append((team, year, url))
    return result


def has_blank_player_ids(path: Path) -> bool:
    """Return True if the roster CSV has any rows with blank player_id."""
    try:
        with open(path, newline="", errors="replace") as fh:
            rows = list(csv.DictReader(fh))
        if not rows or "player_id" not in rows[0]:
            return True
        return any(not r.get("player_id", "").strip() for r in rows)
    except Exception:
        return True


def scrape_roster(
    team: str, year: int, url: str, out_path: Path,
    scraper, verbose: bool = True
) -> bool:
    """Fetch one roster page and save CSV. Returns True on success."""
    for attempt in range(1, 4):
        try:
            soup = scraper.fetch_and_sleep(url, strip_comments=True)
            table = extract_roster_table(soup)
            if table is None:
                if verbose:
                    print(f"  [{team} {year}] no roster table found")
                return False

            df = parse_table_manual(table)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(out_path, index=False)
            if verbose:
                n_with_id = df["player_id"].astype(bool).sum()
                print(f"  [{team} {year}] {len(df)} players, {n_with_id} with player_id → {out_path.name}")
            return True

        except Exception as e:
            if verbose:
                print(f"  [{team} {year}] attempt {attempt} failed: {e}")
            time.sleep(5 * attempt)

    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="Scrape PFR team rosters")
    ap.add_argument("--team",  help="Single team code (e.g. kan)")
    ap.add_argument("--teams", nargs="+", help="Multiple team codes")
    ap.add_argument("--year",  type=int, help="Single year")
    ap.add_argument("--years", help="Year range e.g. 1967-1969")
    ap.add_argument("--overwrite", action="store_true", help="Re-scrape existing files")
    ap.add_argument("--teams-missing-ids", action="store_true",
                    help="Only re-scrape existing files where player_id is blank")
    ap.add_argument("--out", default=str(ROSTER_DIR), help="Output directory")
    ap.add_argument("--limit", type=int, help="Max pages to fetch (for testing)")
    args = ap.parse_args()

    out_dir = Path(args.out)

    # Build team filter
    teams = None
    if args.team:
        teams = [args.team]
    elif args.teams:
        teams = args.teams

    # Build year range
    year_range = None
    if args.year:
        year_range = (args.year, args.year)
    elif args.years:
        parts = args.years.split("-")
        year_range = (int(parts[0]), int(parts[-1]))

    targets = build_season_urls(teams=teams, year_range=year_range)
    print(f"Total target pages: {len(targets)}")

    print("Launching Chrome via nodriver — Cloudflare should pass automatically.")
    scraper = FirefoxScraper(sleep_min=4.0, sleep_max=7.0)

    ok = skip = fail = 0
    for i, (team, year, url) in enumerate(targets):
        if args.limit and i >= args.limit:
            break

        out_path = out_dir / f"{team}_{year}_roster.csv"

        if out_path.exists() and not args.overwrite:
            if args.teams_missing_ids and has_blank_player_ids(out_path):
                pass  # fall through and re-scrape
            else:
                skip += 1
                continue

        success = scrape_roster(team, year, url, out_path, scraper=scraper)
        if success:
            ok += 1
        else:
            fail += 1

    scraper.close()
    print(f"\nDone: {ok} scraped, {skip} skipped, {fail} failed")


if __name__ == "__main__":
    main()
