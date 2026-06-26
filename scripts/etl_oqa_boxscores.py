#!/usr/bin/env python3
"""
ETL: Boxscore CSVs → per-game offensive stats + leave-one-out OQA deltas.

Populates:
  team_game_offense  — what each offense actually did per game (regular season only)
  oqa_game_detail    — delta: actual vs. opponent's season-avg (leave-one-out)

Playoff games are EXCLUDED from both the LOO averages and the output.
Playoff detection: count-based — first (num_teams × games_per_team / 2) game files
by date are regular season; the rest are playoffs.

Fumbles: 2021+ boxscore CSVs contain fumble_lost (offensive fumbles recovered by defense).
Pre-2021: off_fumbles_lost = None until defense game logs are scraped and joined.

Usage:
  python scripts/etl_oqa_boxscores.py                        # all seasons
  python scripts/etl_oqa_boxscores.py --season 1988          # one season
  python scripts/etl_oqa_boxscores.py --season 1988 --qa-team PHI
"""

import argparse
import csv
import glob
import sys
from collections import defaultdict
from pathlib import Path

PFREF        = Path("/Users/devos/data/pfref")
BOXSCORE_DIR = PFREF / "raw" / "boxscores"
ROSTER_DIR   = PFREF / "raw" / "season" / "rosters"
OUTPUT_DIR   = Path(__file__).parent.parent / "data_output"

# Offensive position → receiving group
RB_POS = {'RB', 'FB', 'HB', 'WB', 'B'}
WR_POS = {'WR', 'FL', 'SE', 'E', 'OE'}   # flanker / split end / end (old eras)
TE_POS = {'TE'}

# roster file prefix → additional boxscore team codes for same franchise
# (franchise relocations: boxscore uses city abbrev, roster uses franchise abbrev)
ROSTER_ALIASES: dict[str, list[str]] = {
    'CLT': ['IND', 'BAL'],   # Baltimore/Indianapolis Colts
    'CRD': ['PHO', 'ARI'],   # St. Louis/Phoenix/Arizona Cardinals
    'OTI': ['HOU'],          # Houston Oilers / Tennessee Oilers-Titans
    'RAM': ['STL', 'LAR'],   # Los Angeles/St. Louis/Los Angeles Rams
    'RAI': ['OAK', 'LVR'],   # Oakland/Los Angeles/Las Vegas Raiders
}


# ── helpers ───────────────────────────────────────────────────────────────────

def safe_int(v, default=0):
    try:
        return int(float(v)) if v not in ('', None) else default
    except (ValueError, TypeError):
        return default


def nfl_passer_rating(comp, att, yds, td, ints):
    """NFL passer rating recomputed from raw totals (not an average of per-game rates)."""
    if not att:
        return None
    clamp = lambda x: max(0.0, min(2.375, x))
    a = clamp((comp / att - 0.3) * 5)
    b = clamp((yds / att - 3) * 0.25)
    c = clamp((td / att) * 20)
    d = clamp(2.375 - (ints / att * 25))
    return round((a + b + c + d) / 6 * 100, 1)


def pos_group(pos_str):
    p = (pos_str or '').upper().strip()
    if p in RB_POS: return 'RB'
    if p in WR_POS: return 'WR'
    if p in TE_POS: return 'TE'
    return None


# ── playoff detection (count-based) ──────────────────────────────────────────

def _num_teams(season: int) -> int:
    """Teams in the league for a given season (post-AFL-NFL merger era)."""
    if season >= 2002: return 32
    if season >= 1999: return 31
    if season >= 1995: return 30
    if season >= 1976: return 28
    if season >= 1970: return 26
    return 26  # pre-merger varies; best estimate


def _games_per_team(season: int) -> int:
    if season >= 2021: return 17
    if season >= 1978: return 16
    return 14   # pre-1978 NFL


def get_regular_season_ids(season: int) -> frozenset:
    """
    Return the set of game_id stems that are regular-season games.
    Method: sort all files in the season dir by date prefix; the first
    (num_teams × games_per_team / 2) are regular season, the rest playoffs.
    Works for any era — no hardcoded date cutoffs needed.
    """
    season_dir = BOXSCORE_DIR / str(season)
    if not season_dir.is_dir():
        return frozenset()
    files = sorted(season_dir.glob("*.csv"), key=lambda f: f.name[:8])
    rs_count = _num_teams(season) * _games_per_team(season) // 2
    return frozenset(f.stem for f in files[:rs_count])


