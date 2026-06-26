"""
Team statistics scrapers for Pro Football Reference.

Fetches two season pages per year and saves EVERY table found on each:
  Offense:  https://www.pro-football-reference.com/years/{year}/
  Defense:  https://www.pro-football-reference.com/years/{year}/opp.htm

Tables are identified by their HTML id attribute using data-stat column names
(stable across seasons even when display headers change).  No table ID list is
hardcoded — if PFR adds or removes a table in a given era, it's handled
automatically.

Data saved to:
  ~/data/pfref/raw/season/team/offense/{table_id}/{table_id}_{year}.csv
  ~/data/pfref/raw/season/team/defense/{table_id}/{table_id}_{year}.csv

Metadata tracks the whole page as one unit (offense_page / defense_page) so
one skip check covers all tables for that year.

Usage:
    from ingestion.pfref.team_stats import scrape_offense, scrape_defense, scrape_all

    scrape_all(years=range(2025, 1949, -1))   # newest-first recommended
    scrape_offense(years=[2025])
    scrape_defense(years=[2025])
"""

import pathlib

import pandas as pd

from .metadata import MetadataTracker
from .scraper import BASE_URL
from .scraper_playwright import PlaywrightScraper

RAW_TEAM_DIR = pathlib.Path.home() / "data" / "pfref" / "raw" / "season" / "team"

_OFFENSE_URL = "/years/{year}/"
_DEFENSE_URL = "/years/{year}/opp.htm"

# Tables on these pages that are not season stats (skip them)
_SKIP_TABLE_IDS = frozenset([
    "div_standings",
    "standings",
    "playoff_results",
    "games",           # schedule table
    "superbowl",
])


# ---------------------------------------------------------------------------
# Core table parser — data-stat based, works on any PFR table
# ---------------------------------------------------------------------------

def _parse_table(table, year: int) -> pd.DataFrame:
    """
    Parse a PFR HTML table element into a DataFrame.

    Uses data-stat attribute as column name for every cell.
    Skips group-header cells (data-stat starting with 'header_').
    Skips divider/repeat-header rows.
    Returns empty DataFrame if the table has no usable rows.
    """
    thead = table.find("thead")
    tbody = table.find("tbody")
    if not thead or not tbody:
        return pd.DataFrame()

    # Column names from the last thead row (handles double-decker headers)
    stat_names = [
        th.get("data-stat", "")
        for th in thead.find_all("tr")[-1].find_all(["th", "td"])
        if not th.get("data-stat", "").startswith("header_")
    ]

    rows: list[dict] = []
    for tr in tbody.find_all("tr"):
        classes = tr.get("class", [])
        if "thead" in classes or "divider" in classes:
            continue
        cells = [
            td for td in tr.find_all(["th", "td"])
            if not td.get("data-stat", "").startswith("header_")
        ]
        if not cells:
            continue
        row = {"season": year}
        for stat, cell in zip(stat_names, cells):
            if stat:
                row[stat] = cell.get_text(" ", strip=True)
        if len(row) > 1:  # more than just season
            rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ---------------------------------------------------------------------------
# Page scraper — fetch one page, save every table found
# ---------------------------------------------------------------------------

