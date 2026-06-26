#!/usr/bin/env python3
"""
Comprehensive PFR boxscore scraper.

One page fetch → all tables → per-game directory under:
    ~/data/pfref/raw/boxscores/{year}/{game_id}/

Each table gets its own CSV.  A manifest row is written per game to:
    ~/data/pfref/manifest/page_manifest_{year}.csv

Usage:
    # Single game (QA / test)
    python -m ingestion.boxscores.scrape_all_tables --game 201812100sea

    # Full season
    python -m ingestion.boxscores.scrape_all_tables --season 2024

    # Range of seasons (most-recent-first recommended)
    python -m ingestion.boxscores.scrape_all_tables --seasons 2025-1950

    # Re-scrape even if already done
    python -m ingestion.boxscores.scrape_all_tables --season 2024 --force

Skip logic
----------
A game is skipped if its game_id appears in the manifest with no error AND
every expected CSV exists on disk.  Use --force to override.

Team abbrev normalisation
-------------------------
Team names are resolved from the scorebox (/teams/{abbrev}/ links) before
any table is parsed.  Parsers use data-stat attribute names for columns
so score columns like 'MIN'/'SEA' become 'vis_team_score'/'home_team_score'
automatically — no post-processing needed.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import random
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

# Resolve project root so we can run as a module from the repo root
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from ingestion.boxscores.parsers.tables import TABLE_PARSERS
from ingestion.boxscores.manifest import (
    MANIFEST_DIR,
    write_manifest_row,
    scraped_game_ids,
    load_manifest,
)

RAW_DIR      = Path.home() / "data" / "pfref" / "raw" / "boxscores"
GAMELOGS_DIR = Path.home() / "data" / "pfref" / "raw" / "season" / "gamelogs"
BASE_URL     = "https://www.pro-football-reference.com"

BRAVE_EXE    = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
PROFILE_DIR  = str(Path(__file__).resolve().parents[2] / ".brave_scraper_profile")


# ---------------------------------------------------------------------------
# Browser / fetch
# ---------------------------------------------------------------------------

class BraveScraper:
    """Playwright + real Brave Browser — passes Cloudflare natively."""

    def __init__(self, sleep_min: float = 5.0, sleep_max: float = 9.0):
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._pw   = None
        self._ctx  = None
        self._page = None

    def _start(self):
        from playwright.sync_api import sync_playwright
        Path(PROFILE_DIR).mkdir(exist_ok=True)
        self._pw  = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            executable_path=BRAVE_EXE,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-extensions",
            ],
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def fetch(self, url: str) -> BeautifulSoup:
        if self._page is None:
            self._start()
        try:
            self._page.goto(url, wait_until="networkidle", timeout=45_000)
        except Exception:
            self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            time.sleep(2)

        title = self._page.title()
        if "just a moment" in title.lower():
            raise PermissionError(
                f"Cloudflare challenge at {url}. "
                "Visit PFR in Brave to refresh cookies then re-run."
            )

        html = self._page.content()
        # Strip HTML comments so comment-buried tables are visible
        html = html.replace("<!--", "").replace("-->", "")
        return BeautifulSoup(html, "html.parser")

    def sleep(self):
        time.sleep(random.uniform(self.sleep_min, self.sleep_max))

    def close(self):
        try:
            if self._ctx:
                self._ctx.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Team abbrev extraction
# ---------------------------------------------------------------------------

def extract_team_abbrevs(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (vis_abbrev, home_abbrev) from the scorebox team links."""
    scorebox = soup.find("div", class_="scorebox")
    if not scorebox:
        return "", ""
    abbrevs: list[str] = []
    for a in scorebox.find_all("a", href=True):
        m = re.search(r"/teams/([a-z]{2,4})/\d{4}", a["href"])
        if m:
            ab = m.group(1)
            if ab not in abbrevs:
                abbrevs.append(ab)
        if len(abbrevs) == 2:
            break
    return (abbrevs[0], abbrevs[1]) if len(abbrevs) == 2 else ("", "")


# ---------------------------------------------------------------------------
# Per-game output
# ---------------------------------------------------------------------------

def game_dir(season: int, game_id: str) -> Path:
    d = RAW_DIR / str(season) / game_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_table(df: pd.DataFrame, path: Path) -> None:
    df.to_csv(path, index=False)


# ---------------------------------------------------------------------------
# Core: scrape one game
# ---------------------------------------------------------------------------

