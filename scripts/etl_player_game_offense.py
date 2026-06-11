#!/usr/bin/env python3
"""
ETL: Boxscore CSVs → individual offensive player game stats + position-level OQA.

Outputs per season (in data_output/):
  player_game_offense_{season}.csv   — one row per player per regular-season game
  defense_loo_avg_{season}.csv       — per-game defense LOO averages (defense's perspective)
  player_oqa_season_{season}.csv     — season OQA rollup per player

OQA delta = actual player stat − defense's LOO average allowed for that stat.
  Passing/rushing/receiving: negative delta means defense held player below their norm.
  INT (for QB): negative delta means QB threw fewer picks than this defense typically forces.

Position group assignment (from roster):
  QB  — QB position; must have pass_att >= MIN_QB_ATT to count as a QB game
  RB  — RB/FB/HB/WB; must have rush_att >= 1 or rec >= 1
  WR  — WR/FL/SE/E/OE; must have targets >= 1 or rec >= 1
  TE  — TE; must have targets >= 1 or rec >= 1

For WRs: delta is vs the defense's total WR yards allowed (group-level, not individual).
For TEs: is_primary=TRUE for the top-receiving TE per team per game; OQA uses TE group average.

Usage:
  python scripts/etl_player_game_offense.py               # all seasons
  python scripts/etl_player_game_offense.py --season 1988
  python scripts/etl_player_game_offense.py --season 2023 --qa-player "Travis Kelce"
"""

import argparse
import csv
import glob
import sys
from collections import defaultdict
from pathlib import Path

PFREF        = Path("/Users/devos/data/pfref")
BOXSCORE_DIR = PFREF / "boxscores"
ROSTER_DIR   = PFREF / "team-rosters"
OUTPUT_DIR   = Path(__file__).parent.parent / "data_output"

# Minimum pass attempts to treat a row as a "QB game" for OQA purposes
MIN_QB_ATT = 5

# Position → position_group
QB_POS = {'QB'}
RB_POS = {'RB', 'FB', 'HB', 'WB', 'B'}
WR_POS = {'WR', 'FL', 'SE', 'E', 'OE'}
TE_POS = {'TE'}

# Franchise relocation aliases (roster prefix → boxscore team codes)
ROSTER_ALIASES: dict[str, list[str]] = {
    'CLT': ['IND', 'BAL'],
    'CRD': ['PHO', 'ARI'],
    'OTI': ['HOU'],
    'RAM': ['STL', 'LAR'],
    'RAI': ['OAK', 'LVR'],
}


# ── helpers ────────────────────────────────────────────────────────────────────

def safe_int(v, default=0):
    try:
        return int(float(v)) if v not in ('', None) else default
    except (ValueError, TypeError):
        return default


def safe_float(v):
    try:
        return float(v) if v not in ('', None) else None
    except (ValueError, TypeError):
        return None


def nfl_passer_rating(comp, att, yds, td, ints):
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
    if p in QB_POS: return 'QB'
    if p in RB_POS: return 'RB'
    if p in WR_POS: return 'WR'
    if p in TE_POS: return 'TE'
    return None


# ── playoff detection ──────────────────────────────────────────────────────────

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


def get_regular_season_ids(season: int) -> frozenset:
    season_dir = BOXSCORE_DIR / str(season)
    if not season_dir.is_dir():
        return frozenset()
    files = sorted(season_dir.glob("*.csv"), key=lambda f: f.name[:8])
    rs_count = _num_teams(season) * _games_per_team(season) // 2
    return frozenset(f.stem for f in files[:rs_count])


# ── roster position lookup ─────────────────────────────────────────────────────

def load_season_positions(season: int) -> dict:
    """Return {(TEAM, player_name): position_group} for the season."""
    lookup = {}
    for f in glob.glob(str(ROSTER_DIR / f"*_{season}_roster.csv")):
        prefix = Path(f).stem.split('_')[0].upper()
        codes  = {prefix} | set(ROSTER_ALIASES.get(prefix, []))
        try:
            with open(f) as fh:
                for row in csv.DictReader(fh):
                    name = row.get('Player', '').strip()
                    pg   = pos_group(row.get('Pos', ''))
                    if name and pg:
                        for code in codes:
                            lookup[(code, name)] = pg
        except Exception:
            pass
    return lookup


