"""
Draft pick scraper for Pro Football Reference.

Source: https://www.pro-football-reference.com/years/{year}/draft.htm
Table:  #drafts

Data saved to:
  ~/data/pfref/raw/season/draft/draft_{year}.csv

One CSV per year, one row per pick.  Columns use PFR data-stat names directly
(stable across eras) so no rename list is needed.  A player_id column is
extracted from the player href.

NFL drafts began in 1936; use years=range(1936, 2026) for a full history pull.
Draft years occasionally have no picks listed for very early years — those are
saved as empty files and marked pulled so they're not retried.

Usage:
    from ingestion.pfref.draft import scrape_draft

    # Single year
    scrape_draft(years=[2025])

    # Full history
    scrape_draft(years=range(1936, 2026))

    # Already-pulled years are skipped automatically (use force=True to override)
    scrape_draft(years=range(1936, 2026))
"""

import pathlib

import pandas as pd

from .metadata import MetadataTracker
from .scraper import BASE_URL
from .scraper_playwright import PlaywrightScraper

DRAFT_DIR = pathlib.Path.home() / "data" / "pfref" / "raw" / "season" / "draft"
_TABLE_ID = "drafts"
_URL_PATTERN = "/years/{year}/draft.htm"


def _parse_draft_table(soup, year: int) -> pd.DataFrame:
    """
    Extract the drafts table using data-stat attributes for column names.
    Inserts player_id (from href) and season columns.
    Returns an empty DataFrame if the table isn't found.
    """
    table = soup.find("table", {"id": _TABLE_ID})
    if not table:
        return pd.DataFrame()

    # Build column list from last thead row via data-stat
    thead = table.find("thead")
    if not thead:
        return pd.DataFrame()
    thead_rows = thead.find_all("tr")
    stat_names = [
        th.get("data-stat", f"col_{i}")
        for i, th in enumerate(thead_rows[-1].find_all(["th", "td"]))
        if not th.get("data-stat", "").startswith("header_")
    ]

    tbody = table.find("tbody")
    if not tbody:
        return pd.DataFrame()

    rows: list[dict] = []
    for tr in tbody.find_all("tr"):
        # Skip repeat header rows and divider rows
        if "thead" in tr.get("class", []) or "divider" in tr.get("class", []):
            continue
        cells = [td for td in tr.find_all(["th", "td"])
                 if not td.get("data-stat", "").startswith("header_")]
        if not cells:
            continue

        row: dict = {"season": year}

        # Extract player href for player_id before iterating cells
        player_id = ""
        for a in tr.find_all("a", href=True):
            href = a["href"]
            if "/players/" in href:
                player_id = href.split("/")[-1].replace(".htm", "")
                break
        row["player_id"] = player_id

        for stat, cell in zip(stat_names, cells):
            if stat == "college_link":
                # Store the href so we can scrape college stats later; text is always "College Stats"
                a = cell.find("a", href=True)
                row["college_stats_url"] = a["href"] if a else ""
            else:
                row[stat] = cell.get_text(" ", strip=True)

        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Move season and player_id to front
    front_cols = ["season", "player_id"] + [c for c in df.columns if c not in ("season", "player_id")]
    return df[front_cols]


def scrape_draft(
    years: range | list[int] = range(1936, 2026),
    skip_existing: bool = True,
    scraper: PlaywrightScraper | None = None,
    meta: MetadataTracker | None = None,
) -> list[pathlib.Path]:
    """
    Scrape draft pick data for each year and save to CSV.

    Args:
        years:         Draft years to pull (default 1936–2025, full NFL draft history).
        skip_existing: Skip years already in metadata or already saved on disk.
        scraper:       Reuse an existing PlaywrightScraper (avoids launching a second browser).
        meta:          Reuse an existing MetadataTracker.

    Returns:
        List of saved file paths.
    """
    own_scraper = scraper is None
    scraper = scraper or PlaywrightScraper()
    meta = meta or MetadataTracker()

    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    saved_files: list[pathlib.Path] = []

    try:
        for year in years:
            dataset_key = "draft"
            file_path = DRAFT_DIR / f"draft_{year}.csv"

            if skip_existing and meta.is_pulled(dataset_key, year):
                print(f"  [draft] {year}: already pulled, skipping")
                continue
            if skip_existing and file_path.exists():
                meta.mark_pulled(dataset_key, year, file_path=file_path)
                print(f"  [draft] {year}: file exists, back-filling metadata, skipping")
                continue

            url = BASE_URL + _URL_PATTERN.format(year=year)
            print(f"  [draft] {year}: fetching {url}")

            try:
                soup = scraper.fetch_and_sleep(url, strip_comments=True)
                df = _parse_draft_table(soup, year)

                df.to_csv(file_path, index=False)
                meta.mark_pulled(dataset_key, year, file_path=file_path, record_count=len(df))
                saved_files.append(file_path)
                print(f"    Saved {len(df)} picks -> {file_path.name}")

            except Exception as exc:
                print(f"    ERROR [draft {year}]: {exc}")
                meta.mark_failed(dataset_key, year, str(exc))

    finally:
        if own_scraper:
            scraper.close()

    return saved_files
