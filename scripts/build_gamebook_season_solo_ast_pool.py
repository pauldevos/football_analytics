#!/usr/bin/env python3
"""
Rebuild data_output/tackle_ratio_by_season_1967_1977_gamebook.csv with a
solo/ast split, matching data_output/tackle_ratio_by_season_2001_2025_official.csv's
column layout (season, plays_offense, comb_tackles, solo, asst,
comb_plays_ratio, solo_plays_ratio, asst_plays_ratio).

WHY THIS EXISTS: the previous version of this table only had comb_tackles
(no solo/ast split) because build_tackle_gated_corpus.py's output,
data_output/tackle_gamebooks_gated_1967_1977.csv, only carried a combined
tackle_sum per player-season -- not a real data limitation, just an
aggregation choice. build_tackle_gated_corpus.py was extended 2026-08-22
to also carry solo_sum/ast_sum per player-season (parse_boxscore() in
gamebooks_boxscores/build_defensive_leaderboards.py already extracts both
fields per row; this was purely a matter of carrying them through), and
the corpus was rebuilt. This script re-derives the season-pooled table
from that richer corpus.

METHODOLOGY -- reverse-engineered directly from the numbers in the
existing (pre-2026-08-22) tackle_ratio_by_season_1967_1977_gamebook.csv,
confirmed by exact reproduction before trusting it (see inline checks
run during development): the season-pooled comb_tackles/plays_offense
figures are NOT a sum over every team-season with gamebook data -- they
are a sum ONLY over team-seasons whose gamebook_ratio_denom_source in
data_output/tackle_coverage_ratio_all_sources_1967_2025.csv is exactly
"qualified_games" (i.e. the per-game qualifying-games denominator from
build_gamebook_qualified_plays_offense.py was available AND its
games_qualified count matched the numerator corpus's own count for that
team-season -- see that script's and build_tackle_coverage_all_sources.py's
own docstrings for why "full_season_fallback"/
"full_season_fallback_partial_denom_coverage" team-seasons are excluded
from the pooled ratio: a full-season denominator under a partial-season
numerator understates the ratio, sometimes badly). Team-seasons NOT
qualifying this way are still counted (not silently dropped) via the
n_teams_fallback column, kept unchanged from the prior version of this
table, for transparency about the season's real gamebook coverage.

This script reuses that same team-season classification directly from
tackle_coverage_ratio_all_sources_1967_2025.csv (already built this
session, same gate, not re-derived) and tackle_gamebooks_qualified_plays_
offense_1967_1977.csv (per the task's explicit instruction to reuse it
rather than re-derive the qualifying-games-only plays_offense
denominator), then pools solo_sum/ast_sum from the (now-extended) gated
corpus over the exact same team-season set, so solo + asst reproduces
comb_tackles exactly by construction (same underlying rows, same gate,
just split before summing instead of after).

1976/1977 PROVISIONAL FLAG: per the user's explicit note this session
("our data for 1976 and 1977 will need to be recalculated as we don't yet
have all the games yet"), a data_completeness_note column flags these two
seasons as provisional/subject to revision. Every other season gets an
empty string in that column, not silently implying every season is
equally final -- 1976/1977 specifically are the only ones the user named.

Output: data_output/tackle_ratio_by_season_1967_1977_gamebook.csv
Usage: python3 build_gamebook_season_solo_ast_pool.py
    (pure csv/stdlib, no DB/venv dependency -- everything it reads was
    already built by earlier scripts in this family)
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_OUTPUT = REPO_ROOT / "data_output"

GATED_CSV = DATA_OUTPUT / "tackle_gamebooks_gated_1967_1977.csv"
COVERAGE_CSV = DATA_OUTPUT / "tackle_coverage_ratio_all_sources_1967_2025.csv"
QUALIFIED_PO_CSV = DATA_OUTPUT / "tackle_gamebooks_qualified_plays_offense_1967_1977.csv"
OUT_CSV = DATA_OUTPUT / "tackle_ratio_by_season_1967_1977_gamebook.csv"

SEASONS = list(range(1967, 1978))

# franchise_id -> historic corpus-lowercase code, identical copy to the one
# in build_tackle_gated_corpus.py / build_gamebook_qualified_plays_offense.py
# (kept in sync manually, same convention those scripts already use -- see
# their own comments on why current_abbreviation can't be used instead).
FID_TO_TEAM: dict[int, str] = {
    16: "atl", 4: "buf", 2: "chi", 3: "cin", 6: "cle", 11: "clt", 8: "crd",
    13: "dal", 5: "den", 20: "det", 21: "gnb", 10: "kan", 14: "mia",
    32: "min", 27: "nor", 23: "nwe", 17: "nyg", 19: "nyj", 31: "oti",
    15: "phi", 29: "pit", 24: "rai", 25: "ram", 9: "sdg", 28: "sea",
    1: "sfo", 7: "tam", 12: "was",
}
TEAM_TO_FID = {v: k for k, v in FID_TO_TEAM.items()}

DATA_COMPLETENESS_NOTES = {
    1976: "Provisional: 1976 gamebook corpus is not yet fully processed "
          "(per user note 2026-08-22); numbers subject to revision once "
          "remaining games are added.",
    1977: "Provisional: 1977 gamebook corpus is not yet fully processed "
          "(per user note 2026-08-22); numbers subject to revision once "
          "remaining games are added.",
}


def load_qualified_team_seasons() -> dict[tuple[int, int], dict]:
    """(season, franchise_id) -> row dict, restricted to
    gamebook_ratio_denom_source == 'qualified_games', plus the season-level
    n_teams_* coverage counts (identical definitions to the table this
    replaces: n_teams_qualified_games = count of denom_source ==
    'qualified_games'; n_teams_fallback = count of denom_source in the two
    fallback values; n_teams_total = every team-season row that season,
    qualified or not)."""
    qualified: dict[tuple[int, int], dict] = {}
    counts = defaultdict(lambda: {"qualified": 0, "fallback": 0, "total": 0})
    with open(COVERAGE_CSV, newline="") as f:
        for row in csv.DictReader(f):
            season = int(row["season"])
            if season not in SEASONS:
                continue
            fid = int(row["franchise_id"])
            src = row["gamebook_ratio_denom_source"]
            counts[season]["total"] += 1
            if src == "qualified_games":
                counts[season]["qualified"] += 1
                qualified[(season, fid)] = row
            elif src in ("full_season_fallback", "full_season_fallback_partial_denom_coverage"):
                counts[season]["fallback"] += 1
    return qualified, counts


def load_qualified_plays_offense() -> dict[tuple[int, int], int]:
    """(season, franchise_id) -> plays_offense_qualified, straight from
    build_gamebook_qualified_plays_offense.py's own output -- reused
    directly per the task's instruction, not re-derived."""
    out = {}
    with open(QUALIFIED_PO_CSV, newline="") as f:
        for row in csv.DictReader(f):
            season = int(row["season"])
            fid = TEAM_TO_FID[row["team"]]
            out[(season, fid)] = int(row["plays_offense_qualified"])
    return out