# ── roster position lookup ────────────────────────────────────────────────────

def load_season_positions(season: int) -> dict:
    """
    Return {(TEAM, player_name): position_group} for all teams in a season.
    Stores each player under both the roster file prefix AND any boxscore
    alias codes from ROSTER_ALIASES (handles franchise relocations).
    """
    lookup = {}
    for f in glob.glob(str(ROSTER_DIR / f"*_{season}_roster.csv")):
        prefix = Path(f).stem.split('_')[0].upper()
        codes  = {prefix} | set(ROSTER_ALIASES.get(prefix, []))
        try:
            with open(f) as fh:
                for row in csv.DictReader(fh):
                    name = row.get('Player', '').strip()
                    pg   = pos_group(row.get('Pos', ''))
                    if name:
                        for code in codes:
                            lookup[(code, name)] = pg
        except Exception:
            pass
    return lookup


# ── parse one boxscore ────────────────────────────────────────────────────────

def parse_game(filepath: Path, pos_lookup: dict) -> dict:
    """
    Parse one boxscore CSV.
    Returns {team_abbrev: stats_dict} for both teams in the game.
    """
    try:
        rows = list(csv.DictReader(open(filepath)))
    except Exception as e:
        print(f"WARN: could not read {filepath}: {e}", file=sys.stderr)
        return {}
    if not rows:
        return {}

    game_id = rows[0].get('game_id', '')
    season  = safe_int(rows[0].get('season', 0))

    by_team = defaultdict(list)
    for r in rows:
        by_team[r['team'].upper()].append(r)

    result = {}
    for team, team_rows in by_team.items():
        # ── passing ───────────────────────────────────────────────────────────
        qb_rows = [r for r in team_rows if safe_int(r['pass_att']) > 0]
        pass_comp     = sum(safe_int(r['pass_comp']) for r in qb_rows)
        pass_att      = sum(safe_int(r['pass_att'])  for r in qb_rows)
        pass_yds      = sum(safe_int(r['pass_yds'])  for r in qb_rows)
        pass_td       = sum(safe_int(r['pass_td'])   for r in qb_rows)
        pass_int      = sum(safe_int(r['pass_int'])  for r in qb_rows)
        sacks_taken   = sum(safe_int(r['sacked'])    for r in team_rows)
        sack_yds_lost = sum(safe_int(r.get('sack_yds_lost', 0)) for r in team_rows)
        comp_pct      = round(pass_comp / pass_att * 100, 2) if pass_att else None
        qb_rate       = nfl_passer_rating(pass_comp, pass_att, pass_yds, pass_td, pass_int)

        # ── rushing ───────────────────────────────────────────────────────────
        rush_att = sum(safe_int(r['rush_att']) for r in team_rows)
        rush_yds = sum(safe_int(r['rush_yds']) for r in team_rows)
        rush_td  = sum(safe_int(r['rush_td'])  for r in team_rows)
        rush_ypc = round(rush_yds / rush_att, 2) if rush_att else None

        # ── fumbles (2021+ only — column absent in earlier CSVs) ─────────────
        has_fumble_col   = 'fumble_lost' in (rows[0] if rows else {})
        off_fumbles_lost = sum(safe_int(r.get('fumble_lost', 0)) for r in team_rows) if has_fumble_col else None

        # ── receiving (total + position groups) ───────────────────────────────
        rec_total     = sum(safe_int(r['rec'])     for r in team_rows)
        rec_yds_total = sum(safe_int(r['rec_yds']) for r in team_rows)
        rec_td_total  = sum(safe_int(r['rec_td'])  for r in team_rows)

        grp = defaultdict(int)
        matched_yds = 0
        for r in team_rows:
            recs = safe_int(r['rec'])
            ryds = safe_int(r['rec_yds'])
            rtds = safe_int(r['rec_td'])
            if recs == 0 and ryds == 0 and rtds == 0:
                continue
            pg = pos_lookup.get((team, r['player_name']))
            if pg:
                matched_yds      += ryds
                grp[pg + '_rec'] += recs
                grp[pg + '_yds'] += ryds
                grp[pg + '_td']  += rtds

        has_pos = True if rec_yds_total == 0 else (matched_yds / rec_yds_total) >= 0.75

        result[team] = {
            'game_id': game_id, 'season': season, 'offense_team': team,
            'pass_comp': pass_comp, 'pass_att': pass_att,
            'pass_yds': pass_yds, 'pass_td': pass_td, 'pass_int': pass_int,
            'comp_pct': comp_pct, 'qb_rate': qb_rate,
            'sacks_taken': sacks_taken, 'sack_yds_lost': sack_yds_lost,
            'rush_att': rush_att, 'rush_yds': rush_yds,
            'rush_td': rush_td, 'rush_ypc': rush_ypc,
            'rec_total': rec_total, 'rec_yds_total': rec_yds_total, 'rec_td_total': rec_td_total,
            'rec_rb':     grp['RB_rec'], 'rec_yds_rb': grp['RB_yds'], 'rec_td_rb': grp['RB_td'],
            'rec_wr':     grp['WR_rec'], 'rec_yds_wr': grp['WR_yds'], 'rec_td_wr': grp['WR_td'],
            'rec_te':     grp['TE_rec'], 'rec_yds_te': grp['TE_yds'], 'rec_td_te': grp['TE_td'],
            'has_position_data': has_pos,
            'off_fumbles_lost': off_fumbles_lost,
        }

    teams = list(result.keys())
    if len(teams) == 2:
        result[teams[0]]['defense_team'] = teams[1]
        result[teams[1]]['defense_team'] = teams[0]
    else:
        for t in teams:
            result[t]['defense_team'] = None

    return result


