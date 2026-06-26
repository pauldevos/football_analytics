#!/usr/bin/env python3
"""
build_game_defense.py  (v2)

Builds:
  ~/data/silver/game_defense.parquet        — one row per game × defending team
  ~/data/silver/player_game_defense.parquet — one row per game × defensive participant

Participation = named starter (starters.csv) OR ≥MIN_STAT_EVENTS events in
player_defense.csv.  Pre-2001 tackles are blank so participation defaults to
starters only for those years.

TDGS (Team Defense Game Score) uses a dual-benchmark z-score:
  yds_credit = 0.5*(league_avg_yds - yds_allowed) + 0.5*(opp_avg_yds - yds_allowed)
  pts_credit = 0.5*(league_avg_pts - pts_allowed) + 0.5*(opp_avg_pts - pts_allowed)
  TDGS = 0.55*(yds_credit/season_std_yds) + 0.45*(pts_credit/season_std_pts)

Usage:
  python scripts/build_game_defense.py --seasons 1969 --teams min
  python scripts/build_game_defense.py --seasons 1969-2000 --report min atl rav
  python scripts/build_game_defense.py --seasons 1978-2024
"""

import sys
import argparse
import pandas as pd
import numpy as np
from pathlib import Path

BOXSCORES_DIR  = Path.home() / 'data/pfref/raw/boxscores'
OFF_STATS_DIR  = Path.home() / 'data/pfref/raw/season/team/offense/team_stats'
OFF_SCORE_DIR  = Path.home() / 'data/pfref/raw/season/team/offense/team_scoring'
SILVER_DIR     = Path.home() / 'data/silver'

MIN_STAT_EVENTS = 4   # min defensive stat events to qualify as non-starter participant

_OFF_POS = frozenset({
    'QB','RB','FB','HB','TB','WB','WR','FL','SE','OE','TE',
    'T','G','C','OT','OG','OL','LT','RT','LG','RG','K','P','LS',
    'KR','PR','DP',
})


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe_int(s) -> int | None:
    try:
        return int(str(s).strip())
    except (ValueError, TypeError):
        return None


def _safe_float(s) -> float | None:
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


# ── name map ─────────────────────────────────────────────────────────────────

def _load_name_map() -> dict[str, str]:
    """PFR full team name → lowercase PFR abbreviation."""
    fmap = Path.home() / 'data/pfref/franchise_abbrev_map.csv'
    d: dict[str, str] = {}
    if fmap.exists():
        df = pd.read_csv(fmap)
        for _, r in df.iterrows():
            abbr = str(r['pfr_abbrev']).lower()
            d[r['canonical_name'].lower()] = abbr
            if pd.notna(r.get('directory', '')):
                d[str(r['directory']).lower().replace('_', ' ')] = abbr
    d.update({
        'los angeles raiders': 'rai', 'oakland raiders': 'rai',
        'las vegas raiders': 'rai',
        'los angeles rams': 'ram', 'st. louis rams': 'ram',
        'st. louis cardinals': 'crd', 'arizona cardinals': 'crd',
        'phoenix cardinals': 'crd',
        'houston oilers': 'oti', 'tennessee oilers': 'oti',
        'tennessee titans': 'oti',
        'baltimore colts': 'clt', 'indianapolis colts': 'clt',
        'baltimore ravens': 'rav',
        'san diego chargers': 'sdg', 'los angeles chargers': 'sdg',
        'kansas city chiefs': 'kan',
        'new england patriots': 'nwe', 'boston patriots': 'nwe',
        'new york jets': 'nyj', 'new york giants': 'nyg',
        'san francisco 49ers': 'sfo',
        'green bay packers': 'gnb',
        'washington redskins': 'was', 'washington football team': 'was',
        'washington commanders': 'was',
        'cleveland browns': 'cle', 'pittsburgh steelers': 'pit',
        'dallas cowboys': 'dal', 'philadelphia eagles': 'phi',
        'chicago bears': 'chi', 'detroit lions': 'det',
        'minnesota vikings': 'min', 'atlanta falcons': 'atl',
        'new orleans saints': 'nor', 'tampa bay buccaneers': 'tam',
        'seattle seahawks': 'sea', 'denver broncos': 'den',
        'buffalo bills': 'buf', 'miami dolphins': 'mia',
        'cincinnati bengals': 'cin',
        'jacksonville jaguars': 'jax',
        'carolina panthers': 'car',
    })
    return d


