"""
Player statistics scrapers for Pro Football Reference.

Covers: passing, rushing, receiving, scrimmage, defense, kicking, punting, returns, scoring.

Each stat type is scraped from:
  https://www.pro-football-reference.com/years/{year}/{stat}.htm

Data is saved to:
  ~/data/pfref/raw/season/player/{stat}/{stat}_{year}.csv

Pull history is tracked in metadata.json so already-pulled years are skipped.
"""

import pathlib

import pandas as pd

from .metadata import MetadataTracker
from .scraper import BASE_URL
from .scraper_playwright import PlaywrightScraper

RAW_PLAYER_DIR = pathlib.Path.home() / "data" / "pfref" / "raw" / "season" / "player"

# ---------------------------------------------------------------------------
# Config: table IDs, URL patterns, normalized column names
# ---------------------------------------------------------------------------

_TABLE_IDS: dict[str, str] = {
    "passing": "passing",
    "rushing": "rushing",
    "receiving": "receiving",
    "scrimmage": "scrimmage",
    "defense": "defense",
    "kicking": "kicking",
    "punting": "punting",
    "returns": "returns",
    "scoring": "scoring",
}

_HEADER_ROW_INDEX: dict[str, int] = {
    "passing": 0,
    "rushing": 1,
    "receiving": 1,
    "scrimmage": 1,
    "defense": 1,
    "kicking": 1,
    "punting": 1,
    "returns": 1,
    "scoring": 1,
}

_URL_PATTERNS: dict[str, str] = {
    "passing": "/years/{year}/passing.htm",
    "rushing": "/years/{year}/rushing.htm",
    "receiving": "/years/{year}/receiving.htm",
    "scrimmage": "/years/{year}/scrimmage.htm",
    "defense": "/years/{year}/defense.htm",
    "kicking": "/years/{year}/kicking.htm",
    "punting": "/years/{year}/punting.htm",
    "returns": "/years/{year}/returns.htm",
    "scoring": "/years/{year}/scoring.htm",
}

# Normalized column names applied when the count matches exactly.
# 'player_link' and 'player_id' are inserted at index 1 and 2 before renaming.
_NORMALIZED_COLUMNS: dict[str, list[str]] = {
    "passing": [
        "rank", "player_link", "player_id", "player_name", "age", "team_abbrev", "position",
        "games", "games_started", "qb_record",
        "comp", "att", "comp_pct", "yards", "td", "td_pct", "int", "int_pct",
        "first_down", "succ_pct", "long", "yards_per_att", "avg_yards_per_att",
        "yards_per_comp", "yards_per_game", "qb_rating", "qbr",
        "sack", "sack_yards", "sack_pct", "net_yards_per_att",
        "adj_net_yards_per_att", "comebacks_4q", "gwd", "awards",
    ],
    "rushing": [
        "rank", "player_link", "player_id", "player_name", "age", "team_abbrev", "position",
        "games", "games_started", "att", "yards", "td", "first_down", "succ_pct",
        "long", "yards_per_att", "yards_per_game", "att_per_game", "fumbles", "awards",
    ],
    "receiving": [
        "rank", "player_link", "player_id", "player_name", "age", "team_abbrev", "position",
        "games", "games_started", "targets", "rec", "yards", "yards_per_rec", "td",
        "first_down", "succ_pct", "long", "rec_per_game", "yards_per_game",
        "ctch_pct", "yards_per_target", "fumbles", "awards",
    ],
    "defense": [
        "rank", "player_link", "player_id", "player_name", "age", "team_abbrev", "position",
        "games", "games_started",
        "int", "int_yards", "int_td", "long", "pass_defended",
        "ff", "fumbles", "fr", "fr_yards", "fr_td",
        "sack", "comb_tackles", "solo_tackles", "ast_tackles",
        "tfl", "qb_hits", "safety", "awards",
    ],
    # scrimmage, kicking, punting, returns, scoring: columns vary by era;
    # use data-stat names from the page directly (no rename applied).
}

# ---------------------------------------------------------------------------
# Internal generic scraper
# ---------------------------------------------------------------------------