# ── parse season: both team aggregates and individual rows ─────────────────────

def parse_season(season: int, rs_ids: frozenset, pos_lookup: dict):
    """
    Read all regular-season boxscore CSVs.

    Returns:
      team_stats  — list of team-level dicts (one per team per game)
      player_rows — list of individual player dicts (one per player per game)
    """
    season_dir = BOXSCORE_DIR / str(season)
    team_stats  = []
    player_rows = []

    for f in sorted(season_dir.glob("*.csv")):
        if f.stem not in rs_ids:
            continue

        try:
            rows = list(csv.DictReader(open(f)))
        except Exception as e:
            print(f"WARN: {f}: {e}", file=sys.stderr)
            continue
        if not rows:
            continue

        game_id = rows[0].get('game_id', '')
        season_ = safe_int(rows[0].get('season', season))

        # Group rows by team for team-level aggregates
        by_team = defaultdict(list)
        for r in rows:
            by_team[r['team'].upper()].append(r)

        teams = list(by_team.keys())
        team_of = {teams[0]: teams[1], teams[1]: teams[0]} if len(teams) == 2 else {}

        # ── team-level aggregates ──────────────────────────────────────────────
        for team, team_rows in by_team.items():
            qb_rows = [r for r in team_rows if safe_int(r.get('pass_att', 0)) > 0]
            pass_comp     = sum(safe_int(r['pass_comp']) for r in qb_rows)
            pass_att      = sum(safe_int(r['pass_att'])  for r in qb_rows)
            pass_yds      = sum(safe_int(r['pass_yds'])  for r in qb_rows)
            pass_td       = sum(safe_int(r['pass_td'])   for r in qb_rows)
            pass_int      = sum(safe_int(r['pass_int'])  for r in qb_rows)
            sacks_taken   = sum(safe_int(r.get('sacked', 0)) for r in team_rows)
            rush_att      = sum(safe_int(r['rush_att'])  for r in team_rows)
            rush_yds      = sum(safe_int(r['rush_yds'])  for r in team_rows)
            rush_td       = sum(safe_int(r['rush_td'])   for r in team_rows)

            # Receiving by position group
            grp = defaultdict(int)
            matched_yds = 0
            rec_yds_total = sum(safe_int(r['rec_yds']) for r in team_rows)
            for r in team_rows:
                pg = pos_lookup.get((team, r['player_name']))
                recs = safe_int(r['rec'])
                ryds = safe_int(r['rec_yds'])
                rtds = safe_int(r['rec_td'])
                if pg and (recs or ryds or rtds):
                    matched_yds      += ryds
                    grp[pg + '_rec'] += recs
                    grp[pg + '_yds'] += ryds
                    grp[pg + '_td']  += rtds

            has_pos = (matched_yds / rec_yds_total >= 0.75) if rec_yds_total else True

            team_stats.append({
                'game_id': game_id, 'season': season_, 'offense_team': team,
                'defense_team': team_of.get(team),
                'pass_comp': pass_comp, 'pass_att': pass_att,
                'pass_yds': pass_yds, 'pass_td': pass_td, 'pass_int': pass_int,
                'sacks_taken': sacks_taken,
                'rush_att': rush_att, 'rush_yds': rush_yds, 'rush_td': rush_td,
                'rec_yds_total': rec_yds_total,
                'rec_rb': grp['RB_rec'], 'rec_yds_rb': grp['RB_yds'], 'rec_td_rb': grp['RB_td'],
                'rec_wr': grp['WR_rec'], 'rec_yds_wr': grp['WR_yds'], 'rec_td_wr': grp['WR_td'],
                'rec_te': grp['TE_rec'], 'rec_yds_te': grp['TE_yds'], 'rec_td_te': grp['TE_td'],
                'has_position_data': has_pos,
            })

        # ── individual player rows ─────────────────────────────────────────────
        for team, team_rows in by_team.items():
            defense_team = team_of.get(team)
            if not defense_team:
                continue

            for r in team_rows:
                name  = r['player_name']
                pg    = pos_lookup.get((team, name))
                if not pg:
                    continue

                pass_att = safe_int(r.get('pass_att', 0))
                rush_att = safe_int(r.get('rush_att', 0))
                rec      = safe_int(r.get('rec', 0))
                targets  = safe_int(r.get('targets', 0)) if 'targets' in r else None

                # Skip rows with no meaningful stats for this position
                if pg == 'QB' and pass_att < MIN_QB_ATT:
                    continue
                if pg in ('WR', 'TE') and rec == 0 and (targets is None or targets == 0):
                    continue
                if pg == 'RB' and rush_att == 0 and rec == 0:
                    continue

                pass_comp = safe_int(r.get('pass_comp', 0))
                pass_yds  = safe_int(r.get('pass_yds', 0))
                pass_td   = safe_int(r.get('pass_td', 0))
                pass_int  = safe_int(r.get('pass_int', 0))
                qb_rate   = safe_float(r.get('qb_rate')) if pass_att else None

                player_rows.append({
                    'game_id':       game_id,
                    'pfr_player_id': r.get('player_link', ''),
                    'player_name':   name,
                    'team_abbrev':   team,
                    'defense_team':  defense_team,
                    'season':        season_,
                    'position_group': pg,
                    'is_primary':    False,   # filled below
                    'pass_comp':     pass_comp,
                    'pass_att':      pass_att,
                    'pass_yds':      pass_yds,
                    'pass_td':       pass_td,
                    'pass_int':      pass_int,
                    'sacks_taken':   safe_int(r.get('sacked', 0)),
                    'qb_rate':       qb_rate,
                    'rush_att':      rush_att,
                    'rush_yds':      safe_int(r.get('rush_yds', 0)),
                    'rush_td':       safe_int(r.get('rush_td', 0)),
                    'targets':       targets,
                    'rec':           rec,
                    'rec_yds':       safe_int(r.get('rec_yds', 0)),
                    'rec_td':        safe_int(r.get('rec_td', 0)),
                })

    # ── mark is_primary ───────────────────────────────────────────────────────
    # QB: highest pass_att; RB: highest rush_yds; WR/TE: highest rec_yds
    # per (game_id, team_abbrev, position_group)
    primary_key: dict[tuple, int] = {}  # key → best value seen
    primary_idx: dict[tuple, int] = {}  # key → index of best row

    stat_for_primary = {'QB': 'pass_att', 'RB': 'rush_yds', 'WR': 'rec_yds', 'TE': 'rec_yds'}

    for idx, row in enumerate(player_rows):
        key  = (row['game_id'], row['team_abbrev'], row['position_group'])
        stat = stat_for_primary[row['position_group']]
        val  = row[stat]
        if val > primary_key.get(key, -1):
            primary_key[key] = val
            primary_idx[key] = idx

    for idx in primary_idx.values():
        player_rows[idx]['is_primary'] = True

    return team_stats, player_rows


