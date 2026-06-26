"""
Play-by-play scraper for Pro Football Reference boxscore pages.

Saves the full PBP table for each game, including the detail/description
column that names individual defenders (tackles, sacks, INTs, fumbles).

PFR buries the PBP table in an HTML comment block — strip_comments=True
handles that. The table has id="pbp".

Output: ~/data/pfref/boxscores_pbp/{year}/{game_id}.csv
Each row is one play.

Usage:
    from pfref.play_by_play import scrape_pbp
    scrape_pbp(years=range(1982, 2002))          # era with no per-game defensive stats
    scrape_pbp(years=[1988], teams=["phi"])       # only PHI 1988 games
"""

import csv
import pathlib
import re

import pandas as pd
from bs4 import NavigableString

from .metadata import MetadataTracker
from .scraper import BASE_URL
from .scraper_playwright import PlaywrightScraper

RAW_DIR = pathlib.Path.home() / "data" / "pfref" / "raw"
GAMELOGS_DIR = RAW_DIR / "season" / "gamelogs"
PBP_DIR = RAW_DIR / "boxscores_pbp"

# PBP table data-stat column names (order-independent — we look them up by data-stat)
_PBP_COLUMNS = [
    "quarter",
    "time",
    "down",
    "togo",
    "location",
    "exp_pts_before",
    "exp_pts_after",
    "detail",
]

# Regular expressions to extract defenders from detail text.
# PFR formats vary by era and game type. We do lightweight extraction here;
# full parsing (solo vs. assisted, play type classification) is done in ETL.
_SACK_RE = re.compile(
    r"sacked by ([A-Z]\.[A-Za-z\'\-]+(?: and [A-Z]\.[A-Za-z\'\-]+)?)",
    re.IGNORECASE,
)
_TACKLE_RE = re.compile(
    r"tackled by ([A-Z]\.[A-Za-z\'\-]+(?: and [A-Z]\.[A-Za-z\'\-]+)?)",
    re.IGNORECASE,
)


def scrape_pbp(
    years: range | list[int] = range(1982, 2002),
    teams: list[str] | None = None,
    skip_existing: bool = True,
    scraper: PlaywrightScraper | None = None,
    meta: MetadataTracker | None = None,
) -> list[pathlib.Path]:
    """
    Scrape play-by-play tables from PFR boxscore pages.

    Args:
        years:         Seasons to scrape (default 1982–2001, the gap era for defensive stats).
        teams:         If given, only scrape games where this team played (e.g. ["phi", "gnb"]).
                       Matched against the game_id suffix (home team) and the away team in the CSV.
        skip_existing: Skip game IDs already in metadata or already saved to disk.
        scraper:       Reuse an existing PlaywrightScraper instance.

    Returns:
        List of saved file paths.
    """
    scraper = scraper or PlaywrightScraper()
    meta = meta or MetadataTracker()

    gamelogs_dir = GAMELOGS_DIR
    pbp_base_dir = PBP_DIR
    pbp_base_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[pathlib.Path] = []

    for season in years:
        gamelog_file = gamelogs_dir / f"gamelogs_{season}.csv"
        if not gamelog_file.exists():
            print(f"  [pbp] {season}: no gamelog file — run scrape_season_gamelogs([{season}]) first")
            continue

        game_urls = pd.read_csv(gamelog_file)["game_url"].tolist()

        # Filter by team if requested — game_id encodes home team as suffix
        if teams:
            team_set = {t.lower() for t in teams}
            game_urls = [u for u in game_urls if _game_involves_team(u, team_set, season, gamelogs_dir)]

        season_dir = pbp_base_dir / str(season)
        season_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [pbp] {season}: {len(game_urls)} games to process")

        for i, game_url in enumerate(game_urls):
            game_id = game_url.split("/")[-1].replace(".htm", "")
            dataset_key = "boxscores_pbp"

            if skip_existing and meta.is_pulled(dataset_key, game_id):
                continue

            file_path = season_dir / f"{game_id}.csv"
            if skip_existing and file_path.exists():
                meta.mark_pulled(dataset_key, game_id, file_path=file_path, season=season)
                continue

            boxscore_url = f"{BASE_URL}{game_url}"
            print(f"    ({i + 1}/{len(game_urls)}) {game_id}")

            try:
                # strip_comments=True is required — PFR wraps the pbp table in <!-- -->
                soup = scraper.fetch_and_sleep(boxscore_url, strip_comments=True)

                pbp_table = soup.find("table", {"id": "pbp"})
                if not pbp_table:
                    print(f"      No pbp table found (game may predate PFR PBP data)")
                    meta.mark_failed(dataset_key, game_id, "no pbp table")
                    continue

                rows = _parse_pbp_table(pbp_table, game_id, season)
                if not rows:
                    print(f"      pbp table empty")
                    continue

                df = pd.DataFrame(rows)
                df.to_csv(file_path, index=False)
                meta.mark_pulled(dataset_key, game_id, file_path=file_path, season=season, records=len(df))
                saved_files.append(file_path)

            except Exception as exc:
                print(f"      ERROR [{game_id}]: {exc}")
                meta.mark_failed(dataset_key, game_id, str(exc))

    return saved_files


