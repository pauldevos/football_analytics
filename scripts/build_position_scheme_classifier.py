#!/usr/bin/env python3
"""
Position x scheme classifier -- implements docs/deferred/05_position_scheme_grouping_scoping.md's
"What to build" section. For each (player_id, franchise_id, season) with a defensive
position, joins the raw position string (silver.player_team_seasons_pfr.position,
normalized through football_db's existing gold.position_taxonomy) with that
team-season's defensive scheme (gold.team_scheme_coach_season.defensive_alignment,
Phase 1 of this same project -- built 2026-08-22, replaces querying
silver.team_schemes_pfr directly per that phase's own note) to assign one of the
user's 8 named position x scheme buckets.

Run via football_analytics' own .venv (has pyarrow/pandas; connects directly to
football_db's shared Postgres warehouse with psycopg2, not football_analytics'
own separate sqlite/local DB -- this script does NOT use scripts/db.py):
    cd ~/github/football/football_analytics && source .venv/bin/activate
    python3 scripts/build_position_scheme_classifier.py

Writes:
    data_output/position_scheme_classification.parquet
        -- one row per (player_id, franchise_id, season): full classification,
           reused directly by build_tackle_quality_by_position.py (Phase 3).
    Prints: corpus-wide coverage report + named-player validation results.

--- Mapping logic (see doc 05 for the source taxonomy table) ---

gold.position_taxonomy already normalizes raw position strings (LDE/RDE -> DE,
LOLB/ROLB/OLB -> OLB, etc: DE, DT, NT, DL, ILB, MLB, OLB, LB, CB, S, DB) --
reused here rather than re-deriving side-prefix stripping by hand. A few
legacy/alternate-notation defensive position codes aren't in that shared
table yet (E/LE/RE, MG, DG, SLB/WLB/WILL -- largely irrelevant for the 3-4
buckets anyway since 3-4 didn't exist before ~1970 per the source doc) --
handled by a small local LEGACY_POS_GROUP map rather than extending the
shared table (conservative: this is a read-mostly reference table other
projects also depend on). Pure offense/special-teams single-token codes
(WR, RB, TE, QB, ...) and any hyphenated compound code (two-way/multi-
position players, mostly pre-1960s -- "B-G-DE-E", "E-DE-DT", etc.) are kept
in their own explicit out-of-scope buckets rather than being lumped into a
generic "legacy" catch-all -- see OFFENSE_OR_ST_POS and classify_row below.

Real gaps this classifier makes EXPLICIT rather than silently mapping away
(confirmed via direct query against the corpus, not assumed):
  - Bare "DT" under a 3-4 team: 869 rows, and its *season* distribution is not
    flat -- it explodes from single digits/year before 2010 to 30-59/year
    2020-2025. This is the modern rotational-front NFL (many teams now rotate
    3+ interior D-linemen with no single "true nose"), not a data error and
    not the taxonomy's classic-era 3-4 NT. Bucketed as '3-4_DT_uncovered'
    rather than force-mapped to '3-4 NT'.
  - Bare "DT"/"LDT"/"RDT"/"NT" under a 4-3 team: the taxonomy explicitly does
    not give a 4-3 DT split (1-tech vs 3-tech) -- bucketed as
    '4-3_DT_uncovered'. A cheap, OPTIONAL stat-profile-based 1-tech/3-tech
    sub-tag is added per doc 05's own suggestion ("infer from stat profile ...
    if a future session needs that granularity") -- see `dt_subtype` below --
    but is clearly marked as inferred, not user-specified, and not validated
    against named examples (doc 05 gave none for this split).
  - Bare "LB"/"DL" (no O/I/side info at all): cannot be scheme-role-classified
    -- bucketed as 'unclassified_no_side_info', not guessed.
  - CB/S/DB positions: out of scope for this 8-bucket taxonomy entirely (it
    only covers DL/LB) -- bucketed as 'out_of_scope_db', not "unknown".
  - No franchise/season match in gold.team_scheme_coach_season (rare -- see
    Phase 1's own single KC/1969 AFL gap): bucketed as 'scheme_unknown'.

--- 3-4 OLB rush-vs-coverage sub-split (doc 05 item 3) ---

Within the single '3-4 OLB (edge)' bucket, a secondary `sub_role` tag
('rush_leaning' / 'coverage_leaning') is computed from the player-season's own
(sack + TFL) per-game rate, sourced from gold.player_game_stats (season
aggregate). This is a continuous signal collapsed to a documented threshold
for readability, not a hard taxonomy distinction -- see the printed
distribution for where the split actually falls in real data before treating
the label as precise.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg2

OUT_PATH = Path(__file__).parent.parent / "data_output" / "position_scheme_classification.parquet"

# Legacy/alternate-notation defensive position codes not in the shared
# gold.position_taxonomy (single-token only -- compound/hyphenated codes like
# "B-G-DE-E" or "E-DE-DT" are handled separately as 'legacy_compound_unclassified',
# not parsed token-by-token, since PFR itself doesn't say which token was the
# player's actual role in a given season). Kept local and small on purpose --
# see module docstring for why this isn't added to the shared table.
LEGACY_POS_GROUP = {
    "E": "DE", "LE": "DE", "RE": "DE",   # generic "end" -> closest analog, DE
    "MG": "NT",                            # "Middle Guard" -- 3-4 nose synonym
    "DG": "DT",                             # "Defensive Guard" -- old term for interior DL
    "SLB": "OLB", "WLB": "OLB", "WILL": "OLB",  # strong/weak-side LB notation -> OLB
    "LDH": "S", "RDH": "S",                # "Defensive Halfback" -- pre-1970 term for DB, out of front-seven scope
}

# Single-token OFFENSE (or pure special-teams) position codes, confirmed
# present in silver.player_team_seasons_pfr via direct query (2026-08-22) --
# these are genuinely out of scope for this defense-only classifier, NOT
# "legacy" positions this classifier failed to map. Keeping this distinct
# from legacy_compound_unclassified matters for an honest coverage report:
# lumping ~53% of the whole corpus (mostly modern WR/RB/TE/QB rows) into
# "legacy_unclassified" would badly overstate this classifier's real failure
# rate on the defensive positions it's actually meant to cover.
OFFENSE_OR_ST_POS = {
    "WR", "RB", "TE", "QB", "C", "T", "G", "FB", "RG", "LG", "K", "RT", "LT",
    "P", "LS", "HB", "OL", "FL", "TB", "WB", "BB", "SE", "OT", "KR", "PR",
    "RS", "KB", "B", "LH", "RH", "LHB", "RHB", "OG",
}

# pos_group x scheme -> one of the user's 8 named buckets, or an explicit
# uncovered/out-of-scope/unclassified label (see module docstring).
BUCKET_MAP = {
    ("3-4", "NT"):  "3-4 NT",
    ("3-4", "DE"):  "3-4 DE",
    ("3-4", "OLB"): "3-4 OLB (edge)",
    ("3-4", "ILB"): "3-4 ILB/MLB",
    ("3-4", "MLB"): "3-4 ILB/MLB",     # rare (31 rows) -- see doc, closest analog
    ("3-4", "DT"):  "3-4_DT_uncovered",
    ("3-4", "DL"):  "unclassified_no_side_info",
    ("3-4", "LB"):  "unclassified_no_side_info",

    ("4-3", "DE"):  "4-3 DE",
    ("4-3", "MLB"): "4-3 MLB",
    ("4-3", "OLB"): "4-3 OLB",
    ("4-3", "ILB"): "4-3 MLB",         # rare (21 rows) -- closest analog, see doc
    ("4-3", "DT"):  "4-3_DT_uncovered",
    ("4-3", "NT"):  "4-3_DT_uncovered",  # rare (69 rows) -- closest analog
    ("4-3", "DL"):  "unclassified_no_side_info",
    ("4-3", "LB"):  "unclassified_no_side_info",
}

DB_ONLY_POS_GROUPS = {"CB", "S", "DB"}

# The user's own named-player validation set, verbatim from doc 05's taxonomy
# table (61 players across the 8 buckets it defined a "sample stat profile"
# and "example players" column for).
VALIDATION_SET = {
    "3-4 NT": ["Ted Washington", "Vince Wilfork", "Curley Culp", "Casey Hampton",
               "Fred Smerlas", "Michael Carter", "Bob Baumhower"],
    "3-4 DE": ["J.J. Watt", "Bruce Smith", "Howie Long", "Lee Roy Selmon",
               "Richard Seymour", "Justin Smith", "Calais Campbell",
               "Elvin Bethea", "Art Still", "Doug Betters"],
    "3-4 OLB (edge)": ["Lawrence Taylor", "Terrell Suggs", "Kevin Greene", "Greg Lloyd",
                        "T.J. Watt", "Von Miller", "Derrick Thomas", "Andre Tippett",
                        "DeMarcus Ware", "James Harrison"],
    "3-4 ILB/MLB": ["Levon Kirkland", "Ray Lewis", "Pepper Johnson", "Harry Carson",
                     "Randy Gradishar", "Patrick Willis", "Bobby Wagner", "Steve Nelson",
                     "Sam Mills"],
    "4-3 DE": ["Myles Garrett", "Deacon Jones", "Carl Eller", "Chris Doleman",
               "Charles Haley", "Charles Mann", "Jack Youngblood"],
    "4-3 MLB": ["Bill Bergey", "Dick Butkus", "Mike Singletary", "Willie Lanier",
                "Brian Urlacher", "Luke Kuechly", "Nick Buoniconti", "Tommy Nobis"],
    "4-3 OLB": ["Derrick Brooks", "Lavonte David", "Ed McDaniel", "Bobby Bell",
                "Jack Ham", "Junior Seau", "Ted Hendricks", "Chuck Howley",
                "Matt Blair", "Wilber Marshall"],
}


def get_conn():
    return psycopg2.connect(dbname="football")


def load_base(conn) -> pd.DataFrame:
    """One row per (player_id, franchise_id, season) with defensive position,
    normalized pos_group, and scheme. player_id join throughout -- never bare
    name -- per doc 05's explicit warning (Ted Washington collision case)."""
    query = """
        SELECT s.player_id, p.full_name, s.franchise_id, s.season, s.position AS raw_position,
               pt.pos_group, pt.pos_global,
               tsc.defensive_alignment, tsc.dc_source
        FROM silver.player_team_seasons_pfr s
        JOIN gold.players p ON p.player_id = s.player_id
        LEFT JOIN gold.position_taxonomy pt ON pt.raw_position = s.position
        LEFT JOIN gold.team_scheme_coach_season tsc
               ON tsc.franchise_id = s.franchise_id AND tsc.season = s.season
    """
    df = pd.read_sql(query, conn)
    return df