# ── season-level data ─────────────────────────────────────────────────────────

def _load_league_averages(seasons: list[int]) -> dict[int, dict]:
    """
    Returns {season: {avg_yds, avg_pts, std_yds, std_pts}}
    from offense team_stats files.  These are per-game averages.
    """
    result: dict[int, dict] = {}
    for season in seasons:
        yf = OFF_STATS_DIR  / f'team_stats_{season}.csv'
        sf = OFF_SCORE_DIR  / f'team_scoring_{season}.csv'
        if not yf.exists():
            continue
        dy = pd.read_csv(yf)
        dy['yds_per_g'] = dy['total_yards'].astype(float) / dy['g'].astype(float)
        rec: dict[str, float] = {
            'avg_yds': dy['yds_per_g'].mean(),
            'std_yds': dy['yds_per_g'].std(),
        }
        if sf.exists():
            ds = pd.read_csv(sf)
            ds['pts_per_g'] = ds['scoring'].astype(float) / ds['g'].astype(float)
            rec['avg_pts'] = ds['pts_per_g'].mean()
            rec['std_pts'] = ds['pts_per_g'].std()
        else:
            # fall back to points column in team_stats if present
            if 'points' in dy.columns:
                dy['pts_per_g'] = dy['points'].astype(float) / dy['g'].astype(float)
                rec['avg_pts'] = dy['pts_per_g'].mean()
                rec['std_pts'] = dy['pts_per_g'].std()
        result[season] = rec
    return result


def _load_opp_averages(seasons: list[int],
                        name_map: dict[str, str]) -> dict[tuple[int, str], dict]:
    """
    Returns {(season, pfr_abbrev): {avg_yds, avg_pts}}
    representing each team's offensive production per game.
    """
    result: dict[tuple[int, str], dict] = {}

    def _resolve(name: str) -> str | None:
        k = name.lower().strip()
        abbr = name_map.get(k)
        if not abbr:
            for key, val in name_map.items():
                if key in k or k in key:
                    abbr = val
                    break
        return abbr

    for season in seasons:
        yf = OFF_STATS_DIR / f'team_stats_{season}.csv'
        sf = OFF_SCORE_DIR / f'team_scoring_{season}.csv'

        if yf.exists():
            dy = pd.read_csv(yf)
            for _, r in dy.iterrows():
                abbr = _resolve(str(r['team']))
                if abbr:
                    g = int(r['g']) if str(r['g']).isdigit() else 16
                    result.setdefault((season, abbr), {})
                    result[(season, abbr)]['avg_yds'] = round(
                        float(r['total_yards']) / g, 1)
                    if 'points' in r:
                        result.setdefault((season, abbr), {})
                        result[(season, abbr)].setdefault(
                            'avg_pts', round(float(r['points']) / g, 1))

        if sf.exists():
            ds = pd.read_csv(sf)
            for _, r in ds.iterrows():
                abbr = _resolve(str(r['team']))
                if abbr:
                    g = int(r['g']) if str(r['g']).isdigit() else 16
                    result.setdefault((season, abbr), {})
                    result[(season, abbr)]['avg_pts'] = round(
                        float(r['scoring']) / g, 1)

    return result


# ── team_stats parsing ────────────────────────────────────────────────────────