def _scrape_player_stat(
    stat_type: str,
    years: list[int],
    skip_existing: bool = True,
    scraper: PlaywrightScraper | None = None,
    meta: MetadataTracker | None = None,
) -> list[pathlib.Path]:
    """Pull one player stat type for all given years, skipping already-pulled years."""
    scraper = scraper or PlaywrightScraper()
    meta = meta or MetadataTracker()

    table_id = _TABLE_IDS[stat_type]
    header_idx = _HEADER_ROW_INDEX[stat_type]
    url_pattern = _URL_PATTERNS[stat_type]
    normalized_cols = _NORMALIZED_COLUMNS.get(stat_type)

    save_dir = RAW_PLAYER_DIR / stat_type
    save_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[pathlib.Path] = []

    for year in years:
        dataset_key = f"player_{stat_type}"
        file_path = save_dir / f"{stat_type}_{year}.csv"

        if skip_existing and meta.is_pulled(dataset_key, year):
            print(f"  [{stat_type}] {year}: already pulled, skipping")
            continue
        if skip_existing and file_path.exists():
            # File exists from a previous scraper run that predates this tracker
            meta.mark_pulled(dataset_key, year, file_path=file_path)
            print(f"  [{stat_type}] {year}: file exists, back-filling metadata, skipping")
            continue

        url = BASE_URL + url_pattern.format(year=year)
        print(f"  [{stat_type}] {year}: fetching {url}")

        try:
            # Playwright's browser JS already uncomments tables — strip_comments=False avoids duplicates
            soup = scraper.fetch_and_sleep(url, strip_comments=False)

            headers = scraper.extract_table_headers(soup, table_id, header_idx)
            rows = scraper.extract_table_rows(soup, table_id)
            player_links = scraper.extract_player_links(soup, table_id)

            df = pd.DataFrame(rows, columns=headers)
            df.insert(1, "player_link", player_links[: len(df)])
            df.insert(2, "player_id", df["player_link"].str.extract(r'/([^/]+)\.htm$'))

            if normalized_cols and len(normalized_cols) == len(df.columns):
                df.columns = normalized_cols

            df.to_csv(file_path, index=False)

            meta.mark_pulled(dataset_key, year, file_path=file_path, record_count=len(df))
            saved_files.append(file_path)
            print(f"    Saved {len(df)} rows -> {file_path.name}")

        except ValueError as exc:
            if "not found on page" in str(exc):
                meta.mark_pulled(dataset_key, year, record_count=0)
                print(f"    table not on page for {year} — marked as checked, skipping")
            else:
                print(f"    ERROR [{stat_type} {year}]: {exc}")
                meta.mark_failed(dataset_key, year, str(exc))
        except Exception as exc:
            print(f"    ERROR [{stat_type} {year}]: {exc}")
            meta.mark_failed(dataset_key, year, str(exc))

    return saved_files


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scrape_passing(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    return _scrape_player_stat("passing", list(years), skip_existing, **kwargs)


def scrape_rushing(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    return _scrape_player_stat("rushing", list(years), skip_existing, **kwargs)


def scrape_receiving(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    return _scrape_player_stat("receiving", list(years), skip_existing, **kwargs)


def scrape_scrimmage(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    """Scrape scrimmage totals (rushing + receiving combined)."""
    return _scrape_player_stat("scrimmage", list(years), skip_existing, **kwargs)


def scrape_defense(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    return _scrape_player_stat("defense", list(years), skip_existing, **kwargs)


def scrape_kicking(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    return _scrape_player_stat("kicking", list(years), skip_existing, **kwargs)


def scrape_punting(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    return _scrape_player_stat("punting", list(years), skip_existing, **kwargs)


def scrape_returns(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    return _scrape_player_stat("returns", list(years), skip_existing, **kwargs)


def scrape_scoring(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    **kwargs,
) -> list[pathlib.Path]:
    return _scrape_player_stat("scoring", list(years), skip_existing, **kwargs)


def scrape_all(
    years: range | list[int] = range(1950, 2026),
    skip_existing: bool = True,
    stat_types: list[str] | None = None,
) -> dict[str, list[pathlib.Path]]:
    """
    Scrape player stats for all (or specified) stat types.
    Shares a single scraper/meta instance to avoid redundant browser launches.
    """
    # scrimmage = rushing + receiving combined; useful for total scrimmage yards per era
    all_types = ["passing", "rushing", "receiving", "scrimmage", "defense",
                 "kicking", "punting", "returns", "scoring"]
    types_to_run = stat_types or all_types

    scraper = PlaywrightScraper()
    meta = MetadataTracker()
    results: dict[str, list[pathlib.Path]] = {}
    try:
        for stat_type in types_to_run:
            print(f"\n=== Scraping player {stat_type} ===")
            results[stat_type] = _scrape_player_stat(
                stat_type, list(years), skip_existing, scraper=scraper, meta=meta
            )
    finally:
        scraper.close()
    return results