# ── defense LOO averages ───────────────────────────────────────────────────────

DEF_AVG_COLS = [
    'pass_att', 'pass_comp', 'pass_yds', 'pass_td', 'pass_int', 'sacks_taken',
    'rush_att', 'rush_yds', 'rush_td',
    'rec_yds_rb', 'rec_yds_wr', 'rec_yds_te',
    'rec_rb', 'rec_wr', 'rec_te',
    'rec_td_rb', 'rec_td_wr', 'rec_td_te',
]


def compute_defense_loo_avgs(team_stats: list[dict]) -> dict:
    """
    For each (game_id, defending_team): average of what that defense allowed
    in all OTHER regular-season games that season.
    Returns {(game_id, defending_team): avg_dict}.
    """
    # Group by (season, defense_team) — indexed by (offense_team, game_id) for LOO exclusion
    by_defense = defaultdict(list)
    for s in team_stats:
        if s.get('defense_team'):
            by_defense[(s['season'], s['defense_team'])].append(s)

    avgs = {}
    for (season, def_team), games in by_defense.items():
        if len(games) < 2:
            continue
        for i, g in enumerate(games):
            others = [o for j, o in enumerate(games) if j != i]
            n = len(others)
            avg = {'games_in_avg': n, 'season': season, 'defending_team': def_team, 'game_id': g['game_id']}

            sums = {col: sum(o.get(col, 0) or 0 for o in others) for col in DEF_AVG_COLS}

            # Simple per-game averages
            for col in ['pass_yds', 'pass_td', 'pass_int', 'sacks_taken',
                        'rush_yds', 'rush_td',
                        'rec_yds_rb', 'rec_yds_wr', 'rec_yds_te',
                        'rec_rb', 'rec_wr', 'rec_te',
                        'rec_td_rb', 'rec_td_wr', 'rec_td_te']:
                avg[f'def_avg_{col}'] = round(sums[col] / n, 2)

            # Rate stats recomputed from totals
            att = sums['pass_att']
            avg['def_avg_qb_rate']  = nfl_passer_rating(
                sums['pass_comp'], att, sums['pass_yds'], sums['pass_td'], sums['pass_int']
            )
            avg['def_avg_comp_pct'] = round(sums['pass_comp'] / att * 100, 2) if att else None
            rush_att = sums['rush_att']
            avg['def_avg_rush_ypc'] = round(sums['rush_yds'] / rush_att, 2) if rush_att else None

            avgs[(g['game_id'], def_team)] = avg

    return avgs