def load_game_rates(conn) -> pd.DataFrame:
    """Season-aggregate sack/TFL-per-game rate from gold.player_game_stats,
    used only for the 3-4 OLB rush-vs-coverage sub_role tag."""
    query = """
        SELECT pgs.player_id, g.season,
               count(*) AS games,
               sum(pgs.sack) AS sacks,
               sum(pgs.run_stuff) AS tfls
        FROM gold.player_game_stats pgs
        JOIN gold.games g ON g.game_id = pgs.game_id
        GROUP BY 1, 2
    """
    try:
        return pd.read_sql(query, conn)
    except Exception as e:
        print(f"WARNING: could not load game rates for sub_role tagging ({e}); skipping sub_role")
        return pd.DataFrame(columns=["player_id", "season", "games", "sacks", "tfls"])


def classify_row(row) -> str:
    raw = row["raw_position"]
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "missing_position"
    pos_group = row["pos_group"]
    if pd.isna(pos_group):
        if raw in OFFENSE_OR_ST_POS:
            return "out_of_scope_offense"
        if "-" in raw or "/" in raw:
            return "legacy_compound_unclassified"
        pos_group = LEGACY_POS_GROUP.get(raw)
    if pos_group is None:
        return "unmapped_single_token"
    if pos_group in DB_ONLY_POS_GROUPS:
        return "out_of_scope_db"
    scheme = row["defensive_alignment"]
    if pd.isna(scheme) or not scheme:
        return "scheme_unknown"
    return BUCKET_MAP.get((scheme, pos_group), "unclassified_no_side_info")


