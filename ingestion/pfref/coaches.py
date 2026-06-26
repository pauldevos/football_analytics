"""
Coaches scraper for Pro Football Reference.

Two-phase approach:
  Phase 1 — pull the HC index page (/coaches/) to seed the manifest with every
             coach who was at least a head coach.
  Phase 2 — pull each coach's personal page, appending to 5 consolidated tables:
               coaching_record.csv    HC record by season/team
               team_ranks.csv         team off/def ranks by season (incl. coordinator years)
               coaching_history.csv   full career inc. assistant roles
               worked_for.csv         coaches/teams this coach worked under (+linked_coach_id)
               employed.csv           coaches this coach employed (+linked_coach_id)

  worked_for and employed carry a linked_coach_id column (extracted from href) so
  the coaching tree can be built as a graph without name-matching.

Data saved to:
  ~/data/pfref/raw/coaches/
      coach_manifest.csv       — all known coaches + pull status
      coaching_record.csv      — one row per coach-season (all coaches)
      team_ranks.csv           — one row per coach-season (all coaches)
      coaching_history.csv     — one row per coach-role-year (all coaches)
      worked_for.csv           — edges: coach_id → linked_coach_id
      employed.csv             — edges: coach_id → linked_coach_id

Usage:
    from ingestion.pfref.coaches import seed_manifest, scrape_all_coaches, scrape_pending

    # Step 1 — one time: build manifest from HC index
    seed_manifest()

    # Step 2 — pull all HC pages (takes a while)
    scrape_all_coaches()

    # Step 3 — pull tree coaches found during step 2
    scrape_pending()

    # Or: pull one coach for testing
    from ingestion.pfref.coaches import scrape_coach
    scrape_coach("ShulDo0")
"""

import csv
import pathlib
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup

from .scraper import BASE_URL
from .scraper_playwright import PlaywrightScraper

COACHES_DIR = pathlib.Path.home() / "data" / "pfref" / "raw" / "coaches"
MANIFEST_PATH = COACHES_DIR / "coach_manifest.csv"

_MANIFEST_FIELDS = ["coach_id", "href", "name", "source", "status", "pulled_at", "error"]

# PFR table ids on a coach's personal page (filename → html table id)
_COACH_TABLES = {
    "coaching_record":   "coaching_results",
    "team_ranks":        "coaching_ranks",
    "coaching_history":  "coaching_history",
    "worked_for":        "worked_for",
    "employed":          "employed",
}

# Tables whose coach_name cells contain a /coaches/ href.
# Maps filename → (name_column, id_column) for the linked coach.
_COACH_LINK_COLUMNS: dict[str, tuple[str, str]] = {
    "worked_for": ("worked_for_coach_name", "worked_for_coach_id"),
    "employed":   ("employed_coach_name",   "employed_coach_id"),
}
_COACH_LINK_TABLES = frozenset(_COACH_LINK_COLUMNS)


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _read_manifest() -> dict[str, dict]:
    """Load manifest into {coach_id: row_dict}. Returns empty dict if not found."""
    if not MANIFEST_PATH.exists():
        return {}
    with open(MANIFEST_PATH, newline="") as f:
        return {row["coach_id"]: row for row in csv.DictReader(f)}