# ── join player rows to defense averages and compute deltas ───────────────────

def build_player_game_output(player_rows: list[dict], def_avgs: dict) -> list[dict]:
    """Add defense_avg and delta columns to each player game row."""
    out = []
    for row in player_rows:
        key = (row['game_id'], row['defense_team'])
        avg = def_avgs.get(key)
        r = dict(row)
        if not avg:
            out.append(r)
            continue

        pg = row['position_group']

        if pg == 'QB':
            r['def_avg_pass_yds'] = avg.get('def_avg_pass_yds')
            r['def_avg_pass_td']  = avg.get('def_avg_pass_td')
            r['def_avg_pass_int'] = avg.get('def_avg_pass_int')
            r['def_avg_qb_rate']  = avg.get('def_avg_qb_rate')
            r['delta_pass_yds']   = _delta(row['pass_yds'], avg.get('def_avg_pass_yds'))
            r['delta_pass_td']    = _delta(row['pass_td'],  avg.get('def_avg_pass_td'))
            r['delta_pass_int']   = _delta(row['pass_int'], avg.get('def_avg_pass_int'))
            r['delta_qb_rate']    = _delta(row['qb_rate'],  avg.get('def_avg_qb_rate'))

        elif pg == 'RB':
            # Carry-adjusted expected yards: RB's carries × defense's average YPC allowed.
            # This measures per-carry efficiency vs the defense, not total team rush volume.
            def_ypc  = avg.get('def_avg_rush_ypc')
            rush_att = row['rush_att']
            expected_rush_yds = round(rush_att * def_ypc, 2) if def_ypc and rush_att else None
            r['def_avg_rush_ypc']      = def_ypc
            r['expected_rush_yds']     = expected_rush_yds
            r['delta_rush_yds']        = _delta(row['rush_yds'], expected_rush_yds)
            r['def_avg_rush_td']       = avg.get('def_avg_rush_td')
            r['delta_rush_td']         = _delta(row['rush_td'],  avg.get('def_avg_rush_td'))
            # Receiving for RBs vs defense's RB receiving average
            r['def_avg_rec_yds_rb']    = avg.get('def_avg_rec_yds_rb')
            r['delta_rec_yds']         = _delta(row['rec_yds'], avg.get('def_avg_rec_yds_rb'))

        elif pg == 'WR':
            # Compare individual WR to defense's total WR yards allowed
            r['def_avg_rec_yds_wr'] = avg.get('def_avg_rec_yds_wr')
            r['delta_rec_yds']    = _delta(row['rec_yds'], avg.get('def_avg_rec_yds_wr'))
            r['def_avg_rec_wr']   = avg.get('def_avg_rec_wr')
            r['delta_rec']        = _delta(row['rec'],     avg.get('def_avg_rec_wr'))
            r['delta_rec_td']     = _delta(row['rec_td'],  avg.get('def_avg_rec_td_wr'))

        elif pg == 'TE':
            r['def_avg_rec_yds_te'] = avg.get('def_avg_rec_yds_te')
            r['delta_rec_yds']    = _delta(row['rec_yds'], avg.get('def_avg_rec_yds_te'))
            r['def_avg_rec_te']   = avg.get('def_avg_rec_te')
            r['delta_rec']        = _delta(row['rec'],     avg.get('def_avg_rec_te'))
            r['delta_rec_td']     = _delta(row['rec_td'],  avg.get('def_avg_rec_td_te'))

        out.append(r)
    return out


