"""
Season gamelog and boxscore scrapers for Pro Football Reference.

Two-step workflow:
  1. scrape_season_gamelogs(years)  -- saves a CSV of boxscore URLs per season
  2. scrape_boxscores(years)        -- downloads each game boxscore using those URLs

Gamelogs saved to:  ~/data/pfref/raw/season/gamelogs/gamelogs_{year}.csv
Boxscores saved to: ~/data/pfref/raw/boxscores/{year}/{game_id}.csv

Pull history is tracked in metadata.json so already-pulled items are skipped.
"""

import csv
import pathlib

import pandas as pd
from bs4 import NavigableString

from .metadata import MetadataTracker
from .scraper import BASE_URL
from .scraper_playwright import PlaywrightScraper

RAW_DIR = pathlib.Path.home() / "data" / "pfref" / "raw"
GAMELOGS_DIR = RAW_DIR / "season" / "gamelogs"
BOXSCORES_DIR = RAW_DIR / "boxscores"

# ---------------------------------------------------------------------------
# Boxscore offensive stat column headers vary by era
# ---------------------------------------------------------------------------

_OFF_HEADER_19 = [
    "player_name", "team", "pass_comp", "pass_att", "pass_yds", "pass_td", "pass_int",
    "sacked", "sack_yds_lost", "pass_long", "qb_rate",
    "rush_att", "rush_yds", "rush_td", "rush_long",
    "rec", "rec_yds", "rec_td", "rec_lng",
]
_OFF_HEADER_20 = [
    "player_name", "team", "pass_comp", "pass_att", "pass_yds", "pass_td", "pass_int",
    "sacked", "sack_yds_lost", "pass_long", "qb_rate",
    "rush_att", "rush_yds", "rush_td", "rush_long",
    "targets", "rec", "rec_yds", "rec_td", "rec_lng",
]
_OFF_HEADER_21 = _OFF_HEADER_19 + ["fumble", "fumble_lost"]
_OFF_HEADER_22 = _OFF_HEADER_20 + ["fumble", "fumble_lost"]

_HEADER_BY_COL_COUNT: dict[int, list[str]] = {
    19: _OFF_HEADER_19,
    20: _OFF_HEADER_20,
    21: _OFF_HEADER_21,
    22: _OFF_HEADER_22,
}

# ---------------------------------------------------------------------------
# Season gamelogs (list of boxscore URLs per season)
# ---------------------------------------------------------------------------


def scrape_season_gamelogs(
    years: range | list[int] = range(2023, 2026),
    skip_existing: bool = True,
    scraper: PlaywrightScraper | None = None,
    meta: MetadataTracker | None = None,
) -> list[pathlib.Path]:
    """
    Scrape the list of boxscore URLs for each season from the games schedule page.

    Saves: ~/data/pfref/raw/season/gamelogs/gamelogs_{year}.csv
    Each row contains one 'game_url' column with the relative href.
    """
    scraper = scraper or PlaywrightScraper()
    meta = meta or MetadataTracker()

    gamelogs_dir = GAMELOGS_DIR
    gamelogs_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[pathlib.Path] = []

    for season in years:
        dataset_key = "season_gamelogs"
        if skip_existing and meta.is_pulled(dataset_key, season):
            print(f"  [gamelogs] {season}: already pulled, skipping")
            continue

        url = f"{BASE_URL}/years/{season}/games.htm"
        print(f"  [gamelogs] {season}: fetching {url}")

        try:
            soup = scraper.fetch_and_sleep(url)

            boxscore_urls: list[str] = []
            for item in soup.find("tbody"):
                if isinstance(item, NavigableString):
                    continue
                for box in item.find_all("td", {"data-stat": "boxscore_word"}):
                    link = box.find("a")
                    if link:
                        boxscore_urls.append(link["href"])

            file_path = gamelogs_dir / f"gamelogs_{season}.csv"
            with open(file_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["game_url"])
                writer.writerows([[u] for u in boxscore_urls])

            meta.mark_pulled(dataset_key, season, file_path=file_path, record_count=len(boxscore_urls))
            saved_files.append(file_path)
            print(f"    Saved {len(boxscore_urls)} game URLs -> {file_path.name}")

        except Exception as exc:
            print(f"    ERROR [gamelogs {season}]: {exc}")
            meta.mark_failed(dataset_key, season, str(exc))

    return saved_files


# ---------------------------------------------------------------------------
# Individual game boxscores
# ---------------------------------------------------------------------------


def scrape_boxscores(
    years: range | list[int] = range(2023, 2026),
    skip_existing: bool = True,
    scraper: PlaywrightScraper | None = None,
    meta: MetadataTracker | None = None,
) -> list[pathlib.Path]:
    """
    Download individual game boxscores for all seasons.

    Requires gamelog CSVs to exist (run scrape_season_gamelogs first).
    Saves: ~/data/pfref/raw/boxscores/{year}/{game_id}.csv
    """
    scraper = scraper or PlaywrightScraper()
    meta = meta or MetadataTracker()

    gamelogs_dir = GAMELOGS_DIR
    boxscores_dir = BOXSCORES_DIR
    saved_files: list[pathlib.Path] = []

    for season in years:
        gamelog_file = gamelogs_dir / f"gamelogs_{season}.csv"
        if not gamelog_file.exists():
            print(
                f"  [boxscores] {season}: gamelog file not found – "
                f"run scrape_season_gamelogs([{season}]) first"
            )
            continue

        game_urls = pd.read_csv(gamelog_file)["game_url"].tolist()
        season_dir = boxscores_dir / str(season)
        season_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [boxscores] {season}: {len(game_urls)} games")

        for i, game_url in enumerate(game_urls):
            game_id = game_url.split("/")[-1].replace(".htm", "")
            dataset_key = "boxscores"

            if skip_existing and meta.is_pulled(dataset_key, game_id):
                continue

            file_path = season_dir / f"{game_id}.csv"
            if skip_existing and file_path.exists():
                # File exists but metadata not recorded – back-fill metadata
                meta.mark_pulled(dataset_key, game_id, file_path=file_path, season=season)
                continue

            boxscore_url = f"{BASE_URL}{game_url}"
            print(f"    ({i + 1}/{len(game_urls)}) {game_id}")

            try:
                soup = scraper.fetch_and_sleep(boxscore_url)

                offense_table = soup.find("table", {"id": "player_offense"})
                if not offense_table:
                    print(f"      No player_offense table – skipping")
                    continue

                game_rows: list[list] = []
                player_links: list[str] = []

                for item in offense_table.find("tbody"):
                    if isinstance(item, NavigableString):
                        continue
                    row = [cell.text for cell in item]
                    if len(row) in _HEADER_BY_COL_COUNT:
                        game_rows.append(row)
                    link = item.find("a")
                    if link is not None:
                        player_links.append(link["href"])

                if not game_rows:
                    continue

                col_count = len(game_rows[0])
                header = _HEADER_BY_COL_COUNT.get(col_count, _OFF_HEADER_19)

                df = pd.DataFrame(game_rows, columns=header)
                df.insert(0, "player_link", player_links[: len(df)])
                df.insert(0, "game_id", game_id)
                df.insert(0, "season", season)

                df.to_csv(file_path, index=False)
                meta.mark_pulled(dataset_key, game_id, file_path=file_path, season=season, records=len(df))
                saved_files.append(file_path)

            except Exception as exc:
                print(f"      ERROR [{game_id}]: {exc}")
                meta.mark_failed(dataset_key, game_id, str(exc))

    return saved_files