def _parse_team_stats(path: Path) -> dict:
    """Parse team_stats.csv into {vis: {...}, home: {...}} dicts."""
    df = pd.read_csv(path)
    out: dict[str, dict] = {'vis': {}, 'home': {}}
    for _, row in df.iterrows():
        name = str(row['stat_name']).strip()
        for side in ('vis', 'home'):
            val = str(row[f'{side}_value']).strip()
            if name == 'Total Yards':
                out[side]['total_yds'] = _safe_int(val)
            elif name == 'Net Pass Yards':
                out[side]['pass_yds'] = _safe_int(val)
            elif name.startswith('Rush-Yds'):
                p = val.split('-')
                out[side]['rush_att'] = _safe_int(p[0]) if p else None
                out[side]['rush_yds'] = _safe_int(p[1]) if len(p) > 1 else None
            elif name.startswith('Cmp-Att'):
                p = val.split('-')
                out[side]['cmp'] = _safe_int(p[0]) if p else None
                out[side]['att'] = _safe_int(p[1]) if len(p) > 1 else None
            elif name == 'First Downs':
                out[side]['first_downs'] = _safe_int(val)
            elif name.startswith('Sacked'):
                p = val.split('-')
                out[side]['sacked_n']   = _safe_int(p[0]) if p else None
                out[side]['sacked_yds'] = _safe_int(p[1]) if len(p) > 1 else None
            elif name == 'Turnovers':
                out[side]['turnovers'] = _safe_int(val)
    return out


def _get_game_scores(game_dir: Path) -> tuple[int | None, int | None]:
    """Return (vis_score, home_score) from scoring.csv or pbp.csv."""
    sc = game_dir / 'scoring.csv'
    if sc.exists():
        df = pd.read_csv(sc)
        if not df.empty and 'vis_team_score' in df.columns:
            last = df.iloc[-1]
            return _safe_int(last['vis_team_score']), _safe_int(last['home_team_score'])
    pb = game_dir / 'pbp.csv'
    if pb.exists():
        df = pd.read_csv(pb).dropna(subset=['pbp_score_aw', 'pbp_score_hm'])
        if not df.empty:
            last = df.iloc[-1]
            return _safe_int(last['pbp_score_aw']), _safe_int(last['pbp_score_hm'])
    return None, None


# ── participation ─────────────────────────────────────────────────────────────

def _count_stat_events(row) -> int:
    """Count defensive stat events for a player_defense.csv row."""
    sacks    = _safe_float(row.get('sacks', 0)) or 0.0
    ints     = _safe_int(row.get('def_int', 0)) or 0
    frs      = _safe_int(row.get('fumbles_rec', 0)) or 0
    ffs      = _safe_int(row.get('fumbles_forced', 0)) or 0
    tackles  = _safe_int(row.get('tackles_combined', 0)) or 0
    sack_ev  = 1 if sacks >= 0.5 else 0
    return sack_ev + ints + frs + ffs + tackles


def _filter_pdef_team(pdf: pd.DataFrame, def_abbr: str, off_abbr: str) -> pd.DataFrame:
    """
    Filter player_defense.csv to rows for the defending team.
    player_defense.csv uses NFL/media team codes (RAI, BAL, HOU, JAX…) while
    team_stats.csv uses PFR internal codes (rai, rav, oti, jax…).
    Strategy: try lowercase direct match; on failure use by-exclusion.
    """
    # Direct lowercase match (covers most teams: min, dal, phi, rai, jax, etc.)
    def_rows = pdf[pdf['team'].str.lower() == def_abbr]
    if len(def_rows) > 0:
        return def_rows
    # Try off team match and exclude those rows
    off_rows = pdf[pdf['team'].str.lower() == off_abbr]
    if len(off_rows) > 0:
        off_code = off_rows['team'].iloc[0]
        rest = pdf[pdf['team'] != off_code]
        if len(rest) > 0:
            return rest
    return pdf.iloc[0:0]  # empty


