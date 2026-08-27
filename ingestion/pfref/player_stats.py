"""
Player statistics scrapers for Pro Football Reference.

Covers: passing, rushing, receiving, scrimmage, defense, kicking, punting, returns, scoring.

Each stat type is scraped from:
  https://www.pro-football-reference.com/years/{year}/{stat}.htm

Data is saved to:
  ~/data/pfref/raw/season/player/{stat}/{stat}_{year}.csv

Pull history is tracked in metadata.json so already-pulled years are skipped.
"""

from __future__ import annotations

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

# 1966-1969 had separate AFL season pages (pre-1970 merger), same URL
# pattern with a "_AFL" year suffix — mirrors team_stats.py's approach.
_URL_PATTERNS_AFL: dict[str, str] = {
    stat: pattern.replace("/years/{year}/", "/years/{year}_AFL/")
    for stat, pattern in _URL_PATTERNS.items()
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
        # "tfl" deliberately NOT renamed to "pfr_tfl" or "run_stuff" here --
        # this is PFR's own official, sack-inclusive tackles-for-loss stat,
        # and this whole list normalizes column names at the raw/bronze
        # scrape layer (RAW_PLAYER_DIR is under ~/data/pfref/raw/... --
        # already a PFR-namespaced location), which
        # gamebooks_boxscores/docs/RUN_STUFFS_RENAME_PLAN.md SS7a point 2
        # says to leave untouched at the point of ingestion. Downstream
        # consumers outside this PFR-namespaced tree (e.g.
        # scripts/fit_idi_additive_weights.py) rename it to "pfr_tfl" on
        # their own side when they load this CSV -- do NOT rename it here
        # too, and never call it "run_stuff" (that's this project's own,
        # different, non-sack convention -- see the same doc's SS7a point 1).
        "tfl", "qb_hits", "safety", "awards",
    ],
    # scrimmage, kicking, punting, returns, scoring: columns vary by era;
    # use data-stat names from the page directly (no rename applied).
}

# ---------------------------------------------------------------------------
# Internal generic scraper
# ---------------------------------------------------------------------------


def _dedupe_columns(cols) -> list[str]:
    """
    Rename repeated column labels the same way pandas.read_csv does on load
    (first stays bare, later ones get '.1', '.2', ...). Some PFR pages
    (e.g. the 1969 AFL defense table) reuse a raw data-stat name ('yds')
    for two different columns (INT yards, FR yards) when the normalized
    rename doesn't apply (column-count mismatch). Without this, a
    duplicate-named column breaks pd.concat during the AFL merge with
    'Reindexing only valid with uniquely valued Index objects'. Applying
    it consistently to both sides of a merge keeps position-based
    alignment correct either way.
    """
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        if c not in seen:
            seen[c] = 0
            out.append(c)
        else:
            seen[c] += 1
            out.append(f"{c}.{seen[c]}")
    return out


def _merge_player_rows(df: pd.DataFrame, file_path: pathlib.Path) -> pd.DataFrame:
    """
    Append df's (AFL) rows to whatever is already saved at file_path (NFL
    rows for that year) instead of overwriting it.

    Dedupe key is (player_id, team) when both are present, else falls back
    to (player_name, team) — team is REQUIRED in the key, not just
    player_id: a player traded mid-season gets a '2TM' aggregate row plus
    one row per team under the SAME player_id (a real, legitimate PFR
    pattern, confirmed on 1969 defense: Rosey Taylor / Nate Wright each
    have 3 same-id rows for 2TM/CHI/SFO and 2TM/ATL/STL respectively).
    player_id alone as the key silently collapsed those down to one row
    the first time this was tried — caught and fixed before any real
    AFL run. 1967-69 AFL/NFL were fully separate leagues so no player
    appears in both in the same season; this key still guards a rerun of
    the same league/year without discarding real per-team splits.
    Existing rows win ties.
    """
    if file_path.exists():
        existing = pd.read_csv(file_path)
        existing.columns = _dedupe_columns(existing.columns)
        df = df.copy()
        df.columns = _dedupe_columns(df.columns)
        combined = pd.concat([existing, df], ignore_index=True)

        if "player_id" in combined.columns and combined["player_id"].notna().any():
            id_col = "player_id"
        else:
            id_col = "player_name" if "player_name" in combined.columns else None
        team_col = "team_abbrev" if "team_abbrev" in combined.columns else (
            "team" if "team" in combined.columns else None
        )
        key_cols = [c for c in (id_col, team_col) if c is not None]

        before = len(combined)
        if key_cols:
            # Rows with a null id (section-header/divider rows PFR's HTML
            # leaves in the tbody) aren't real players — drop them outright
            # rather than deduping, since NaN==NaN would otherwise collapse
            # many unrelated blank rows into one.
            if id_col is not None:
                combined = combined[combined[id_col].notna()]
            combined = combined.drop_duplicates(subset=key_cols, keep="first")
        if len(combined) != before:
            print(f"    merge into {file_path.name}: dropped "
                  f"{before - len(combined)} duplicate/blank player row(s)")
    else:
        combined = df
    combined.to_csv(file_path, index=False)
    return combined


