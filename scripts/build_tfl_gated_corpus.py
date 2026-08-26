#!/usr/bin/env python3
"""
Build a completeness-ratio-gated TFL corpus for gamebooks_boxscores' 1967-1977
season range, for use as IDI's TFL source in dpvs/idi.py.

WHY THIS EXISTS: a prior rebuild of IDI's TFL component used raw
games_observed as the denominator for a player's season tfl_share, which
produced degenerate values for small samples (1 TFL in 1 observed game =
share 1.0). This script fixes that by reusing gamebooks_boxscores' own
established completeness-ratio test (see that repo's
build_defensive_leaderboards.py, which this script imports directly rather
than re-deriving): team-side Solo+Ast / opponent(rush attempts + completions
+ times sacked) >= 0.70 qualifies a team-side's game for inclusion. Only
games where the player's team-side cleared that bar are counted, both for
the TFL numerator and the games_qualified denominator (n_obs) IDI's
empirical-Bayes shrinkage needs.

This covers all of 1967-1977 (build_defensive_leaderboards.py itself
defaults to 1967-1974 only; here we call its build() function directly for
1976 and 1977 too, confirmed to resolve cleanly via the DB ratio in both
seasons).

Output: season, team, player, tfl_sum, games_qualified — one row per
player-season with at least one qualifying game. tfl_sum/games_qualified
is the qualifying-games TFL rate (NOT a share of team total — dpvs/idi.py
computes the share itself from these summed numerator/denominator pairs,
same pattern as before).

Usage: python3 build_tfl_gated_corpus.py
    (needs football_db's .venv on PYTHONPATH — same requirement as
    gamebooks_boxscores/build_defensive_leaderboards.py itself)
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path.home() / "github" / "football" / "football_db" / "src"))
sys.path.insert(0, str(Path.home() / "github" / "football" / "gamebooks_boxscores"))

from football_db.db import get_connection  # noqa: E402
from build_defensive_leaderboards import (  # noqa: E402
    ABBR_TO_FID, GAMES_ROOT, THRESHOLD, parse_boxscore, text_classify,
)
from roster_name_resolver import GamebookRosterCanonicalizer  # noqa: E402
import json  # noqa: E402

SEASONS = list(range(1967, 1978))  # 1967-1977 inclusive
OUT_PATH = Path(__file__).resolve().parent.parent / "data_output" / "tfl_gamebooks_gated_1967_1977.csv"

# franchise_id -> gold-parquet-compatible team code. See
# build_tackle_gated_corpus.py's identical FID_TO_TEAM for the full
# rationale (2026-08-21 bug fix, docs/framework_decisions.md §14):
# gold.franchises.current_abbreviation (what this used to query) differs
# from gold parquet's team_pfref for 12 of 28 franchises, so this corpus's
# TFL numerator never matched onto dpvs/idi.py's merge for those
# franchises at all -- silently zero TFL coverage for Willie Lanier/KC,
# the Raiders, Rams, Cardinals, Colts, Packers, Saints, Patriots,
# Oilers/Titans, Chargers, 49ers, and Buccaneers for the entire
# 1967-1977 span, undetected until this pass's spot-checks.
FID_TO_TEAM: dict[int, str] = {
    16: "atl", 4: "buf", 2: "chi", 3: "cin", 6: "cle", 11: "clt", 8: "crd",
    13: "dal", 5: "den", 20: "det", 21: "gnb", 10: "kan", 14: "mia",
    32: "min", 27: "nor", 23: "nwe", 17: "nyg", 19: "nyj", 31: "oti",
    15: "phi", 29: "pit", 24: "rai", 25: "ram", 9: "sdg", 28: "sea",
    1: "sfo", 7: "tam", 12: "was",
}


def build(seasons: list[int]) -> pd.DataFrame:
    conn = get_connection()
    cur = conn.cursor()
    fid_to_abbr = FID_TO_TEAM

    raw = []
    resolved_ct, qual_ct, total_sides = 0, 0, 0

    for gdir in sorted(GAMES_ROOT.iterdir()):
        gid = gdir.name
        try:
            season = int(gid[:4])
        except ValueError:
            continue
        if season not in seasons:
            continue
        box_path, meta_path = gdir / "boxscore.md", gdir / "meta.json"
        if not box_path.exists() or not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        md_text = box_path.read_text()
        home_ab, away_ab = meta['home_team'].lower(), meta['away_team'].lower()
        home_fid, away_fid = ABBR_TO_FID.get(home_ab), ABBR_TO_FID.get(away_ab)

        tstats, db_resolved = {}, False
        pfr_game_id = f"{meta['content_date']}0{meta['home_team']}"
        cur.execute(
            "SELECT game_id FROM internal.game_xref WHERE source_system='pfr' AND source_game_id=%s",
            (pfr_game_id,),
        )
        r = cur.fetchone()
        if r:
            cur.execute(
                "SELECT franchise_id, rush_attempts, pass_completions, times_sacked "
                "FROM gold.team_game_stats WHERE game_id=%s", (r[0],))
            rows_ = cur.fetchall()
            if rows_:
                db_resolved = True
                tstats = {row[0]: {'rush': row[1] or 0, 'cmp': row[2] or 0, 'sacked': row[3] or 0} for row in rows_}

        text_verdict = None

        for sec in parse_boxscore(md_text):
            total_sides += 1
            abbrev = sec['abbrev']
            if abbrev == home_ab or ABBR_TO_FID.get(abbrev) == home_fid:
                own_fid, opp_fid = home_fid, away_fid
            elif abbrev == away_ab or ABBR_TO_FID.get(abbrev) == away_fid:
                own_fid, opp_fid = away_fid, home_fid
            else:
                own_fid = ABBR_TO_FID.get(abbrev)
                opp_fid = away_fid if own_fid == home_fid else (home_fid if own_fid == away_fid else None)
            if own_fid is None or opp_fid is None:
                continue

            qualifies = False
            if db_resolved and opp_fid in tstats:
                opp = tstats[opp_fid]
                opportunities = opp['rush'] + opp['cmp'] + opp['sacked']
                if opportunities > 0:
                    resolved_ct += 1
                    tt = sec['team_total']
                    team_tkl = (tt['solo'] + tt['ast']) if tt else sum(rw['solo'] + rw['ast'] for rw in sec['rows'])
                    if (team_tkl / opportunities) >= THRESHOLD:
                        qualifies = True
            else:
                if text_verdict is None:
                    text_verdict = text_classify(md_text)
                qualifies = text_verdict

            if qualifies:
                qual_ct += 1

            for rw in sec['rows']:
                raw.append({
                    'season': season, 'fid': own_fid, 'name': rw['name'],
                    'tfl': rw['run_stuff'], 'qualifies': qualifies,
                })

    print(f"  sides={total_sides} db_resolved={resolved_ct} qualifying={qual_ct}")

    # Canonical name merge: roster-based, not a text heuristic (2026-08-21
    # rewrite -- see roster_name_resolver.py's module docstring for why the
    # prior pure-text heuristic left real players fragmented, e.g. Jack
    # Lambert's 1976 PIT TFL total split across "Jack Lambert"/"J. Lambert"/
    # "J.Lambert"/"Lambert" because "Jack Lambert" and any comma-order
    # variant both looked like distinct "full" names to that heuristic).
    #
    # For each (season, franchise_id) group, every distinct raw name string
    # is resolved against football_db's real team-season roster
    # (silver.player_team_seasons_pfr + gold.players, same source
    # lookup_roster.py and parse_pfr_pbp.py's RosterResolver use):
    #   - unique surname match on that roster -> merge ALL format variants
    #     (comma-order, initials, bare surname, paren-qualified) to that
    #     one player's canonical full_name
    #   - 2+ roster players share the surname -> disambiguate via first
    #     name/initial; genuinely ambiguous -> do NOT guess, keep separate
    #   - jersey-number-only rows ("56") and unresolved/ambiguous markers
    #     ("Smith (unresolved)") -> excluded from the per-player numerator
    #     entirely (never guessed onto a player); they were never part of
    #     the team-total/ratio computation above either (team_tkl/qualifies
    #     comes from sec['team_total'] or the raw parse_boxscore() rows
    #     directly, not from this per-name step), so this exclusion only
    #     affects which names appear in the final per-player output
    #   - no roster surname match at all (likely OCR garbage, e.g.
    #     "Wilting Heashoff") -> left unmatched/unmerged, still counted
    #     under its own normalized name rather than dropped or guessed
    canonicalizer = GamebookRosterCanonicalizer(conn)
    canon = {}       # (season, fid, raw_name) -> canonical display name
    excluded = set()  # (season, fid, raw_name) to drop from output entirely

    names_by_team = defaultdict(set)
    for r in raw:
        names_by_team[(r['season'], r['fid'])].add(r['name'])
    for (season, fid), names in names_by_team.items():
        for n in names:
            res = canonicalizer.resolve(n, season, fid)
            if res.status in ('excluded_jersey', 'excluded_marker'):
                excluded.add((season, fid, n))
            elif res.status in ('matched_unique', 'matched_disambiguated'):
                canon[(season, fid, n)] = res.canonical_name
            # 'ambiguous' / 'unmatched': leave unmerged -- keep r['name'] as-is

    canonicalizer.print_stats()

    tfl_sum = defaultdict(float)
    games_qual = defaultdict(int)
    for r in raw:
        if not r['qualifies']:
            continue
        rkey = (r['season'], r['fid'], r['name'])
        if rkey in excluded:
            continue
        name = canon.get(rkey, r['name'])
        key = (r['season'], r['fid'], name)
        tfl_sum[key] += r['tfl']
        games_qual[key] += 1

    rows = []
    for key in games_qual:
        season, fid, name = key
        rows.append({
            'season': season,
            'team': fid_to_abbr.get(fid, '??').lower(),
            'player': name,
            'tfl_sum': tfl_sum[key],
            'games_qualified': games_qual[key],
        })
    return pd.DataFrame(rows)


def main():
    df = build(SEASONS)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"wrote {len(df)} player-seasons -> {OUT_PATH}")
    print(df.groupby('season').size())


if __name__ == '__main__':
    main()