def _get_defense_participants(
    game_dir: Path,
    def_abbr: str,
    off_abbr: str,
    starters_df: pd.DataFrame,
    min_events: int = MIN_STAT_EVENTS,
) -> dict[str, dict]:
    """
    Build defensive participation dict: pfr_player_id → attrs.
    Participation = named starter (starters.csv) OR ≥min_events stat events.
    """
    parts: dict[str, dict] = {}

    # 1. Named defensive starters
    def_starts = starters_df[
        (starters_df['team_abbrev'] == def_abbr) &
        (~starters_df['pos'].isin(_OFF_POS))
    ]
    for _, r in def_starts.iterrows():
        pid = str(r['pfr_player_id'])
        parts[pid] = {
            'pfr_player_id': pid,
            'player_name':   str(r['player']),
            'pos':           str(r['pos']),
            'is_starter':    True,
            'stat_events':   0,
        }

    # 2. Supplement from player_defense.csv
    pdef_file = game_dir / 'player_defense.csv'
    if pdef_file.exists():
        pdf = pd.read_csv(pdef_file)
        def_rows = _filter_pdef_team(pdf, def_abbr, off_abbr)

        for _, r in def_rows.iterrows():
            pid    = str(r['pfr_player_id'])
            events = _count_stat_events(r)
            if pid in parts:
                parts[pid]['stat_events'] = events
            elif events >= min_events:
                parts[pid] = {
                    'pfr_player_id': pid,
                    'player_name':   str(r['player']),
                    'pos':           '',
                    'is_starter':    False,
                    'stat_events':   events,
                }

    return parts


# ── TDGS formula ──────────────────────────────────────────────────────────────

def _compute_tdgs(
    yds_allowed:  int | None,
    pts_allowed:  int | None,
    opp_avg_yds:  float | None,
    opp_avg_pts:  float | None,
    lg_avg_yds:   float | None,
    lg_avg_pts:   float | None,
    lg_std_yds:   float | None,
    lg_std_pts:   float | None,
) -> float | None:
    """
    TDGS = 0.55 * yds_z + 0.45 * pts_z
    where each z = credit / season_std and
    credit = 0.5*(vs_league) + 0.5*(vs_opponent).
    Falls back to league-only if opponent average unavailable.
    """
    if yds_allowed is None or pts_allowed is None:
        return None
    if not lg_std_yds or not lg_std_pts:
        return None

    # Yards component
    yds_credits = []
    if lg_avg_yds is not None:
        yds_credits.append(lg_avg_yds - yds_allowed)
    if opp_avg_yds is not None:
        yds_credits.append(opp_avg_yds - yds_allowed)
    if not yds_credits:
        return None
    yds_z = (sum(yds_credits) / len(yds_credits)) / lg_std_yds

    # Points component
    pts_credits = []
    if lg_avg_pts is not None:
        pts_credits.append(lg_avg_pts - pts_allowed)
    if opp_avg_pts is not None:
        pts_credits.append(opp_avg_pts - pts_allowed)
    if not pts_credits:
        return None
    pts_z = (sum(pts_credits) / len(pts_credits)) / lg_std_pts

    return round(0.55 * yds_z + 0.45 * pts_z, 4)


# ── main build ────────────────────────────────────────────────────────────────