def _write_manifest(rows: dict[str, dict]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows.values():
            # Ensure all fields exist
            writer.writerow({k: row.get(k, "") for k in _MANIFEST_FIELDS})


def _add_to_manifest(
    manifest: dict[str, dict],
    coach_id: str,
    href: str,
    name: str = "",
    source: str = "tree",
) -> bool:
    """Add coach to manifest if not already present. Returns True if newly added."""
    if coach_id in manifest:
        return False
    manifest[coach_id] = {
        "coach_id": coach_id,
        "href": href,
        "name": name,
        "source": source,
        "status": "pending",
        "pulled_at": "",
        "error": "",
    }
    return True


def _mark_pulled(manifest: dict[str, dict], coach_id: str) -> None:
    manifest[coach_id]["status"] = "pulled"
    manifest[coach_id]["pulled_at"] = datetime.now().isoformat()
    manifest[coach_id]["error"] = ""


def _mark_failed(manifest: dict[str, dict], coach_id: str, error: str) -> None:
    manifest[coach_id]["status"] = "failed"
    manifest[coach_id]["error"] = error[:200]


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def _coach_id_from_href(href: str) -> str:
    """Extract coach_id from href like '/coaches/ShulDo0.htm'."""
    return pathlib.Path(href).stem


def _extract_coach_hrefs(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """
    Return (href, name) tuples for every coach link in the page.
    Matches /coaches/{id}.htm where id has no underscores (excludes _register pages).
    """
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/coaches/") and href.endswith(".htm") and href not in seen:
            coach_id = pathlib.Path(href).stem
            if "_" in coach_id:  # skip _register and other non-coach-page variants
                continue
            seen.add(href)
            results.append((href, a.get_text(strip=True)))
    return results


def _append_to_consolidated(filename: str, coach_id: str, coach_name: str, fieldnames: list[str], rows: list[dict]) -> None:
    """Append rows to the consolidated CSV for this table type, writing header if new file."""
    out_path = COACHES_DIR / f"{filename}.csv"
    write_header = not out_path.exists() or out_path.stat().st_size == 0
    all_fields = ["coach_id", "coach_name"] + fieldnames
    with open(out_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow({"coach_id": coach_id, "coach_name": coach_name, **row})


def _save_table(soup: BeautifulSoup, table_id: str, filename: str, coach_id: str, coach_name: str = "") -> bool:
    """
    Parse a PFR table and append rows to the consolidated CSV for that table type.
    For worked_for/employed tables, extracts linked_coach_id from coach_name hrefs.
    Returns True if the table was found and had rows.
    """
    table = soup.find("table", {"id": table_id})
    if not table:
        return False

    thead = table.find("thead")
    tbody = table.find("tbody")
    if not thead or not tbody:
        return False

    stat_names = [
        th.get("data-stat", "")
        for th in thead.find_all("tr")[-1].find_all(["th", "td"])
        if not th.get("data-stat", "").startswith("header_")
    ]

    link_cols = _COACH_LINK_COLUMNS.get(filename)  # (name_col, id_col) or None
    rows: list[dict] = []
    for tr in tbody.find_all("tr"):
        if "thead" in tr.get("class", []) or "divider" in tr.get("class", []):
            continue
        cells = tr.find_all(["th", "td"])
        row: dict[str, str] = {}
        for stat, td in zip(stat_names, cells):
            if stat.startswith("header_"):
                continue
            if link_cols and stat == "coach_name":
                name_col, id_col = link_cols
                row[name_col] = td.get_text(" ", strip=True)
                a = td.find("a", href=True)
                row[id_col] = (
                    pathlib.Path(a["href"]).stem
                    if a and "/coaches/" in a["href"] and "_" not in pathlib.Path(a["href"]).stem
                    else ""
                )
            else:
                row[stat] = td.get_text(" ", strip=True)
        if row:
            rows.append(row)

    if not rows:
        return False

    fieldnames = list(dict.fromkeys(k for r in rows for k in r.keys()))
    # Keep name_col → id_col adjacent
    if link_cols:
        name_col, id_col = link_cols
        if id_col in fieldnames and name_col in fieldnames:
            fieldnames.remove(id_col)
            fieldnames.insert(fieldnames.index(name_col) + 1, id_col)

    _append_to_consolidated(filename, coach_id, coach_name, fieldnames, rows)
    return True


# ---------------------------------------------------------------------------
# Phase 1: Seed manifest from HC index
# ---------------------------------------------------------------------------


def seed_manifest(
    scraper: Optional[PlaywrightScraper] = None,
    force: bool = False,
) -> int:
    """
    Fetch /coaches/ and add all HC hrefs to the manifest.

    Args:
        scraper: Reuse an existing scraper instance.
        force:   Re-seed even if manifest already exists.

    Returns:
        Number of coaches newly added to the manifest.
    """
    manifest = _read_manifest()

    if manifest and not force:
        pending = sum(1 for r in manifest.values() if r["status"] == "pending")
        pulled  = sum(1 for r in manifest.values() if r["status"] == "pulled")
        print(f"Manifest already exists: {pulled} pulled, {pending} pending. "
              f"Use force=True to re-seed.")
        return 0

    own_scraper = scraper is None
    scraper = scraper or PlaywrightScraper()

    try:
        url = f"{BASE_URL}/coaches/"
        print(f"Fetching HC index: {url}")
        soup = scraper.fetch_and_sleep(url, strip_comments=True)

        coach_links = _extract_coach_hrefs(soup)
        added = 0
        for href, name in coach_links:
            coach_id = _coach_id_from_href(href)
            if _add_to_manifest(manifest, coach_id, href, name=name, source="hc_index"):
                added += 1

        _write_manifest(manifest)
        print(f"Manifest seeded: {added} coaches added ({len(manifest)} total).")
        return added

    finally:
        if own_scraper:
            scraper.close()


# ---------------------------------------------------------------------------
# Phase 2: Pull individual coach pages
# ---------------------------------------------------------------------------


def scrape_coach(
    coach_id: str,
    scraper: Optional[PlaywrightScraper] = None,
    manifest: Optional[dict] = None,
) -> list[tuple[str, str]]:
    """
    Pull one coach's personal page and save all 4 tables.

    Returns list of (href, name) tuples for coaches found in the page,
    to be added to the manifest by the caller.
    """
    own_scraper = scraper is None
    scraper = scraper or PlaywrightScraper()
    own_manifest = manifest is None
    manifest = manifest if manifest is not None else _read_manifest()

    if coach_id not in manifest:
        raise ValueError(f"Coach '{coach_id}' not in manifest. Run seed_manifest() first.")

    href = manifest[coach_id]["href"]
    url = f"{BASE_URL}{href}"

    found_hrefs: list[tuple[str, str]] = []

    try:
        print(f"  [{coach_id}] fetching {url}")
        soup = scraper.fetch_and_sleep(url, strip_comments=True)

        # Update name from page title if we don't have it
        if not manifest[coach_id].get("name"):
            h1 = soup.find("h1", {"itemprop": "name"})
            if h1:
                manifest[coach_id]["name"] = h1.get_text(strip=True)

        coach_name = manifest[coach_id].get("name", "")
        # Append all tables to consolidated CSVs
        for filename, table_id in _COACH_TABLES.items():
            found = _save_table(soup, table_id, filename, coach_id, coach_name)
            if found:
                print(f"    saved → {filename}.csv")
            else:
                print(f"    [{table_id}] table not found (may not apply to this coach)")

        # Collect all coach hrefs from the full page for manifest seeding
        found_hrefs = _extract_coach_hrefs(soup)
        # Remove self-reference
        found_hrefs = [(h, n) for h, n in found_hrefs if _coach_id_from_href(h) != coach_id]

        _mark_pulled(manifest, coach_id)
        print(f"    done — {len(found_hrefs)} coach hrefs found on page")

    except Exception as exc:
        err = str(exc)
        print(f"    ERROR [{coach_id}]: {err}")
        _mark_failed(manifest, coach_id, err)

    finally:
        if own_scraper:
            scraper.close()
        if own_manifest:
            _write_manifest(manifest)

    return found_hrefs


# ---------------------------------------------------------------------------
# Batch scraper
# ---------------------------------------------------------------------------


def scrape_all_coaches(
    skip_pulled: bool = True,
    source_filter: Optional[str] = None,
) -> None:
    """
    Pull all coaches in the manifest (or those matching source_filter).

    After each coach is pulled, any new coach hrefs discovered are added
    to the manifest as source="tree", status="pending".

    Args:
        skip_pulled:   Skip coaches already marked "pulled" (default True).
        source_filter: If set, only pull coaches with this source value
                       (e.g. "hc_index" to pull only HCs first).
    """
    manifest = _read_manifest()
    if not manifest:
        print("Manifest is empty. Run seed_manifest() first.")
        return

    to_pull = [
        coach_id for coach_id, row in manifest.items()
        if (not skip_pulled or row["status"] != "pulled")
        and (source_filter is None or row["source"] == source_filter)
    ]

    print(f"Coaches to pull: {len(to_pull)}")

    scraper = PlaywrightScraper()
    try:
        for i, coach_id in enumerate(to_pull):
            print(f"\n[{i+1}/{len(to_pull)}] {coach_id}")
            found_hrefs = scrape_coach(coach_id, scraper=scraper, manifest=manifest)

            # Seed any newly discovered coaches into manifest
            newly_added = 0
            for href, name in found_hrefs:
                cid = _coach_id_from_href(href)
                if _add_to_manifest(manifest, cid, href, name=name, source="tree"):
                    newly_added += 1

            if newly_added:
                print(f"    +{newly_added} new coach(es) added to manifest")

            # Write manifest after every coach so progress is never lost
            _write_manifest(manifest)

    finally:
        scraper.close()

    pulled = sum(1 for r in manifest.values() if r["status"] == "pulled")
    pending = sum(1 for r in manifest.values() if r["status"] == "pending")
    failed = sum(1 for r in manifest.values() if r["status"] == "failed")
    print(f"\nDone. pulled={pulled}  pending={pending}  failed={failed}")


def scrape_pending() -> None:
    """Pull all coaches in the manifest with status='pending'."""
    scrape_all_coaches(skip_pulled=True)


# ---------------------------------------------------------------------------
# Status / inspection helpers
# ---------------------------------------------------------------------------


def manifest_summary() -> None:
    """Print a summary of the coach manifest."""
    manifest = _read_manifest()
    if not manifest:
        print("Manifest is empty. Run seed_manifest() first.")
        return

    by_source: dict[str, dict[str, int]] = {}
    for row in manifest.values():
        src = row.get("source", "unknown")
        status = row.get("status", "unknown")
        by_source.setdefault(src, {})
        by_source[src][status] = by_source[src].get(status, 0) + 1

    print(f"{'Source':<12} {'Pending':>8} {'Pulled':>8} {'Failed':>8} {'Total':>8}")
    print("-" * 50)
    for src, counts in sorted(by_source.items()):
        total = sum(counts.values())
        print(f"{src:<12} {counts.get('pending',0):>8} {counts.get('pulled',0):>8} "
              f"{counts.get('failed',0):>8} {total:>8}")
    print("-" * 50)
    total = len(manifest)
    all_pulled = sum(1 for r in manifest.values() if r["status"] == "pulled")
    all_pending = sum(1 for r in manifest.values() if r["status"] == "pending")
    all_failed = sum(1 for r in manifest.values() if r["status"] == "failed")
    print(f"{'TOTAL':<12} {all_pending:>8} {all_pulled:>8} {all_failed:>8} {total:>8}")
