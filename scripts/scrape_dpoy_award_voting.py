#!/usr/bin/env python3
"""
Scrape full AP Defensive Player of the Year voting (rank/votes/share, not
just winner) from PFR's per-year awards-voting pages.

Source : https://www.pro-football-reference.com/awards/awards_{year}.htm
         (one page per year, holds AP MVP / OPoY / DPoY / ORoY / DRoY / CPoY
         / CoY voting tables together -- this script only parses the DPoY
         table, id="voting_apdpoy")
Output : ~/data/pfref/ap_dpoy_voting.csv

Columns:
  season, dpoy_voting_rank, player_id (PFR short id), player_name, pos,
  team, votes, share_pct, tackles_solo, tackles_ast, sacks, def_int,
  def_int_yds, def_int_td

Why this page over the per-player season Awards column (defense_{year}.csv,
already scraped, lives in raw/season/player/defense/): that column only
carries a bare "AP DPoY-N" rank tag (no vote count/share), and the existing
local scrape of it stops being populated after 2005 (checked directly:
zero non-empty awards cells in defense_2006.csv onward). This page is the
single, complete, still-current source PFR maintains for full multi-
candidate voting detail, one page per year, back through 1971 (first AP
DPOY voting year).

NOTE: This page is AP-only (voting_apdpoy et al. are all AP tables -- no
PFWA/Sporting News voting appears on it, confirmed by inspecting the raw
HTML for 2005). PFWA's own DPOY is winner-only publicly available data
(see docs/deferred/04_award_recognition_vs_int_value_20260822.md Part 2)
-- there is no PFWA equivalent of this page to scrape.

Uses Playwright + the real Brave browser binary to bypass Cloudflare, same
pattern as scrape_team_schemes.py (see that file's docstring for why).

Rate   : 4-7s between requests (PFR_DELAY_MIN/PFR_DELAY_MAX env vars)
Resume : already-scraped seasons are skipped
Errors : logged to ~/data/pfref/ap_dpoy_voting_errors.csv -- rerun to retry

Usage:
  python scripts/scrape_dpoy_award_voting.py                  # 1971-2025
  python scripts/scrape_dpoy_award_voting.py --seasons 1971-1990
  python scripts/scrape_dpoy_award_voting.py --test 3
  python scripts/scrape_dpoy_award_voting.py --retry-errors
"""

import csv
import os
import random
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

OUTPUT_DIR = Path("/Users/devos/data/pfref")
OUTPUT_CSV = OUTPUT_DIR / "ap_dpoy_voting.csv"
ERROR_CSV = OUTPUT_DIR / "ap_dpoy_voting_errors.csv"
LOG_FILE = OUTPUT_DIR / "ap_dpoy_voting_scrape.log"
BASE_URL = "https://www.pro-football-reference.com"