def build(
    seasons: list[int],
    team_filter: list[str] | None = None,
    min_stat_events: int = MIN_STAT_EVENTS,
) -> tuple[pd.DataFrame, pd.DataFrame]:

    name_map  = _load_name_map()
    opp_avgs  = _load_opp_averages(seasons, name_map)
    lg_avgs   = _load_league_averages(seasons)

    game_rows:   list[dict] = []
    player_rows: list[dict] = []

    for season in seasons:
        season_dir = BOXSCORES_DIR / str(season)
        if not season_dir.exists():
            print(f"  {season}: no boxscores directory", file=sys.stderr)
            continue

        lg = lg_avgs.get(season, {})
        lg_avg_yds = lg.get('avg_yds')
        lg_avg_pts = lg.get('avg_pts')
        lg_std_yds = lg.get('std_yds')
        lg_std_pts = lg.get('std_pts')

        game_dirs = [d for d in sorted(season_dir.iterdir()) if d.is_dir()]
        print(f"  {season}: {len(game_dirs)} games", end='', flush=True)
        processed = 0

        for game_dir in game_dirs:
            stats_file    = game_dir / 'team_stats.csv'
            starters_file = game_dir / 'starters.csv'
            if not stats_file.exists() or not starters_file.exists():
                continue

            raw = pd.read_csv(stats_file)
            if raw.empty:
                continue

            game_id   = str(raw.iloc[0]['game_id'])
            home_abbr = str(raw.iloc[0]['home_abbrev']).lower()
            vis_abbr  = str(raw.iloc[0]['vis_abbrev']).lower()

            if team_filter and not (home_abbr in team_filter or vis_abbr in team_filter):
                continue

            stats       = _parse_team_stats(stats_file)
            starters_df = pd.read_csv(starters_file)
            vis_score, home_score = _get_game_scores(game_dir)

            for (off_side, def_side, off_abbr, def_abbr) in [
                ('vis', 'home', vis_abbr, home_abbr),
                ('home', 'vis', home_abbr, vis_abbr),
            ]:
                allowed = stats.get(off_side, {})

                rush_yds  = allowed.get('rush_yds')
                pass_yds  = allowed.get('pass_yds')
                total_yds = allowed.get('total_yds') or (
                    (rush_yds or 0) + (pass_yds or 0) if (rush_yds or pass_yds) else None
                )
                pts_allowed = vis_score if off_side == 'vis' else home_score

                opp_key     = (season, off_abbr)
                opp_avg_yds = opp_avgs.get(opp_key, {}).get('avg_yds')
                opp_avg_pts = opp_avgs.get(opp_key, {}).get('avg_pts')

                oqa_yds = round(opp_avg_yds - total_yds, 1) if (
                    opp_avg_yds and total_yds) else None
                oqa_pts = round(opp_avg_pts - pts_allowed, 1) if (
                    opp_avg_pts and pts_allowed is not None) else None

                tdgs = _compute_tdgs(
                    total_yds, pts_allowed,
                    opp_avg_yds, opp_avg_pts,
                    lg_avg_yds, lg_avg_pts,
                    lg_std_yds, lg_std_pts,
                )

                game_rows.append({
                    'game_id':             game_id,
                    'season':              season,
                    'team':                def_abbr,
                    'opponent':            off_abbr,
                    'pts_allowed':         pts_allowed,
                    'rush_yds_allowed':    rush_yds,
                    'pass_yds_allowed':    pass_yds,
                    'total_yds_allowed':   total_yds,
                    'rush_att_vs':         allowed.get('rush_att'),
                    'cmp_vs':              allowed.get('cmp'),
                    'att_vs':              allowed.get('att'),
                    'sacks_made':          allowed.get('sacked_n'),
                    'turnovers_forced':    allowed.get('turnovers'),
                    'opp_avg_yds_offense': opp_avg_yds,
                    'opp_avg_pts_offense': opp_avg_pts,
                    'league_avg_yds':      round(lg_avg_yds, 1) if lg_avg_yds else None,
                    'league_avg_pts':      round(lg_avg_pts, 1) if lg_avg_pts else None,
                    'oqa_yds_surplus':     oqa_yds,
                    'oqa_pts_surplus':     oqa_pts,
                    'tdgs':                tdgs,
                })

                # Participation
                parts = _get_defense_participants(
                    game_dir, def_abbr, off_abbr, starters_df, min_stat_events
                )
                n_parts = len(parts)
                credit  = round(tdgs / n_parts, 5) if (tdgs is not None and n_parts > 0) else None

                for pid, p in parts.items():
                    player_rows.append({
                        'game_id':          game_id,
                        'season':           season,
                        'team':             def_abbr,
                        'pfr_player_id':    pid,
                        'player_name':      p['player_name'],
                        'pos':              p['pos'],
                        'is_starter':       p['is_starter'],
                        'stat_events':      p['stat_events'],
                        'tdgs':             tdgs,
                        'n_participants':   n_parts,
                        'team_credit_share': credit,
                    })

            processed += 1

        print(f" → {processed} parsed", flush=True)

    return pd.DataFrame(game_rows), pd.DataFrame(player_rows)