def _delta(actual, avg):
    if actual is None or avg is None:
        return None
    return round(actual - avg, 2)


# ── season OQA rollup ─────────────────────────────────────────────────────────

def build_player_oqa_season(player_game_rows: list[dict]) -> list[dict]:
    """Aggregate per-game player OQA to season level."""
    by_player = defaultdict(list)
    for row in player_game_rows:
        key = (row['pfr_player_id'], row['player_name'], row['team_abbrev'],
               row['season'], row['position_group'])
        by_player[key].append(row)

    out = []
    for (pid, name, team, season, pg), games in by_player.items():
        n = len(games)
        # Initialize all columns to None so every row has a consistent schema
        row = {
            'pfr_player_id':         pid,
            'player_name':           name,
            'team_abbrev':           team,
            'season':                season,
            'position_group':        pg,
            'games':                 n,
            'total_pass_yds':        None,
            'total_pass_td':         None,
            'total_pass_int':        None,
            'avg_qb_rate':           None,
            'total_rush_yds':        None,
            'total_rush_td':         None,
            'total_rec_yds':         None,
            'total_rec':             None,
            'total_rec_td':          None,
            'delta_pass_yds_total':  None,
            'delta_pass_yds_pg':     None,
            'delta_pass_td_total':   None,
            'delta_pass_td_pg':      None,
            'delta_pass_int_total':  None,
            'delta_pass_int_pg':     None,
            'delta_qb_rate_total':   None,
            'delta_qb_rate_pg':      None,
            'delta_rush_yds_total':  None,
            'delta_rush_yds_pg':     None,
            'delta_rush_td_total':   None,
            'delta_rush_td_pg':      None,
            'delta_rec_yds_total':   None,
            'delta_rec_yds_pg':      None,
            'delta_rec_total_d':     None,
            'delta_rec_pg':          None,
            'delta_rec_td_total':    None,
            'delta_rec_td_pg':       None,
        }

        if pg == 'QB':
            total_comp = sum(g['pass_comp'] for g in games)
            total_att  = sum(g['pass_att']  for g in games)
            total_yds  = sum(g['pass_yds']  for g in games)
            total_td   = sum(g['pass_td']   for g in games)
            total_int  = sum(g['pass_int']  for g in games)
            row['total_pass_yds'] = total_yds
            row['total_pass_td']  = total_td
            row['total_pass_int'] = total_int
            row['avg_qb_rate']    = nfl_passer_rating(total_comp, total_att, total_yds, total_td, total_int)

            row.update(_season_delta(games, 'delta_pass_yds', 'delta_pass_yds_total', 'delta_pass_yds_pg'))
            row.update(_season_delta(games, 'delta_pass_td',  'delta_pass_td_total',  'delta_pass_td_pg'))
            row.update(_season_delta(games, 'delta_pass_int', 'delta_pass_int_total', 'delta_pass_int_pg'))
            row.update(_season_delta(games, 'delta_qb_rate',  'delta_qb_rate_total',  'delta_qb_rate_pg'))

        elif pg == 'RB':
            row['total_rush_yds'] = sum(g['rush_yds'] for g in games)
            row['total_rush_td']  = sum(g['rush_td']  for g in games)
            row['total_rec_yds']  = sum(g['rec_yds']  for g in games)
            row['total_rec']      = sum(g['rec']       for g in games)
            row['total_rec_td']   = sum(g['rec_td']    for g in games)

            row.update(_season_delta(games, 'delta_rush_yds', 'delta_rush_yds_total', 'delta_rush_yds_pg'))
            row.update(_season_delta(games, 'delta_rush_td',  'delta_rush_td_total',  'delta_rush_td_pg'))
            row.update(_season_delta(games, 'delta_rec_yds',  'delta_rec_yds_total',  'delta_rec_yds_pg'))

        elif pg in ('WR', 'TE'):
            row['total_rec_yds'] = sum(g['rec_yds'] for g in games)
            row['total_rec']     = sum(g['rec']      for g in games)
            row['total_rec_td']  = sum(g['rec_td']   for g in games)

            row.update(_season_delta(games, 'delta_rec_yds', 'delta_rec_yds_total', 'delta_rec_yds_pg'))
            row.update(_season_delta(games, 'delta_rec',     'delta_rec_total_d',   'delta_rec_pg'))
            row.update(_season_delta(games, 'delta_rec_td',  'delta_rec_td_total',  'delta_rec_td_pg'))

        out.append(row)

    out.sort(key=lambda r: (r['season'], r['position_group'], r.get('total_pass_yds') or
                            r.get('total_rush_yds') or r.get('total_rec_yds') or 0), reverse=True)
    return out


