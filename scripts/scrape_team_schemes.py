#!/usr/bin/env python3
"""
Scrape Defensive Alignment (scheme) from PFR team pages.

Source : https://www.pro-football-reference.com/teams/{team}/{year}.htm
Example: https://www.pro-football-reference.com/teams/atl/1982.htm
Output : ~/data/pfref/team_schemes.csv

Columns:
  team                  PFR lowercase abbrev (e.g. atl, gnb, clt)
  season                integer year
  defensive_alignment   e.g. "3-4", "4-3", "4-6", "3-4 Eagle" (or "N/A" if absent)
  defensive_coordinator coordinator name (or "N/A" if absent)

Uses Playwright + the real Brave browser binary to bypass Cloudflare.
Cloudflare's JS challenge requires a real browser fingerprint — curl_cffi
cookie reuse no longer works as of mid-2026.  Running the actual Brave
executable via Playwright's CDP passes the challenge transparently.

NOTE: This opens a visible Brave browser window while running.  Keep it
open; closing it will terminate the scrape.  The window can be minimized.

Rate   : 4–7 s between requests
Resume : already-scraped (team, season) rows (incl. N/A) are skipped
Errors : logged to ~/data/pfref/team_schemes_errors.csv — rerun to retry

Teams enumerated from ~/data/pfref/raw/boxscores/ directory structure.
Scope:  1978–2025 (48 seasons × ~32 teams = ~1,457 pages ≈ 2–3 hours)

Usage:
  python scripts/scrape_team_schemes.py                   # all teams/seasons
  python scripts/scrape_team_schemes.py --seasons 2000-2010
  python scripts/scrape_team_schemes.py --seasons 2005,2010,2015
  python scripts/scrape_team_schemes.py --teams atl,pit,gnb
  python scripts/scrape_team_schemes.py --dry-run         # print URLs, no fetch
  python scripts/scrape_team_schemes.py --test 5          # first 5 pages then stop
  python scripts/scrape_team_schemes.py --retry-errors    # retry previously errored rows

Environment:
  PFR_DELAY_MIN   float seconds (default 4.0)
  PFR_DELAY_MAX   float seconds (default 7.0)
  BRAVE_PATH      override Brave executable path
"""

import csv
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

# ── paths ──────────────────────────────────────────────────────────────────────

BOXSCORE_DIR = Path("/Users/devos/data/pfref/raw/boxscores")
OUTPUT_DIR   = Path("/Users/devos/data/pfref")
OUTPUT_CSV   = OUTPUT_DIR / "team_schemes.csv"
ERROR_CSV    = OUTPUT_DIR / "team_schemes_errors.csv"
LOG_FILE     = OUTPUT_DIR / "team_schemes_scrape.log"
BASE_URL     = "https://www.pro-football-reference.com"

