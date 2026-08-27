#!/usr/bin/env python3
"""
Build a per-team-season "qualified-games-only" plays_offense denominator
for gamebooks_boxscores' 1967-1977 range, to fix a real numerator/
denominator mismatch in
data_output/tackle_coverage_ratio_all_sources_1967_2025.csv's
gamebook_comb_plays_ratio column.

THE BUG THIS FIXES: build_tackle_coverage_all_sources.py's
gamebook_comb_plays_ratio divides the GATED tackle corpus's comb_tackles
(tackle_gamebooks_gated_1967_1977.csv -- summed ONLY across games that
passed the >=70% completeness-ratio gate, see
gamebooks_boxscores/build_defensive_leaderboards.py's THRESHOLD) by a
FULL-SEASON plays_offense (team_stats_{year}.csv, every game that team
played that season, gated or not). A team-season where only 10 of 14
games qualified had its 10-games tackle numerator divided by a 14-games
opponent-plays denominator -- understating the true ratio.

THE FIX: recompute plays_offense at the GAME level, summed only across
the SAME games that qualified for that team-season's gamebook tackle
numerator, using the exact same qualification gate
(build_tackle_gated_corpus.py / build_defensive_leaderboards.py's
ABBR_TO_FID / GAMES_ROOT / THRESHOLD / parse_boxscore / text_classify --
imported directly here, not re-derived) applied per (season, team-side,
game), not per team-season.

DENOMINATOR SOURCE: ~/data/pfref/raw/boxscores/{year}/{game_id}/
player_offense.csv (per-game, real per-team offensive lines), NOT
gold.team_game_stats -- because gold.team_game_stats has ZERO PFR data
for AFL games in 1967-1969 (the same known gap
build_tackle_coverage_all_sources.py already documents), so any AFL game
that qualifies via the text_classify fallback would have no denominator
at all if sourced from team_game_stats. player_offense.csv is raw
scraped PFR boxscore data and has real rows for those games too.

Confirmed columns in player_offense.csv (read a real file first, per
task instructions -- ~/data/pfref/raw/boxscores/1967/196709170clt/
player_offense.csv): game_id, season, home_abbrev, vis_abbrev, player,
pfr_player_id, team, pass_cmp, pass_att, pass_yds, pass_td, pass_int,
pass_sacked, pass_sacked_yds, pass_long, pass_rating, rush_att, rush_yds,
rush_td, rush_long, rec, rec_yds, rec_td, rec_long.
NOTE: the task description said "pass_comp" -- the real column is
"pass_cmp". "pass_sacked" and "rush_att" matched as expected.
Formula reused exactly as elsewhere in this project: pass_cmp + rush_att
+ pass_sacked = opponent offensive "opportunities".

TEAM-CODE CARE (this session's recurring failure mode): player_offense.
csv's own 'team' column does NOT use the corpus's stable lowercase code
convention -- confirmed directly: game 196709170clt (home_abbrev='clt',
i.e. Baltimore Colts) has 'team' values {'ATL', 'BAL'}, and 'BAL' is NOT
equal to 'clt'.upper(). A same-string 'BAL' alias is also ambiguous
astride two different franchises (Colts franchise_id=11 through 1983,
Ravens franchise_id=26 from 1996 on) -- confirmed directly against
gold.franchise_aliases, which turns out to be SEASON-SCOPED
(season_start/season_end columns), not a flat text->franchise_id map.
So every 'team' value here is resolved via gold.franchise_aliases
filtered to (alias_text ilike team) AND (season BETWEEN season_start AND
COALESCE(season_end, 9999)) -- this correctly resolves 'BAL' 1967 to the
Colts (11) and would resolve 'BAL' 1996+ to the Ravens (26), never
conflating them. home_abbrev/vis_abbrev are NOT used as the team-identity
signal for row bucketing (they don't reliably textually match the 'team'
column's own convention either) -- only used, together with meta.json,
to know which franchise_id is "opponent" for the qualifying team-side
before the player_offense.csv rows are even read.

QUALIFICATION GATE: line-for-line the same per-(season, team-side, game)
gate as build_tackle_gated_corpus.py (itself already the project's
established reuse of build_defensive_leaderboards.py's THRESHOLD test) --
imported directly, not reimplemented. The only difference from that
script: this one keeps the per-game qualifying list (season, own_fid,
opp_fid, pfr_game_id) instead of collapsing straight into a player-level
tackle sum, because the qualifying GAME is exactly the unit this
denominator needs.

Output: data_output/tackle_gamebooks_qualified_plays_offense_1967_1977.csv
  season, team (corpus code), franchise_id, games_qualified,
  plays_offense_qualified

Usage: python3 build_gamebook_qualified_plays_offense.py
    (needs football_db's .venv on PYTHONPATH, same as every other script
    in this family)
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path.home() / "github" / "football" / "football_db" / "src"))
sys.path.insert(0, str(Path.home() / "github" / "football" / "gamebooks_boxscores"))

from football_db.db import get_connection  # noqa: E402
from build_defensive_leaderboards import (  # noqa: E402
    ABBR_TO_FID, GAMES_ROOT, THRESHOLD, parse_boxscore, text_classify,
)

SEASONS = list(range(1967, 1978))  # 1967-1977 inclusive
PFREF_BOXSCORES = Path.home() / "data" / "pfref" / "raw" / "boxscores"
OUT_PATH = Path(__file__).resolve().parent.parent / "data_output" / "tackle_gamebooks_qualified_plays_offense_1967_1977.csv"

# franchise_id -> corpus-standard lowercase code, same map used by
# build_tackle_gated_corpus.py / build_run_stuff_gated_corpus.py (2026-08-21 fix
# -- current_abbreviation differs from this for 12/28 franchises).
FID_TO_TEAM: dict[int, str] = {
    16: "atl", 4: "buf", 2: "chi", 3: "cin", 6: "cle", 11: "clt", 8: "crd",
    13: "dal", 5: "den", 20: "det", 21: "gnb", 10: "kan", 14: "mia",
    32: "min", 27: "nor", 23: "nwe", 17: "nyg", 19: "nyj", 31: "oti",
    15: "phi", 29: "pit", 24: "rai", 25: "ram", 9: "sdg", 28: "sea",
    1: "sfo", 7: "tam", 12: "was",
}


def load_alias_map(conn) -> list[tuple[str, int, int, int | None]]:
    cur = conn.cursor()
    cur.execute("SELECT franchise_id, alias_text, season_start, season_end FROM gold.franchise_aliases")
    rows = cur.fetchall()
    cur.close()
    return [(a.lower(), fid, s, e) for fid, a, s, e in rows]


def resolve_team(alias_map, text: str, season: int) -> int | None:
    """Season-scoped alias resolution. Returns None if zero or >1 distinct
    franchise_id candidates match (never guesses on ambiguity)."""
    text_l = text.strip().lower()
    candidates = {
        fid for (a, fid, s, e) in alias_map
        if a == text_l and s <= season and (e is None or season <= e)
    }
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def find_qualifying_games(conn) -> list[tuple[int, int, int, str, str, str]]:
    """Replicates build_tackle_gated_corpus.py's per-(season, team-side,
    game) qualification gate exactly, but returns the per-game list
    (season, own_fid, opp_fid, pfr_game_id, home_ab, away_ab) instead of
    collapsing into a player-level tackle sum. home_ab/away_ab are kept
    (not just baked into pfr_game_id) so a missing-file lookup can try a
    home/away swap -- see _locate_player_offense_csv."""
    cur = conn.cursor()
    qual_games: list[tuple[int, int, int, str, str, str]] = []
    total_sides = resolved_ct = qual_ct = 0

    for gdir in sorted(GAMES_ROOT.iterdir()):
        gid = gdir.name
        try:
            season = int(gid[:4])
        except ValueError:
            continue
        if season not in SEASONS:
            continue
        box_path, meta_path = gdir / "boxscore.md", gdir / "meta.json"
        if not box_path.exists() or not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        md_text = box_path.read_text()
        home_ab, away_ab = meta['home_team'].lower(), meta['away_team'].lower()
        home_fid, away_fid = ABBR_TO_FID.get(home_ab), ABBR_TO_FID.get(away_ab)
        pfr_game_id = f"{meta['content_date']}0{meta['home_team']}"

        tstats, db_resolved = {}, False
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
                qual_games.append((season, own_fid, opp_fid, pfr_game_id, home_ab, away_ab))

    print(f"  sides={total_sides} db_resolved={resolved_ct} qualifying={qual_ct}")
    cur.close()
    return qual_games


def _locate_player_offense_csv(pfr_season: int, content_date: str, home_ab: str, away_ab: str):
    """Exact path first; then two fallbacks confirmed against REAL, already-
    diagnosed cases in this corpus (not guesses):
      (1) home/away swap -- Super Bowl VI (19720116_sb_dal_at_mia) has
          content_date/home_team 'mia' in the gamebook's own meta.json, but
          PFR's own boxscore folder is .../1971/197201160dal/ (PFR
          designates Dallas the "home" team for a neutral-site game). The
          already-fixed SB V case has an explicit correction_note
          describing exactly this same PFR-vs-gamebook home-team
          convention gap.
      (2) content_date +/- 1 day, same home team -- two corpus games
          (19701019_wk04_clt_at_oti, 19731001_wk03_gnb_at_min) have a
          content_date one calendar day after the real Sunday game date
          in PFR's own folder (197010180oti, 197309300min) -- games in
          this era are always played on a Sunday, so a 1-day slip is a
          label bug in the gamebook corpus's content_date, not a
          different game.
    Every candidate is validated before being accepted: the found file's
    OWN home_abbrev/vis_abbrev pair (read from its first row) must equal
    {home_ab, away_ab} -- this matters because the date_offset fallback
    found a real but WRONG game on first implementation (clt_at_oti's
    content_date is 8 days off from PFR's real date, not 1 -- the +/-1
    probe landed on the SAME team's very next chronological game
    (oti_at_pit) instead, which would have silently summed the wrong
    opponent's offense had this check not caught it). A candidate that
    fails validation is treated as not found, not accepted anyway.

    Returns (path_or_None, how) where how in
    {'exact','home_away_swap','date_offset', None}."""
    def try_path(season, date, home):
        fp = PFREF_BOXSCORES / str(season) / f"{date}0{home}" / "player_offense.csv"
        if not fp.exists():
            return None
        with open(fp, newline="") as f:
            row = next(csv.DictReader(f), None)
        if row is None:
            return None
        found_pair = {row["home_abbrev"].lower(), row["vis_abbrev"].lower()}
        if found_pair != {home_ab.lower(), away_ab.lower()}:
            return None
        return fp

    fp = try_path(pfr_season, content_date, home_ab)
    if fp:
        return fp, "exact"
    fp = try_path(pfr_season, content_date, away_ab)
    if fp:
        return fp, "home_away_swap"
    from datetime import datetime, timedelta
    base = datetime.strptime(content_date, "%Y%m%d")
    for delta in (-1, 1):
        alt_date = (base + timedelta(days=delta)).strftime("%Y%m%d")
        alt_season = pfr_season  # +/-1 day never crosses the Jan/Feb season boundary in this corpus
        fp = try_path(alt_season, alt_date, home_ab)
        if fp:
            return fp, "date_offset"
        fp = try_path(alt_season, alt_date, away_ab)
        if fp:
            return fp, "date_offset"
    return None, None


def main() -> None:
    conn = get_connection()
    alias_map = load_alias_map(conn)

    qual_games = find_qualifying_games(conn)
    print(f"  distinct qualifying (season, own_fid, game) rows: {len(qual_games)}")

    plays_sum: dict[tuple[int, int], int] = defaultdict(int)
    games_count: dict[tuple[int, int], int] = defaultdict(int)
    missing_file = []
    unresolved_opp = []
    csv_cache: dict[tuple[int, str], list[dict] | None] = {}

    fallback_used = defaultdict(int)
    for season, own_fid, opp_fid, pfr_game_id, home_ab, away_ab in qual_games:
        # File-path lookup needs the REAL PFR season folder, which follows
        # NFL convention (a Jan/Feb-dated postseason game belongs to the
        # season that started the previous fall) -- NOT the `season`
        # bucket used for output aggregation, which is int(gid[:4]) taken
        # from the gamebooks_v2 folder id (same convention
        # build_tackle_gated_corpus.py already uses for the numerator
        # corpus this denominator must match up with). Confirmed directly:
        # 19710117_sb_dal_at_clt (Super Bowl V) has content_date
        # "19710117" -> gid-year season bucket 1971, but its real PFR
        # boxscore folder is .../1970/197101170clt/ (30 such playoff games
        # in this corpus, all in Jan; verified every one resolves once
        # this offset is applied). Keeping the OUTPUT bucketed by the same
        # gid-year convention as the numerator is required -- fixing only
        # the season label here without changing tackle_gamebooks_gated_
        # 1967_1977.csv's own labeling would just move the mismatch rather
        # than remove it.
        content_date = pfr_game_id[:8]
        month = int(content_date[4:6])
        pfr_season = season - 1 if month <= 2 else season

        cache_key = (pfr_season, pfr_game_id)
        if cache_key not in csv_cache:
            fp, how = _locate_player_offense_csv(pfr_season, content_date, home_ab, away_ab)
            if fp:
                if how != "exact":
                    fallback_used[how] += 1
                with open(fp, newline="") as f:
                    csv_cache[cache_key] = list(csv.DictReader(f))
            else:
                csv_cache[cache_key] = None
        rows = csv_cache[cache_key]
        if rows is None:
            missing_file.append((season, own_fid, pfr_game_id))
            continue

        opp_cmp = opp_rush = opp_sacked = 0
        resolved_any = False
        for row in rows:
            fid = resolve_team(alias_map, row["team"], pfr_season)
            if fid != opp_fid:
                continue
            resolved_any = True
            opp_cmp += int(row["pass_cmp"] or 0)
            opp_rush += int(row["rush_att"] or 0)
            opp_sacked += int(row["pass_sacked"] or 0)

        if not resolved_any:
            unresolved_opp.append((season, own_fid, opp_fid, pfr_game_id))
            continue

        key = (season, own_fid)
        plays_sum[key] += opp_cmp + opp_rush + opp_sacked
        games_count[key] += 1

    print(f"  fallback path resolutions used: {dict(fallback_used)}")
    print(f"  missing player_offense.csv files: {len(missing_file)}")
    if missing_file:
        print(f"    e.g. {missing_file[:5]}")
    print(f"  qualifying games where opponent's rows never resolved in player_offense.csv: {len(unresolved_opp)}")
    if unresolved_opp:
        print(f"    e.g. {unresolved_opp[:5]}")

    rows_out = []
    for key in sorted(plays_sum, key=lambda k: (k[1], k[0])):
        season, fid = key
        rows_out.append({
            "season": season,
            "team": FID_TO_TEAM.get(fid, "??"),
            "franchise_id": fid,
            "games_qualified": games_count[key],
            "plays_offense_qualified": plays_sum[key],
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["season", "team", "franchise_id", "games_qualified", "plays_offense_qualified"])
        w.writeheader()
        w.writerows(rows_out)
    print(f"wrote {len(rows_out)} team-season rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