def _season_delta(games, delta_col, total_col, pg_col):
    vals = [g[delta_col] for g in games if g.get(delta_col) is not None]
    if not vals:
        return {total_col: None, pg_col: None}
    total = round(sum(vals), 1)
    return {total_col: total, pg_col: round(total / len(vals), 2)}


# ── CSV output ─────────────────────────────────────────────────────────────────

def write_csv(rows, path: Path):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {len(rows):,} rows → {path}")


DEF_AVG_FIELDS = [
    'game_id', 'defending_team', 'season', 'games_in_avg',
    'def_avg_pass_yds', 'def_avg_pass_td', 'def_avg_pass_int',
    'def_avg_qb_rate', 'def_avg_comp_pct', 'def_avg_sacks_taken',
    'def_avg_rush_yds', 'def_avg_rush_td', 'def_avg_rush_ypc',
    'def_avg_rec_yds_rb', 'def_avg_rec_yds_wr', 'def_avg_rec_yds_te',
    'def_avg_rec_rb', 'def_avg_rec_wr', 'def_avg_rec_te',
    'def_avg_rec_td_rb', 'def_avg_rec_td_wr', 'def_avg_rec_td_te',
]

PGO_FIELDS = [
    'game_id', 'pfr_player_id', 'player_name', 'team_abbrev', 'defense_team',
    'season', 'position_group', 'is_primary',
    'pass_comp', 'pass_att', 'pass_yds', 'pass_td', 'pass_int', 'sacks_taken', 'qb_rate',
    'rush_att', 'rush_yds', 'rush_td',
    'targets', 'rec', 'rec_yds', 'rec_td',
    # OQA deltas (populated for the relevant position_group)
    'def_avg_pass_yds', 'def_avg_pass_td', 'def_avg_pass_int', 'def_avg_qb_rate',
    'delta_pass_yds', 'delta_pass_td', 'delta_pass_int', 'delta_qb_rate',
    'def_avg_rush_yds', 'def_avg_rush_td',
    'delta_rush_yds', 'delta_rush_td',
    'def_avg_rec_yds_rb', 'def_avg_rec_yds_wr', 'def_avg_rec_yds_te',
    'def_avg_rec_wr', 'def_avg_rec_te',
    'delta_rec_yds', 'delta_rec', 'delta_rec_td',
]

POQA_FIELDS = [
    'pfr_player_id', 'player_name', 'team_abbrev', 'season', 'position_group', 'games',
    'total_pass_yds', 'total_pass_td', 'total_pass_int', 'avg_qb_rate',
    'total_rush_yds', 'total_rush_td',
    'total_rec_yds', 'total_rec', 'total_rec_td',
    'delta_pass_yds_total', 'delta_pass_yds_pg',
    'delta_pass_td_total', 'delta_pass_td_pg',
    'delta_pass_int_total', 'delta_pass_int_pg',
    'delta_qb_rate_total', 'delta_qb_rate_pg',
    'delta_rush_yds_total', 'delta_rush_yds_pg',
    'delta_rush_td_total', 'delta_rush_td_pg',
    'delta_rec_yds_total', 'delta_rec_yds_pg',
    'delta_rec_total_d', 'delta_rec_pg',
    'delta_rec_td_total', 'delta_rec_td_pg',
]


