#!/usr/bin/env python3
"""
Tackle quality by position -- implements docs/deferred/07_tackle_quality_by_position.md's
"What to build" section. Tests the user's hypothesis directly: does a tackle's
average yards-gained-on-the-play differ by the tackler's position (DL closest
to the LOS, LB in between, Safety furthest downfield)?

Source data: ~/data/pfref/raw/boxscores/{year}/{game}/pbp.csv, 1978-2025 (see
"Scope" below for why 1967-1977 is excluded). Per-play tackler identity is
resolved via gamebooks_boxscores/parse_pfr_pbp.py's own RosterResolver +
PFR-id cross-reference machinery -- reused directly rather than re-derived,
same reasoning ingest_pfr_defensive_stats.py already applied to this problem
(player_defense.csv's own pfr_player_id cross-references into
internal.player_xref far more reliably than name/surname matching alone).
Position group comes from build_position_scheme_classifier.py's Phase 2
output (data_output/position_scheme_classification.parquet) -- the finer
scheme-aware buckets where available, falling back to the coarse 3-group
dpvs/positions.py taxonomy's DL/LB/DB split otherwise, per doc 07 item 2.

Run via football_analytics' own .venv (needs PYTHONPATH pointed at both
football_db's package and gamebooks_boxscores, same as
ingest_pfr_defensive_stats.py's own usage note):
    cd ~/github/football/football_analytics && source .venv/bin/activate
    python3 scripts/build_tackle_quality_by_position.py
    python3 scripts/build_tackle_quality_by_position.py --start-year 2020 --end-year 2022  # smoke test

--- Scope: why 1978-2025, not 1967-1977 ---

1967-1977 has no PFR pbp.csv at all (this project's data-feasibility notes,
docs/deferred/03_epa_pbp_value_model.md, confirm pbp.csv exists 1978-2025
only) -- the only PBP for that era is gamebooks_boxscores' own OCR-derived
prose, which has neither a structured yards-gained field nor the volume to
build a reliable per-position distribution from scratch here, and carries
its own documented completeness caveats
(gamebooks_boxscores/docs/experiments/2026-08-20_pfr_pbp_vs_gamebook_
completeness/README.md). Scoping to 1978-2025 only is the more defensible
choice of the two the source doc offered -- stated explicitly, not a silent
omission.

Within 1978-2025, sack plays are EXCLUDED from this analysis entirely (a
sack is a different kind of event with its own established scoring/analysis
path elsewhere in this project -- not a counterexample to or confirmation of
this hypothesis, which is specifically about tackles on runs/completions).
Special-teams plays (kickoffs, punts, FG/XP) are also excluded -- tackles
there belong to gamebooks_boxscores' own "Special Teams" bucket, a distinct
category by this project's own established convention, not the main tackle
table.

--- Multi-tackler plays ---

A play crediting two tacklers ("tackle by X and Y") gives BOTH the same
play's yards-gained value, not a split. Reasoning: yards-gained is a fact
about the PLAY (where it ended relative to where it started), not something
to divide between people -- an assisting tackler was still involved in a
play that ended at that yard line, and the whole point of this analysis is
"how far downfield does this position's tackles happen," which the second
tackler's presence doesn't change. Documented explicitly per doc 07's own
request, not defaulted silently.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.expanduser("~/github/football/gamebooks_boxscores"))
sys.path.insert(0, os.path.expanduser("~/github/football/football_db/src"))
from parse_pfr_pbp import (  # noqa: E402
    NAME, RosterResolver, load_pfr_player_id_cache, load_game_id_map, ROOT,
)
from football_db.db import get_connection  # noqa: E402

CLASSIFIER_PARQUET = Path(__file__).parent.parent / "data_output" / "position_scheme_classification.parquet"
OUT_JSON = Path(__file__).parent.parent / "data_output" / "tackle_quality_by_position_results.json"
OUT_EVENTS = Path(__file__).parent.parent / "data_output" / "tackle_quality_events.parquet"

SACK_RE = re.compile(rf"sacked by ({NAME})(?: and ({NAME}))? for (-?\d+) yards?")
TACKLE_YARDS_RE = re.compile(rf"for (-?\d+) yards? \(tackle by ({NAME})(?: and ({NAME}))? ?\)")
SPECIAL_TEAMS_RE = re.compile(r"kicks off|punts|field goal|extra point|point after", re.I)

# Coarse fallback groups (dpvs/positions.py's own 3-group split, reduced here
# to just the DL/LB/S distinction doc 07 asks about -- CB is out of scope for
# this specific hypothesis, only Safety/LB/DL were given ranges to test).
COARSE_FALLBACK = {
    "DE": "DL", "LDE": "DL", "RDE": "DL", "DT": "DL", "LDT": "DL", "RDT": "DL",
    "NT": "DL", "DL": "DL",
    "LB": "LB", "ILB": "LB", "MLB": "LB", "LILB": "LB", "RILB": "LB",
    "OLB": "LB", "LOLB": "LB", "ROLB": "LB", "LLB": "LB", "RLB": "LB",
    "S": "S", "FS": "S", "SS": "S",
}

# Phase 2 fine bucket -> coarse S/LB/DL group, for the primary hypothesis test.
FINE_TO_COARSE = {
    "3-4 NT": "DL", "3-4 DE": "DL", "4-3 DE": "DL",
    "3-4_DT_uncovered": "DL", "4-3_DT_uncovered": "DL",
    "3-4 OLB (edge)": "LB", "3-4 ILB/MLB": "LB", "4-3 MLB": "LB", "4-3 OLB": "LB",
}


def load_position_lookup() -> dict[tuple[int, int], dict]:
    """(player_id, season) -> {'fine_bucket':..., 'coarse_group':..., 'raw_pos_group':...}
    Sourced from Phase 2's classification parquet; a player can appear more
    than once per season (multi-team) -- fine, this analysis only needs
    position, not team, so first row wins (positions rarely differ within a
    season for the same player)."""
    clf = pd.read_parquet(CLASSIFIER_PARQUET)
    out = {}
    for r in clf.itertuples():
        key = (r.player_id, r.season)
        if key in out:
            continue
        fine = r.bucket
        coarse = FINE_TO_COARSE.get(fine)
        if coarse is None:
            pos_group = r.pos_group if isinstance(r.pos_group, str) else None
            coarse = COARSE_FALLBACK.get(pos_group)
        out[key] = {"fine_bucket": fine, "coarse_group": coarse}
    return out


def iter_games(start_year: int, end_year: int):
    for year in range(start_year, end_year + 1):
        d = ROOT / str(year)
        if not d.exists():
            continue
        for gd in sorted(d.iterdir()):
            if gd.is_dir() and (gd / "pbp.csv").exists():
                yield year, gd


def parse_tackle_events(pbp_path: Path):
    """Yields (yards_gained, [tackler_names]) for every non-sack, non-special-teams
    play crediting a tackle, anchoring yards-gained directly to the tackle credit
    (see module docstring) rather than a bare first-number-in-the-line heuristic."""
    with open(pbp_path) as f:
        for row in csv.DictReader(f):
            detail = row.get("detail") or ""
            if not detail:
                continue
            if SPECIAL_TEAMS_RE.search(detail):
                continue
            if SACK_RE.search(detail):
                continue
            m = TACKLE_YARDS_RE.search(detail)
            if not m:
                continue
            yards = int(m.group(1))
            names = [n for n in (m.group(2), m.group(3)) if n]
            yield yards, names


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=1978)
    ap.add_argument("--end-year", type=int, default=2025)
    ap.add_argument("--limit-games", type=int, default=None, help="smoke-test cap on total games processed")
    args = ap.parse_args()

    print("Loading Phase 2 position/scheme classification...")
    pos_lookup = load_position_lookup()
    print(f"  {len(pos_lookup)} (player_id, season) entries")

    conn = get_connection()
    resolver = RosterResolver(conn)
    id_cache = load_pfr_player_id_cache(conn)
    print(f"  {len(id_cache)} PFR player_id xref entries")

    events = []  # dicts: season, game_id, yards, player_id, fine_bucket, coarse_group, n_tacklers
    games_processed, plays_seen, plays_resolved = 0, 0, 0

    for year, gd in iter_games(args.start_year, args.end_year):
        if args.limit_games and games_processed >= args.limit_games:
            break
        pbp_path = gd / "pbp.csv"
        with open(pbp_path) as f:
            first = next(csv.DictReader(f))
            season = int(first["season"])
            home_ab, vis_ab = first["home_abbrev"], first["vis_abbrev"]
        home_fid = resolver.resolve_alias(home_ab, season)
        vis_fid = resolver.resolve_alias(vis_ab, season)
        if not home_fid or not vis_fid:
            continue
        candidates = {home_fid, vis_fid}
        id_map = load_game_id_map(gd, id_cache)

        for yards, names in parse_tackle_events(pbp_path):
            plays_seen += 1
            for name in names:
                fid, pid, method = resolver.resolve_player(name, season, candidates)
                id_pid = id_map.get(name)
                if id_pid is not None and fid is not None:
                    pid, method = id_pid, "pfr_id_xref"
                if pid is None:
                    continue
                info = pos_lookup.get((pid, season))
                if info is None or info["coarse_group"] is None:
                    continue
                plays_resolved += 1
                events.append({
                    "season": season, "game_id": gd.name, "yards": yards,
                    "player_id": pid, "fine_bucket": info["fine_bucket"],
                    "coarse_group": info["coarse_group"], "n_tacklers": len(names),
                })
        games_processed += 1
        if games_processed % 1000 == 0:
            print(f"  ...{games_processed} games, {plays_resolved} position-resolved tackle events so far")

    conn.close()
    print(f"\nProcessed {games_processed} games, {plays_seen} tackle plays seen, "
          f"{plays_resolved} tackle-events resolved to a known position group")

    ev = pd.DataFrame(events)
    ev.to_parquet(OUT_EVENTS, index=False)
    print(f"Wrote {len(ev)} tackle events to {OUT_EVENTS}")

    # --- Primary hypothesis test: coarse S / LB / DL groups ---
    HYPOTHESIS = {
        "S":  (8, 30, 13),
        "LB": (-3, 12, 6),
        "DL": (-3, 5, 3),
    }
    results = {"scope": f"{args.start_year}-{args.end_year}", "n_events": len(ev), "groups": {}}
    print("\n=== Primary hypothesis test (coarse S / LB / DL groups) ===")
    for group in ("S", "LB", "DL"):
        sub = ev[ev.coarse_group == group]["yards"]
        if sub.empty:
            continue
        lo, hi, hyp_mean = HYPOTHESIS[group]
        pct_in_range = 100 * ((sub >= lo) & (sub <= hi)).mean()
        g = {
            "n": int(len(sub)), "mean": float(sub.mean()), "median": float(sub.median()),
            "std": float(sub.std()), "p10": float(sub.quantile(.10)), "p25": float(sub.quantile(.25)),
            "p75": float(sub.quantile(.75)), "p90": float(sub.quantile(.90)),
            "hypothesized_range": [lo, hi], "hypothesized_mean": hyp_mean,
            "pct_in_hypothesized_range": float(pct_in_range),
        }
        results["groups"][group] = g
        print(f"{group}: n={g['n']:>7}  mean={g['mean']:+.2f}  median={g['median']:+.1f}  "
              f"std={g['std']:.1f}  [p10={g['p10']:+.1f} p25={g['p25']:+.1f} "
              f"p75={g['p75']:+.1f} p90={g['p90']:+.1f}]  "
              f"hyp=[{lo},{hi}]~{hyp_mean}  %in_range={pct_in_range:.1f}%  "
              f"(hyp: >80%)")

    # --- Secondary breakdown: fine scheme-aware buckets, where sample size allows ---
    print("\n=== Secondary breakdown: fine scheme-aware buckets ===")
    fine_results = {}
    for bucket, sub_df in ev.groupby("fine_bucket"):
        sub = sub_df["yards"]
        if len(sub) < 200:
            continue
        fine_results[bucket] = {
            "n": int(len(sub)), "mean": float(sub.mean()), "median": float(sub.median()),
        }
        print(f"  {bucket:22s} n={len(sub):>7}  mean={sub.mean():+.2f}  median={sub.median():+.1f}")
    results["fine_buckets"] = fine_results

    import json
    OUT_JSON.parent.mkdir(exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote results to {OUT_JSON}")


if __name__ == "__main__":
    main()
