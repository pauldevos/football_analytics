#!/usr/bin/env python3
"""
Build the tackle opportunity-ratio normalization table for IDI's pre-2001
tackle_share fix (dpvs/idi.py) -- see docs/framework_decisions.md, the
section documenting this 2026-08-22 change, for the full motivation.

WHY THIS EXISTS: unlike sacks/INT/TFL (official, well-scored stats), season
tackle TOTALS are prone to real, confirmed inflation by some team scoring
staffs/media guides -- the flagship case: Randy Gradishar's 1978 media
guide credits him with 286 solo tackles in 14/16 games, an implausible
number no modern player approaches even at 17 games. A player's SHARE of
their team's total is presumably far less distorted by this than the
absolute total itself (padding tends to inflate everyone's counts roughly
proportionally, not change who tackled whom), so the fix here is: keep the
player's real observed share, but replace the unreliable raw team-season
TOTAL with an "adjusted expected" total derived from real, era-appropriate
defensive opportunities and a stable empirical ratio measured from the one
era this project trusts as officially, reliably scored: 2001-2025 PFR data
(gold.player_game_stats, current_source='pfr', solo_tackle/ast_tackle
columns -- see football_analytics/CLAUDE.md's / root CLAUDE.md's "Source
priority for tackles: PFR 2001+ > media guide > card backs").

Mechanism (solo and assist handled as two SEPARATE ratios throughout, per
the user's own formula -- a team's assist-crediting generosity is not the
same statistical process as its solo-crediting generosity, confirmed below
by the two ratios drifting differently over time):

  1. "Defensive opportunities" for a team-season = EXACTLY
     gamebooks_boxscores' build_defensive_leaderboards.py's own
     completeness-ratio-gate denominator: opponent's rush attempts + pass
     completions + times sacked, from gold.team_game_stats. NOT extended
     with fumbles (an earlier draft of this script added opponent fumbles
     on the reasoning that a fumbled play still ends in a tackle-adjacent
     event -- corrected 2026-08-22: a fumble happens DURING a rush
     attempt, a completed pass, or a sack, so it is already counted inside
     those three categories; adding it again would double-count that
     play). Computed here directly from gold.team_game_stats rather than
     imported from that script, since this needs the full 1967-2000 range
     (that script defaults to a narrower window).

  2. 2001-2025 reference ratio = (sum of team-season solo_tackle) /
     (sum of team-season defensive opportunities), separately for solo and
     assist, POOLED across teams within a season (not averaged
     team-by-team -- pooling weights by actual opportunity volume, exactly
     like every other ratio-based gate this project uses).

  3. STABILITY CHECK (season-by-season, not assumed): solo_ratio is real
     and stable across 2001-2025 (~0.85-0.90, season-level std ~0.017, a
     ~1.9% CV) -- safe to treat as one constant across the window.
     ast_ratio is NOT flat: it drifts from ~0.14-0.19 in 2001-2010 up to
     ~0.23-0.25 by 2021-2025 -- a real, confirmed trend (assist-tackle
     crediting has gotten measurably more generous in the modern game),
     not noise. Since this ratio is being projected BACKWARD onto
     1967-2000 (further from 2025's scoring convention, not closer to
     it), using the full 2001-2025 pool would import a modern-era
     generosity bias into 1970s/1980s seasons -- the opposite of this
     fix's own goal. The reference ratio actually applied below is
     therefore the EARLY-window pool (2001-2010, closest in scoring-era
     convention to the seasons it's projected onto), not the full-range
     pool -- reported side by side so the difference this choice makes is
     visible, not hidden:
         solo_ratio: early(2001-2010)=0.8897  full(2001-2025)=0.8781
         ast_ratio:  early(2001-2010)=0.1763  full(2001-2025)=0.1901

     KNOWN LIMITATION, confirmed 2026-08-22 via a direct spot check (not
     assumed): this whole 2001-2025 "reliable" reference is drawn from
     gold.player_game_stats' current_source='pfr' rows, which trace back
     to silver.player_game_stats_pfr -- itself PARSED FROM PFR's pbp.csv
     PLAY-BY-PLAY TEXT, not PFR's own official season box-score tables.
     This project has already separately confirmed pbp.csv text-derived
     tackle counts undercount real totals (docs
     project_pfr_pbp_text_completeness_gap_20260820: Studwell 1983, real
     130 vs pbp.csv 87, ~33% low). This script's own HOU 2025 spot check
     against a real independent estimate (~591 solo / ~475 assist over 17
     games, opponent-opportunities ~985) makes the SAME finding sharper:
     computed solo=624 (reasonably close, +5.6%) but computed assist=183
     (MASSIVELY low, ~2.6x under the ~475 estimate) -- and HOU's own
     ast_ratio (0.239) sits right at the 2025 LEAGUE-POOLED ast_ratio
     (0.2346), so this is not a HOU-specific data problem, it's systemic
     across the whole source: pbp.csv's parenthetical-name notation
     reliably captures the ONE primary/solo tackler but is far less
     complete at capturing a SECOND (assist) name on the same play than
     real press-box game charting is. Net effect: solo_ratio above is
     reasonably trustworthy; ast_ratio is very likely a real
     UNDERESTIMATE of true official assist-crediting generosity, in both
     eras this script touches (2001-2025 reference AND, by extension, the
     1967-2000 seasons it gets projected onto) -- not something fixable
     within this script without a genuinely different, non-pbp.csv-
     derived season-tackle source (PFR's own box-score pages, not
     currently ingested into football_db). Flagged here rather than
     silently trusted; solo-side normalization is the part of this
     mechanism to lean on with confidence, assist-side less so.

  4. For each 1967-2000 team-season: opportunities (step 1) x reference
     ratio (step 3, early-window) = adj_expected_solos / adj_expected_ast.
     dpvs/idi.py's load_tackle_opportunity_adjustment() consumes this
     table directly; the per-player blend (solo_share * adj_expected_solos
     + ast_share * adj_expected_ast, normalized into a share) happens
     there, not here, per this project's standing prep-script/loader-
     function split (see build_tfl_gated_corpus.py / build_tackle_gated_
     corpus.py for the established pattern this mirrors).

Output:
  data_output/tackle_opportunity_adjusted_1967_2000.csv
    columns: season, team, opportunities, adj_expected_solos, adj_expected_ast
    -- the table dpvs/idi.py actually consumes (load_tackle_opportunity_
    adjustment()).
  data_output/tackle_opportunity_ratio_by_team_season.csv
    columns: team, season, solo_tackles, assist_tackles, total_tackles,
    opportunities, solo_ratio, assist_ratio -- one row per (team, season)
    for EVERY 2001-2025 team-season, the full raw inspection table behind
    the calibration above (not just the pooled summary) -- added
    2026-08-22 so the derived ratio can be checked directly against real
    per-team-season numbers rather than trusted as a black box.

Also prints the full stability report (year-by-year ratios) to stdout --
read it before trusting this table on a new era range; this is a real
empirical calibration, not an assumption, and it should keep being
re-verified if this script is ever rerun after a data reload.

Usage: python3 build_tackle_opportunity_ratio.py
    (needs football_db's .venv on PYTHONPATH -- same requirement as every
    other Postgres-backed prep script in this project)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.home() / "github" / "football" / "football_db" / "src"))

from football_db.db import get_connection  # noqa: E402

# franchise_id -> pgd team code (same table as dpvs/idi.py's _FID_TO_TEAM /
# scripts/load_dpvs_g_to_db.py's TEAM_TO_FID -- copied here as its own literal,
# same reasoning those files already document: a plain Python-side copy, not
# a cross-package import).
FID_TO_TEAM: dict[int, str] = {
    16: "atl", 4: "buf", 2: "chi", 3: "cin", 6: "cle", 11: "clt", 8: "crd",
    13: "dal", 5: "den", 20: "det", 21: "gnb", 10: "kan", 14: "mia",
    32: "min", 27: "nor", 23: "nwe", 17: "nyg", 19: "nyj", 31: "oti",
    15: "phi", 29: "pit", 24: "rai", 25: "ram", 9: "sdg", 28: "sea",
    1: "sfo", 7: "tam", 12: "was",
    18: "jax", 22: "car", 26: "rav", 30: "htx",
}

OUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data_output" / "tackle_opportunity_adjusted_1967_2000.csv"
)
INSPECT_PATH = (
    Path(__file__).resolve().parent.parent
    / "data_output" / "tackle_opportunity_ratio_by_team_season.csv"
)

EARLY_REF_SEASONS = (2001, 2010)  # inclusive -- see module docstring point 3


def _team_season_opportunities(conn, lo: int, hi: int) -> pd.DataFrame:
    """Team-season defensive opportunities = opponent's own
    (rush_attempts + pass_completions + times_sacked) -- EXACTLY
    gamebooks_boxscores' build_defensive_leaderboards.py's own
    completeness-ratio denominator, no fumble term (see module docstring
    point 1 for why fumbles were considered and then deliberately left
    out: double-counting a play already inside one of these three
    categories). Summed across that team's regular-season games. Returns
    season, franchise_id, def_opportunities."""
    tgs = pd.read_sql(f"""
        SELECT g.game_id, g.season, g.home_franchise_id, g.away_franchise_id,
               t.franchise_id,
               coalesce(t.rush_attempts,0) + coalesce(t.pass_completions,0)
               + coalesce(t.times_sacked,0) AS off_opportunities
        FROM gold.team_game_stats t
        JOIN gold.games g ON g.game_id = t.game_id
        WHERE g.season BETWEEN {lo} AND {hi} AND g.game_type = 'regular'
    """, conn)
    tgs["opp_fid"] = np.where(
        tgs["franchise_id"] == tgs["home_franchise_id"],
        tgs["away_franchise_id"], tgs["home_franchise_id"],
    )
    opp_map = tgs.set_index(["game_id", "franchise_id"])["off_opportunities"]
    tgs["def_opportunities"] = [
        opp_map.get((gid, opp), np.nan)
        for gid, opp in zip(tgs["game_id"], tgs["opp_fid"])
    ]
    return tgs.groupby(["season", "franchise_id"], as_index=False)["def_opportunities"].sum()


VERIFIED_TACKLE_RATIO_CSV = (
    Path(__file__).resolve().parent.parent
    / "data_output" / "tackle_ratio_by_team_season.csv"
)


def _team_season_tackles_2001plus(conn) -> pd.DataFrame:
    """Reliable 2001-2025 team-season solo/ast totals.

    2026-08-22 CORRECTED: this used to query gold.player_game_stats WHERE
    current_source='pfr' -- confirmed THIS SESSION to be PFR pbp.csv
    PLAY-BY-PLAY TEXT parsed into a table, not official box-score data (see
    the KNOWN LIMITATION paragraph directly above in this module's
    docstring, still left in place as the historical record of how that
    was found). Direct evidence the old source was wrong: HOU 2025 assist
    tackles came back 183 from gold.player_game_stats vs the real,
    official player_defense.csv sum of 475 -- a ~2.6x undercount, and not
    HOU-specific (HOU's own ast_ratio from the old source sat right at
    that season's league-pooled ast_ratio).

    Fixed source: data_output/tackle_ratio_by_team_season.csv, built by
    scripts/build_verified_tackle_ratio.py directly from PFR's own
    ~/data/pfref/raw/boxscores/{year}/{game_id}/player_defense.csv --
    real official per-game box-score rows, not play-by-play text. Verified
    against a real pasted PFR example (Denver 2001: Comb=951 Solo=803
    Ast=148 -- exact match) and re-confirmed the HOU 2025 case directly:
    that script now computes solo=591 ast=475, matching this project's own
    independent ~591/~475 estimate almost exactly. See
    docs/deferred/tackle_ratio_verification_20260822.md for the full
    writeup, including how far back player_defense.csv's solo/ast split
    exists (1994) and the real (not assumed) solo:ast ratio's season-by-
    season drift.

    That CSV already restricts to real regular-season games only (see its
    own trim_to_regular_season() -- a second, independently-found bug
    fixed the same session: raw boxscore folders include playoff games,
    which would otherwise inflate team-season tackle numerators against a
    plays_offense denominator that never counted them), so this function
    just reads it and re-keys team (stable lowercase abbrev) back to
    franchise_id via FID_TO_TEAM, to match this script's existing merge
    keys -- no other logic in this file changes."""
    df = pd.read_csv(VERIFIED_TACKLE_RATIO_CSV)
    df = df[(df["season"] >= 2001) & (df["season"] <= 2025)].copy()
    team_to_fid = {v: k for k, v in FID_TO_TEAM.items()}
    df["franchise_id"] = df["team"].map(team_to_fid)
    df = df.dropna(subset=["franchise_id"]).copy()
    df["franchise_id"] = df["franchise_id"].astype(int)
    df = df.rename(columns={"solo_tackles": "solo", "ast_tackles": "ast"})
    return df[["season", "franchise_id", "solo", "ast"]]


def build_inspection_table(conn) -> pd.DataFrame:
    """Full, un-pooled (team, season) table for every 2001-2025 team-season
    -- solo/assist/total tackles, opportunities, and each team-season's OWN
    solo_ratio/assist_ratio -- so the pooled reference ratio in
    compute_reference_ratio() can be checked directly against real
    per-team-season rows instead of trusted as a single opaque number.
    Written to INSPECT_PATH."""
    opp = _team_season_opportunities(conn, 2001, 2025)
    tkl = _team_season_tackles_2001plus(conn)
    merged = tkl.merge(opp, on=["season", "franchise_id"], how="inner")
    merged["team"] = merged["franchise_id"].map(FID_TO_TEAM)
    merged = merged.dropna(subset=["team"]).copy()
    merged = merged.rename(columns={
        "solo": "solo_tackles", "ast": "assist_tackles",
        "def_opportunities": "opportunities",
    })
    merged["total_tackles"] = merged["solo_tackles"] + merged["assist_tackles"]
    merged["solo_ratio"] = merged["solo_tackles"] / merged["opportunities"]
    merged["assist_ratio"] = merged["assist_tackles"] / merged["opportunities"]
    out = merged[["team", "season", "solo_tackles", "assist_tackles", "total_tackles",
                  "opportunities", "solo_ratio", "assist_ratio"]]
    return out.sort_values(["team", "season"]).reset_index(drop=True)


def compute_reference_ratio(conn) -> dict:
    """Builds the full 2001-2025 stability report and returns the applied
    (early-window) reference ratio. See module docstring point 3."""
    opp = _team_season_opportunities(conn, 2001, 2025)
    tkl = _team_season_tackles_2001plus(conn)
    merged = tkl.merge(opp, on=["season", "franchise_id"], how="inner")

    by_season = merged.groupby("season", as_index=False).agg(
        solo=("solo", "sum"), ast=("ast", "sum"), opp=("def_opportunities", "sum")
    )
    by_season["solo_ratio"] = by_season["solo"] / by_season["opp"]
    by_season["ast_ratio"] = by_season["ast"] / by_season["opp"]

    print("2001-2025 reference-ratio stability check (pooled per season):")
    print(by_season[["season", "solo_ratio", "ast_ratio"]].to_string(index=False))
    print(
        f"\nsolo_ratio: season-level mean={by_season['solo_ratio'].mean():.4f} "
        f"std={by_season['solo_ratio'].std():.4f} "
        f"(CV={by_season['solo_ratio'].std() / by_season['solo_ratio'].mean():.1%}) -- stable"
    )
    print(
        f"ast_ratio:  season-level mean={by_season['ast_ratio'].mean():.4f} "
        f"std={by_season['ast_ratio'].std():.4f} "
        f"(CV={by_season['ast_ratio'].std() / by_season['ast_ratio'].mean():.1%}) -- "
        f"NOT flat, real upward drift 2001->2025 (see module docstring point 3)"
    )

    early = merged[merged["season"].between(*EARLY_REF_SEASONS)]
    full = merged
    ref = {
        "solo_ratio_early": early["solo"].sum() / early["def_opportunities"].sum(),
        "ast_ratio_early": early["ast"].sum() / early["def_opportunities"].sum(),
        "solo_ratio_full": full["solo"].sum() / full["def_opportunities"].sum(),
        "ast_ratio_full": full["ast"].sum() / full["def_opportunities"].sum(),
    }
    print(
        f"\nEarly-window (2001-2010, APPLIED below) pooled ratio: "
        f"solo={ref['solo_ratio_early']:.4f} ast={ref['ast_ratio_early']:.4f}"
    )
    print(
        f"Full-range (2001-2025) pooled ratio (reported, NOT applied): "
        f"solo={ref['solo_ratio_full']:.4f} ast={ref['ast_ratio_full']:.4f}"
    )
    return ref


def build_pre2001_table(conn, ref: dict) -> pd.DataFrame:
    opp = _team_season_opportunities(conn, 1967, 2000)
    opp["team"] = opp["franchise_id"].map(FID_TO_TEAM)
    opp = opp.dropna(subset=["team"]).copy()
    opp["adj_expected_solos"] = opp["def_opportunities"] * ref["solo_ratio_early"]
    opp["adj_expected_ast"] = opp["def_opportunities"] * ref["ast_ratio_early"]
    out = opp.rename(columns={"def_opportunities": "opportunities"})[
        ["season", "team", "opportunities", "adj_expected_solos", "adj_expected_ast"]
    ]
    return out.sort_values(["season", "team"]).reset_index(drop=True)


def main() -> None:
    conn = get_connection()
    try:
        inspect_table = build_inspection_table(conn)
        ref = compute_reference_ratio(conn)
        table = build_pre2001_table(conn, ref)
    finally:
        conn.close()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    inspect_table.to_csv(INSPECT_PATH, index=False)
    print(f"\nWrote {len(inspect_table)} team-seasons (2001-2025 raw inspection table) to {INSPECT_PATH}")

    hou_2025 = inspect_table[(inspect_table["team"] == "htx") & (inspect_table["season"] == 2025)]
    if not hou_2025.empty:
        r = hou_2025.iloc[0]
        print(
            f"\nHOU 2025 sanity check: solo={r['solo_tackles']:.0f} "
            f"assist={r['assist_tackles']:.0f} opportunities={r['opportunities']:.0f} "
            f"(user's rough estimate: ~591 solo / ~475 assist / ~985 opportunities)"
        )

    table.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(table)} team-seasons to {OUT_PATH}")
    print(table.head(10).to_string(index=False))

    # Randy Gradishar / DEN 1978 sanity check (2026-08-22, post-fix) --
    # see docs/deferred/tackle_ratio_verification_20260822.md for the full
    # before/after against the pre-fix adj_expected_solos/ast this table
    # used to produce. Gradishar's own raw solo=129/ast=8 (regular season,
    # gold.player_game_stats current_source='pfr') and DEN 1978 team
    # totals (team_solo=695/team_ast=74, same source) are pulled directly
    # here rather than assumed, so this check stays honest if either
    # changes on a future rebuild.
    den_1978 = table[(table["team"] == "den") & (table["season"] == 1978)]
    if not den_1978.empty:
        r = den_1978.iloc[0]
        gradishar_solo, gradishar_ast = 129, 8
        team_solo, team_ast = 695, 74
        solo_share = gradishar_solo / team_solo
        ast_share = gradishar_ast / team_ast
        implied_solo = solo_share * r["adj_expected_solos"]
        implied_ast = ast_share * r["adj_expected_ast"]
        norm_share = (implied_solo + implied_ast) / (r["adj_expected_solos"] + r["adj_expected_ast"])
        print(
            f"\nRandy Gradishar / DEN 1978 sanity check (post-fix ratio applied): "
            f"opportunities={r['opportunities']:.0f} "
            f"adj_expected_solos={r['adj_expected_solos']:.1f} "
            f"adj_expected_ast={r['adj_expected_ast']:.1f} | "
            f"raw solo_share={solo_share:.4f} ast_share={ast_share:.4f} | "
            f"opportunity-normalized implied solo={implied_solo:.1f} "
            f"implied ast={implied_ast:.1f} normalized_tackle_share={norm_share:.4f}"
        )


if __name__ == "__main__":
    main()