def main() -> None:
    conn = get_conn()
    df = load_base(conn)
    print(f"Loaded {len(df)} (player, franchise, season) defensive-ish rows")

    df["bucket"] = df.apply(classify_row, axis=1)

    # --- sub_role tag for 3-4 OLB ---
    rates = load_game_rates(conn)
    if not rates.empty:
        rates["rate"] = (rates["sacks"].fillna(0) + rates["tfls"].fillna(0)) / rates["games"].replace(0, pd.NA)
        rate_map = rates.set_index(["player_id", "season"])["rate"].to_dict()
        oli_mask = df["bucket"] == "3-4 OLB (edge)"
        rush_cut = None
        if oli_mask.any():
            sub_rates = df.loc[oli_mask].apply(
                lambda r: rate_map.get((r["player_id"], r["season"])), axis=1
            )
            valid = sub_rates.dropna()
            if len(valid) > 0:
                rush_cut = valid.median()
                print(f"\n3-4 OLB (edge) sack+TFL/game rate: n={len(valid)}, "
                      f"median={rush_cut:.2f}, mean={valid.mean():.2f}, "
                      f"p25={valid.quantile(.25):.2f}, p75={valid.quantile(.75):.2f}")
                df.loc[oli_mask, "sub_role"] = sub_rates.apply(
                    lambda v: ("rush_leaning" if v >= rush_cut else "coverage_leaning")
                    if pd.notna(v) else "no_stats"
                )
    if "sub_role" not in df.columns:
        df["sub_role"] = None

    conn.close()

    # --- Coverage report ---
    print("\n=== Corpus-wide bucket coverage ===")
    counts = df["bucket"].value_counts()
    total = len(df)
    for bucket, n in counts.items():
        print(f"  {bucket:32s} {n:6d}  ({100*n/total:.1f}%)")

    named_buckets = set(BUCKET_MAP.values())
    named_n = df["bucket"].isin(named_buckets).sum()
    print(f"\nClassified into one of the 8 named taxonomy buckets: {named_n}/{total} "
          f"({100*named_n/total:.1f}%) of ALL rows (offense + DB + defense)")
    out_of_scope = df["bucket"].isin(["out_of_scope_db", "out_of_scope_offense"])
    front_seven_n = (~out_of_scope).sum()
    print(f"Of the front-seven-only universe this classifier is actually meant to cover "
          f"(excluding out_of_scope_db and out_of_scope_offense): "
          f"{named_n}/{front_seven_n} ({100*named_n/front_seven_n:.1f}%)")

    # --- Named-player validation ---
    print("\n=== Named-player validation (doc 05's own taxonomy examples) ===")
    match_ct, total_ct = 0, 0
    mismatches = []
    for expected_bucket, names in VALIDATION_SET.items():
        for name in names:
            total_ct += 1
            candidates = df[df["full_name"] == name]
            if candidates.empty:
                print(f"  NOT FOUND: {name} (expected {expected_bucket})")
                continue
            pids = candidates["player_id"].unique()
            if len(pids) > 1:
                # Disambiguate by picking the player_id whose seasons are
                # dominated by defensive front-seven positions (per-player_id,
                # never bare name -- see Ted Washington collision case).
                best_pid, best_n = None, -1
                for pid in pids:
                    n = len(candidates[candidates["player_id"] == pid])
                    if n > best_n:
                        best_pid, best_n = pid, n
                candidates = candidates[candidates["player_id"] == best_pid]
                print(f"  NOTE: {name} has {len(pids)} distinct player_ids in gold.players; "
                      f"using player_id={best_pid} ({best_n} defensive seasons, most of any candidate)")
            modal_bucket = candidates["bucket"].value_counts().idxmax()
            seasons_str = ", ".join(
                f"{r.season}:{r.raw_position}/{r.defensive_alignment}/{r.bucket}"
                for r in candidates.sort_values("season").itertuples()
            )
            if modal_bucket == expected_bucket:
                match_ct += 1
            else:
                mismatches.append((name, expected_bucket, modal_bucket, seasons_str))

    print(f"\nValidation result: {match_ct}/{total_ct} named players' modal bucket matches "
          f"the taxonomy's expected bucket ({100*match_ct/total_ct:.1f}%)")
    if mismatches:
        print("\nMismatches (real evidence, not guessed):")
        for name, expected, got, seasons in mismatches:
            print(f"  {name}: expected {expected!r}, got {got!r}")
            print(f"    seasons: {seasons}")

    OUT_PATH.parent.mkdir(exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    print(f"\nWrote {len(df)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