def scrape_game(
    scraper: BraveScraper,
    game_id: str,
    season: int,
    force: bool = False,
    dry_run: bool = False,
    tables_filter: set[str] | None = None,
) -> dict:
    """
    Fetch and parse all tables for one boxscore page.
    Returns a result dict with keys: game_id, home_abbrev, vis_abbrev,
    found_tables, tables_written, error.

    tables_filter: if provided, only write CSV for tables in this set.
    All tables are still parsed (for found_tables tracking) but only the
    filtered ones are written to disk.  Pass None to write all tables.
    """
    result = {
        "game_id":       game_id,
        "home_abbrev":   "",
        "vis_abbrev":    "",
        "found_tables":  {},
        "tables_written": 0,
        "error":         None,
    }

    url = f"{BASE_URL}/boxscores/{game_id}.htm"

    try:
        soup = scraper.fetch(url)
    except PermissionError as e:
        result["error"] = "cloudflare"
        raise   # bubble up to stop the run
    except Exception as e:
        result["error"] = str(e)[:200]
        return result

    vis_abbrev, home_abbrev = extract_team_abbrevs(soup)
    result["vis_abbrev"]  = vis_abbrev
    result["home_abbrev"] = home_abbrev

    if not home_abbrev or not vis_abbrev:
        result["error"] = "no_team_abbrevs"
        return result

    out_dir = game_dir(season, game_id)
    found: dict[str, bool] = {}

    for table_name, (parser_fn, filename) in TABLE_PARSERS.items():
        try:
            df, found_flag = parser_fn(soup, game_id, season, home_abbrev, vis_abbrev)
            found[table_name] = found_flag
            write_this = (tables_filter is None or table_name in tables_filter)
            if df is not None and not dry_run and write_this:
                write_table(df, out_dir / filename)
                result["tables_written"] += 1
        except Exception as e:
            found[table_name] = False
            print(f"    WARN [{table_name}]: {e}")

    result["found_tables"] = found
    return result


# ---------------------------------------------------------------------------
# Game ID discovery
# ---------------------------------------------------------------------------

def get_game_ids(season: int) -> list[str]:
    """Load game IDs from season-gamelogs CSV."""
    gl_file = GAMELOGS_DIR / f"gamelogs_{season}.csv"
    if not gl_file.exists():
        print(f"  No gamelog file for {season}: {gl_file}")
        return []
    df = pd.read_csv(gl_file)
    col = "game_url" if "game_url" in df.columns else df.columns[0]
    ids = []
    for url in df[col].dropna():
        gid = str(url).split("/")[-1].replace(".htm", "").strip()
        if gid:
            ids.append(gid)
    return ids


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def errored_games() -> list[tuple[int, str]]:
    """Return [(season, game_id), ...] for all manifest rows that have an error."""
    pairs: list[tuple[int, str]] = []
    for path in sorted(MANIFEST_DIR.glob("page_manifest_*.csv")):
        season = int(path.stem.split("_")[2])
        with open(path, newline="") as f:
            for row in __import__("csv").DictReader(f):
                if row.get("error", "").strip():
                    pairs.append((season, row["game_id"]))
    return pairs


def run(
    seasons: list[int],
    force: bool = False,
    dry_run: bool = False,
    game_override: str | None = None,
    retry_errors: bool = False,
    tables_filter: set[str] | None = None,
):
    scraper = BraveScraper(sleep_min=5.0, sleep_max=9.0)
    total_written = 0
    total_errors  = 0

    if tables_filter:
        print(f"  Writing only tables: {sorted(tables_filter)}")

    try:
        if game_override:
            season = int(game_override[:4])
            _run_season(scraper, season, [game_override], force, dry_run,
                        total_written, total_errors, tables_filter)
            return

        if retry_errors:
            pairs = errored_games()
            if not pairs:
                print("No errored games found in any manifest.")
                return
            print(f"\n=== Retrying {len(pairs)} errored games ===")
            by_season: dict[int, list[str]] = {}
            for s, gid in pairs:
                by_season.setdefault(s, []).append(gid)
            for season in sorted(by_season, reverse=True):
                gids = by_season[season]
                print(f"\n--- {season}: {len(gids)} games ---")
                tw, te = _run_season(scraper, season, gids, force=True,
                                     dry_run=dry_run, tw=0, te=0,
                                     tables_filter=tables_filter)
                total_written += tw
                total_errors  += te
            print(f"\n{'='*60}")
            print(f"Total CSV files written: {total_written}")
            print(f"Total errors remaining:  {total_errors}")
            return

        for season in seasons:
            game_ids = get_game_ids(season)
            if not game_ids:
                continue

            if not force:
                done = scraped_game_ids(season)
                pending = [g for g in game_ids if g not in done]
                skipped = len(game_ids) - len(pending)
                if skipped:
                    print(f"  {season}: skipping {skipped} already-done, "
                          f"{len(pending)} remaining")
                game_ids = pending

            if not game_ids:
                print(f"  {season}: all games done")
                continue

            print(f"\n=== Season {season}: {len(game_ids)} games ===")
            tw, te = _run_season(scraper, season, game_ids, force, dry_run, 0, 0,
                                 tables_filter)
            total_written += tw
            total_errors  += te

    finally:
        scraper.close()

    print(f"\n{'='*60}")
    print(f"Total CSV files written: {total_written}")
    print(f"Total errors:            {total_errors}")