BRAVE_PATH = os.environ.get(
    "BRAVE_PATH",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
DELAY_MIN = float(os.environ.get("PFR_DELAY_MIN", "4.0"))
DELAY_MAX = float(os.environ.get("PFR_DELAY_MAX", "7.0"))

SEASON_MIN = 1971  # first AP DPOY voting year
SEASON_MAX = 2025

OUTPUT_FIELDS = [
    "season", "dpoy_voting_rank", "player_id", "player_name", "pos", "team",
    "votes", "share_pct", "tackles_solo", "tackles_ast", "sacks",
    "def_int", "def_int_yds", "def_int_td",
]
ERROR_FIELDS = ["season", "reason"]


# ── resume / error tracking ──────────────────────────────────────────────

def load_scraped_seasons() -> set[int]:
    if not OUTPUT_CSV.exists():
        return set()
    with open(OUTPUT_CSV, newline="") as fh:
        return {int(r["season"]) for r in csv.DictReader(fh) if r.get("season")}


def load_error_seasons() -> set[int]:
    if not ERROR_CSV.exists():
        return set()
    with open(ERROR_CSV, newline="") as fh:
        return {int(r["season"]) for r in csv.DictReader(fh) if r.get("season")}


# ── page parsing ─────────────────────────────────────────────────────────

def parse_dpoy_table(page) -> list[dict]:
    """
    Extract rows from the voting_apdpoy table. Returns [] if the table
    isn't present on this year's page (e.g. a season before DPOY voting
    existed, or a real structural surprise -- caller should treat an empty
    result as worth double-checking, not silently accept it for in-range
    years).
    """
    rows = page.evaluate(r"""() => {
        const table = document.getElementById('voting_apdpoy');
        if (!table) return [];
        const body = table.querySelector('tbody');
        if (!body) return [];
        const out = [];
        for (const tr of body.querySelectorAll('tr')) {
            if (tr.classList.contains('thead')) continue;
            const rankCell = tr.querySelector('th[data-stat="ranker"]');
            const get = (stat) => {
                const td = tr.querySelector(`td[data-stat="${stat}"]`);
                return td ? td.innerText.trim() : '';
            };
            const playerCell = tr.querySelector('td[data-stat="player"]');
            const playerLink = playerCell ? playerCell.querySelector('a') : null;
            const playerHref = playerLink ? playerLink.getAttribute('href') : '';
            out.push({
                rank: rankCell ? rankCell.innerText.trim() : '',
                player_id: playerHref ? playerHref.split('/').pop().replace('.htm', '') : '',
                player_name: playerCell ? playerCell.innerText.trim() : '',
                pos: get('pos'),
                team: get('team'),
                votes: get('votes'),
                share: get('share'),
                tackles_solo: get('tackles_solo'),
                tackles_ast: get('tackles_assists'),
                sacks: get('sacks'),
                def_int: get('def_int'),
                def_int_yds: get('def_int_yds'),
                def_int_td: get('def_int_td'),
            });
        }
        return out;
    }""")
    return rows or []


# ── output writers ───────────────────────────────────────────────────────

def append_rows(season: int, rows: list[dict]):
    write_header = not OUTPUT_CSV.exists()
    with open(OUTPUT_CSV, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow({
                "season": season,
                "dpoy_voting_rank": r["rank"],
                "player_id": r["player_id"],
                "player_name": r["player_name"],
                "pos": r["pos"],
                "team": r["team"],
                "votes": r["votes"],
                "share_pct": r["share"].replace("%", ""),
                "tackles_solo": r["tackles_solo"],
                "tackles_ast": r["tackles_ast"],
                "sacks": r["sacks"],
                "def_int": r["def_int"],
                "def_int_yds": r["def_int_yds"],
                "def_int_td": r["def_int_td"],
            })


def log_error(season: int, reason: str):
    write_header = not ERROR_CSV.exists()
    with open(ERROR_CSV, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=ERROR_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerow({"season": season, "reason": reason})


def log_progress(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as fh:
        fh.write(line + "\n")


# ── browser launch (same pattern as scrape_team_schemes.py) ────────────────

def _launch_browser(pw, tmp_profile: Path):
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
        log_progress("Homepage still shows Cloudflare challenge -- waiting 20s and rechecking...")
        time.sleep(20)
        if "moment" in pg.title().lower():
            log_progress(
                "WARNING: Cloudflare challenge persists.  "
                "Visit PFR in Brave to refresh cookies, then rerun."
            )
            ctx.close()
            sys.exit(1)
    log_progress("Clearance confirmed.")
    return ctx, pg


def _is_browser_closed_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "browser has been closed" in msg or "target page, context or browser" in msg


def parse_seasons_arg(arg: str) -> list[int]:
    if "-" in arg and "," not in arg:
        lo, hi = arg.split("-")
        return list(range(int(lo), int(hi) + 1))
    return [int(y.strip()) for y in arg.split(",")]


# ── main ─────────────────────────────────────────────────────────────────

def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", help="Range 'YYYY-YYYY' or 'YYYY,YYYY,...'")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test", type=int, metavar="N")
    ap.add_argument("--retry-errors", action="store_true")
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    seasons = list(range(SEASON_MIN, SEASON_MAX + 1))
    if args.seasons:
        seasons = parse_seasons_arg(args.seasons)

    scraped = load_scraped_seasons()
    errored = load_error_seasons() if not args.retry_errors else set()
    pending = [s for s in seasons if s not in scraped and s not in errored]

    log_progress(
        f"Scope: {len(seasons)} seasons | Already done: {len(seasons) - len(pending)} | "
        f"Pending: {len(pending)} | dry_run={args.dry_run}"
    )

    if args.dry_run:
        for s in pending:
            print(f"  DRY: {BASE_URL}/awards/awards_{s}.htm")
        return

    from playwright.sync_api import sync_playwright

    tmp_root = Path(tempfile.mkdtemp())
    tmp_profile = tmp_root / "brave-pfr-dpoy"
    fetch_count = 0
    written_seasons = 0

    with sync_playwright() as pw:
        context, page = _launch_browser(pw, tmp_profile)
        try:
            for season in pending:
                url = f"{BASE_URL}/awards/awards_{season}.htm"
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(3)
                    status = resp.status if resp else 0
                    title = page.title()

                    if "moment" in title.lower():
                        log_progress(f"CLOUDFLARE CHALLENGE at {season}. Waiting 20s...")
                        time.sleep(20)
                        title = page.title()
                        if "moment" in title.lower():
                            log_progress(f"  Still blocked, retrying once more after 30s...")
                            time.sleep(30)
                            page.goto(url, wait_until="domcontentloaded", timeout=25000)
                            time.sleep(3)
                            title = page.title()
                        if "moment" in title.lower():
                            log_error(season, "cloudflare_block")
                            log_progress(f"  Still blocked. Skipping {season}.")
                            fetch_count += 1
                            if args.test and fetch_count >= args.test:
                                break
                            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                            continue

                    if status == 404:
                        log_error(season, "404_not_found")
                        log_progress(f"  404 {season}")
                        fetch_count += 1
                        if args.test and fetch_count >= args.test:
                            break
                        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                        continue

                except Exception as e:
                    if _is_browser_closed_error(e):
                        log_progress("Browser closed -- relaunching...")
                        try:
                            context.close()
                        except Exception:
                            pass
                        context, page = _launch_browser(pw, tmp_profile)
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=25000)
                            time.sleep(3)
                        except Exception as e2:
                            log_error(season, str(e2)[:120])
                            fetch_count += 1
                            if args.test and fetch_count >= args.test:
                                break
                            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                            continue
                    else:
                        log_error(season, str(e)[:120])
                        log_progress(f"  ERROR {season}: {e}")
                        fetch_count += 1
                        if args.test and fetch_count >= args.test:
                            break
                        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                        continue

                rows = parse_dpoy_table(page)
                if not rows:
                    log_error(season, "no_dpoy_table_or_empty")
                    log_progress(f"  {season}: no voting_apdpoy rows found (real gap or structure surprise -- check by hand)")
                else:
                    append_rows(season, rows)
                    written_seasons += 1
                    log_progress(f"  {season}: {len(rows)} DPOY voting rows written (top: {rows[0]['player_name']})")

                fetch_count += 1
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

    log_progress(f"Run complete. Fetched: {fetch_count}  Seasons written: {written_seasons}")


if __name__ == "__main__":
    main()