# ── leave-one-out season averages ─────────────────────────────────────────────

# Raw additive components summed for LOO; rates are recomputed from these.
RAW_COLS = [
    'pass_comp', 'pass_att', 'pass_yds', 'pass_td', 'pass_int',
    'sacks_taken', 'sack_yds_lost',
    'rush_att', 'rush_yds', 'rush_td',
    'rec_total', 'rec_yds_total', 'rec_td_total',
    'rec_rb', 'rec_yds_rb', 'rec_td_rb',
    'rec_wr', 'rec_yds_wr', 'rec_td_wr',
    'rec_te', 'rec_yds_te', 'rec_td_te',
    'off_fumbles_lost',   # None for pre-2021; 2021+ from fumble_lost column
]

# Simple per-game average stats (count/td stats, no recomputation needed)
SIMPLE_AVG_COLS = [
    'pass_yds', 'pass_td', 'pass_int', 'sacks_taken',
    'rush_yds', 'rush_td',
    'rec_total', 'rec_yds_total', 'rec_td_total',
    'rec_rb',    'rec_yds_rb',    'rec_td_rb',
    'rec_wr',    'rec_yds_wr',    'rec_td_wr',
    'rec_te',    'rec_yds_te',    'rec_td_te',
    'off_fumbles_lost',
]


def compute_loo_averages(all_stats: list[dict]) -> dict:
    """
    Build leave-one-out season averages for every (game_id, offense_team) pair.
    Input should already be filtered to regular-season games only.
    Returns {(game_id, offense_team): avg_dict}.
    """
    by_team = defaultdict(list)
    for s in all_stats:
        by_team[(s['season'], s['offense_team'])].append(s)

    avgs = {}
    for (season, team), games in by_team.items():
        if len(games) < 2:
            continue
        for i, g in enumerate(games):
            others = [o for j, o in enumerate(games) if j != i]
            n = len(others)
            # Build sums, skipping None values (nullable cols like off_fumbles_lost pre-2021)
            sums   = {}
            n_col  = {}
            for col in RAW_COLS:
                vals = [o[col] for o in others if o.get(col) is not None]
                sums[col]  = sum(vals) if vals else None
                n_col[col] = len(vals)

            avg = {'games_in_avg': n}

            # Simple per-game averages (None when no data available for that col)
            for col in SIMPLE_AVG_COLS:
                nc = n_col.get(col, 0)
                avg[f'avg_{col}'] = round(sums[col] / nc, 3) if nc > 0 and sums[col] is not None else None

            # Rate stats: recompute from accumulated totals for accuracy
            att = sums['pass_att']
            avg['avg_comp_pct'] = round(sums['pass_comp'] / att * 100, 2) if att else None
            avg['avg_qb_rate']  = nfl_passer_rating(
                sums['pass_comp'], att,
                sums['pass_yds'], sums['pass_td'], sums['pass_int']
            )
            rush = sums['rush_att']
            avg['avg_rush_ypc'] = round(sums['rush_yds'] / rush, 2) if rush else None

            avgs[(g['game_id'], team)] = avg

    return avgs


