#!/usr/bin/env python3
"""
Live monitor for scrape_game_starters.py progress.

Queries the DB every N seconds and prints a running summary:
  - Games scraped so far (starters rows → distinct game_ids)
  - Breakdown by decade
  - PBP sack rows written
  - Snap count rows written
  - Rate (games/hour)

Usage:
  python scripts/monitor_scrape.py           # refresh every 30s
  python scripts/monitor_scrape.py --interval 10
  python scripts/monitor_scrape.py --once    # print once and exit
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import get_engine
from sqlalchemy import text

CLEAR = "\033[2J\033[H"   # clear screen + move cursor to top


def fetch_stats(engine) -> dict:
    with engine.connect() as conn:
        # Games scraped (distinct game_ids in game_starters)
        r = conn.execute(text(
            "SELECT COUNT(DISTINCT game_id) FROM game_starters"
        ))
        games_total = r.scalar() or 0

        # Starter rows total
        r = conn.execute(text("SELECT COUNT(*) FROM game_starters"))
        starter_rows = r.scalar() or 0

        # Snap count rows
        r = conn.execute(text("SELECT COUNT(*) FROM player_snap_counts"))
        snap_rows = r.scalar() or 0

        # PBP sack rows
        r = conn.execute(text("SELECT COUNT(*) FROM play_by_play_sacks"))
        sack_rows = r.scalar() or 0

        # Games per decade (extract year from game_id prefix YYYYMMDD...)
        r = conn.execute(text("""
            SELECT
                CAST(SUBSTR(game_id, 1, 3) AS INTEGER) * 10 AS decade,
                COUNT(DISTINCT game_id) AS games
            FROM game_starters
            GROUP BY 1
            ORDER BY 1
        """))
        by_decade = {str(row[0]) + "s": row[1] for row in r}

        # Season breakdown (last 5 seasons with data)
        r = conn.execute(text("""
            SELECT
                SUBSTR(game_id, 1, 4) AS season,
                COUNT(DISTINCT game_id) AS games,
                COUNT(*) AS starter_rows
            FROM game_starters
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 8
        """))
        recent = [(row[0], row[1], row[2]) for row in r]

        # Most recently scraped game
        r = conn.execute(text("""
            SELECT game_id FROM game_starters
            ORDER BY rowid DESC LIMIT 1
        """))
        last_game = r.scalar()

        # PBP sacks by season (top seasons)
        r = conn.execute(text("""
            SELECT
                SUBSTR(game_id, 1, 4) AS season,
                COUNT(DISTINCT game_id) AS games_with_sacks,
                COUNT(*) AS sack_rows
            FROM play_by_play_sacks
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 5
        """))
        sack_by_season = [(row[0], row[1], row[2]) for row in r]

    return {
        "games_total":   games_total,
        "starter_rows":  starter_rows,
        "snap_rows":     snap_rows,
        "sack_rows":     sack_rows,
        "by_decade":     by_decade,
        "recent":        recent,
        "last_game":     last_game,
        "sack_by_season": sack_by_season,
    }


def render(stats: dict, start_time: float, prev_games: int) -> None:
    now    = datetime.now().strftime("%H:%M:%S")
    elapsed = time.time() - start_time
    delta  = stats["games_total"] - prev_games

    rate_hr = (stats["games_total"] / elapsed * 3600) if elapsed > 0 else 0

    print(f"{'='*58}")
    print(f"  PFR Scraper Monitor   {now}")
    print(f"{'='*58}")
    print(f"  Games scraped:     {stats['games_total']:>6,}")
    print(f"  Starter rows:      {stats['starter_rows']:>6,}")
    print(f"  Snap count rows:   {stats['snap_rows']:>6,}")
    print(f"  PBP sack rows:     {stats['sack_rows']:>6,}")
    print(f"  Rate:              {rate_hr:>6.0f} games/hr")
    print(f"  Last game:         {stats['last_game'] or '—'}")
    print()

    if stats["by_decade"]:
        print("  Games by decade:")
        for decade, cnt in sorted(stats["by_decade"].items()):
            bar = "█" * min(cnt // 10, 30)
            print(f"    {decade}  {bar} {cnt:,}")
        print()

    if stats["recent"]:
        print("  Recent seasons (newest first):")
        print(f"    {'Season':<8} {'Games':>6}  {'Starter rows':>12}")
        for season, games, rows in stats["recent"]:
            print(f"    {season:<8} {games:>6,}  {rows:>12,}")
        print()

    if stats["sack_by_season"]:
        print("  PBP sacks (newest seasons):")
        print(f"    {'Season':<8} {'Games w/ sacks':>14}  {'Sack rows':>10}")
        for season, gwsacks, srows in stats["sack_by_season"]:
            print(f"    {season:<8} {gwsacks:>14,}  {srows:>10,}")
        print()

    print(f"{'='*58}")


def main():
    ap = argparse.ArgumentParser(description="Monitor scrape_game_starters progress")
    ap.add_argument("--interval", type=int, default=30, help="Refresh interval in seconds")
    ap.add_argument("--once", action="store_true", help="Print once and exit")
    args = ap.parse_args()

    engine     = get_engine()
    start_time = time.time()
    prev_games = 0

    while True:
        try:
            stats = fetch_stats(engine)
        except Exception as e:
            print(f"DB error: {e}")
            time.sleep(5)
            continue

        if not args.once:
            print(CLEAR, end="")

        render(stats, start_time, prev_games)
        prev_games = stats["games_total"]

        if args.once:
            break

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