BRAVE_PATH = os.environ.get(
    "BRAVE_PATH",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
DELAY_MIN = float(os.environ.get("PFR_DELAY_MIN", "4.0"))
DELAY_MAX = float(os.environ.get("PFR_DELAY_MAX", "7.0"))

SEASON_MIN = 1960
SEASON_MAX = 2025

OUTPUT_FIELDS = ["team", "season", "defensive_alignment", "defensive_coordinator"]
ERROR_FIELDS  = ["team", "season", "reason"]


# ── team-season enumeration ────────────────────────────────────────────────────

def enumerate_team_seasons(season_min: int = SEASON_MIN,
                           season_max: int = SEASON_MAX) -> list[tuple[str, int]]:
    """
    Walk ~/data/pfref/raw/boxscores/{year}/{YYYYMMDDNTTT} to extract unique
    (team, season) pairs.  Game directory names are 12 chars: 8-digit date +
    1 suffix digit + 3-char home team abbreviation.
    """
    team_seasons: dict[str, set[int]] = {}

    for season_dir in sorted(BOXSCORE_DIR.iterdir()):
        if not season_dir.is_dir() or not season_dir.name.isdigit():
            continue
        year = int(season_dir.name)
        if not (season_min <= year <= season_max):
            continue
        for game_dir in season_dir.iterdir():
            name = game_dir.name
            if name.startswith(".") or len(name) != 12:
                continue
            team = name[9:]  # last 3 chars are home-team abbrev
            if len(team) == 3 and team.isalpha():
                team_seasons.setdefault(team, set()).add(year)

    # Flatten to sorted list: season ascending, then team alphabetically
    pairs: list[tuple[str, int]] = []
    for team, seasons in sorted(team_seasons.items()):
        for season in sorted(seasons):
            pairs.append((team, season))

    return pairs


# ── resume / error tracking ────────────────────────────────────────────────────

def load_scraped_keys() -> set[tuple[str, int]]:
    """Return set of (team, season) already written to output CSV (any value)."""
    if not OUTPUT_CSV.exists():
        return set()
    with open(OUTPUT_CSV, newline="") as fh:
        return {
            (r["team"], int(r["season"]))
            for r in csv.DictReader(fh)
            if r.get("team") and r.get("season")
        }


def load_error_keys() -> set[tuple[str, int]]:
    """Return set of (team, season) that previously errored."""
    if not ERROR_CSV.exists():
        return set()
    with open(ERROR_CSV, newline="") as fh:
        return {
            (r["team"], int(r["season"]))
            for r in csv.DictReader(fh)
            if r.get("team") and r.get("season")
        }


# ── page parsing ───────────────────────────────────────────────────────────────

def parse_team_page(page) -> dict[str, str]:
    """
    Extract Defensive Alignment and Defensive Coordinator from a PFR team page.
    Returns dict with keys 'defensive_alignment' and 'defensive_coordinator'.
    Each value is the found text, or "N/A" if the field is not present.

    PFR team info block HTML (typical):
      <div id="info">
        <p><strong>Defensive Alignment:</strong> 3-4</p>
        <p><strong>Defensive Coordinator:</strong> Fritz Shurmur</p>
      </div>
    """
    result = page.evaluate(r"""() => {
        function extractAfterLabel(labelText) {
            // Search all <strong> elements for the label text
            const strongs = document.querySelectorAll('strong');
            for (const strong of strongs) {
                if (strong.innerText.trim().startsWith(labelText)) {
                    // Value is in the same <p>: text nodes after the <strong>
                    const p = strong.closest('p') || strong.parentElement;
                    if (!p) continue;
                    // Collect all text nodes directly in the <p> that are not
                    // inside the <strong>
                    let value = '';
                    for (const node of p.childNodes) {
                        if (node === strong) continue;
                        if (node.nodeType === Node.TEXT_NODE) {
                            value += node.textContent;
                        } else if (node.nodeName === 'A') {
                            // coordinator may be a link
                            value += node.innerText || node.textContent;
                        }
                    }
                    value = value.replace(/^\s*:?\s*/, '').trim();
                    if (value) return value;
                }
            }
            return null;
        }

        return {
            defensive_alignment:   extractAfterLabel('Defensive Alignment'),
            defensive_coordinator: extractAfterLabel('Defensive Coordinator'),
        };
    }""")

    return {
        "defensive_alignment":   result.get("defensive_alignment")   or "N/A",
        "defensive_coordinator": result.get("defensive_coordinator")  or "N/A",
    }


# ── output writers ─────────────────────────────────────────────────────────────

def append_row(team: str, season: int, fields: dict):
    write_header = not OUTPUT_CSV.exists()
    with open(OUTPUT_CSV, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow({"team": team, "season": season, **fields})


def log_error(team: str, season: int, reason: str):
    write_header = not ERROR_CSV.exists()
    with open(ERROR_CSV, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ERROR_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow({"team": team, "season": season, "reason": reason})


def log_progress(msg: str):
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as fh:
        fh.write(line + "\n")


# ── CLI parsing ────────────────────────────────────────────────────────────────

def parse_seasons_arg(arg: str) -> list[int]:
    """Parse '2000-2010' or '2005,2010,2015' into a list of ints."""
    if "-" in arg and "," not in arg:
        lo, hi = arg.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(y.strip()) for y in arg.split(",")]


# ── browser launch ─────────────────────────────────────────────────────────────

def _launch_browser(pw, tmp_profile: Path):
    """Copy Brave profile, launch persistent context, verify Cloudflare clearance."""
    brave_src = Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser"

    log_progress("Copying Brave profile (cookies + fingerprint) to temp dir...")
    shutil.copytree(
        str(brave_src / "Default"),
        str(tmp_profile / "Default"),
        ignore=shutil.ignore_patterns(
            "*.log", "Cache", "Cache *", "Code Cache", "GPUCache", "Service Worker"
        ),
    )
    shutil.copy2(str(brave_src / "Local State"), str(tmp_profile / "Local State"))
    log_progress("Profile copied.  Launching browser.")

    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(tmp_profile),
        executable_path=BRAVE_PATH,
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    log_progress("Visiting PFR homepage to verify Cloudflare clearance...")
    pg.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=20000)
    time.sleep(4)
    if "moment" in pg.title().lower():
        log_progress(
            "WARNING: Cloudflare challenge detected.  "
            "Visit PFR in Brave to refresh cookies, then rerun."
        )
        ctx.close()
        sys.exit(1)
    log_progress("Clearance confirmed.")
    return ctx, pg


def _is_browser_closed_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "browser has been closed" in msg or "target page, context or browser" in msg


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons",      help="Range 'YYYY-YYYY' or 'YYYY,YYYY,...'")
    ap.add_argument("--teams",        help="Comma-separated PFR team abbrevs, e.g. atl,pit,gnb")
    ap.add_argument("--dry-run",      action="store_true", help="Print URLs without fetching")
    ap.add_argument("--test",         type=int, metavar="N", help="Stop after N fetches")
    ap.add_argument("--retry-errors", action="store_true",
                    help="Retry previously errored (team, season) pairs")
    ap.add_argument("--force", action="store_true",
                    help="Re-scrape all rows, ignoring existing cache (overwrites output CSV)")
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Build full (team, season) list from boxscore directories
    all_pairs = enumerate_team_seasons()

    # Apply --seasons filter
    if args.seasons:
        wanted_seasons = set(parse_seasons_arg(args.seasons))
        all_pairs = [(t, s) for t, s in all_pairs if s in wanted_seasons]

    # Apply --teams filter
    if args.teams:
        wanted_teams = {t.strip().lower() for t in args.teams.split(",")}
        all_pairs = [(t, s) for t, s in all_pairs if t in wanted_teams]

    if not all_pairs:
        print("No (team, season) pairs matched the given filters.  Exiting.")
        sys.exit(0)

    scraped_keys = set() if args.force else load_scraped_keys()
    error_keys   = load_error_keys() if not args.retry_errors else set()

    if args.force and OUTPUT_CSV.exists():
        OUTPUT_CSV.unlink()
        log_progress("--force: cleared existing output CSV for full re-scrape.")

    pending = [
        (t, s) for t, s in all_pairs
        if (t, s) not in scraped_keys and (t, s) not in error_keys
    ]

    total_scope   = len(all_pairs)
    already_done  = len(all_pairs) - len(pending)
    total_pending = len(pending)

    avg_delay = (DELAY_MIN + DELAY_MAX) / 2
    est_hours = (total_pending * avg_delay) / 3600

    log_progress(
        f"Scope: {total_scope} (team, season) pairs  |  "
        f"Already done: {already_done}  |  "
        f"Pending: {total_pending}  |  "
        f"Est. time: {est_hours:.1f} h  |  "
        f"dry_run={args.dry_run}"
    )

    # ── dry-run ────────────────────────────────────────────────────────────────
    if args.dry_run:
        fetch_count = 0
        for team, season in pending:
            url = f"{BASE_URL}/teams/{team}/{season}.htm"
            print(f"  DRY: {url}")
            fetch_count += 1
            if args.test and fetch_count >= args.test:
                break
        print(f"\nTotal URLs that would be fetched: {fetch_count}")
        return

    # ── live run ───────────────────────────────────────────────────────────────
    from playwright.sync_api import sync_playwright

    tmp_root    = Path(tempfile.mkdtemp())
    tmp_profile = tmp_root / "brave-pfr"

    fetch_count   = 0
    written_count = 0
    start_time    = time.time()

    with sync_playwright() as pw:
        context, page = _launch_browser(pw, tmp_profile)

        try:
            for team, season in pending:
                url = f"{BASE_URL}/teams/{team}/{season}.htm"

                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(3)
                    status = resp.status if resp else 0

                    title = page.title()
                    if "moment" in title.lower():
                        log_progress(f"CLOUDFLARE CHALLENGE at {team}/{season}.  Waiting 20s...")
                        time.sleep(20)
                        title = page.title()
                        if "moment" in title.lower():
                            log_error(team, season, "cloudflare_block")
                            log_progress(f"  Still blocked.  Skipping {team}/{season}.")
                            fetch_count += 1
                            if args.test and fetch_count >= args.test:
                                break
                            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                            continue

                    if status == 404:
                        # Page doesn't exist — record as N/A rather than an error
                        log_progress(f"  404 {team}/{season} — recording N/A")
                        append_row(team, season, {
                            "defensive_alignment":   "N/A",
                            "defensive_coordinator": "N/A",
                        })
                        written_count += 1
                        fetch_count += 1
                        if args.test and fetch_count >= args.test:
                            break
                        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                        continue

                except Exception as e:
                    if _is_browser_closed_error(e):
                        log_progress("Browser was closed — relaunching automatically...")
                        try:
                            context.close()
                        except Exception:
                            pass
                        context, page = _launch_browser(pw, tmp_profile)
                        # Retry once with the fresh browser
                        try:
                            resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
                            time.sleep(3)
                        except Exception as e2:
                            log_error(team, season, str(e2)[:120])
                            log_progress(f"  RETRY FAILED {team}/{season}: {e2}")
                            fetch_count += 1
                            if args.test and fetch_count >= args.test:
                                break
                            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                            continue
                    else:
                        log_error(team, season, str(e)[:120])
                        log_progress(f"  ERROR {team}/{season}: {e}")
                        fetch_count += 1
                        if args.test and fetch_count >= args.test:
                            break
                        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                        continue

                # Parse the page
                fields = parse_team_page(page)
                append_row(team, season, fields)
                written_count += 1

                alignment = fields["defensive_alignment"]
                coordinator = fields["defensive_coordinator"]
                log_progress(
                    f"  {team} {season}  alignment={alignment!r}  coord={coordinator!r}"
                )

                fetch_count += 1

                # Progress estimate every 25 fetches
                if fetch_count % 25 == 0:
                    elapsed   = time.time() - start_time
                    rate      = fetch_count / elapsed if elapsed > 0 else 0
                    remaining = (total_pending - fetch_count) / rate if rate > 0 else 0
                    log_progress(
                        f"  Progress: {fetch_count}/{total_pending} fetched  "
                        f"({written_count} written)  "
                        f"rate={rate:.2f}/s  "
                        f"ETA={remaining/3600:.1f}h"
                    )

                if args.test and fetch_count >= args.test:
                    log_progress(f"--test limit ({args.test}) reached; stopping.")
                    break

                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

        finally:
            try:
                context.close()
            except Exception:
                pass
            shutil.rmtree(str(tmp_root), ignore_errors=True)

    elapsed = time.time() - start_time
    log_progress(
        f"Run complete.  "
        f"Fetched: {fetch_count}  Written: {written_count}  "
        f"Elapsed: {elapsed/60:.1f} min"
    )


if __name__ == "__main__":
    main()