def _scrape_season_page(
    side: str,
    url_pattern: str,
    year: int,
    scraper: PlaywrightScraper,
    meta: MetadataTracker,
    skip_existing: bool,
    force: bool = False,
) -> list[pathlib.Path]:
    """
    Fetch one season page (offense or defense) and save all tables on it.

    Args:
        side:        'offense' or 'defense' — determines save directory
        url_pattern: URL template with {year} placeholder
        year:        Season year
        scraper:     Active PlaywrightScraper instance
        meta:        MetadataTracker instance
        skip_existing: If True, skip years already marked as pulled in metadata
        force:       Override skip_existing and re-pull even if metadata says done

    Returns:
        List of file paths written.
    """
    dataset_key = f"{side}_page"

    if not force and skip_existing and meta.is_pulled(dataset_key, year):
        print(f"  [{side}] {year}: already pulled, skipping")
        return []

    save_base = RAW_TEAM_DIR / side
    url = BASE_URL + url_pattern.format(year=year)
    print(f"  [{side}] {year}: fetching {url}")

    saved: list[pathlib.Path] = []

    try:
        # Playwright's browser runs PFR's JS which already uncomments tables in the DOM.
        # strip_comments=True on the serialized DOM would find each table twice.
        soup = scraper.fetch_and_sleep(url, strip_comments=False)

        # Deduplicate by table id — take first occurrence only
        seen: set[str] = set()
        tables = []
        for t in soup.find_all("table", id=True):
            tid = t["id"]
            if tid not in seen and tid not in _SKIP_TABLE_IDS:
                seen.add(tid)
                tables.append(t)

        for table in tables:
            table_id = table["id"]
            df = _parse_table(table, year)
            if df.empty:
                continue

            table_dir = save_base / table_id
            table_dir.mkdir(parents=True, exist_ok=True)
            file_path = table_dir / f"{table_id}_{year}.csv"
            df.to_csv(file_path, index=False)
            saved.append(file_path)

        table_ids = [t["id"] for t in tables if not _parse_table(t, year).empty]
        meta.mark_pulled(dataset_key, year, record_count=len(saved),
                         tables=",".join(table_ids))
        print(f"    saved {len(saved)} table(s): {', '.join(t['id'] for t in tables[:8])}"
              f"{'...' if len(tables) > 8 else ''}")

    except Exception as exc:
        print(f"    ERROR [{side} {year}]: {exc}")
        meta.mark_failed(dataset_key, year, str(exc))

    return saved


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_offense(
    years: range | list[int] = range(2025, 1949, -1),
    skip_existing: bool = True,
    scraper: PlaywrightScraper | None = None,
    meta: MetadataTracker | None = None,
    force: bool = False,
) -> list[pathlib.Path]:
    """Scrape all tables from the offense season page for each year."""
    own = scraper is None
    scraper = scraper or PlaywrightScraper()
    meta = meta or MetadataTracker()
    saved: list[pathlib.Path] = []
    try:
        for year in years:
            saved += _scrape_season_page(
                "offense", _OFFENSE_URL, year, scraper, meta, skip_existing, force
            )
    finally:
        if own:
            scraper.close()
    return saved


def scrape_defense(
    years: range | list[int] = range(2025, 1949, -1),
    skip_existing: bool = True,
    scraper: PlaywrightScraper | None = None,
    meta: MetadataTracker | None = None,
    force: bool = False,
) -> list[pathlib.Path]:
    """Scrape all tables from the defense (opp) season page for each year."""
    own = scraper is None
    scraper = scraper or PlaywrightScraper()
    meta = meta or MetadataTracker()
    saved: list[pathlib.Path] = []
    try:
        for year in years:
            saved += _scrape_season_page(
                "defense", _DEFENSE_URL, year, scraper, meta, skip_existing, force
            )
    finally:
        if own:
            scraper.close()
    return saved


def scrape_all(
    years: range | list[int] = range(2025, 1949, -1),
    skip_existing: bool = True,
    force: bool = False,
) -> list[pathlib.Path]:
    """Scrape offense and defense pages for all years, sharing one browser session."""
    scraper = PlaywrightScraper()
    meta = MetadataTracker()
    saved: list[pathlib.Path] = []
    try:
        for year in years:
            saved += _scrape_season_page(
                "offense", _OFFENSE_URL, year, scraper, meta, skip_existing, force
            )
            saved += _scrape_season_page(
                "defense", _DEFENSE_URL, year, scraper, meta, skip_existing, force
            )
    finally:
        scraper.close()
    return saved


# ---------------------------------------------------------------------------
# Discovery helper — list all table IDs on a page without saving
# ---------------------------------------------------------------------------

def list_page_tables(year: int, side: str = "offense") -> list[str]:
    """
    Fetch one season page and return all table IDs found on it.
    Useful for discovering what tables PFR provides for a given year.

    Example:
        from ingestion.pfref.team_stats import list_page_tables
        print(list_page_tables(2025, "offense"))
        print(list_page_tables(1950, "offense"))
    """
    url_pattern = _OFFENSE_URL if side == "offense" else _DEFENSE_URL
    url = BASE_URL + url_pattern.format(year=year)
    with PlaywrightScraper() as scraper:
        soup = scraper.fetch_and_sleep(url, strip_comments=False)
    seen: set[str] = set()
    table_ids = []
    for t in soup.find_all("table", id=True):
        if t["id"] not in seen:
            seen.add(t["id"])
            table_ids.append(t["id"])
    print(f"{side} page {year}: {len(table_ids)} tables")
    for tid in table_ids:
        print(f"  {tid}")
    return table_ids
