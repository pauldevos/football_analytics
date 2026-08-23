#!/usr/bin/env python3
"""
Compute real average expected-points-value per defensive event type from PFR's
pbp.csv (exp_pts_before/exp_pts_after columns), 1978-2025.

Reuses the exact regex definitions from gamebooks_boxscores/parse_pfr_pbp.py
(SACK_RE, TACKLE_RE, LOSS_TACKLE_RE, FF_RE, FR_RE, INT_RE, PD_RE,
SPECIAL_TEAMS_RE) -- copied inline here rather than importing the module
directly, because that module's own DB-backed player-resolution machinery
(football_db.db.get_connection, RosterResolver) is not needed for this
aggregate event-value analysis (no per-player attribution required, only
per-play event-type classification). The regex patterns themselves are
character-for-character identical to the source module.

2026-08-22 FR-attribution fix (see docs/framework_decisions.md next section):
the original FR_RE match ("recovered by X", X != the named fumbler) was a
name-only heuristic with NO team check -- it silently averaged real defensive
takeaways together with an offensive player recovering a TEAMMATE's fumble
(e.g. an OL falling on his own QB's sack-fumble), which is not a turnover at
all and often carries a strongly POSITIVE value for the offense. This script
now DOES import parse_pfr_pbp.py's RosterResolver (a real DB dependency this
script previously avoided) specifically to resolve both the fumbler's and the
recoverer's franchise for that game/season, and only counts a "fr" event when
the two franchises differ -- i.e. a genuine possession change. This needs
football_db reachable; see the Run instructions below.

Semantics (verified by direct spot-check before this script was written --
see the writeup doc): exp_pts_before/exp_pts_after are both expressed in the
reference frame of whichever team started that specific play with the ball.
within one continuing drive (same team, no PFR row gap), exp_pts_after(N) ==
exp_pts_before(N+1) exactly. A score sets exp_pts_after to exactly +7.000 (TD)
or +3.000 (FG make) for the offense; a defensive/return score sets it to
-7.000 (bad for the original offense). So "value to the defense" for any
play = -(exp_pts_after - exp_pts_before).

Full writeup: docs/deferred/04_event_value_results_20260822.md
Output: data_output/event_value_results.json (per-season, per-category
n/sum/sumsq -- the doc's summary tables are all derived from this file).
Also writes fr_team_resolution_stats (how many FR matches resolved both
names to teams vs. fell through unresolved) for transparency.

Run (now needs football_db reachable for the FR team-resolution fix):
    cd ~/github/football/football_db && source .venv/bin/activate
    cd ~/github/football/football_analytics
    PYTHONPATH=~/github/football/football_db/src:~/github/football/gamebooks_boxscores \
        python3 scripts/build_event_value_by_era.py
Takes ~2-3 min over the full 1978-2025 corpus, ~1.8M play rows / ~12,100
games (slower than the original ~60s stdlib-only run because of the added
per-play roster resolution).
"""
import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict

ROOT = "/Users/devos/data/pfref/raw/boxscores"

sys.path.insert(0, os.path.expanduser('~/github/football/football_db/src'))
sys.path.insert(0, os.path.expanduser('~/github/football/gamebooks_boxscores'))
from football_db.db import get_connection  # noqa: E402
from parse_pfr_pbp import RosterResolver  # noqa: E402

NAME = r"[A-Za-z.\'\-]+(?: [A-Za-z.\'\-]+)*?"
TACKLE_RE = re.compile(rf'\(tackle by ({NAME})(?: and ({NAME}))? ?\)')
SACK_RE = re.compile(rf'sacked by ({NAME})(?: and ({NAME}))? for (-?\d+) yards?')
LOSS_TACKLE_RE = re.compile(rf'for (-\d+) yards? \(tackle by ({NAME})(?: and ({NAME}))? ?\)')
FF_RE = re.compile(rf'forced by ({NAME}) ?\)')
FR_RE = re.compile(rf'recovered by ({NAME})(?: at | and |\.|,|$)')
INT_RE = re.compile(rf'intercepted by ({NAME})(?: at | and |\.|,|$)')
PD_RE = re.compile(rf'defended by ({NAME}) ?\)')
BLK_RE = re.compile(rf'blocked by ({NAME})')
SPECIAL_TEAMS_RE = re.compile(r'kicks off|punts|field goal|extra point|point after', re.I)
FUMBLER_RE = re.compile(rf'({NAME}) fumbles')

CATS = ["int", "sack", "tfl", "fr", "tackle"]
BONUS = ["pd", "ff"]

# per-season, per-category: n, sum, sumsq
agg = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))
bonus_agg = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0]))
ff_sack_overlap = [0, 0]  # [ff_plays_total, ff_plays_that_are_also_sack]

