#!/usr/bin/env python3
"""
ETL: Defense-facing flip of the RB carry-adjusted OQA (see docs/offensive_oqa_framework.md,
Q15 in docs/open_questions.md). That framework asks: given how good a defense normally is,
how much did this RB outperform it? This script asks the mirror question at the defense
level: given the volume and QUALITY (their own leave-one-out season YPC) of the rushers a
defense actually faced, how many rush yards should it have allowed, and how does that
compare to what it actually allowed?

This directly answers a strength-of-schedule question: a defense allowing 90 rush yds/gm
against a slate of backup-caliber backs is not obviously better than one allowing 125 yds/gm
against a slate of elite backs.

Naive version (rejected, same lesson as the offensive Q15 fix): comparing a defense's rush
yards allowed to the league average, or to a flat per-team-game average, ignores WHO they
actually faced and how much volume that back got. The correct version credits each opposing
rusher's OWN season leave-one-out YPC (excluding the game in question, to avoid circularity)
for the carries they got against this specific defense:

  expected_rush_yds_allowed(defense, season) =
      SUM over games g of defense's season of
        SUM over opposing rushers r in g of
          ( r's rush_att in g ) x ( r's own season YPC, from all OTHER games that season,
                                    i.e. leave-one-out )

  delta = actual_rush_yds_allowed - expected_rush_yds_allowed
  Negative delta = defense allowed FEWER yards than the quality/volume of what it faced
                   would predict = good defense given its schedule.
  Positive delta = allowed more than expected = bad defense given its schedule.

Data source note: `etl_player_game_offense.py`'s own file-discovery logic (BOXSCORE_DIR /
{season}/*.csv, one flat combined file per game) targets a raw pfref layout that has since
been reorganized into per-game subdirectories (BOXSCORE_DIR/{season}/{game_id}/player_offense.csv,
team_stats.csv, ...) — the same current layout scripts/build_game_defense.py reads. Rather than
trust the already-materialized (and now stale relative to that reorg) data_output/
player_game_offense_{season}.csv files, this script reads player_offense.csv directly per game
and applies the identical carry/attempt-level LOO-YPC methodology proven in
etl_player_game_offense.py (docs/offensive_oqa_framework.md Q15) — same idea, current data
source. `actual_rush_yds_allowed` is the sum of individual rush_yds across all rushers listed
for the offense in player_offense.csv for that game, matching how the original script itself
computed team-level rush totals (never touching team_stats.csv's aggregate row either) — this
can run a few yards under the official PFR box score total on games with an unattributed
"Team" rushing line (e.g. a kneel-down), a known, minor, and accepted approximation.

Outputs (in data_output/):
  defense_rush_oqa_{season}.csv   — one row per defense-team-season
  defense_rush_oqa_allseasons.csv — every season processed, concatenated, for convenience

Usage:
  python scripts/etl_defense_expected_rush.py                # all seasons found under BOXSCORE_DIR
  python scripts/etl_defense_expected_rush.py --season 2008
  python scripts/etl_defense_expected_rush.py --season 2007 --season 2008 --season 2009
"""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import etl_player_game_offense as epgo  # reuse _num_teams / _games_per_team era tables only

PFREF        = Path.home() / "data" / "pfref"
BOXSCORE_DIR = PFREF / "raw" / "boxscores"
OUTPUT_DIR   = Path(__file__).parent.parent / "data_output"


def safe_int(v, default=0):
    try:
        return int(float(v)) if v not in ('', None) else default
    except (ValueError, TypeError):
        return default


def regular_season_game_dirs(season: int) -> list[Path]:
    """First N game dirs (sorted chronologically by game_id, which starts YYYYMMDD)
    where N = teams * games_per_team // 2, matching etl_player_game_offense.py's own
    regular-season slicing logic (same era tables) but against the current per-game
    directory layout."""
    season_dir = BOXSCORE_DIR / str(season)
    if not season_dir.is_dir():
        return []
    dirs = sorted((d for d in season_dir.iterdir() if d.is_dir()), key=lambda d: d.name[:8])
    rs_count = epgo._num_teams(season) * epgo._games_per_team(season) // 2
    return dirs[:rs_count]


def load_game_rushers(game_dir: Path) -> list[dict]:
    """One row per rusher (any position) with rush_att > 0 in this game."""
    f = game_dir / "player_offense.csv"
    if not f.exists():
        return []
    out = []
    with open(f) as fh:
        for r in csv.DictReader(fh):
            att = safe_int(r.get('rush_att'))
            if att <= 0:
                continue
            out.append({
                'game_id':       r.get('game_id', game_dir.name),
                'pfr_player_id': r.get('pfr_player_id') or r.get('player', ''),
                'team':          (r.get('team') or '').upper(),
                'rush_att':      att,
                'rush_yds':      safe_int(r.get('rush_yds')),
            })
    return out


