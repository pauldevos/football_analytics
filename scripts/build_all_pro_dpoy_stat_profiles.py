#!/usr/bin/env python3
"""
Build a real, position-organized stat-profile reference dataset for every
1st-Team All-Pro defender and every DPOY-board/DPOY-winning defender, per
docs/deferred/04_award_recognition_vs_int_value_20260822.md's follow-on ask.

This is a VALIDATION/SANITY-CHECK dataset for DPVS-G weighting schemes, not
an optimization target -- see the companion doc
docs/deferred/04_all_pro_dpoy_stat_profiles_20260822.md for the full writeup
and the explicit "don't just reproduce DPOY winners" framing.

Population (union of four sources, all keyed to football_db's internal
integer player_id via internal.player_xref where the source uses a PFR
string id):
  1. AP 1st-Team All-Pro, defensive positions only (gold.player_awards,
     org='AP', designation='1st Tm') -- the primary All-Pro cohort per the
     task brief ("prioritize AP as primary").
  2. AP DPOY full voting board, 1971-2025 (~/data/pfref/ap_dpoy_voting.csv,
     413 rows, every player who got at least one vote, not just winners).
  3. NEA/PFWA/101 Awards DPOY winners (gold.player_awards, designation LIKE
     'DPOY%', org in ('NEA','PFWA','101AWARDS')).
  4. AP DPOY winners (gold.player_awards, org='AP', designation='DPOY') --
     included for cross-check completeness against (2)'s rank-1 rows.

AP 2nd-Team and other orgs' 1st-Team selections are NOT population-expanding
(pulling a full stat profile for every SN/UPI/FW/PFW 1st-team selection
across 1920-2025 would be a much larger and lower-value undertaking) but ARE
used to enrich rows already in the population: all_pro_tier reflects AP's
own 1st/2nd/none, and other_org_1st_tm records which other bodies also named
that player-season 1st-team, for the "note when orgs disagree" ask.

Stat source: gold.player_game_stats, aggregated to season. This table
already IS the "best available source per era" merge the task asked for --
built 2026-08-21/22 (see framework_decisions.md SS16-17) from
silver.player_game_stats_gamebook (1967-1977, gamebooks_boxscores'
corpus) for current_source='gamebook' and silver.player_game_stats_pfr
(1978-2025, PFR pbp.csv-derived) for current_source='pfr' -- no separate
1999+ vs 1978-1998 split needed, gold.player_game_stats already is that
split, done once, upstream. Seasons before 1967 are NOT covered by this
table (no Postgres per-game source exists that far back) -- any pre-1967
award-population row is reported as a stat-profile gap, not silently
dropped or backfilled from a different-shaped source.

PD (pass deflections): populated for BOTH sources (30,385/30,388 gamebook
rows, 422,823/422,823 pfr rows carry a non-null pd column) -- used directly,
no need to fabricate or leave blank for either era.

Position bucket: data_output/position_scheme_classification.parquet
(player_id, franchise_id, season) 8-bucket DL/LB scheme taxonomy, used
where it covers the player-season; falls back to dpvs/positions.py's
3-group taxonomy (pass_rusher/run_stopper/coverage) otherwise (mainly
DB/CB/S, which the scheme classifier explicitly scopes out as
'out_of_scope_db', and any season missing from the classifier's coverage
window). `position_source` column on the output records which taxonomy was
used per row, per the task's explicit ask.

Team defensive ranks: gamebooks_boxscores/outputs/pass_rush_srs_1967_2025.csv
(already-built Thread-1 output -- ppg_allowed_rank, ypg_allowed_rank,
any_a_z_avg_rank reused directly, not rebuilt) joined on (season,
franchise_id), PLUS three new columns computed here directly from
gold.team_game_stats (which that script already reads, extended for the
rush/pass yardage split it didn't need before): ypc_allowed_rank,
rush_yds_allowed_rank, pass_yds_allowed_rank.

Run via football_db's own .venv (needs psycopg2 + pandas):
    cd ~/github/football/football_db && source .venv/bin/activate
    cd ~/github/football/football_analytics
    PYTHONPATH=~/github/football/football_db/src python3 \
        scripts/build_all_pro_dpoy_stat_profiles.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.expanduser("~/github/football/football_db/src"))
from football_db.db import get_connection  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from dpvs.positions import map_position  # noqa: E402

REPO = Path(__file__).parent.parent
AP_DPOY_CSV = Path("~/data/pfref/ap_dpoy_voting.csv").expanduser()
SCHEME_PARQUET = REPO / "data_output" / "position_scheme_classification.parquet"
SRS_CSV = Path("~/github/football/gamebooks_boxscores/outputs/pass_rush_srs_1967_2025.csv").expanduser()
OUT_CSV = REPO / "data_output" / "all_pro_dpoy_stat_profiles.csv"

DEFENSIVE_POS = {
    "CB", "DB", "DE", "DL", "DT", "FS", "ILB", "LB", "LCB", "LDE", "LDT",
    "LE", "LILB", "LLB", "LOLB", "MLB", "NT", "OLB", "RCB", "RCB/SS",
    "RCB/WR", "RDE", "RDT", "RDT/LDE", "RILB", "RLB", "RLB/MLB", "ROLB",
    "ROLB/RILB", "S", "SS",
}


def load_ap_all_pro(conn) -> pd.DataFrame:
    df = pd.read_sql("""
        SELECT player_id, season, franchise_id, position, designation
        FROM gold.player_awards
        WHERE org = 'AP' AND designation IN ('1st Tm', '2nd Tm')
    """, conn)
    df = df[df["position"].isin(DEFENSIVE_POS)].copy()
    return df


def load_other_org_1st_tm(conn) -> pd.DataFrame:
    """All non-AP orgs' 1st-Team-style designations, defensive positions
    only -- enrichment only (agreement/disagreement flag), not
    population-expanding. Includes '1st Tm', '1st Tm All-Conf.',
    '1st Tm All-NFL/AFL' variants."""
    df = pd.read_sql("""
        SELECT player_id, season, org, designation, position
        FROM gold.player_awards
        WHERE org != 'AP' AND designation LIKE '1st Tm%'
    """, conn)
    df = df[df["position"].isin(DEFENSIVE_POS)].copy()
    return df


def load_dpoy_board(conn) -> pd.DataFrame:
    """AP DPOY full voting board (413 rows, 1971-2025), PFR string id
    resolved to football_db's internal player_id via internal.player_xref."""
    board = pd.read_csv(AP_DPOY_CSV)
    xref = pd.read_sql(
        "SELECT source_player_id, player_id FROM internal.player_xref WHERE source_system = 'pfr'",
        conn,
    )
    board = board.merge(xref, left_on="player_id", right_on="source_player_id", how="left",
                         suffixes=("_pfr", ""))
    unresolved = board[board["player_id"].isna()]
    if len(unresolved):
        print(f"  [dpoy_board] WARNING: {len(unresolved)}/{len(board)} rows unresolved to internal player_id: "
              f"{unresolved['player_name'].tolist()}")
    board = board.dropna(subset=["player_id"]).copy()
    board["player_id"] = board["player_id"].astype(int)
    return board[["player_id", "season", "dpoy_voting_rank", "votes", "share_pct"]]