# FR team-resolution transparency counters (2026-08-22 fix) --
# fr_stats: candidate "recovered by X, X != fumbler name" matches, broken
# down by how the team-resolution check resolved.
fr_stats = {
    "name_mismatch_candidates": 0,   # frm.group(1) != fum_m.group(1) (old heuristic's full set)
    "both_resolved": 0,              # both fumbler and recoverer resolved to a franchise_id
    "different_teams_real_fr": 0,    # both resolved AND different franchise -- counted as "fr"
    "same_team_not_turnover": 0,     # both resolved but SAME franchise -- teammate recovery, excluded
    "unresolved_one_or_both": 0,     # couldn't resolve one or both names -- excluded (can't verify)
}

n_games = 0
n_rows = 0
n_valid = 0

conn = get_connection()
resolver = RosterResolver(conn)

years = list(range(1978, 2026))
for year in years:
    d = f"{ROOT}/{year}"
    files = glob.glob(f"{d}/*/pbp.csv")
    for fp in files:
        n_games += 1
        try:
            with open(fp, newline='') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if not rows:
                continue
            season = int(rows[0]['season'])
            home_ab, vis_ab = rows[0]['home_abbrev'], rows[0]['vis_abbrev']
            home_fid = resolver.resolve_alias(home_ab, season)
            vis_fid = resolver.resolve_alias(vis_ab, season)
            candidates = {fid for fid in (home_fid, vis_fid) if fid is not None}
            try:
                for row in rows:
                    n_rows += 1
                    detail = row.get('detail') or ''
                    if not detail:
                        continue
                    eb, ea = row.get('exp_pts_before'), row.get('exp_pts_after')
                    if not eb or not ea:
                        continue
                    try:
                        eb = float(eb); ea = float(ea)
                    except ValueError:
                        continue
                    n_valid += 1
                    value = -(ea - eb)  # value to defense

                    is_kick = bool(SPECIAL_TEAMS_RE.search(detail))
                    int_m = INT_RE.search(detail)
                    sack_m = SACK_RE.search(detail)
                    tfl_m = None
                    if not is_kick and not sack_m:
                        tfl_m = LOSS_TACKLE_RE.search(detail)
                    fr_m = None
                    fum_m = FUMBLER_RE.search(detail)
                    if fum_m:
                        frm = FR_RE.search(detail)
                        if frm and frm.group(1).strip() != fum_m.group(1).strip():
                            fr_stats["name_mismatch_candidates"] += 1
                            if candidates:
                                fum_fid, _, _ = resolver.resolve_player(
                                    fum_m.group(1).strip(), season, candidates)
                                rec_fid, _, _ = resolver.resolve_player(
                                    frm.group(1).strip(), season, candidates)
                                if fum_fid and rec_fid:
                                    fr_stats["both_resolved"] += 1
                                    if fum_fid != rec_fid:
                                        fr_stats["different_teams_real_fr"] += 1
                                        fr_m = frm
                                    else:
                                        fr_stats["same_team_not_turnover"] += 1
                                else:
                                    fr_stats["unresolved_one_or_both"] += 1
                            else:
                                fr_stats["unresolved_one_or_both"] += 1
                    tackle_m = None
                    if not int_m and not sack_m and not tfl_m:
                        tackle_m = TACKLE_RE.search(detail)

                    if int_m:
                        cat = "int"
                    elif sack_m:
                        cat = "sack"
                    elif tfl_m:
                        cat = "tfl"
                    elif fr_m:
                        cat = "fr"
                    elif tackle_m:
                        cat = "tackle"
                    else:
                        cat = None

                    if cat:
                        s = agg[year][cat]
                        s[0] += 1; s[1] += value; s[2] += value * value

                    # bonus categories (independent, may overlap primary)
                    pd_m = PD_RE.search(detail)
                    if pd_m:
                        s = bonus_agg[year]["pd"]
                        s[0] += 1; s[1] += value; s[2] += value * value
                    ff_m = FF_RE.search(detail)
                    if ff_m:
                        s = bonus_agg[year]["ff"]
                        s[0] += 1; s[1] += value; s[2] += value * value
                        ff_sack_overlap[0] += 1
                        if sack_m:
                            ff_sack_overlap[1] += 1
            except Exception as e:
                print(f"ERROR (row loop) {fp}: {e}")
                raise
        except Exception as e:
            print(f"ERROR {fp}: {e}")
    print(f"{year}: {len(files)} games done (cum rows={n_rows}, valid={n_valid})", flush=True)

conn.close()

print("FR team-resolution stats:", fr_stats)

out = {
    "n_games": n_games,
    "n_rows": n_rows,
    "n_valid_rows": n_valid,
    "ff_sack_overlap": ff_sack_overlap,
    "fr_team_resolution_stats": fr_stats,
    "by_year": {y: {c: agg[y][c] for c in CATS} for y in years},
    "by_year_bonus": {y: {c: bonus_agg[y][c] for c in BONUS} for y in years},
}
OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_output", "event_value_results.json")
with open(OUT_PATH, "w") as f:
    json.dump(out, f, indent=1)
print("DONE")