# ── QA printer ─────────────────────────────────────────────────────────────────

def qa_player(player_name: str, season: int, player_rows: list[dict]):
    rows = [r for r in player_rows
            if r['player_name'].lower() == player_name.lower() and r['season'] == season]
    if not rows:
        # Try partial match
        rows = [r for r in player_rows
                if player_name.lower() in r['player_name'].lower() and r['season'] == season]
    if not rows:
        print(f"\n  [no data for '{player_name}' in {season}]")
        return

    pg = rows[0]['position_group']
    print(f"\n{'═'*90}")
    print(f"  QA — {rows[0]['player_name']} ({rows[0]['team_abbrev']}) {season}  [{pg}]  ({len(rows)} games)")
    print(f"{'═'*90}")

    if pg == 'QB':
        print(f"  {'Game':<18} {'Opp':<5} {'PaYd':>5} {'AvgAlw':>7} {'Δ':>7}  {'TD':>3} {'Δ':>5}  {'INT':>3} {'Δ':>5}  {'Rtg':>5} {'ΔRtg':>6}")
        print('  ' + '─'*88)
        for r in sorted(rows, key=lambda x: x['game_id']):
            print(
                f"  {r['game_id']:<18} {r['defense_team']:<5}"
                f" {r['pass_yds']:>5}"
                f" {_fmt(r.get('def_avg_pass_yds'),7,1)}"
                f" {_fmt(r.get('delta_pass_yds'),7,1)}"
                f"  {r['pass_td']:>3} {_fmt(r.get('delta_pass_td'),5,1)}"
                f"  {r['pass_int']:>3} {_fmt(r.get('delta_pass_int'),5,1)}"
                f"  {_fmt(r.get('qb_rate'),5,1)} {_fmt(r.get('delta_qb_rate'),6,1)}"
            )
        totals = _player_totals(rows, pg)
        print('  ' + '─'*88)
        print(f"  {'SEASON TOTAL':<22} {totals.get('total_pass_yds',''):>5}"
              f" {'':>7} {_fmt(totals.get('delta_pass_yds_total'),7,1)}"
              f"  {totals.get('total_pass_td',''):>3} {_fmt(totals.get('delta_pass_td_total'),5,1)}"
              f"  {totals.get('total_pass_int',''):>3} {_fmt(totals.get('delta_pass_int_total'),5,1)}"
              f"  {_fmt(totals.get('avg_qb_rate'),5,1)} {_fmt(totals.get('delta_qb_rate_pg'),6,1)}")

    elif pg == 'RB':
        print(f"  {'Game':<18} {'Opp':<5} {'Att':>3} {'RuYd':>5} {'ExpYd':>6} {'Δ':>7}  {'DefYPC':>6}  {'TD':>3} {'Δ':>5}  {'RecYd':>5} {'Δ':>7}")
        print('  ' + '─'*93)
        for r in sorted(rows, key=lambda x: x['game_id']):
            print(
                f"  {r['game_id']:<18} {r['defense_team']:<5}"
                f" {r['rush_att']:>3}"
                f" {r['rush_yds']:>5}"
                f" {_fmt(r.get('expected_rush_yds'),6,1)}"
                f" {_fmt(r.get('delta_rush_yds'),7,1)}"
                f"  {_fmt(r.get('def_avg_rush_ypc'),6,2)}"
                f"  {r['rush_td']:>3} {_fmt(r.get('delta_rush_td'),5,1)}"
                f"  {r['rec_yds']:>5} {_fmt(r.get('delta_rec_yds'),7,1)}"
            )
        totals = _player_totals(rows, pg)
        print('  ' + '─'*93)
        print(f"  {'SEASON TOTAL':<22} {'':>3} {totals.get('total_rush_yds',''):>5}"
              f" {'':>6} {_fmt(totals.get('delta_rush_yds_total'),7,1)}"
              f"  {'':>6}"
              f"  {totals.get('total_rush_td',''):>3} {_fmt(totals.get('delta_rush_td_total'),5,1)}"
              f"  {totals.get('total_rec_yds',''):>5} {_fmt(totals.get('delta_rec_yds_total'),7,1)}")

    elif pg in ('WR', 'TE'):
        label = 'WR grp avg' if pg == 'WR' else 'TE grp avg'
        print(f"  {'Game':<18} {'Opp':<5} {'RecYd':>5} {label:>10} {'Δ':>7}  {'Rec':>4} {'Δ':>5}  {'TD':>3} {'Δ':>5}")
        print('  ' + '─'*82)
        avg_key = 'def_avg_rec_yds_wr' if pg == 'WR' else 'def_avg_rec_yds_te'
        for r in sorted(rows, key=lambda x: x['game_id']):
            print(
                f"  {r['game_id']:<18} {r['defense_team']:<5}"
                f" {r['rec_yds']:>5}"
                f" {_fmt(r.get(avg_key),10,1)}"
                f" {_fmt(r.get('delta_rec_yds'),7,1)}"
                f"  {r['rec']:>4} {_fmt(r.get('delta_rec'),5,1)}"
                f"  {r['rec_td']:>3} {_fmt(r.get('delta_rec_td'),5,1)}"
            )
        totals = _player_totals(rows, pg)
        print('  ' + '─'*82)
        print(f"  {'SEASON TOTAL':<22} {totals.get('total_rec_yds',''):>5}"
              f" {'':>10} {_fmt(totals.get('delta_rec_yds_total'),7,1)}"
              f"  {totals.get('total_rec',''):>4} {_fmt(totals.get('delta_rec_total_d'),5,1)}"
              f"  {totals.get('total_rec_td',''):>3} {_fmt(totals.get('delta_rec_td_total'),5,1)}")


