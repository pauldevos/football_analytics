#!/usr/bin/env python3
"""
Scrape per-player defensive game stats from PFR boxscore pages.

Source : https://www.pro-football-reference.com/boxscores/{game_id}.htm
Table  : #player_defense  (Int / Sacks / Tackles / Fumbles)
Output : /Users/devos/data/pfref/boxscore-defense/defense_game_{year}.csv

Uses Playwright + the real Brave browser binary to bypass Cloudflare.
Cloudflare's JS challenge requires a real browser fingerprint — curl_cffi
cookie reuse no longer works as of mid-2026.  Running the actual Brave
executable via Playwright's CDP passes the challenge transparently.

NOTE: This opens a visible Brave browser window while running.  Keep it
open; closing it will terminate the scrape.  The window can be minimized.

Rate   : 4–7 s between requests (~600–900 games / hr)
Resume : already-scraped game_ids are skipped automatically
Errors : logged to <output_dir>/scrape_errors.csv — rerun to retry

Season order (default): newest first, descending to fill history.
Total scope: ~15,444 regular-season games ≈ 19–26 hours full run.

Usage:
  python scripts/scrape_defense_gamelogs.py                  # all seasons, newest first
  python scripts/scrape_defense_gamelogs.py --seasons 1985-1998   # Reggie White era
  python scripts/scrape_defense_gamelogs.py --seasons 1988,1993   # specific years
  python scripts/scrape_defense_gamelogs.py --dry-run        # print URLs, no fetch
  python scripts/scrape_defense_gamelogs.py --test 3         # first 3 games then stop

Environment:
  PFR_DELAY_MIN   float seconds (default 4.0)
  PFR_DELAY_MAX   float seconds (default 7.0)
  BRAVE_PATH      override Brave executable path
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

# ── paths ─────────────────────────────────────────────────────────────────────

GAMELOG_DIR  = Path("/Users/devos/data/pfref/raw/season/gamelogs")
BOXSCORE_DIR = Path("/Users/devos/data/pfref/raw/boxscores")
OUTPUT_DIR   = Path("/Users/devos/data/pfref/boxscore-defense")
BASE_URL     = "https://www.pro-football-reference.com"

BRAVE_PATH   = os.environ.get(
    "BRAVE_PATH",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)
DELAY_MIN = float(os.environ.get("PFR_DELAY_MIN", "4.0"))
DELAY_MAX = float(os.environ.get("PFR_DELAY_MAX", "7.0"))

OUTPUT_FIELDS = [
    "game_id", "season", "player_link", "player_name", "team",
    "def_int", "int_yds", "int_td", "int_lng",
    "sacks",
    "comb_tackles", "solo_tackles", "ast_tackles",
    "fumble_rec", "fr_yds", "fr_td", "forced_fumbles",
]

# ── regular-season game detection (count-based, same as etl_oqa_boxscores) ───

def _num_teams(season: int) -> int:
    if season >= 2002: return 32
    if season >= 1999: return 31
    if season >= 1995: return 30
    if season >= 1976: return 28
    if season >= 1970: return 26
    return 26

def _games_per_team(season: int) -> int:
    if season >= 2021: return 17
    if season >= 1978: return 16
    return 14

def regular_season_game_ids(season: int) -> list[str]:
    """Return regular-season game_ids in chronological order."""
    season_dir = BOXSCORE_DIR / str(season)
    if season_dir.is_dir():
        files = sorted(season_dir.glob("*.csv"), key=lambda f: f.name[:8])
        rs_n  = _num_teams(season) * _games_per_team(season) // 2
        return [f.stem for f in files[:rs_n]]

    log_path = GAMELOG_DIR / f"gamelogs_{season}.csv"
    if log_path.exists():
        with open(log_path) as fh:
            urls = [r["game_url"] for r in csv.DictReader(fh)]
        ids = []
        for u in urls:
            m = re.search(r"/boxscores/(\w+)\.htm", u)
            if m:
                ids.append(m.group(1))
        ids.sort(key=lambda x: x[:8])
        rs_n = _num_teams(season) * _games_per_team(season) // 2
        return ids[:rs_n]

    return []


# ── resume / error tracking ───────────────────────────────────────────────────

def load_scraped_ids(season: int) -> set:
    path = OUTPUT_DIR / f"defense_game_{season}.csv"
    if not path.exists():
        return set()
    with open(path) as fh:
        return {r["game_id"] for r in csv.DictReader(fh) if r.get("game_id")}

def load_error_ids() -> set:
    path = OUTPUT_DIR / "scrape_errors.csv"
    if not path.exists():
        return set()
    with open(path) as fh:
        return {r["game_id"] for r in csv.DictReader(fh) if r.get("game_id")}


# ── Playwright page parsing ───────────────────────────────────────────────────

def parse_defense_table(page, game_id: str, season: int) -> list[dict]:
    """
    Extract per-player rows from the #player_defense table via Playwright.
    JavaScript has already rendered the page, so no comment-stripping needed.
    """
    rows_js = page.evaluate(r"""() => {
        const tbl = document.getElementById('player_defense');
        if (!tbl) return null;
        const tbody = tbl.querySelector('tbody');
        if (!tbody) return null;

        function cell(row, stat) {
            const td = row.querySelector('[data-stat="' + stat + '"]');
            return td ? td.innerText.trim() : '';
        }

        const results = [];
        for (const tr of tbody.querySelectorAll('tr')) {
            // skip divider / sub-header rows
            if (tr.classList.contains('thead') || tr.classList.contains('divider')) continue;

            const playerTd = tr.querySelector('[data-stat="player"]');
            if (!playerTd) continue;
            const name = playerTd.innerText.trim();
            if (!name) continue;

            const a = playerTd.querySelector('a');
            results.push({
                player_link:    a ? a.getAttribute('href') : '',
                player_name:    name,
                team:           (cell(tr, 'team') || cell(tr, 'team_id')).toUpperCase(),
                def_int:        cell(tr, 'def_int'),
                int_yds:        cell(tr, 'def_int_yds'),
                int_td:         cell(tr, 'def_int_td'),
                int_lng:        cell(tr, 'def_int_long'),
                sacks:          cell(tr, 'sacks'),
                comb_tackles:   cell(tr, 'tackles_combined'),
                solo_tackles:   cell(tr, 'tackles_solo'),
                ast_tackles:    cell(tr, 'tackles_assists'),
                fumble_rec:     cell(tr, 'fumbles_rec'),
                fr_yds:         cell(tr, 'fumbles_rec_yds'),
                fr_td:          cell(tr, 'fumbles_rec_td'),
                forced_fumbles: cell(tr, 'fumbles_forced'),
            });
        }
        return results;
    }""")

    if not rows_js:
        return []

    return [{**r, "game_id": game_id, "season": season} for r in rows_js]


# ── output writers ────────────────────────────────────────────────────────────

def append_rows(season: int, rows: list[dict]):
    path         = OUTPUT_DIR / f"defense_game_{season}.csv"
    write_header = not path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerows(rows)

def log_error(game_id: str, season: int, reason: str):
    path         = OUTPUT_DIR / "scrape_errors.csv"
    write_header = not path.exists()
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["game_id", "season", "reason"])
        if write_header:
            w.writeheader()
        w.writerow({"game_id": game_id, "season": season, "reason": reason})

def log_progress(msg: str):
    ts   = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(OUTPUT_DIR / "scrape_progress.log", "a") as fh:
        fh.write(line + "\n")


# ── season ordering ───────────────────────────────────────────────────────────

def season_priority_order(available: list[int]) -> list[int]:
    return sorted(available, reverse=True)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_seasons_arg(arg: str, available: list[int]) -> list[int]:
    if "-" in arg and "," not in arg:
        lo, hi = arg.split("-")
        return [y for y in available if int(lo) <= y <= int(hi)]
    return [int(y.strip()) for y in arg.split(",")]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons",       help="range 'YYYY-YYYY' or 'YYYY,YYYY,...'")
    ap.add_argument("--dry-run",       action="store_true")
    ap.add_argument("--test",          type=int, metavar="N", help="stop after N fetches")
    ap.add_argument("--retry-errors",  action="store_true", help="retry previously errored games")
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    available = sorted(
        int(p.stem.split("_")[1]) for p in GAMELOG_DIR.glob("gamelogs_*.csv")
    )

    if args.seasons:
        seasons = parse_seasons_arg(args.seasons, available)
    else:
        seasons = season_priority_order(available)

    error_ids = load_error_ids() if not args.retry_errors else set()

    fetch_count   = 0
    total_written = 0

    log_progress(
        f"Starting: {len(seasons)} seasons, delay {DELAY_MIN}-{DELAY_MAX}s, "
        f"dry_run={args.dry_run}"
    )

    if args.dry_run:
        for season in seasons:
            game_ids = regular_season_game_ids(season)
            scraped  = load_scraped_ids(season)
            pending  = [g for g in game_ids if g not in scraped and g not in error_ids]
            for game_id in pending:
                print(f"  DRY: {BASE_URL}/boxscores/{game_id}.htm")
                fetch_count += 1
                if args.test and fetch_count >= args.test:
                    return
        return

    # ── launch Playwright + Brave (using real profile for Cloudflare clearance) ──
    from playwright.sync_api import sync_playwright

    brave_src   = Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser"
    tmp_root    = Path(tempfile.mkdtemp())
    tmp_profile = tmp_root / "brave-pfr"

    log_progress("Copying Brave profile (cookies + fingerprint) to temp dir...")
    shutil.copytree(
        str(brave_src / "Default"), str(tmp_profile / "Default"),
        ignore=shutil.ignore_patterns("*.log", "Cache", "Cache *", "Code Cache", "GPUCache", "Service Worker"),
    )
    shutil.copy2(str(brave_src / "Local State"), str(tmp_profile / "Local State"))
    log_progress("Profile copied. Launching browser.")

    def _launch(pw):
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(tmp_profile),
            executable_path=BRAVE_PATH,
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run",
                  "--no-default-browser-check"],
        )
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        log_progress("Visiting PFR homepage to verify Cloudflare clearance...")
        pg.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=20000)
        time.sleep(4)
        if "moment" in pg.title().lower():
            log_progress("WARNING: Cloudflare challenge. Visit PFR in Brave to refresh cookies, then rerun.")
            ctx.close()
            shutil.rmtree(str(tmp_root), ignore_errors=True)
            sys.exit(1)
        log_progress("Clearance confirmed.")
        return ctx, pg

    def _is_browser_closed_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "browser has been closed" in msg or "target page, context or browser" in msg

    with sync_playwright() as pw:
        context, page = _launch(pw)

        for season in seasons:
            game_ids = regular_season_game_ids(season)
            scraped  = load_scraped_ids(season)
            pending  = [g for g in game_ids if g not in scraped and g not in error_ids]

            if not pending:
                continue

            log_progress(
                f"Season {season}: {len(pending)} pending / {len(scraped)} already done"
            )

            season_written = 0
            for game_id in pending:
                url = f"{BASE_URL}/boxscores/{game_id}.htm"

                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    time.sleep(3)
                    status = resp.status if resp else 0

                    title = page.title()
                    if "moment" in title.lower():
                        log_progress(f"CLOUDFLARE CHALLENGE at {game_id}. Waiting 20s...")
                        time.sleep(20)
                        title = page.title()
                        if "moment" in title.lower():
                            log_error(game_id, season, "cloudflare_block")
                            log_progress(f"  Still blocked. Skipping {game_id}.")
                            fetch_count += 1
                            if args.test and fetch_count >= args.test:
                                context.close()
                                return
                            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                            continue

                    if status == 404:
                        log_error(game_id, season, "http_404")
                        fetch_count += 1
                        if args.test and fetch_count >= args.test:
                            context.close()
                            return
                        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                        continue

                except Exception as e:
                    if _is_browser_closed_error(e):
                        log_progress("Browser was closed — relaunching automatically...")
                        try:
                            context.close()
                        except Exception:
                            pass
                        context, page = _launch(pw)
                        # Retry this game once with the fresh browser
                        try:
                            resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
                            time.sleep(3)
                        except Exception as e2:
                            log_error(game_id, season, str(e2)[:120])
                            log_progress(f"  RETRY FAILED {game_id}: {e2}")
                            fetch_count += 1
                            if args.test and fetch_count >= args.test:
                                context.close()
                                return
                            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                            continue
                    else:
                        log_error(game_id, season, str(e)[:120])
                        log_progress(f"  ERROR {game_id}: {e}")
                        fetch_count += 1
                        if args.test and fetch_count >= args.test:
                            context.close()
                            return
                        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                        continue

                rows = parse_defense_table(page, game_id, season)

                if rows:
                    append_rows(season, rows)
                    season_written += 1
                    total_written  += 1
                else:
                    log_error(game_id, season, "no_player_defense_table")
                    log_progress(f"  NO TABLE {game_id}")

                fetch_count += 1
                if fetch_count % 50 == 0:
                    log_progress(
                        f"  Progress: {total_written} rows written this run  "
                        f"(current season {season}: {season_written}/{len(pending)})"
                    )

                if args.test and fetch_count >= args.test:
                    log_progress(f"--test limit ({args.test}) reached; stopping.")
                    context.close()
                    return

                time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

            if season_written:
                log_progress(
                    f"  Season {season} done: {season_written} games  "
                    f"(total this run: {total_written})"
                )

        log_progress(f"Run complete. Total written: {total_written} games.")
        context.close()

    shutil.rmtree(str(tmp_root), ignore_errors=True)


if __name__ == "__main__":
    main()
