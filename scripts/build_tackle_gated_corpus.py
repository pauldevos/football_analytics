#!/usr/bin/env python3
"""
Build a completeness-ratio-gated TACKLE corpus for gamebooks_boxscores'
1967-1977 season range, for use as IDI's tackle_share source in dpvs/idi.py.

WHY THIS EXISTS: dpvs/idi.py's load_all_gamebook_idi() read
~/data/gamebooks_processed/teams/{team}/seasons/{season}_defense.csv — a
path that does not exist on this machine at all (confirmed directly, and
by build_dpvs_g.py's own run log printing "Gamebook tackle data: 0
player-seasons"). So tackle_share_z (IDI's highest-weighted single
component, 0.23) has been silently NaN for essentially all of 1967-1977,
with IDI's gated-component rebalancing (see idi.py's _idi_row /
_GATED_COMPONENTS) absorbing the gap by spreading that weight across the
other four components rather than using real tackle data.

This is a direct structural clone of build_tfl_gated_corpus.py (same
directory) — same completeness-ratio gate (team-side Solo+Ast / opponent
(rush attempts + completions + times sacked) >= THRESHOLD=0.70, imported
directly from gamebooks_boxscores' build_defensive_leaderboards.py rather
than re-derived), same roster-based name canonicalization
(roster_name_resolver.py's GamebookRosterCanonicalizer), same 1967-1977
season range. The only difference: this script sums each player's
Solo+Ast (tackle count) per qualifying game instead of TFL.

Checked before building this: gamebooks_boxscores/outputs/ and
~/data/gamebooks_v2/defensive_leaderboards.json both already compute
season tackle numbers with this same gate, but defensive_leaderboards.json
truncates to the top-15 tacklers per season (per its own module
docstring) — not a full population, so not usable as a season-wide
z-score denominator (mean/sd need the whole population, not the visible
top slice). Hence this full-population build.

Output: season, team, player, tackle_sum, games_qualified — one row per
player-season with at least one qualifying game. tackle_sum/games_qualified
is the qualifying-games tackle rate; dpvs/idi.py computes shrinkage/z-score
treatment from these summed numerator/denominator pairs, same pattern as
the TFL corpus.

Usage: python3 build_tackle_gated_corpus.py
    (needs football_db's .venv on PYTHONPATH — same requirement as
    build_tfl_gated_corpus.py and gamebooks_boxscores/build_defensive_leaderboards.py)
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
OUT_PATH = Path(__file__).resolve().parent.parent / "data_output" / "tackle_gamebooks_gated_1967_1977.csv"

# franchise_id -> gold-parquet-compatible team code (the historic PFR-style
# code idi.py's merge keys use, e.g. "kan" not "kc", "rai" not "lv"), NOT
# gold.franchises.current_abbreviation. Identical to dpvs/idi.py's own
# _FID_TO_TEAM (kept as a separate copy here to avoid a cross-package
# import from a scripts/ file into dpvs/ -- must stay in sync with it).
#
# 2026-08-21 bug fix (found while wiring in the tackle_share corpus, see
# docs/framework_decisions.md §14): the code this replaced queried
# gold.franchises.current_abbreviation directly, which differs from gold
# parquet's team_pfref for 12 of 28 franchises (clt->ind, crd->ari,
# gnb->gb, kan->kc, nor->no, nwe->ne, oti->ten, rai->lv, ram->lar,
# sdg->lac, sfo->sf, tam->tb) -- confirmed directly against
# gold.franchises. Since dpvs/idi.py merges this corpus onto its own
# frame on the "team" column, using current_abbreviation meant those 12
# franchises' entire gamebook-era TFL/tackle numerator NEVER matched at
# all (Willie Lanier/KC, the Raiders' 1967 leaderboard-topping front
# four, etc. all silently zeroed) -- this affected build_tfl_gated_corpus.py
# too (same bug, same fix needed there).
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
                    'tackle': rw['solo'] + rw['ast'], 'qualifies': qualifies,
                })

    print(f"  sides={total_sides} db_resolved={resolved_ct} qualifying={qual_ct}")

    # Canonical name merge: same roster-based resolver used by
    # build_tfl_gated_corpus.py (see roster_name_resolver.py's module
    # docstring) — reused directly, not reimplemented.
    canonicalizer = GamebookRosterCanonicalizer(conn)
    canon = {}
    excluded = set()

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

    tackle_sum = defaultdict(float)
    games_qual = defaultdict(int)
    for r in raw:
        if not r['qualifies']:
            continue
        rkey = (r['season'], r['fid'], r['name'])
        if rkey in excluded:
            continue
        name = canon.get(rkey, r['name'])
        key = (r['season'], r['fid'], name)
        tackle_sum[key] += r['tackle']
        games_qual[key] += 1

    rows = []
    for key in games_qual:
        season, fid, name = key
        rows.append({
            'season': season,
            'team': fid_to_abbr.get(fid, '??').lower(),
            'player': name,
            'tackle_sum': tackle_sum[key],
            'games_qualified': games_qual[key],
        })
    return pd.DataFrame(rows)


def main():
    df = build(SEASONS)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"wrote {len(df)} player-seasons -> {OUT_PATH}")
    print(df.groupby('season').size())

    # Quick quasi-Poisson overdispersion estimate for this stat (same
    # method-of-moments idea idi.py's TFL/INT/FF _PHI values came from —
    # season-pooled population rate as mu, Pearson chi-square / (N-1)),
    # printed here so the resulting k can be hand-derived the same way as
    # _K0 / (phi - 1) in dpvs/idi.py. Not persisted -- informational only.
    season_rate = df.groupby('season').apply(
        lambda g: g['tackle_sum'].sum() / g['games_qualified'].sum()
    )
    d = df.copy()
    d['mu'] = d['season'].map(season_rate)
    d['expected'] = d['games_qualified'] * d['mu']
    d['pearson_resid2'] = (d['tackle_sum'] - d['expected']) ** 2 / d['expected']
    phi = d['pearson_resid2'].sum() / (len(d) - d['season'].nunique())
    print(f"quasi-Poisson overdispersion (phi) for tackle, season-pooled rate: {phi:.3f}")


if __name__ == '__main__':
    main()