def _run_season(scraper, season, game_ids, force, dry_run, tw, te,
                tables_filter=None):
    for i, game_id in enumerate(game_ids, 1):
        print(f"  [{i}/{len(game_ids)}] {game_id} ...", end=" ", flush=True)
        try:
            result = scrape_game(scraper, game_id, season, force, dry_run,
                                 tables_filter)
        except PermissionError:
            print("\nCLOUDFLARE BLOCK — stopping.")
            break

        err   = result["error"]
        found = result["found_tables"]
        ha    = result["home_abbrev"]
        va    = result["vis_abbrev"]

        if err:
            print(f"ERROR: {err}")
            te += 1
        else:
            n_found = sum(1 for v in found.values() if v)
            print(f"{va}@{ha}  {n_found}/{len(TABLE_PARSERS)} tables  "
                  f"({result['tables_written']} CSVs)")
            tw += result["tables_written"]

        if not dry_run:
            write_manifest_row(
                season=season,
                game_id=game_id,
                home_abbrev=ha,
                vis_abbrev=va,
                found_tables=found,
                error=err,
            )

        scraper.sleep()

    return tw, te


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Scrape all tables from PFR boxscore pages (1950–2025).\n"
                    "Writes per-game directories to ~/data/pfref/raw/boxscores/{year}/{game_id}/\n"
                    "Manifest at ~/data/pfref/manifest/page_manifest_{year}.csv"
    )
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--game",         help="Single game_id, e.g. 201812100sea")
    grp.add_argument("--season",       type=int, help="Single season year")
    grp.add_argument("--seasons",      help="Inclusive range, most-recent-first: 2025-1950")
    grp.add_argument("--retry-errors", action="store_true",
                     help="Re-scrape every game that has an error in any manifest")
    ap.add_argument("--force",   action="store_true",
                    help="Re-scrape games already in manifest")
    ap.add_argument("--dry-run", action="store_true",
                    help="Parse but don't write CSVs or manifest")
    ap.add_argument("--tables",  nargs="+", default=None,
                    metavar="TABLE",
                    help=(
                        "Only write these table CSVs (others are parsed but not saved). "
                        f"Available: {', '.join(sorted(TABLE_PARSERS))}. "
                        "Example: --tables starters snap_counts"
                    ))
    args = ap.parse_args()

    tables_filter = set(args.tables) if args.tables else None
    if tables_filter:
        unknown = tables_filter - set(TABLE_PARSERS)
        if unknown:
            ap.error(f"Unknown table names: {unknown}. "
                     f"Available: {', '.join(sorted(TABLE_PARSERS))}")

    if args.game:
        run([], game_override=args.game, force=args.force, dry_run=args.dry_run,
            tables_filter=tables_filter)
    elif args.season:
        run([args.season], force=args.force, dry_run=args.dry_run,
            tables_filter=tables_filter)
    elif args.retry_errors:
        run([], retry_errors=True, dry_run=args.dry_run,
            tables_filter=tables_filter)
    else:
        lo_s, hi_s = args.seasons.split("-")
        lo, hi = int(lo_s), int(hi_s)
        if lo > hi:
            seasons = list(range(lo, hi - 1, -1))
        else:
            seasons = list(range(lo, hi + 1))
        run(seasons, force=args.force, dry_run=args.dry_run,
            tables_filter=tables_filter)


if __name__ == "__main__":
    main()
