#!/usr/bin/env python3
"""
Starter-focused position/scheme anomaly check -- per user request (2026-08-22),
follow-on to build_position_scheme_classifier.py (Phase 2). Restricts the
anomaly check to STARTERS ONLY (starters.csv is, by definition, the starter
list for that game -- appearing in it IS what "starter" means here), per the
user's own scoping rule: a bench/depth player showing up at multiple
positions is expected noise, not a signal; a STARTER whose real per-game
position drifts from their season-level classified bucket is the real,
actionable case.

Source: ~/data/pfref/raw/boxscores/{year}/{game_id}/starters.csv, 1967-2025
(scoped to match build_position_scheme_classifier.py's own named-bucket
coverage, which only exists 1967+ since gold.team_scheme_coach_season starts
there -- see this script's own docstring note below for why 1950-1966 is
excluded rather than checked without a scheme label).

Read-only against football_db and the local parquet; writes only its own
output files under football_analytics/data_output/. Does not touch any
production pipeline code.

Run via football_analytics' own .venv:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    python3 <this script>
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
import psycopg2

CLASSIFIER_PARQUET = Path.home() / "github/football/football_analytics/data_output/position_scheme_classification.parquet"
BOXSCORE_ROOT = Path.home() / "data/pfref/raw/boxscores"
OUT_CSV = Path.home() / "github/football/football_analytics/data_output/starter_position_anomalies.csv"
OUT_SUMMARY = Path.home() / "github/football/football_analytics/data_output/starter_position_anomalies_summary.txt"

PFR_ID_RE = re.compile(r"/([A-Za-z0-9]+)\.htm")

MIN_SEASON = 1967  # matches classifier's own named-bucket coverage start
MAX_SEASON = 2025

# Named 8-bucket -> the pos_group(s) consistent with that classification.
# Mirrors build_position_scheme_classifier.py's own BUCKET_MAP logic in reverse.
BUCKET_FAMILY = {
    "3-4 NT": {"NT"},
    "3-4 DE": {"DE"},
    "3-4 OLB (edge)": {"OLB"},
    "3-4 ILB/MLB": {"ILB", "MLB"},
    "4-3 DE": {"DE"},
    "4-3 MLB": {"MLB", "ILB"},
    "4-3 OLB": {"OLB"},
}
NAMED_BUCKETS = set(BUCKET_FAMILY)

# Threshold: an alternate pos_group must appear in >=3 starts in that season
# to count as a real, repeated inconsistency (not a one-off game-plan
# wrinkle or data quirk) -- per the user's own suggested threshold language.
MIN_INCONSISTENT_STARTS = 3

# starters.csv's own position-slot template changed materially over time --
# confirmed by direct inspection (1975-2010ish rows: LDE/LDT/RDT/RDE,
# LOLB/LILB/RILB/ROLB or LLB/MLB/RLB, i.e. always side/role-specific; 2016+
# rows increasingly just say bare "LB" x2-3 and bare "DL"/generic slots with
# NO side or role info at all). A bare "LB" or "DL" carries zero positional
# signal -- it is not evidence the player played a role inconsistent with
# their classified bucket, it is PFR's own box-score template losing
# granularity. Treated as UNINFORMATIVE: counted toward total games started,
# but never eligible to trigger (or be selected as) an inconsistency flag.
GENERIC_UNINFORMATIVE_POS = {"LB", "DL"}


def load_classifier():
    df = pd.read_parquet(CLASSIFIER_PARQUET)
    df = df[df["bucket"].isin(NAMED_BUCKETS)]
    lookup = {}
    for r in df.itertuples():
        lookup[(r.player_id, r.franchise_id, r.season)] = r.bucket
    return lookup


def load_player_xref(conn) -> dict[str, int]:
    cur = conn.cursor()
    cur.execute("SELECT source_player_id, player_id FROM internal.player_xref WHERE source_system='pfr'")
    return dict(cur.fetchall())


def load_pos_taxonomy(conn) -> dict[str, str]:
    cur = conn.cursor()
    cur.execute("SELECT raw_position, pos_group FROM gold.position_taxonomy")
    return dict(cur.fetchall())


def load_franchise_aliases(conn):
    cur = conn.cursor()
    cur.execute("SELECT alias_text, franchise_id, season_start, season_end FROM gold.franchise_aliases")
    rows = cur.fetchall()
    by_alias = defaultdict(list)
    for alias, fid, s0, s1 in rows:
        by_alias[alias].append((s0, s1, fid))
    return by_alias


def resolve_franchise(alias_text, season, by_alias, cache):
    key = (alias_text, season)
    if key in cache:
        return cache[key]
    fid = None
    for s0, s1, f in by_alias.get(alias_text, []):
        if s0 <= season and (s1 is None or s1 >= season):
            fid = f
            break
    cache[key] = fid
    return fid


# Legacy position codes that appear in old starters.csv rows but aren't in
# gold.position_taxonomy (mirrors build_position_scheme_classifier.py's own
# small local LEGACY_POS_GROUP map -- kept in sync deliberately).
LEGACY_POS_GROUP = {
    "E": "DE", "LE": "DE", "RE": "DE",
    "MG": "NT",
    "DG": "DT",
    "SLB": "OLB", "WLB": "OLB", "WILL": "OLB",
    "LDH": "S", "RDH": "S",
}


def normalize_pos(raw_pos, taxonomy):
    if not raw_pos:
        return None
    raw_pos = raw_pos.strip()
    if raw_pos in taxonomy:
        return taxonomy[raw_pos]
    return LEGACY_POS_GROUP.get(raw_pos)


def main():
    print("Loading classifier parquet (named 8-bucket rows only)...")
    clf_lookup = load_classifier()
    print(f"  {len(clf_lookup)} (player_id, franchise_id, season) classified rows in named buckets")

    conn = psycopg2.connect(dbname="football")
    xref = load_player_xref(conn)
    taxonomy = load_pos_taxonomy(conn)
    by_alias = load_franchise_aliases(conn)
    conn.close()
    print(f"  {len(xref)} PFR player_id xref entries, {len(taxonomy)} taxonomy entries")

    alias_cache = {}

    # (player_id, season) -> bucket (first franchise match wins; a player
    # traded mid-season could show up under 2 franchise keys -- rare, and
    # the per-game loop below re-resolves franchise per game anyway so this
    # dict is only used to know WHICH (player_id, season) pairs to track.
    tracked_seasons = defaultdict(dict)  # (player_id, season) -> {franchise_id: bucket}
    for (pid, fid, season), bucket in clf_lookup.items():
        tracked_seasons[(pid, season)][fid] = bucket

    # per (player_id, season): pos_group -> games_started count
    game_pos_counts = defaultdict(lambda: defaultdict(int))
    # per (player_id, season): which franchise/bucket combo was seen (for reporting)
    season_bucket = {}
    season_name = {}
    season_franchises = defaultdict(set)

    games_scanned = 0
    starter_rows_scanned = 0
    unresolved_player = 0
    unresolved_franchise = 0
    no_classifier_match = 0
    no_pos_group = 0

    years = sorted(int(p.name) for p in BOXSCORE_ROOT.iterdir() if p.is_dir() and p.name.isdigit()
                    and MIN_SEASON <= int(p.name) <= MAX_SEASON)
    print(f"Scanning {len(years)} seasons: {years[0]}-{years[-1]}")

    for year in years:
        ydir = BOXSCORE_ROOT / str(year)
        for gdir in sorted(ydir.iterdir()):
            scsv = gdir / "starters.csv"
            if not scsv.exists():
                continue
            games_scanned += 1
            with open(scsv, newline="") as f:
                for row in csv.DictReader(f):
                    starter_rows_scanned += 1
                    pfr_url = row.get("pfr_player_id") or ""
                    m = PFR_ID_RE.search(pfr_url)
                    if not m:
                        continue
                    pfr_id = m.group(1)
                    pid = xref.get(pfr_id)
                    if pid is None:
                        unresolved_player += 1
                        continue
                    try:
                        season = int(row["season"])
                    except (KeyError, ValueError, TypeError):
                        season = year
                    key = (pid, season)
                    if key not in tracked_seasons:
                        no_classifier_match += 1
                        continue
                    team_abbrev = row.get("team_abbrev") or ""
                    fid = resolve_franchise(team_abbrev, season, by_alias, alias_cache)
                    if fid is None:
                        unresolved_franchise += 1
                        continue
                    fid_bucket_map = tracked_seasons[key]
                    bucket = fid_bucket_map.get(fid)
                    if bucket is None:
                        # traded mid-season and this game's franchise isn't the
                        # classified one for this (player,season) key at all --
                        # still worth tracking games under whichever franchise
                        # bucket exists (take the only/first one) since the
                        # classifier is season-level, not per-stint.
                        if len(fid_bucket_map) == 1:
                            bucket = next(iter(fid_bucket_map.values()))
                        else:
                            no_classifier_match += 1
                            continue
                    pos_group = normalize_pos(row.get("pos"), taxonomy)
                    if pos_group is None:
                        no_pos_group += 1
                        continue
                    game_pos_counts[key][pos_group] += 1
                    season_bucket[key] = bucket
                    season_name[key] = row.get("player")
                    season_franchises[key].add(team_abbrev)

    print(f"\nScanned {games_scanned} games, {starter_rows_scanned} starter rows")
    print(f"  unresolved player_id (no xref): {unresolved_player}")
    print(f"  no classifier match for (player,season): {no_classifier_match}")
    print(f"  unresolved franchise: {unresolved_franchise}")
    print(f"  no pos_group mapping: {no_pos_group}")
    print(f"\n{len(game_pos_counts)} (player_id, season) starter-seasons checked against a named classified bucket")

    # --- Build flagged list ---
    flagged = []
    total_checked = 0
    for key, pos_counts in game_pos_counts.items():
        pid, season = key
        bucket = season_bucket[key]
        family = BUCKET_FAMILY[bucket]
        total_games = sum(pos_counts.values())
        total_checked += 1
        consistent_games = sum(n for pg, n in pos_counts.items() if pg in family)
        uninformative_games = sum(n for pg, n in pos_counts.items() if pg in GENERIC_UNINFORMATIVE_POS)
        inconsistent = {pg: n for pg, n in pos_counts.items()
                         if pg not in family and pg not in GENERIC_UNINFORMATIVE_POS
                         and n >= MIN_INCONSISTENT_STARTS}
        if not inconsistent:
            continue
        max_inconsistent_pos, max_inconsistent_n = max(inconsistent.items(), key=lambda kv: kv[1])
        flagged.append({
            "player_id": pid,
            "player_name": season_name[key],
            "season": season,
            "franchises": ",".join(sorted(season_franchises[key])),
            "classified_bucket": bucket,
            "total_games_started": total_games,
            "games_at_classified_family": consistent_games,
            "games_at_generic_uninformative": uninformative_games,
            "top_inconsistent_pos": max_inconsistent_pos,
            "games_at_top_inconsistent_pos": max_inconsistent_n,
            "all_pos_breakdown": ";".join(f"{pg}:{n}" for pg, n in sorted(pos_counts.items(), key=lambda kv: -kv[1])),
        })

    flagged.sort(key=lambda r: (-r["games_at_top_inconsistent_pos"], -r["total_games_started"]))

    print(f"\n{total_checked} total starter player-seasons checked (>=1 tracked start)")
    print(f"{len(flagged)} flagged as real anomalies (an alternate pos_group with >= {MIN_INCONSISTENT_STARTS} starts "
          f"outside the classified bucket's family)")

    fdf = pd.DataFrame(flagged)
    fdf.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {len(fdf)} flagged rows to {OUT_CSV}")

    with open(OUT_SUMMARY, "w") as f:
        f.write(f"games_scanned={games_scanned}\n")
        f.write(f"starter_rows_scanned={starter_rows_scanned}\n")
        f.write(f"unresolved_player={unresolved_player}\n")
        f.write(f"no_classifier_match={no_classifier_match}\n")
        f.write(f"unresolved_franchise={unresolved_franchise}\n")
        f.write(f"no_pos_group={no_pos_group}\n")
        f.write(f"starter_seasons_checked={total_checked}\n")
        f.write(f"flagged_anomalies={len(flagged)}\n")

    print("\n=== Top 30 flagged (by games at inconsistent position, then total starts) ===")
    for r in flagged[:30]:
        print(f"  {r['player_name']:24s} pid={r['player_id']:6d} {r['season']} [{r['franchises']}] "
              f"classified={r['classified_bucket']:18s} total_starts={r['total_games_started']:2d} "
              f"at_classified={r['games_at_classified_family']:2d} "
              f"top_alt={r['top_inconsistent_pos']}({r['games_at_top_inconsistent_pos']}) "
              f"breakdown={r['all_pos_breakdown']}")


if __name__ == "__main__":
    main()