def process_season(season: int) -> list[dict]:
    game_dirs = regular_season_game_dirs(season)
    if not game_dirs:
        return []

    # game_id -> {team -> {'att':, 'yds':}}   (per-game team rushing, from summed player rows)
    game_team_totals: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {'att': 0, 'yds': 0}))
    # all rusher rows, kept for per-player LOO computation
    all_rows: list[dict] = []

    for gd in game_dirs:
        rows = load_game_rushers(gd)
        if not rows:
            continue
        game_id = rows[0]['game_id']
        for r in rows:
            gt = game_team_totals[game_id][r['team']]
            gt['att'] += r['rush_att']
            gt['yds'] += r['rush_yds']
        all_rows.extend(rows)

    if not all_rows:
        return []

    # ── player-season rushing totals, for LOO YPC ──────────────────────────
    totals_by_player = defaultdict(lambda: {'att': 0, 'yds': 0})
    for r in all_rows:
        key = (r['pfr_player_id'], r['team'])
        totals_by_player[key]['att'] += r['rush_att']
        totals_by_player[key]['yds'] += r['rush_yds']

    # ── team-season rushing totals (own team's LOO fallback for one-off rushers) ──
    totals_by_team = defaultdict(lambda: {'att': 0, 'yds': 0})
    for game_id, teams in game_team_totals.items():
        for team, t in teams.items():
            totals_by_team[team]['att'] += t['att']
            totals_by_team[team]['yds'] += t['yds']

    # ── expected yards per (game_id, offense_team), from individually-attributed
    #    rushers' own LOO YPC ────────────────────────────────────────────────
    expected_by_game_team: dict[tuple, float] = defaultdict(float)
    for r in all_rows:
        pkey = (r['pfr_player_id'], r['team'])
        pt = totals_by_player[pkey]
        loo_att = pt['att'] - r['rush_att']
        loo_yds = pt['yds'] - r['rush_yds']
        if loo_att > 0:
            loo_ypc = loo_yds / loo_att
        else:
            # only game this player rushed in this season — fall back to his
            # team's own season LOO YPC for that game (see module docstring)
            tt = totals_by_team[r['team']]
            gt = game_team_totals[r['game_id']][r['team']]
            t_loo_att = tt['att'] - gt['att']
            t_loo_yds = tt['yds'] - gt['yds']
            loo_ypc = (t_loo_yds / t_loo_att) if t_loo_att > 0 else None
        if loo_ypc is not None:
            expected_by_game_team[(r['game_id'], r['team'])] += r['rush_att'] * loo_ypc

    # ── roll up to defense-season: for each game, each team's expected/actual
    #    rushing production is "allowed" by the OTHER team in that game ──────
    by_defense = defaultdict(lambda: {'games': 0, 'actual': 0.0, 'expected': 0.0})
    for game_id, teams in game_team_totals.items():
        team_codes = list(teams.keys())
        if len(team_codes) != 2:
            continue  # malformed/incomplete game file — skip rather than guess
        for off_team in team_codes:
            def_team = [t for t in team_codes if t != off_team][0]
            actual = teams[off_team]['yds']
            expected = expected_by_game_team.get((game_id, off_team), 0.0)
            d = by_defense[def_team]
            d['games'] += 1
            d['actual'] += actual
            d['expected'] += expected

    rows = []
    for team, d in by_defense.items():
        actual = round(d['actual'], 1)
        expected = round(d['expected'], 1)
        delta = round(actual - expected, 1)
        rows.append({
            'season': season,
            'team': team,
            'games': d['games'],
            'actual_rush_yds_allowed': actual,
            'expected_rush_yds_allowed': expected,
            'delta': delta,
            'delta_per_game': round(delta / d['games'], 2) if d['games'] else None,
        })

    rows.sort(key=lambda r: r['delta_per_game'])
    for i, r in enumerate(rows, start=1):
        r['rank_best_to_worst'] = i

    return rows


FIELDS = [
    'season', 'team', 'games', 'actual_rush_yds_allowed', 'expected_rush_yds_allowed',
    'delta', 'delta_per_game', 'rank_best_to_worst',
]


def write_csv(rows, path: Path):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {len(rows):,} rows -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, action='append', help='process only these seasons (repeatable)')
    args = ap.parse_args()

    if args.season:
        seasons = sorted(set(args.season))
    else:
        seasons = sorted(int(p.name) for p in BOXSCORE_DIR.iterdir() if p.is_dir() and p.name.isdigit())

    all_rows = []
    for season in seasons:
        print(f"\n-- {season} --")
        rows = process_season(season)
        if not rows:
            print("  (no data)")
            continue
        write_csv(rows, OUTPUT_DIR / f"defense_rush_oqa_{season}.csv")
        all_rows.extend(rows)

    if all_rows:
        write_csv(all_rows, OUTPUT_DIR / "defense_rush_oqa_allseasons.csv")


if __name__ == '__main__':
    main()