def load_solo_ast_by_team_season() -> dict[tuple[int, int], dict]:
    """(season, franchise_id) -> {"solo": x, "ast": y, "comb": z}, summed
    across every player-season row in the (now solo/ast-extended) gated
    corpus. Includes ALL team-seasons present in that file -- filtering to
    the qualified_games set happens by the caller, at pooling time, so this
    stays a straight reusable groupby."""
    out: dict[tuple[int, int], dict] = defaultdict(lambda: {"solo": 0.0, "ast": 0.0, "comb": 0.0})
    with open(GATED_CSV, newline="") as f:
        for row in csv.DictReader(f):
            season = int(row["season"])
            fid = TEAM_TO_FID[row["team"]]
            key = (season, fid)
            out[key]["solo"] += float(row["solo_sum"])
            out[key]["ast"] += float(row["ast_sum"])
            out[key]["comb"] += float(row["tackle_sum"])
    return out


def main() -> None:
    qualified, counts = load_qualified_team_seasons()
    qpo = load_qualified_plays_offense()
    solo_ast = load_solo_ast_by_team_season()

    rows_out = []
    for season in SEASONS:
        plays_offense = comb_tackles = solo = asst = 0.0
        team_seasons_used = 0
        for (s, fid) in qualified:
            if s != season:
                continue
            po = qpo.get((s, fid))
            sa = solo_ast.get((s, fid))
            if po is None or sa is None:
                # Shouldn't happen -- every qualified_games team-season by
                # construction has both a qualified-PO row and gated-corpus
                # rows (that's what made it "qualified_games" in the
                # coverage file to begin with). Skip defensively, don't
                # silently fabricate a zero contribution as if it were real.
                continue
            plays_offense += po
            comb_tackles += sa["comb"]
            solo += sa["solo"]
            asst += sa["ast"]
            team_seasons_used += 1

        c = counts[season]
        # Round solo/asst first, then derive the displayed comb_tackles as
        # their sum -- NOT an independent round(comb_tackles) -- so
        # solo + asst == comb_tackles holds exactly in the output, every
        # row, by construction. (A handful of qualifying player-seasons
        # carry a genuine .5 tackle -- e.g. 1973 Otis Sistrunk, tackle_sum
        # 77.5 = solo_sum 66.5 + ast_sum 11.0, a pre-existing artifact of
        # the underlying gated corpus, not introduced here -- so rounding
        # solo/asst independently and comb_tackles independently can land
        # 1 apart; deriving comb_tackles from the already-rounded solo/asst
        # avoids that instead of leaving a sanity-check mismatch.)
        solo_r, asst_r = round(solo), round(asst)
        rows_out.append({
            "season": season,
            "plays_offense": round(plays_offense),
            "comb_tackles": solo_r + asst_r,
            "solo": solo_r,
            "asst": asst_r,
            "comb_plays_ratio": round(comb_tackles / plays_offense, 4) if plays_offense else "",
            "solo_plays_ratio": round(solo / plays_offense, 4) if plays_offense else "",
            "asst_plays_ratio": round(asst / plays_offense, 4) if plays_offense else "",
            "n_teams_qualified_games": c["qualified"],
            "n_teams_fallback": c["fallback"],
            "n_teams_total": c["total"],
            "data_completeness_note": DATA_COMPLETENESS_NOTES.get(season, ""),
        })
        assert team_seasons_used == c["qualified"], (
            f"{season}: pooled {team_seasons_used} team-seasons but coverage file "
            f"says {c['qualified']} qualified -- mismatch, investigate before trusting output"
        )

    fieldnames = list(rows_out[0].keys())
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows_out)
    print(f"wrote {len(rows_out)} season rows -> {OUT_CSV}")
    for r in rows_out:
        print(r)


if __name__ == "__main__":
    main()
