#!/usr/bin/env python3
"""
Scrape job monitor — shows progress across all seasons.

Usage:
    python scripts/scrape_status.py           # summary table
    python scripts/scrape_status.py --errors  # also list error game IDs
    python scripts/scrape_status.py --watch   # refresh every 30s (Ctrl+C to stop)
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from pathlib import Path

MANIFEST_DIR  = Path.home() / "data" / "pfref" / "manifest"
GAMELOGS_DIR  = Path.home() / "data" / "pfref" / "raw" / "season" / "gamelogs"
SCRAPER_MODULE = "ingestion.boxscores.scrape_all_tables"

# ANSI colours
_GRN  = "\033[32m"
_YLW  = "\033[33m"
_RED  = "\033[31m"
_DIM  = "\033[2m"
_BOLD = "\033[1m"
_RST  = "\033[0m"

def _colour(text, code):
    return f"{code}{text}{_RST}" if sys.stdout.isatty() else str(text)


def scraper_pid() -> int | None:
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", SCRAPER_MODULE], text=True
        ).strip()
        return int(out.split()[0]) if out else None
    except subprocess.CalledProcessError:
        return None


def gamelog_counts() -> dict[int, int]:
    """Return {year: game_count} from gamelog CSV files."""
    counts: dict[int, int] = {}
    for p in GAMELOGS_DIR.glob("gamelogs_*.csv"):
        year = int(p.stem.split("_")[1])
        with open(p) as f:
            counts[year] = sum(1 for line in f) - 1  # exclude header
    return counts


def manifest_stats() -> dict[int, dict]:
    """Return {year: {total, errors, [error_ids]}} from manifest CSVs."""
    stats: dict[int, dict] = {}
    for p in MANIFEST_DIR.glob("page_manifest_*.csv"):
        year = int(p.stem.split("_")[2])
        total = 0
        errors: list[str] = []
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                total += 1
                err = row.get("error", "").strip()
                if err:
                    errors.append((row["game_id"], err[:60]))
        stats[year] = {"total": total, "errors": errors}
    return stats


def print_status(show_errors: bool = False) -> None:
    pid    = scraper_pid()
    glogs  = gamelog_counts()
    mstats = manifest_stats()

    all_years = sorted(set(list(glogs.keys()) + list(mstats.keys())), reverse=True)

    # Header
    running_label = (
        _colour(f"  RUNNING (pid {pid})", _GRN) if pid
        else _colour("  not running", _DIM)
    )
    print(f"\n{_BOLD}Boxscore scrape status{_RST}{running_label}")
    print(f"{'─'*62}")
    print(f"  {'Year':<6} {'Scraped':>8} {'Expected':>9} {'Pct':>6}  {'Errors':>7}  {'Status'}")
    print(f"{'─'*62}")

    total_scraped = total_expected = total_errors = 0

    for year in all_years:
        expected = glogs.get(year, 0)
        ms       = mstats.get(year, {})
        scraped  = ms.get("total", 0)
        errs     = ms.get("errors", [])
        n_err    = len(errs)

        pct = (scraped / expected * 100) if expected else 0

        if scraped == 0:
            status = _colour("pending", _DIM)
        elif scraped >= expected and n_err == 0:
            status = _colour("done", _GRN)
        elif scraped >= expected and n_err > 0:
            status = _colour(f"done ({n_err} err)", _YLW)
        else:
            status = _colour(f"in progress", _YLW)

        err_str = _colour(str(n_err), _RED) if n_err else _colour("0", _DIM)

        print(f"  {year:<6} {scraped:>8,} {expected:>9,} {pct:>5.0f}%  {err_str:>7}  {status}")

        total_scraped   += scraped
        total_expected  += expected
        total_errors    += n_err

    print(f"{'─'*62}")
    overall_pct = (total_scraped / total_expected * 100) if total_expected else 0
    err_total_str = _colour(str(total_errors), _RED) if total_errors else "0"
    print(f"  {'TOTAL':<6} {total_scraped:>8,} {total_expected:>9,} {overall_pct:>5.0f}%  {err_total_str:>7}")
    print()

    if show_errors and total_errors:
        print(f"{_BOLD}Errors:{_RST}")
        for year in all_years:
            errs = mstats.get(year, {}).get("errors", [])
            for game_id, msg in errs:
                print(f"  {year}  {game_id}  {_colour(msg, _DIM)}")
        print()


def main():
    ap = argparse.ArgumentParser(description="Monitor PFR boxscore scrape progress.")
    ap.add_argument("--errors", action="store_true", help="Show error game IDs")
    ap.add_argument("--watch",  action="store_true", help="Refresh every 30s")
    args = ap.parse_args()

    if args.watch:
        try:
            while True:
                os.system("clear")
                print_status(show_errors=args.errors)
                print(_colour("  Refreshing every 30s — Ctrl+C to stop", _DIM))
                time.sleep(30)
        except KeyboardInterrupt:
            print()
    else:
        print_status(show_errors=args.errors)


if __name__ == "__main__":
    main()