def load_other_dpoy_winners(conn) -> pd.DataFrame:
    """NEA / PFWA / 101 Awards DPOY winners, plus AP DPOY winners (for
    cross-check against the voting-board rank-1 rows)."""
    df = pd.read_sql("""
        SELECT player_id, season, org, designation
        FROM gold.player_awards
        WHERE designation LIKE 'DPOY%'
    """, conn)
    return df


def load_season_stats(conn, player_ids: list[int]) -> pd.DataFrame:
    """Season-aggregate stat profile from gold.player_game_stats -- the
    already-built, era-spanning (1967-2025) merge of gamebook (1967-77) and
    pfr pbp.csv-derived (1978-2025) per-game data. franchise_id/position
    chosen as the modal value across that player-season's games (handles
    mid-season trades by picking the team they played the most games for --
    same convention idi.py's own loaders use)."""
    # pgs."position" is NULL for every row sourced from silver.player_game_stats_pfr
    # (422,823/422,823 rows -- pbp.csv, its stat source, carries no position field at
    # all; same finding dpvs/idi.py's load_gold_stats_from_db() already documents and
    # fixes, see docs/framework_decisions.md SS17). Backfilled here from
    # silver.player_team_seasons_pfr the same way, via coalesce -- without this, EVERY
    # 1978+ row would groupby-drop out of the modal-franchise/position pick below
    # (pandas groupby drops NaN keys by default), silently blanking both position AND
    # team_franchise_id (and therefore the team-defensive-rank join) for the entire
    # pfr era. Confirmed against a real run before this fix: J.J. Watt/Aaron Donald/
    # Reggie White/Lawrence Taylor/Micah Parsons all came back with position=NaN,
    # team_franchise_id=NaN, and every team-rank column empty.
    df = pd.read_sql("""
        SELECT pgs.player_id, g.season, pgs.franchise_id,
               coalesce(pgs.position, pts.position) AS position, pgs.current_source,
               pgs.solo_tackle, pgs.ast_tackle, pgs.comb_tackle, pgs.sack, pgs.run_stuff,
               pgs.fr, pgs.def_int, pgs.pd, pgs.ff
        FROM gold.player_game_stats pgs
        JOIN gold.games g ON g.game_id = pgs.game_id
        LEFT JOIN silver.player_team_seasons_pfr pts
               ON pts.player_id = pgs.player_id
              AND pts.franchise_id = pgs.franchise_id
              AND pts.season = g.season
        WHERE pgs.player_id = ANY(%(pids)s)
    """, conn, params={"pids": player_ids})
    if df.empty:
        return df
    # modal (player_id, season) -> franchise_id: pick the franchise with the most
    # games that season (handles mid-season trades). Position picked SEPARATELY
    # (not coupled to the franchise groupby) so a still-missing position (rare,
    # post-backfill) can't blank out an otherwise-resolvable franchise_id, or vice
    # versa -- these two groupbys were previously combined and that coupling was
    # exactly the bug the comment above describes.
    modal_fid = (
        df.groupby(["player_id", "season", "franchise_id"])
        .size().reset_index(name="g")
        .sort_values("g", ascending=False)
        .drop_duplicates(subset=["player_id", "season"], keep="first")
        [["player_id", "season", "franchise_id"]]
        .rename(columns={"franchise_id": "team_franchise_id"})
    )
    modal_pos = (
        df.dropna(subset=["position"])
        .groupby(["player_id", "season", "position"])
        .size().reset_index(name="g")
        .sort_values("g", ascending=False)
        .drop_duplicates(subset=["player_id", "season"], keep="first")
        [["player_id", "season", "position"]]
        .rename(columns={"position": "team_position"})
    )
    modal = modal_fid.merge(modal_pos, on=["player_id", "season"], how="left")
    agg = df.groupby(["player_id", "season"], as_index=False).agg(
        games=("comb_tackle", "size"),
        tackles_solo=("solo_tackle", "sum"),
        tackles_ast=("ast_tackle", "sum"),
        tackles_total=("comb_tackle", "sum"),
        sacks=("sack", "sum"),
        run_stuff=("run_stuff", "sum"),
        fr=("fr", "sum"),
        int_=("def_int", "sum"),
        pd_=("pd", "sum"),
        ff=("ff", "sum"),
        source=("current_source", lambda s: "/".join(sorted(set(s)))),
    )
    agg = agg.rename(columns={"int_": "int", "pd_": "pd"})
    agg = agg.merge(modal, on=["player_id", "season"], how="left")
    return agg