# ── WOWY rollup ───────────────────────────────────────────────────────────────

def compute_wowy(player_df: pd.DataFrame, game_df: pd.DataFrame) -> pd.DataFrame:
    """Per player-season: avg TDGS with vs. without them in the lineup."""
    rows = []
    for (season, pid, name, team), grp in player_df.groupby(
            ['season', 'pfr_player_id', 'player_name', 'team']):
        games_w   = set(grp['game_id'])
        avg_w     = grp['tdgs'].mean()
        team_games = game_df[(game_df['season'] == season) & (game_df['team'] == team)]
        games_wo  = team_games[~team_games['game_id'].isin(games_w)]
        n_out     = len(games_wo)
        avg_wo    = games_wo['tdgs'].mean() if n_out > 0 else None
        rows.append({
            'season':        season,
            'pfr_player_id': pid,
            'player_name':   name,
            'team':          team,
            'games_in':      len(games_w),
            'games_out':     n_out,
            'tdgs_with':     round(avg_w, 4),
            'tdgs_without':  round(avg_wo, 4) if avg_wo is not None else None,
            'wowy_delta':    round(avg_w - avg_wo, 4) if avg_wo is not None else None,
        })
    return pd.DataFrame(rows).sort_values(['season', 'wowy_delta'],
                                           ascending=[True, False],
                                           na_position='last')


# ── season report ─────────────────────────────────────────────────────────────