# ── delta computation ─────────────────────────────────────────────────────────

# (actual_key, avg_key, delta_key)
# For sacks_taken and pass_int: positive delta = defense outperformed (want higher)
# For all others: negative delta = defense held below average (want lower)
DELTA_SPEC = [
    # Passing
    ('pass_yds',      'avg_pass_yds',      'delta_pass_yds'),
    ('pass_td',       'avg_pass_td',       'delta_pass_td'),
    ('comp_pct',      'avg_comp_pct',      'delta_comp_pct'),
    ('qb_rate',       'avg_qb_rate',       'delta_qb_rate'),
    # Rushing
    ('rush_yds',      'avg_rush_yds',      'delta_rush_yds'),
    ('rush_td',       'avg_rush_td',       'delta_rush_td'),
    ('rush_ypc',      'avg_rush_ypc',      'delta_rush_ypc'),
    # Big plays (positive = defense generated more than opponent's typical rate)
    ('sacks_taken',   'avg_sacks_taken',   'delta_sacks_taken'),
    ('pass_int',      'avg_pass_int',      'delta_pass_int'),
    # Receiving — totals
    ('rec_total',     'avg_rec_total',     'delta_rec_total'),
    ('rec_yds_total', 'avg_rec_yds_total', 'delta_rec_yds_total'),
    ('rec_td_total',  'avg_rec_td_total',  'delta_rec_td_total'),
    # Receiving — RB/FB
    ('rec_rb',        'avg_rec_rb',        'delta_rec_rb'),
    ('rec_yds_rb',    'avg_rec_yds_rb',    'delta_rec_yds_rb'),
    ('rec_td_rb',     'avg_rec_td_rb',     'delta_rec_td_rb'),
    # Receiving — WR
    ('rec_wr',        'avg_rec_wr',        'delta_rec_wr'),
    ('rec_yds_wr',    'avg_rec_yds_wr',    'delta_rec_yds_wr'),
    ('rec_td_wr',     'avg_rec_td_wr',     'delta_rec_td_wr'),
    # Receiving — TE
    ('rec_te',        'avg_rec_te',        'delta_rec_te'),
    ('rec_yds_te',    'avg_rec_yds_te',    'delta_rec_yds_te'),
    ('rec_td_te',     'avg_rec_td_te',     'delta_rec_td_te'),
    # Fumbles — positive delta = defense forced more fumbles than opponent's typical rate
    # Available 2021+ from offensive CSVs; pre-2021 requires defense gamelog join
    ('off_fumbles_lost', 'avg_off_fumbles_lost', 'delta_off_fumbles_lost'),
]


def compute_deltas(all_stats: list[dict], loo_avgs: dict) -> list[dict]:
    rows = []
    for s in all_stats:
        key  = (s['game_id'], s['offense_team'])
        avgs = loo_avgs.get(key)
        if not avgs:
            continue
        row = {
            'game_id':        s['game_id'],
            'defending_team': s.get('defense_team'),
            'offense_team':   s['offense_team'],
            'season':         s['season'],
            'games_in_avg':   avgs['games_in_avg'],
        }
        for (act_k, avg_k, delta_k) in DELTA_SPEC:
            actual = s.get(act_k)
            avg    = avgs.get(avg_k)
            row[f'opp_{avg_k}']    = avg
            row[f'actual_{act_k}'] = actual
            row[delta_k] = round(actual - avg, 2) if (actual is not None and avg is not None) else None
        rows.append(row)
    return rows


# ── season processor ──────────────────────────────────────────────────────────

