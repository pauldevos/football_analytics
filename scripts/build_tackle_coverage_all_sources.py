#!/usr/bin/env python3
"""
Build ONE comprehensive per-team-season tackle-coverage reference table
spanning 1967-2025, combining the three tackle-count sources this session
has been separately verifying:

  1. Gamebooks (1967-1977 only) -- completeness-ratio-gated, roster-resolved
     player-level tackle sums. `data_output/tackle_gamebooks_gated_1967_1977.csv`
     (season, team, player, tackle_sum, games_qualified). Summed here to
     TEAM-SEASON grain. `games_qualified` is per-player (how many of that
     team's qualifying games that player appears in); the team-season
     coverage figure reported here is MAX(games_qualified) across a team's
     players in a season -- a full-season player appears in every
     qualifying game, so the max is the real qualifying-game count for
     that team-side that season (confirmed: 1967 DEN max=14, and 1967 was
     a 14-game season).

  2. PFR PBP-derived (1978-2025) -- text-parsed play-by-play tackle
     attribution, franchise_id already canonical (resolved through
     gold.franchise_aliases inside gamebooks_boxscores/parse_pfr_pbp.py).
     `gamebooks_boxscores/outputs/pfr_pbp_defensive_stats_1978_2025.csv`,
     filtered to game_type == 'regular', grouped by (season, franchise_id).

  3. Official PFR box scores (2001-2025 reused here) -- real per-game
     Solo/Ast box-score sums, already built at team-season grain by
     scripts/build_verified_tackle_ratio.py.
     `data_output/tackle_ratio_by_team_season.csv`. Reused directly, not
     rebuilt -- filtered to season >= 2001.

Denominator (`plays_offense`, opponent real offensive plays that season)
built fresh for ALL of 1967-2025 from
`~/data/pfref/raw/season/team/defense/team_stats/team_stats_{year}.csv`
(confirmed present 1950-2025, so 1967-1977 is covered), joined to a
franchise via `~/data/pfref/franchise_year_abbrev.csv` (season, team_name)
-> stable lowercase code, then that code -> canonical franchise_id.

TEAM-CODE RECONCILIATION -- the thing this session has broken on
repeatedly before, so it is NOT done as a naive string join here. All
three sources' team identifiers get resolved to football_db's
`gold.franchises.franchise_id` via `gold.franchise_aliases`
(case-insensitive lookup), queried directly and cross-checked below (see
`_verify_team_code_map()`), not just trusted from a copied dict:
  - Gamebook / official-table 'team' columns and
    franchise_year_abbrev.csv's 'abbrev' column all already share ONE
    stable lowercase code convention (den, crd, oti, htx, rai, ram, sdg,
    clt, ...) -- confirmed identical to `dpvs/idi.py`'s own `_FID_TO_TEAM`
    map, itself already validated against gold.franchises per that file's
    comment. This script re-validates the same 32-entry mapping live
    against the DB rather than re-trusting the copied dict blind.
  - PFR-PBP's franchise_id is ALREADY the canonical football_db id --
    no translation needed, confirmed by reading parse_pfr_pbp.py's own
    franchise resolution (it queries gold.franchise_aliases directly).

Output: data_output/tackle_coverage_ratio_all_sources_1967_2025.csv
One row per (franchise_id, season), 1967-2025 -- only for seasons a
franchise actually existed, driven by which seasons appear in the
plays_offense build (team_stats_{year}.csv naturally only lists teams
that existed that year).

Known gap, not fixed here: PFR's Team Defense "opponent stats" page
(team_stats_{year}.csv) has NO AFL data for 1967-1969 (confirmed: that
file lists only 16 teams in each of 1967/1968/1969, all NFL; the 25-ish
AFL+NFL franchise list in franchise_year_abbrev.csv for the same years
shows the AFL teams exist in that mapping file but not in team_stats).
plays_offense (and therefore every *_comb_plays_ratio column) is
correctly left null for AFL team-seasons 1967-1969 rather than guessed --
consistent with this project's standing "AFL/NFL are one league, but flag
lower confidence, never fabricate" convention
(feedback_afl_nfl_one_league.md).

Nothing in dpvs/idi.py, dpvs/tcs.py, or any other production pipeline
file is read for its logic (only for the already-validated _FID_TO_TEAM
comment as a cross-check) and nothing is written back to it. Not
committed to git per this task's instructions.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_OUTPUT = REPO_ROOT / "data_output"
GAMEBOOKS_REPO = REPO_ROOT.parent / "gamebooks_boxscores"
PFREF_RAW = Path.home() / "data" / "pfref" / "raw"
PFREF_ROOT = Path.home() / "data" / "pfref"

GAMEBOOK_CSV = DATA_OUTPUT / "tackle_gamebooks_gated_1967_1977.csv"
GAMEBOOK_QUALIFIED_PO_CSV = DATA_OUTPUT / "tackle_gamebooks_qualified_plays_offense_1967_1977.csv"
PBP_CSV = GAMEBOOKS_REPO / "outputs" / "pfr_pbp_defensive_stats_1978_2025.csv"
OFFICIAL_CSV = DATA_OUTPUT / "tackle_ratio_by_team_season.csv"
FRANCHISE_ABBREV_CSV = PFREF_ROOT / "franchise_year_abbrev.csv"
TEAM_STATS_DIR = PFREF_RAW / "season" / "team" / "defense" / "team_stats"

OUT_CSV = DATA_OUTPUT / "tackle_coverage_ratio_all_sources_1967_2025.csv"

SEASON_MIN, SEASON_MAX = 1967, 2025


def _get_db_connection():
    sys.path.insert(0, str(REPO_ROOT.parent / "football_db" / "src"))
    from football_db.db import get_connection  # noqa: E402
    return get_connection()


def load_franchise_maps() -> tuple[dict[str, int], dict[int, dict]]:
    """Query gold.franchises / gold.franchise_aliases directly (not a
    copied dict) to build:
      - code_to_fid: the 32-entry stable-lowercase-code -> franchise_id map
        this whole script's team-code reconciliation depends on
      - fid_info: franchise_id -> {current_abbreviation, current_city, current_team_name}
    """
    conn = _get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT franchise_id, current_city, current_team_name, current_abbreviation "
        "FROM gold.franchises ORDER BY franchise_id"
    )
    fid_info = {
        r[0]: {"current_city": r[1], "current_team_name": r[2], "current_abbreviation": r[3]}
        for r in cur.fetchall()
    }

    # The 32 stable lowercase codes used throughout this project's CSVs
    # (gamebooks_boxscores corpus, official table, franchise_year_abbrev.csv).
    candidate_codes = [
        "atl", "buf", "chi", "cin", "cle", "clt", "crd", "dal", "den", "det",
        "gnb", "kan", "mia", "min", "nor", "nwe", "nyg", "nyj", "oti", "phi",
        "pit", "rai", "ram", "sdg", "sea", "sfo", "tam", "was",
        "jax", "car", "rav", "htx",
    ]
    code_to_fid: dict[str, int] = {}
    ambiguous = []
    for code in candidate_codes:
        cur.execute(
            "SELECT DISTINCT franchise_id FROM gold.franchise_aliases WHERE lower(alias_text) = %s",
            (code,),
        )
        fids = [r[0] for r in cur.fetchall()]
        if len(fids) != 1:
            ambiguous.append((code, fids))
        else:
            code_to_fid[code] = fids[0]

    if ambiguous:
        raise RuntimeError(f"Ambiguous/unresolved team codes against gold.franchise_aliases: {ambiguous}")
    if len(code_to_fid) != 32:
        raise RuntimeError(f"Expected 32 resolved codes, got {len(code_to_fid)}")

    cur.close()
    conn.close()
    return code_to_fid, fid_info


def _verify_team_code_map(code_to_fid: dict[str, int], fid_info: dict[int, dict]) -> None:
    """Concrete sanity checks the task explicitly asked for, run against
    the LIVE DB-resolved map, not an assumed one."""
    checks = [
        ("oti", 31, "ten", "Houston Oilers / Tennessee Titans franchise"),
        ("htx", 30, "hou", "Houston Texans (separate expansion franchise)"),
        ("ram", 25, "lar", "Rams (LA -> STL -> LA)"),
        ("rai", 24, "lv", "Raiders (Oakland -> LA -> Oakland -> Las Vegas)"),
        ("sdg", 9, "lac", "Chargers (San Diego -> LA)"),
        ("clt", 11, "ind", "Colts (Baltimore -> Indianapolis)"),
        ("crd", 8, "ari", "Cardinals (Chicago -> St. Louis -> Arizona)"),
    ]
    print("=== Team-code reconciliation verification ===")
    ok = True
    for code, expected_fid, expected_abbr, label in checks:
        got_fid = code_to_fid.get(code)
        got_abbr = fid_info.get(got_fid, {}).get("current_abbreviation")
        status = "OK" if (got_fid == expected_fid and got_abbr == expected_abbr) else "MISMATCH"
        if status != "OK":
            ok = False
        print(f"  [{status}] {code!r} -> franchise_id={got_fid} (current_abbr={got_abbr})  -- {label}")
    assert code_to_fid["oti"] != code_to_fid["htx"], "Oilers/Texans must NOT merge"
    if not ok:
        raise RuntimeError("Team-code verification failed -- see mismatches above")
    print("All spot checks passed. Oilers (oti) and Texans (htx) confirmed distinct franchise_ids.\n")


def load_plays_offense(code_to_fid: dict[str, int]) -> dict[tuple[int, int], int]:
    """(franchise_id, season) -> plays_offense, built from
    team_stats_{year}.csv + franchise_year_abbrev.csv, 1967-2025."""
    # season -> {team_name: abbrev}
    name_to_code_by_season: dict[int, dict[str, str]] = defaultdict(dict)
    with open(FRANCHISE_ABBREV_CSV, newline="") as f:
        for row in csv.DictReader(f):
            season = int(row["year"])
            name_to_code_by_season[season][row["team_name"]] = row["abbrev"]
    max_abbrev_year = max(name_to_code_by_season)

    result: dict[tuple[int, int], int] = {}
    unmapped = []
    for season in range(SEASON_MIN, SEASON_MAX + 1):
        fp = TEAM_STATS_DIR / f"team_stats_{season}.csv"
        if not fp.exists():
            continue
        # franchise_year_abbrev.csv currently tops out at max_abbrev_year
        # (checked: 2024). For any later season, fall back to that last
        # available year's team_name->code mapping -- verified this is a
        # safe no-op, not a guess: the 2025 team_stats.csv's distinct
        # team-name set is IDENTICAL to 2024's (no franchise renamed or
        # relocated between the two), confirmed with a direct diff before
        # relying on this fallback.
        lookup_season = season if season in name_to_code_by_season else max_abbrev_year
        with open(fp, newline="") as f:
            for row in csv.DictReader(f):
                team_name = row["team"]
                code = name_to_code_by_season.get(lookup_season, {}).get(team_name)
                if code is None or code not in code_to_fid:
                    unmapped.append((season, team_name, code))
                    continue
                fid = code_to_fid[code]
                po = row.get("plays_offense", "")
                if po in ("", None):
                    continue
                result[(fid, season)] = int(float(po))
    if unmapped:
        print(f"WARNING: {len(unmapped)} team_stats rows could not be mapped to a franchise_id "
              f"(showing up to 10): {unmapped[:10]}")
    return result


def load_gamebook(code_to_fid: dict[str, int]) -> dict[tuple[int, int], dict]:
    """(franchise_id, season) -> {comb_tackles, games_qualified}."""
    tackles: dict[tuple[int, int], float] = defaultdict(float)
    max_games: dict[tuple[int, int], int] = defaultdict(int)
    with open(GAMEBOOK_CSV, newline="") as f:
        for row in csv.DictReader(f):
            season = int(row["season"])
            code = row["team"]
            fid = code_to_fid[code]
            key = (fid, season)
            tackles[key] += float(row["tackle_sum"])
            gq = int(row["games_qualified"])
            if gq > max_games[key]:
                max_games[key] = gq
    return {
        key: {"comb_tackles": tackles[key], "games_qualified": max_games[key]}
        for key in tackles
    }


def load_gamebook_qualified_plays_offense(code_to_fid: dict[str, int]) -> dict[tuple[int, int], dict]:
    """(franchise_id, season) -> {plays_offense_qualified, games_qualified},
    from build_gamebook_qualified_plays_offense.py's output.

    THE BUG THIS FEEDS INTO: gamebook_comb_plays_ratio used to divide the
    GATED tackle numerator (comb_tackles from GAMEBOOK_CSV, summed ONLY
    across games that passed the >=70% completeness-ratio gate) by
    plays_offense from load_plays_offense() above, which is a FULL-SEASON
    total across every game that franchise played, gated or not -- a real
    numerator/denominator mismatch whenever a team-season's qualifying
    games were a strict subset of its full schedule. This loads the fix:
    a denominator built at the GAME level from
    ~/data/pfref/raw/boxscores/{year}/{game_id}/player_offense.csv
    (pass_cmp + rush_att + pass_sacked for the opponent), summed only
    across the SAME qualifying games as the numerator -- see that
    script's own module docstring for the full method, including the
    season-scoped gold.franchise_aliases team-code resolution and the
    handful of confirmed real-world path fallbacks (postseason-game PFR
    season offset, one home/away swap, one date-label slip) it needed to
    reach full coverage.

    1967-1969 AFL games remain a genuine gap here (as everywhere else in
    this project) -- PFR's own raw boxscores archive has zero AFL games
    for those seasons, not just gold.team_game_stats -- so any team-season
    resting entirely on AFL-era qualifying games will have no corrected
    ratio, same convention as the rest of this table (null over guessed).
    """
    result: dict[tuple[int, int], dict] = {}
    if not GAMEBOOK_QUALIFIED_PO_CSV.exists():
        print(f"WARNING: {GAMEBOOK_QUALIFIED_PO_CSV} not found -- "
              f"gamebook_comb_plays_ratio will fall back to the uncorrected full-season denominator")
        return result
    with open(GAMEBOOK_QUALIFIED_PO_CSV, newline="") as f:
        for row in csv.DictReader(f):
            season = int(row["season"])
            code = row["team"]
            fid = code_to_fid[code]
            result[(fid, season)] = {
                "plays_offense_qualified": int(row["plays_offense_qualified"]),
                "games_qualified_denom": int(row["games_qualified"]),
            }
    return result


def load_pbp() -> dict[tuple[int, int], float]:
    """(franchise_id, season) -> comb_tackles, regular season only.
    franchise_id already canonical -- no code translation."""
    tackles: dict[tuple[int, int], float] = defaultdict(float)
    with open(PBP_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row["game_type"] != "regular":
                continue
            season = int(row["season"])
            fid = int(row["franchise_id"])
            solo = float(row["solo"] or 0)
            ast = float(row["ast"] or 0)
            tackles[(fid, season)] += solo + ast
    return tackles


def load_official(code_to_fid: dict[str, int]) -> dict[tuple[int, int], float]:
    """(franchise_id, season) -> comb_tackles, season >= 2001 only."""
    tackles: dict[tuple[int, int], float] = {}
    with open(OFFICIAL_CSV, newline="") as f:
        for row in csv.DictReader(f):
            season = int(row["season"])
            if season < 2001:
                continue
            code = row["team"]
            fid = code_to_fid[code]
            tackles[(fid, season)] = float(row["comb_tackles"])
    return tackles


def main() -> None:
    code_to_fid, fid_info = load_franchise_maps()
    _verify_team_code_map(code_to_fid, fid_info)

    plays_offense = load_plays_offense(code_to_fid)
    gamebook = load_gamebook(code_to_fid)
    gamebook_qualified_po = load_gamebook_qualified_plays_offense(code_to_fid)
    pbp = load_pbp()
    official = load_official(code_to_fid)

    # Grain: union of (fid, season) keys across all four sources -- this
    # naturally bounds each franchise to seasons it actually existed
    # (expansion teams simply have no plays_offense/pbp/official rows
    # before they existed) without needing a founded_season column
    # (gold.franchises.founded_season is currently unpopulated -- checked
    # directly, all 32 rows NULL).
    all_keys = set(plays_offense) | set(gamebook) | set(pbp) | set(official)
    all_keys = {k for k in all_keys if SEASON_MIN <= k[1] <= SEASON_MAX}

    rows = []
    for fid, season in sorted(all_keys, key=lambda k: (k[1], k[0])):
        info = fid_info[fid]
        city, team_name = info["current_city"], info["current_team_name"]
        display_name = team_name if team_name.startswith(city) else f"{city} {team_name}"
        po = plays_offense.get((fid, season))
        gb = gamebook.get((fid, season))
        gb_qpo = gamebook_qualified_po.get((fid, season))
        pbp_t = pbp.get((fid, season))
        off_t = official.get((fid, season))

        # gamebook_comb_plays_ratio's denominator: qualified-games-only
        # plays_offense (gb_qpo) when available -- the fix this script now
        # carries (see load_gamebook_qualified_plays_offense's docstring)
        # -- falling back to the old full-season plays_offense when it
        # isn't.
        #
        # CRITICAL GUARD, found by inspecting a real case (NYJ 1969) before
        # trusting this blindly: the qualified-games-only denominator is
        # only correct if it was built from EVERY game backing the
        # numerator. PFR's raw boxscores archive is missing essentially
        # all 1967-1969 AFL games (the same archive-level gap already
        # documented project-wide, not new to this script), so for a
        # team-season whose games_qualified spans mostly AFL-era games,
        # plays_offense_qualified can rest on just a handful of the
        # numerator's real qualifying games while gamebook_comb_tackles
        # still reflects ALL of them -- confirmed on NYJ 1969: numerator
        # corpus says 8 games qualified, but only 1 of those 8 had a
        # resolvable player_offense.csv, so the naive corrected ratio
        # came out to 11.3 (i.e. >1100%), an obviously wrong number driven
        # by a 1-game denominator under an 8-game numerator -- WORSE than
        # the bug being fixed, not better. So the qualified denominator is
        # only trusted when gb_qpo's own games_qualified count EXACTLY
        # matches the numerator corpus's games_qualified for that
        # team-season; any mismatch (including "no qualified-PO rows
        # found at all") falls back to the full-season denominator instead,
        # flagged via gamebook_ratio_denom_source.
        gb_po_qualified = gb_qpo["plays_offense_qualified"] if gb_qpo else None
        gb_games_matched = (
            gb_qpo is not None and gb is not None
            and gb_qpo["games_qualified_denom"] == gb["games_qualified"]
        )
        if gb and gb_po_qualified and gb_games_matched:
            gb_ratio = gb["comb_tackles"] / gb_po_qualified
            gb_denom_source = "qualified_games"
        elif gb and po:
            gb_ratio = gb["comb_tackles"] / po
            gb_denom_source = "full_season_fallback_partial_denom_coverage" if gb_qpo else "full_season_fallback"
        else:
            gb_ratio = None
            gb_denom_source = ""

        pbp_ratio = (pbp_t / po) if (pbp_t is not None and po) else None
        off_ratio = (off_t / po) if (off_t is not None and po) else None

        diff = None
        if season >= 2001 and pbp_ratio is not None and off_ratio is not None:
            diff = pbp_ratio - off_ratio

        rows.append({
            "franchise_id": fid,
            "team_current_abbr": info["current_abbreviation"],
            "team_current_name": display_name,
            "season": season,
            "plays_offense": po if po is not None else "",
            "gamebook_comb_tackles": gb["comb_tackles"] if gb else "",
            "gamebook_plays_offense_qualified": gb_po_qualified if gb_po_qualified is not None else "",
            "gamebook_comb_plays_ratio": round(gb_ratio, 4) if gb_ratio is not None else "",
            "gamebook_ratio_denom_source": gb_denom_source,
            "gamebook_games_qualified": gb["games_qualified"] if gb else "",
            "pbp_comb_tackles": pbp_t if pbp_t is not None else "",
            "pbp_comb_plays_ratio": round(pbp_ratio, 4) if pbp_ratio is not None else "",
            "official_comb_tackles": off_t if off_t is not None else "",
            "official_comb_plays_ratio": round(off_ratio, 4) if off_ratio is not None else "",
            "pbp_vs_official_ratio_diff": round(diff, 4) if diff is not None else "",
        })

    fieldnames = list(rows[0].keys())
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {OUT_CSV}")

    # Coverage summary
    n1 = n2 = n3 = 0
    for r in rows:
        n_sources = sum([
            bool(r["gamebook_comb_tackles"] != ""),
            bool(r["pbp_comb_tackles"] != ""),
            bool(r["official_comb_tackles"] != ""),
        ])
        if n_sources == 1:
            n1 += 1
        elif n_sources == 2:
            n2 += 1
        elif n_sources == 3:
            n3 += 1
    print(f"Team-seasons with exactly 1 source: {n1}")
    print(f"Team-seasons with exactly 2 sources: {n2}")
    print(f"Team-seasons with exactly 3 sources: {n3}")
    n_null_po = sum(1 for r in rows if r["plays_offense"] == "")
    print(f"Team-seasons with NO plays_offense (denominator gap, expect AFL 1967-1969): {n_null_po}")
    afl_gap = sorted({(r["season"], r["team_current_abbr"]) for r in rows if r["plays_offense"] == ""})
    print(f"  seasons/teams affected: {afl_gap[:15]}{' ...' if len(afl_gap) > 15 else ''}")


if __name__ == "__main__":
    main()