def print_season_report(game_df: pd.DataFrame, player_df: pd.DataFrame,
                         report_teams: list[str]) -> None:
    """Print season-level TDGS summaries and top defenders for report_teams."""
    print("\n" + "="*72)
    print("TEAM DEFENSE GAME SCORE — SEASON REPORT")
    print("="*72)

    for team in report_teams:
        tg = game_df[game_df['team'] == team].copy()
        if tg.empty:
            print(f"\n  {team.upper()}: no data")
            continue

        for season in sorted(tg['season'].unique()):
            sg = tg[tg['season'] == season].sort_values('game_id')
            n  = len(sg)
            avg_tdgs  = sg['tdgs'].mean()
            avg_yds   = sg['total_yds_allowed'].mean()
            avg_pts   = sg['pts_allowed'].mean()
            lg_yds    = sg['league_avg_yds'].iloc[0]
            lg_pts    = sg['league_avg_pts'].iloc[0]

            print(f"\n{team.upper()} {season}  ({n} games)")
            print(f"  season TDGS avg:  {avg_tdgs:+.3f}")
            print(f"  yds allowed/g:    {avg_yds:.1f}  (league avg: {lg_yds:.1f})")
            print(f"  pts allowed/g:    {avg_pts:.1f}  (league avg: {lg_pts:.1f})")

            # Top 3 and bottom 2 games
            best  = sg.nlargest(3, 'tdgs')[['game_id','opponent','total_yds_allowed',
                                             'pts_allowed','oqa_yds_surplus',
                                             'oqa_pts_surplus','tdgs']]
            worst = sg.nsmallest(2, 'tdgs')[['game_id','opponent','total_yds_allowed',
                                              'pts_allowed','oqa_yds_surplus',
                                              'oqa_pts_surplus','tdgs']]
            print("  Best games:")
            for _, r in best.iterrows():
                print(f"    {r['game_id']}  vs {r['opponent']:5s}  "
                      f"{r['total_yds_allowed']:.0f}yds  {r['pts_allowed']:.0f}pts  "
                      f"oqa_y={r['oqa_yds_surplus']:+.0f}  oqa_p={r['oqa_pts_surplus']:+.1f}  "
                      f"TDGS={r['tdgs']:+.3f}")
            print("  Worst games:")
            for _, r in worst.iterrows():
                print(f"    {r['game_id']}  vs {r['opponent']:5s}  "
                      f"{r['total_yds_allowed']:.0f}yds  {r['pts_allowed']:.0f}pts  "
                      f"oqa_y={r['oqa_yds_surplus']:+.0f}  oqa_p={r['oqa_pts_surplus']:+.1f}  "
                      f"TDGS={r['tdgs']:+.3f}")

            # Top players by accumulated team_credit_share
            tp = player_df[
                (player_df['team'] == team) & (player_df['season'] == season)
            ].groupby(['pfr_player_id', 'player_name', 'pos'], as_index=False).agg(
                games=('game_id', 'count'),
                total_credit=('team_credit_share', 'sum'),
                avg_stat_events=('stat_events', 'mean'),
            ).sort_values('total_credit', ascending=False).head(15)
            tp['per_game_credit'] = tp['total_credit'] / tp['games']

            print("  Top defenders (accumulated team credit — per-game credit is game-specific):")
            print(f"    {'Player':22s} {'Pos':6s}  {'G':>3}  {'Total':>8}  {'Per-G':>7}  Stat-ev/g")
            for _, r in tp.iterrows():
                print(f"    {r['player_name']:22s} {r['pos']:6s}  "
                      f"{r['games']:3.0f}  "
                      f"{r['total_credit']:+8.3f}  "
                      f"{r['per_game_credit']:+7.3f}  "
                      f"{r['avg_stat_events']:.1f}")


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='1978-2000',
                    help='Range like 1969-2000 or single year like 1969')
    ap.add_argument('--teams', nargs='*', default=None,
                    help='Filter to specific teams (e.g. min rav atl)')
    ap.add_argument('--report', nargs='*', default=None,
                    help='Print season report for these teams after build')
    ap.add_argument('--min-events', type=int, default=MIN_STAT_EVENTS,
                    help='Min stat events to qualify as non-starter participant')
    ap.add_argument('--out-game',
                    default=str(SILVER_DIR / 'game_defense.parquet'))
    ap.add_argument('--out-player',
                    default=str(SILVER_DIR / 'player_game_defense.parquet'))
    ap.add_argument('--out-wowy',
                    default=str(SILVER_DIR / 'player_season_wowy.parquet'))
    ap.add_argument('--no-save', action='store_true',
                    help='Skip saving parquets (useful with --report for quick checks)')
    args = ap.parse_args()

    if '-' in args.seasons and not args.seasons.startswith('-'):
        lo, hi = args.seasons.split('-', 1)
        seasons = list(range(int(lo), int(hi) + 1))
    else:
        seasons = [int(args.seasons)]

    print(f"Building game_defense for seasons {seasons[0]}–{seasons[-1]}")
    if args.teams:
        print(f"  Filtering to teams: {args.teams}")
    print(f"  Min stat events for non-starter participation: {args.min_events}")

    game_df, player_df = build(seasons, team_filter=args.teams,
                                min_stat_events=args.min_events)

    print(f"\ngame_defense:        {len(game_df):,} rows")
    print(f"player_game_defense: {len(player_df):,} rows")

    if not args.no_save:
        wowy_df = compute_wowy(player_df, game_df)
        print(f"player_season_wowy:  {len(wowy_df):,} rows")
        game_df.to_parquet(args.out_game,   index=False)
        player_df.to_parquet(args.out_player, index=False)
        wowy_df.to_parquet(args.out_wowy,   index=False)
        print(f"\nSaved: {args.out_game}")
        print(f"       {args.out_player}")
        print(f"       {args.out_wowy}")

    report_teams = args.report or (args.teams or [])
    if report_teams:
        print_season_report(game_df, player_df, report_teams)


if __name__ == '__main__':
    main()