def _player_totals(rows, pg):
    season_rows = build_player_oqa_season(rows)
    return season_rows[0] if season_rows else {}


def _fmt(v, w=7, d=1):
    return f"{v:{w}.{d}f}" if v is not None else f"{'—':>{w}}"


# ── main ───────────────────────────────────────────────────────────────────────

def process_season(season: int):
    season_dir = BOXSCORE_DIR / str(season)
    if not season_dir.is_dir():
        return [], [], {}

    rs_ids     = get_regular_season_ids(season)
    pos_lookup = load_season_positions(season)

    print(f"  {len(rs_ids)} regular-season games; {len(pos_lookup)} roster positions loaded")
    if not pos_lookup:
        print(f"  WARN: no roster data for {season} — position_group will be empty", file=sys.stderr)

    team_stats, player_rows = parse_season(season, rs_ids, pos_lookup)
    def_avgs = compute_defense_loo_avgs(team_stats)
    player_game_out = build_player_game_output(player_rows, def_avgs)
    player_oqa_out  = build_player_oqa_season(player_game_out)

    return player_game_out, player_oqa_out, def_avgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season',    type=int, help='process only this season')
    ap.add_argument('--qa-player', default='', help='print game-by-game OQA for this player')
    ap.add_argument('--qa-season', type=int, default=None)
    args = ap.parse_args()

    seasons = [args.season] if args.season else sorted(
        int(p.name) for p in BOXSCORE_DIR.iterdir()
        if p.is_dir() and p.name.isdigit()
    )

    for season in seasons:
        print(f"\n── {season} ──────────────────────────────────────────────────────")
        pgo, poqa, def_avgs = process_season(season)
        if not pgo:
            print("  (no data)")
            continue

        write_csv(pgo,  OUTPUT_DIR / f"player_game_offense_{season}.csv")
        write_csv(poqa, OUTPUT_DIR / f"player_oqa_season_{season}.csv")

        def_avg_rows = [
            {**v, 'def_avg_sacks_taken': v.get('def_avg_sacks_taken')}
            for v in def_avgs.values()
        ]
        write_csv(def_avg_rows, OUTPUT_DIR / f"defense_loo_avg_{season}.csv")

        qa_s = args.qa_season or season
        if args.qa_player and season == qa_s:
            qa_player(args.qa_player, season, pgo)


if __name__ == '__main__':
    main()