def _scrape_player_stat(
    stat_type: str,
    years: list[int],
    skip_existing: bool = True,
    scraper: PlaywrightScraper | None = None,
    meta: MetadataTracker | None = None,
    league: str = "NFL",
) -> list[pathlib.Path]:
    """Pull one player stat type for all given years, skipping already-pulled years.

    league='AFL' fetches the parallel pre-merger AFL page (1966-1969 only,
    /years/{year}_AFL/{stat}.htm) and MERGES its rows into the existing
    per-year CSV rather than overwriting it, tracked under its own
    metadata dataset key so it never collides with the NFL pull's
    skip-existing state.
    """
    scraper = scraper or PlaywrightScraper()
    meta = meta or MetadataTracker()

    table_id = _TABLE_IDS[stat_type]
    header_idx = _HEADER_ROW_INDEX[stat_type]
    url_pattern = _URL_PATTERNS[stat_type] if league == "NFL" else _URL_PATTERNS_AFL[stat_type]
    normalized_cols = _NORMALIZED_COLUMNS.get(stat_type)

    save_dir = RAW_PLAYER_DIR / stat_type
    save_dir.mkdir(parents=True, exist_ok=True)

    saved_files: list[pathlib.Path] = []

    for year in years:
        dataset_key = f"player_{stat_type}" if league == "NFL" else f"player_{stat_type}_{league.lower()}"
        file_path = save_dir / f"{stat_type}_{year}.csv"

        if skip_existing and meta.is_pulled(dataset_key, year):
            print(f"  [{stat_type}/{league}] {year}: already pulled, skipping")
            continue
        if league == "NFL" and skip_existing and file_path.exists():
            # File exists from a previous scraper run that predates this tracker
            meta.mark_pulled(dataset_key, year, file_path=file_path)
            print(f"  [{stat_type}/{league}] {year}: file exists, back-filling metadata, skipping")
            continue

        url = BASE_URL + url_pattern.format(year=year)
        print(f"  [{stat_type}/{league}] {year}: fetching {url}")

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

            if league == "NFL":
                df.to_csv(file_path, index=False)
            else:
                df = _merge_player_rows(df, file_path)

            meta.mark_pulled(dataset_key, year, file_path=file_path, record_count=len(df))
            saved_files.append(file_path)
            print(f"    Saved {len(df)} rows -> {file_path.name}")

        except ValueError as exc:
            if "not found on page" in str(exc):
                meta.mark_pulled(dataset_key, year, record_count=0)
                print(f"    table not on page for {year} — marked as checked, skipping")
            else:
                print(f"    ERROR [{stat_type}/{league} {year}]: {exc}")
                meta.mark_failed(dataset_key, year, str(exc))
        except Exception as exc:
            print(f"    ERROR [{stat_type}/{league} {year}]: {exc}")
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
    league: str = "NFL",
) -> dict[str, list[pathlib.Path]]:
    """
    Scrape player stats for all (or specified) stat types.
    Shares a single scraper/meta instance to avoid redundant browser launches.

    league='AFL' fetches the parallel pre-merger AFL pages (1966-1969 only)
    and merges rows into the existing per-year CSVs — see _scrape_player_stat.
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
            print(f"\n=== Scraping player {stat_type} ({league}) ===")
            results[stat_type] = _scrape_player_stat(
                stat_type, list(years), skip_existing, scraper=scraper, meta=meta,
                league=league,
            )
    finally:
        scraper.close()
    return results