def process_season(season: int) -> tuple[list, list]:
    season_dir = BOXSCORE_DIR / str(season)
    if not season_dir.is_dir():
        return [], []

    rs_ids     = get_regular_season_ids(season)
    pos_lookup = load_season_positions(season)

    all_stats = []
    for f in sorted(season_dir.glob("*.csv")):
        if f.stem not in rs_ids:
            continue   # skip playoff games
        for stats in parse_game(f, pos_lookup).values():
            if stats.get('defense_team'):
                all_stats.append(stats)

    if not all_stats:
        return [], []

    loo_avgs   = compute_loo_averages(all_stats)
    delta_rows = compute_deltas(all_stats, loo_avgs)
    return all_stats, delta_rows


# ── CSV output ────────────────────────────────────────────────────────────────

TGO_FIELDS = [
    'game_id', 'season', 'offense_team', 'defense_team',
    'pass_comp', 'pass_att', 'pass_yds', 'pass_td', 'pass_int',
    'comp_pct', 'qb_rate', 'sacks_taken', 'sack_yds_lost',
    'rush_att', 'rush_yds', 'rush_td', 'rush_ypc',
    'rec_total', 'rec_yds_total', 'rec_td_total',
    'rec_rb', 'rec_yds_rb', 'rec_td_rb',
    'rec_wr', 'rec_yds_wr', 'rec_td_wr',
    'rec_te', 'rec_yds_te', 'rec_td_te',
    'has_position_data',
    'off_fumbles_lost',
]

OQA_FIELDS = (
    ['game_id', 'defending_team', 'offense_team', 'season', 'games_in_avg'] +
    [f'opp_{avg_k}' for (_, avg_k, _) in DELTA_SPEC] +
    [f'actual_{act_k}' for (act_k, _, _) in DELTA_SPEC] +
    [delta_k for (_, _, delta_k) in DELTA_SPEC]
)