def _parse_pbp_table(table, game_id: str, season: int) -> list[dict]:
    """Extract rows from the PBP BeautifulSoup table element."""
    rows = []
    tbody = table.find("tbody")
    if not tbody:
        return rows

    for tr in tbody.find_all("tr"):
        if "thead" in tr.get("class", []) or "divider" in tr.get("class", []):
            continue

        cells = {td.get("data-stat"): td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])}
        if not cells.get("detail"):
            continue

        row = {
            "season":   season,
            "game_id":  game_id,
            "quarter":  cells.get("quarter", ""),
            "time":     cells.get("time", ""),
            "down":     cells.get("down", ""),
            "togo":     cells.get("togo", ""),
            "location": cells.get("location", ""),
            "epb":      cells.get("exp_pts_before", ""),
            "epa":      cells.get("exp_pts_after", ""),
            "detail":   cells.get("detail", ""),
        }
        rows.append(row)

    return rows


def _game_involves_team(game_url: str, team_set: set[str], season: int, gamelogs_dir: pathlib.Path) -> bool:
    """
    Return True if either team in this game matches any team in team_set.
    The game_id suffix is the home team. Away team requires reading the boxscore CSV
    if already downloaded; otherwise we include the game conservatively.
    """
    game_id = game_url.split("/")[-1].replace(".htm", "")
    # Home team is the last 2-3 chars of the game_id (after the date prefix YYYYMMDD)
    home_team = re.sub(r"^\d{8}", "", game_id).lower()
    if home_team in team_set:
        return True

    # Check if already-downloaded boxscore has the away team
    existing_csv = RAW_DIR / "boxscores" / str(season) / game_id / "player_offense.csv"
    if existing_csv.exists():
        try:
            with open(existing_csv) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("team", "").lower() in team_set:
                        return True
        except Exception:
            pass
        return False

    # Can't determine away team without fetching — include conservatively
    return True


def load_pbp(game_id: str, season: int | None = None) -> pd.DataFrame | None:
    """Load a saved PBP CSV by game_id. Returns None if not yet scraped."""
    if season is None:
        season = int(game_id[:4])
    path = pathlib.Path.home() / "data" / "pfref" / "boxscores_pbp" / str(season) / f"{game_id}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def extract_defenders_from_detail(detail: str) -> dict:
    """
    Lightweight extraction of defenders named in a play detail string.

    Returns a dict with:
        play_type:  'sack' | 'tackle' | 'other'
        defenders:  list of name strings as they appear in the text
        raw_detail: original string

    Full normalization (mapping names to pfr_player_id) happens in ETL,
    not here — this just structures the raw text.
    """
    result = {"play_type": "other", "defenders": [], "raw_detail": detail}

    sack_match = _SACK_RE.search(detail)
    if sack_match:
        result["play_type"] = "sack"
        result["defenders"] = [n.strip() for n in re.split(r"\s+and\s+", sack_match.group(1))]
        return result

    tackle_match = _TACKLE_RE.search(detail)
    if tackle_match:
        result["play_type"] = "tackle"
        result["defenders"] = [n.strip() for n in re.split(r"\s+and\s+", tackle_match.group(1))]

    return result