def build_team_rank_supplement(conn, start_year=1967, end_year=2025) -> pd.DataFrame:
    """ypc_allowed_rank, rush_yds_allowed_rank, pass_yds_allowed_rank --
    the three team-defense rank columns pass_rush_srs_1967_2025.csv doesn't
    already have. Computed directly from gold.team_game_stats, the same
    underlying source that script reads, following its own
    load_team_game_stats() pattern (opponent's offensive output = this
    team's defensive-allowed number)."""
    df = pd.read_sql("""
        SELECT g.game_id, g.season, g.game_type, g.home_franchise_id, g.away_franchise_id,
               th.rush_yards AS h_rush, ta.rush_yards AS a_rush,
               th.rush_attempts AS h_ratt, ta.rush_attempts AS a_ratt,
               th.pass_yards AS h_pass, ta.pass_yards AS a_pass
        FROM gold.games g
        JOIN gold.team_game_stats th ON th.game_id = g.game_id AND th.franchise_id = g.home_franchise_id
        JOIN gold.team_game_stats ta ON ta.game_id = g.game_id AND ta.franchise_id = g.away_franchise_id
        WHERE g.season BETWEEN %(sy)s AND %(ey)s AND g.game_type = 'regular'
    """, conn, params={"sy": start_year, "ey": end_year})
    from collections import defaultdict
    agg = defaultdict(lambda: {"rush_yds": 0.0, "rush_att": 0.0, "pass_yds": 0.0})
    for r in df.itertuples():
        h = agg[(r.season, r.home_franchise_id)]
        h["rush_yds"] += r.a_rush or 0
        h["rush_att"] += r.a_ratt or 0
        h["pass_yds"] += r.a_pass or 0
        a = agg[(r.season, r.away_franchise_id)]
        a["rush_yds"] += r.h_rush or 0
        a["rush_att"] += r.h_ratt or 0
        a["pass_yds"] += r.h_pass or 0
    rows = []
    for (season, fid), v in agg.items():
        ypc = v["rush_yds"] / v["rush_att"] if v["rush_att"] else None
        rows.append({"season": season, "franchise_id": fid,
                      "rush_yds_allowed": v["rush_yds"], "pass_yds_allowed": v["pass_yds"],
                      "ypc_allowed": ypc})
    out = pd.DataFrame(rows)
    for col, higher_is_better in [("rush_yds_allowed", False), ("pass_yds_allowed", False), ("ypc_allowed", False)]:
        out[f"{col}_rank"] = out.groupby("season")[col].rank(ascending=higher_is_better, method="min")
    return out