def write_csv(rows, fields, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {len(rows):,} rows → {path}")


# ── QA printer ────────────────────────────────────────────────────────────────

def qa_team_season(team: str, season: int, delta_rows: list[dict]):
    rows = [
        r for r in delta_rows
        if r['defending_team'] == team.upper() and r['season'] == season
    ]
    if not rows:
        print(f"\n[no data for {team} {season}]")
        return

    def f(v, w=6, d=1):
        return f"{v:{w}.{d}f}" if v is not None else f"{'—':>{w}}"

    print(f"\n{'═'*110}")
    print(f"  QA — {team.upper()} {season} defense  ({len(rows)} regular-season games)")
    print(f"{'═'*110}")
    print(
        f"  {'Game':<18} {'Opp':<5}"
        f" {'PaYd':>5} {'ΔPaYd':>7}"
        f" {'RuYd':>5} {'ΔRuYd':>7}"
        f" {'QBRt':>5} {'ΔQBRt':>6}"
        f" {'Cmp%':>5} {'ΔCmp%':>6}"
        f" {'Sks':>3} {'ΔSks':>5}"
        f" {'INT':>3} {'ΔINT':>5}"
    )
    print('  ' + '─' * 108)

    season_deltas = defaultdict(list)
    for r in sorted(rows, key=lambda x: x['game_id']):
        print(
            f"  {r['game_id']:<18} {r['offense_team']:<5}"
            f" {f(r.get('actual_pass_yds'),5,0)}"
            f" {f(r.get('delta_pass_yds'),7,1)}"
            f" {f(r.get('actual_rush_yds'),5,0)}"
            f" {f(r.get('delta_rush_yds'),7,1)}"
            f" {f(r.get('actual_qb_rate'),5,1)}"
            f" {f(r.get('delta_qb_rate'),6,1)}"
            f" {f(r.get('actual_comp_pct'),5,1)}"
            f" {f(r.get('delta_comp_pct'),6,1)}"
            f" {f(r.get('actual_sacks_taken'),3,0)}"
            f" {f(r.get('delta_sacks_taken'),5,1)}"
            f" {f(r.get('actual_pass_int'),3,0)}"
            f" {f(r.get('delta_pass_int'),5,1)}"
        )
        for (_, _, dk) in DELTA_SPEC:
            if r.get(dk) is not None:
                season_deltas[dk].append(r[dk])

    print('  ' + '─' * 108)
    avg_delta = {k: round(sum(v) / len(v), 1) for k, v in season_deltas.items()}
    print(
        f"  {'AVG DELTA':<23}"
        f" {'':>5} {f(avg_delta.get('delta_pass_yds'),7,1)}"
        f" {'':>5} {f(avg_delta.get('delta_rush_yds'),7,1)}"
        f" {'':>5} {f(avg_delta.get('delta_qb_rate'),6,1)}"
        f" {'':>5} {f(avg_delta.get('delta_comp_pct'),6,1)}"
        f" {'':>3} {f(avg_delta.get('delta_sacks_taken'),5,1)}"
        f" {'':>3} {f(avg_delta.get('delta_pass_int'),5,1)}"
    )
    print()

    # Receiving breakdown
    print(f"  Receiving by position group (avg delta vs opp's season avg):")
    print(f"  {'Group':<8} {'Rec':>6} {'ΔRec':>7}  {'Yds':>6} {'ΔYds':>7}  {'TDs':>5} {'ΔTDs':>6}")
    print('  ' + '─' * 52)
    for grp in ['rb', 'wr', 'te']:
        rec_mu  = avg_delta.get(f'delta_rec_{grp}')
        yds_mu  = avg_delta.get(f'delta_rec_yds_{grp}')
        td_mu   = avg_delta.get(f'delta_rec_td_{grp}')
        actual_rec_mu = round(sum(r.get(f'actual_rec_{grp}', 0) or 0 for r in rows) / len(rows), 1)
        actual_yds_mu = round(sum(r.get(f'actual_rec_yds_{grp}', 0) or 0 for r in rows) / len(rows), 1)
        actual_td_mu  = round(sum(r.get(f'actual_rec_td_{grp}', 0) or 0 for r in rows) / len(rows), 1)
        print(
            f"  {grp.upper():<8}"
            f" {f(actual_rec_mu,6,1)} {f(rec_mu,7,1)}"
            f"  {f(actual_yds_mu,6,1)} {f(yds_mu,7,1)}"
            f"  {f(actual_td_mu,5,1)} {f(td_mu,6,1)}"
        )


# ── season leaderboard ────────────────────────────────────────────────────────

def season_leaderboard(season: int, delta_rows: list[dict], metric: str, n: int = 10):
    by_team = defaultdict(list)
    for r in delta_rows:
        v = r.get(metric)
        if v is not None and r['season'] == season:
            by_team[r['defending_team']].append(v)

    ranked = sorted(
        [(t, round(sum(v) / len(v), 1), len(v)) for t, v in by_team.items()],
        key=lambda x: x[1]
    )
    print(f"\n  {metric} leaderboard ({season})")
    for rank, (team, mu, cnt) in enumerate(ranked[:n], 1):
        print(f"  #{rank:<3} {team:<6} {mu:>+8.1f}  ({cnt} games)")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season',    type=int, help='process only this season')
    ap.add_argument('--qa-team',   default='PHI')
    ap.add_argument('--qa-season', type=int, default=1988)
    ap.add_argument('--leaderboard', action='store_true')
    args = ap.parse_args()

    if args.season:
        seasons = [args.season]
    else:
        seasons = sorted(
            int(p.name) for p in BOXSCORE_DIR.iterdir()
            if p.is_dir() and p.name.isdigit()
        )

    for season in seasons:
        print(f"\n── {season} ──────────────────────────────────────────────────────")
        rs_ids = get_regular_season_ids(season)
        total_files = len(list((BOXSCORE_DIR / str(season)).glob("*.csv")))
        print(f"  {len(rs_ids)} regular-season games / {total_files} total (excluded {total_files - len(rs_ids)} playoffs)")

        game_rows, delta_rows = process_season(season)
        if not game_rows:
            print("  (no data)")
            continue
        write_csv(game_rows, TGO_FIELDS, OUTPUT_DIR / f"team_game_offense_{season}.csv")
        write_csv(delta_rows, OQA_FIELDS, OUTPUT_DIR / f"oqa_game_detail_{season}.csv")

        if season == args.qa_season:
            qa_team_season(args.qa_team, season, delta_rows)
            if args.leaderboard:
                season_leaderboard(season, delta_rows, 'delta_rush_yds')
                season_leaderboard(season, delta_rows, 'delta_pass_yds')


if __name__ == '__main__':
    main()