def resolve_position_bucket(row, scheme_df: pd.DataFrame) -> tuple[str, str]:
    """Returns (bucket, source) -- scheme classifier first, 3-group fallback second."""
    fid = row.get("team_franchise_id")
    season = row.get("season")
    pid = row.get("player_id")
    match = scheme_df[(scheme_df["player_id"] == pid) & (scheme_df["franchise_id"] == fid)
                       & (scheme_df["season"] == season)]
    if len(match) and match.iloc[0]["bucket"] not in (
        "out_of_scope_db", "out_of_scope_offense", "scheme_unknown",
        "unclassified_no_side_info", "missing_position", "legacy_compound_unclassified",
    ):
        return match.iloc[0]["bucket"], "position_scheme_classifier"
    pos3 = map_position(row.get("team_position"))
    return pos3, "positions_py_3group"


def main():
    conn = get_connection()

    print("Loading award population...")
    ap_awards = load_ap_all_pro(conn)
    other_1st = load_other_org_1st_tm(conn)
    dpoy_board = load_dpoy_board(conn)
    other_dpoy = load_other_dpoy_winners(conn)

    ap_1st = ap_awards[ap_awards["designation"] == "1st Tm"]
    print(f"  AP 1st-Team defensive player-seasons: {len(ap_1st)}")
    print(f"  AP DPOY voting-board rows resolved: {len(dpoy_board)}")
    print(f"  Other-org DPOY winner rows: {len(other_dpoy)}")

    population = pd.concat([
        ap_awards[["player_id", "season"]],
        dpoy_board[["player_id", "season"]],
        other_dpoy[["player_id", "season"]],
    ]).drop_duplicates()
    print(f"  Total unique (player_id, season) population: {len(population)}")

    print("Loading season stat profiles from gold.player_game_stats...")
    pids = population["player_id"].unique().tolist()
    stats = load_season_stats(conn, pids)
    print(f"  Stat rows returned: {len(stats)}")

    df = population.merge(stats, on=["player_id", "season"], how="left")
    have_stats = df["games"].notna().sum()
    print(f"  Population rows with a stat profile: {have_stats}/{len(df)} "
          f"({have_stats / len(df) * 100:.1f}%)")

    # player names
    names = pd.read_sql("SELECT player_id, full_name FROM gold.players", conn)
    df = df.merge(names, on="player_id", how="left")

    # all_pro_tier: AP 1st takes priority over AP 2nd
    ap_tier = (
        ap_awards.sort_values("designation")  # '1st Tm' < '2nd Tm' alphabetically -- 1st sorts first
        .drop_duplicates(subset=["player_id", "season"], keep="first")
        [["player_id", "season", "designation"]]
        .rename(columns={"designation": "all_pro_tier"})
    )
    ap_tier["all_pro_tier"] = ap_tier["all_pro_tier"].map({"1st Tm": "1st", "2nd Tm": "2nd"})
    df = df.merge(ap_tier, on=["player_id", "season"], how="left")
    df["all_pro_tier"] = df["all_pro_tier"].fillna("none")

    # other-org 1st-team agreement/disagreement
    other_1st_agg = (
        other_1st.groupby(["player_id", "season"])["org"]
        .apply(lambda s: ",".join(sorted(set(s))))
        .reset_index().rename(columns={"org": "other_org_1st_tm"})
    )
    df = df.merge(other_1st_agg, on=["player_id", "season"], how="left")
    df["other_org_1st_tm"] = df["other_org_1st_tm"].fillna("")

    # dpoy_rank_ap
    dpoy_rank = dpoy_board[["player_id", "season", "dpoy_voting_rank"]].rename(
        columns={"dpoy_voting_rank": "dpoy_rank_ap"})
    df = df.merge(dpoy_rank, on=["player_id", "season"], how="left")

    # dpoy_won_other_org
    other_dpoy_agg = (
        other_dpoy.groupby(["player_id", "season"])
        .apply(lambda g: ",".join(sorted(f"{o}:{d}" for o, d in zip(g["org"], g["designation"]))))
        .reset_index().rename(columns={0: "dpoy_won_other_org"})
    )
    df = df.merge(other_dpoy_agg, on=["player_id", "season"], how="left")
    df["dpoy_won_other_org"] = df["dpoy_won_other_org"].fillna("")

    # position bucket
    print("Loading position-scheme classification...")
    scheme_df = pd.read_parquet(SCHEME_PARQUET)
    buckets, sources = [], []
    for row in df.to_dict("records"):
        b, s = resolve_position_bucket(row, scheme_df)
        buckets.append(b)
        sources.append(s)
    df["position_group_or_bucket"] = buckets
    df["position_source"] = sources

    # team defensive ranks
    print("Loading team defensive ranks...")
    srs = pd.read_csv(SRS_CSV)
    srs_cols = srs[["season", "franchise_id", "ppg_allowed_rank", "ypg_allowed_rank", "any_a_z_avg_rank"]].rename(
        columns={"ppg_allowed_rank": "team_ppg_allowed_rank",
                 "ypg_allowed_rank": "team_yds_allowed_rank",
                 "any_a_z_avg_rank": "team_any_a_allowed_rank"})
    rank_supp = build_team_rank_supplement(conn)
    rank_supp_cols = rank_supp[["season", "franchise_id", "ypc_allowed_rank",
                                 "rush_yds_allowed_rank", "pass_yds_allowed_rank"]].rename(
        columns={"ypc_allowed_rank": "team_ypc_allowed_rank",
                 "rush_yds_allowed_rank": "team_rush_yds_allowed_rank",
                 "pass_yds_allowed_rank": "team_pass_yds_allowed_rank"})
    team_ranks = srs_cols.merge(rank_supp_cols, on=["season", "franchise_id"], how="outer")

    df = df.merge(team_ranks, left_on=["season", "team_franchise_id"], right_on=["season", "franchise_id"],
                   how="left", suffixes=("", "_ranksrc"))

    out_cols = [
        "player_id", "full_name", "season", "team_position", "position_group_or_bucket", "position_source",
        "team_franchise_id", "games", "sacks", "tackles_solo", "tackles_ast", "tackles_total",
        "ff", "fr", "int", "pd", "all_pro_tier", "other_org_1st_tm", "dpoy_rank_ap", "dpoy_won_other_org",
        "team_ppg_allowed_rank", "team_yds_allowed_rank", "team_ypc_allowed_rank",
        "team_any_a_allowed_rank", "team_rush_yds_allowed_rank", "team_pass_yds_allowed_rank",
        "source",
    ]
    df = df.rename(columns={"team_position": "position", "source": "stat_source"})
    out_cols = [c.replace("team_position", "position").replace("source", "stat_source") for c in out_cols]
    df = df[[c for c in out_cols if c in df.columns]].sort_values(["season", "player_id"])
    df.to_csv(OUT_CSV, index=False)
    print(f"Wrote {len(df)} rows to {OUT_CSV}")

    no_stats = df["games"].isna().sum()
    print(f"Rows with NO stat profile (pre-1967 or unresolved): {no_stats}")
    if no_stats:
        gap = df[df["games"].isna()]
        print(f"  Season range of gap rows: {gap['season'].min()}-{gap['season'].max()}")


if __name__ == "__main__":
    main()
