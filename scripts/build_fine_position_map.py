#!/usr/bin/env python3
"""
Builds a per (pfr_player_id, franchise team-code, season) fine-position
resolution table for the new position-weighted TCS mechanism
(scripts/build_game_defense.py's team_credit_share computation).

For each row, resolves:
  scheme          -- '3-4' / '4-3' / None  (gold.team_scheme_coach_season)
  run_pos_label   -- the label used to key into the RUN weight table
                      (NT/MLB/DE/OLB/SS/FS+CB for 3-4;
                       DT/MLB/LDE/LOLB/RDE/ROLB/SS/FS+CB for 4-3)
  pass_pos_label  -- the label used to key into the PASS weight table
                      (OLB/DB/DE/MLB for 3-4; DE/DT/CB/FS/SS/MLB/OLB for 4-3)

Sources (join order, see module for detail):
  - gold.team_scheme_coach_season   -- scheme per (franchise_id, season)
  - data_output/position_scheme_classification.parquet
      -- front-seven (DL/LB) bucket + raw_position, per (player_id,
         franchise_id, season) -- built by build_position_scheme_classifier.py
  - silver.player_team_seasons_pfr  -- raw position string for players NOT
      covered by the classifier parquet (secondary DBs: CB/S/SS/FS, which
      the classifier explicitly puts out of scope) and as a fallback for
      any player-season missing from the classifier output.
  - internal.player_xref (source_system='pfr') -- pfr_player_id <-> player_id

DE/OLB side (L/R) for the 4-3 RUN table's split weights (LDE 0.160 vs
RDE 0.104, LOLB 0.104 vs ROLB 0.068) comes directly from the raw position
string (LDE/RDE/LOLB/ROLB). When a player's raw string is bare "DE"/"OLB"
under a 4-3 team (no side given), side is UNKNOWN -- credited using the
AVERAGE of the two side weights rather than guessing a side (documented
judgment call; see docs/deferred/09_dl_technique_research_pilot_20260823.md
Sec. 3 for why a forced default isn't used when even the side isn't known).

Secondary positions (CB/S/SS/FS/DB): "S"/"DB" bare (no SS/FS distinction)
also can't be split -- credited using the average of the SS and FS+CB (run)
or SS/FS (4-3 pass) weights for that scheme, same reasoning.

Players with NO resolvable scheme+position at all (bucket in
{'scheme_unknown','unclassified_no_side_info','legacy_compound_unclassified',
'missing_position','unmapped_single_token'}, or no scheme row, or a raw
secondary position PFR doesn't even give a coarse S/CB/DB read on) are left
UNRESOLVED (all fields None) -- per the project's "leave unassigned rather
than guess" convention. Rate reported in the printed summary.

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    python3 scripts/build_fine_position_map.py

Writes: data_output/fine_position_map.parquet
    one row per (pfr_player_id, team, season): scheme, run_pos_label,
    pass_pos_label, source (which tier of the resolution logic fired).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg2

OUT_PATH = Path(__file__).parent.parent / "data_output" / "fine_position_map.parquet"
CLASSIFIER_PATH = Path(__file__).parent.parent / "data_output" / "position_scheme_classification.parquet"

# franchise_id -> lowercase PFR-style historic team code (copied from
# scripts/load_dpvs_g_to_db.py's TEAM_TO_FID, inverted -- kept as its own
# copy per this project's established convention, see that file's header).
FID_TO_TEAM: dict[int, str] = {
    16: "atl", 4: "buf", 2: "chi", 3: "cin", 6: "cle", 11: "clt", 8: "crd",
    13: "dal", 5: "den", 20: "det", 21: "gnb", 10: "kan", 14: "mia",
    32: "min", 27: "nor", 23: "nwe", 17: "nyg", 19: "nyj", 31: "oti",
    15: "phi", 29: "pit", 24: "rai", 25: "ram", 9: "sdg", 28: "sea",
    1: "sfo", 7: "tam", 12: "was", 18: "jax", 22: "car", 26: "rav", 30: "htx",
}

# Front-seven bucket -> (scheme, run_pos_base, pass_pos_label). run_pos_base
# is either a fixed label (no side split needed) or 'DE_SPLIT'/'OLB_SPLIT'
# sentinel meaning "look at raw_position for L/R".
BUCKET_TO_LABELS: dict[str, tuple[str, str, str]] = {
    "3-4 NT":         ("3-4", "NT", "DE"),      # NT has no dedicated 3-4 PASS row; closest analog is DE (interior lineman)
    "3-4 DE":         ("3-4", "DE", "DE"),
    "3-4 OLB (edge)": ("3-4", "OLB", "OLB"),
    "3-4 ILB/MLB":    ("3-4", "MLB", "MLB"),
    "3-4_DT_uncovered": ("3-4", "NT", "DE"),    # only interior label 3-4 RUN has is NT
    "4-3 DE":         ("4-3", "DE_SPLIT", "DE"),
    "4-3 MLB":        ("4-3", "MLB", "MLB"),
    "4-3 OLB":        ("4-3", "OLB_SPLIT", "OLB"),
    "4-3_DT_uncovered": ("4-3", "DT", "DT"),
}
# NOTE: 3-4 NT's pass-weight analog is a genuine judgment call -- the given
# 3-4 PASS table has no NT row at all (OLB/DB/DE/MLB only). NT is credited
# under the "DE" pass label as the closest interior-lineman analog. Flagged
# explicitly, not silently assumed.

SS_TOKENS = {"SS"}
FS_TOKENS = {"FS"}
CB_TOKENS = {"CB", "LCB", "RCB"}
S_BARE_TOKENS = {"S", "SAF"}
DB_BARE_TOKENS = {"DB"}


def get_conn():
    return psycopg2.connect(dbname="football")


def load_scheme(conn) -> dict[tuple[int, int], str]:
    cur = conn.cursor()
    cur.execute("SELECT franchise_id, season, defensive_alignment FROM gold.team_scheme_coach_season")
    return {(fid, season): scheme for fid, season, scheme in cur.fetchall() if scheme}


def load_pfr_xref(conn) -> dict[int, str]:
    """player_id -> pfr_player_id ('/players/X/XxxxYy00.htm' style)."""
    cur = conn.cursor()
    cur.execute("SELECT player_id, source_player_id FROM internal.player_xref WHERE source_system='pfr'")
    return dict(cur.fetchall())


def load_secondary_raw_positions(conn) -> pd.DataFrame:
    """player_id, franchise_id, season, raw_position for CB/S/SS/FS/DB rows
    (out of scope for the front-seven classifier parquet)."""
    query = """
        SELECT s.player_id, s.franchise_id, s.season, s.position AS raw_position
        FROM silver.player_team_seasons_pfr s
        WHERE s.position IN ('CB','LCB','RCB','S','SS','FS','DB','SAF')
    """
    return pd.read_sql(query, conn)


def resolve_run_pos(base: str, raw_position: str) -> str:
    if base == "DE_SPLIT":
        rp = (raw_position or "").upper()
        if rp == "LDE":
            return "LDE"
        if rp == "RDE":
            return "RDE"
        return "DE_AVG"  # side unknown -> average of LDE/RDE at credit time
    if base == "OLB_SPLIT":
        rp = (raw_position or "").upper()
        if rp == "LOLB":
            return "LOLB"
        if rp == "ROLB":
            return "ROLB"
        return "OLB_AVG"
    return base


def resolve_secondary(raw_position: str, scheme: str) -> tuple[str, str]:
    """Returns (run_pos_label, pass_pos_label) for a CB/S/SS/FS/DB player."""
    rp = (raw_position or "").upper()
    if rp in CB_TOKENS:
        run_label = "FS+CB"
        pass_label = "CB" if scheme == "4-3" else "DB"
        return run_label, pass_label
    if rp in FS_TOKENS:
        run_label = "FS+CB"
        pass_label = "FS" if scheme == "4-3" else "DB"
        return run_label, pass_label
    if rp in SS_TOKENS:
        return "SS", "SS" if scheme == "4-3" else "DB"
    if rp in S_BARE_TOKENS or rp in DB_BARE_TOKENS:
        # side/role unknown (SS vs FS/CB) -> average of the two run weights;
        # pass label: 3-4 has one combined 'DB' bucket anyway (no ambiguity);
        # 4-3 has to average SS vs FS(=CB) since we don't know which
        return "SS_FSCB_AVG", ("DB" if scheme == "3-4" else "SS_FS_AVG")
    return "", ""


def main() -> None:
    conn = get_conn()
    scheme_map = load_scheme(conn)
    pid_to_pfr = load_pfr_xref(conn)
    secondary_df = load_secondary_raw_positions(conn)
    conn.close()

    classifier_df = pd.read_parquet(CLASSIFIER_PATH)
    print(f"Loaded classifier: {len(classifier_df):,} rows; secondary raw positions: {len(secondary_df):,} rows")

    rows = []
    unresolved = 0
    n_total = 0

    # ── front-seven (classifier) rows ───────────────────────────────────────
    for r in classifier_df.itertuples(index=False):
        n_total += 1
        pid, fid, season, bucket, raw_pos = r.player_id, r.franchise_id, r.season, r.bucket, r.raw_position
        pfr_id = pid_to_pfr.get(pid)
        if pfr_id is None:
            unresolved += 1
            continue
        team = FID_TO_TEAM.get(fid)
        if team is None:
            unresolved += 1
            continue
        if bucket not in BUCKET_TO_LABELS:
            unresolved += 1
            continue
        scheme, run_base, pass_label = BUCKET_TO_LABELS[bucket]
        run_label = resolve_run_pos(run_base, raw_pos)
        rows.append({
            "pfr_player_id": pfr_id, "team": team, "season": season,
            "scheme": scheme, "run_pos_label": run_label, "pass_pos_label": pass_label,
            "source": "classifier_front7",
        })

    # ── secondary (DB) rows ─────────────────────────────────────────────────
    for r in secondary_df.itertuples(index=False):
        n_total += 1
        pid, fid, season, raw_pos = r.player_id, r.franchise_id, r.season, r.raw_position
        pfr_id = pid_to_pfr.get(pid)
        team = FID_TO_TEAM.get(fid)
        scheme = scheme_map.get((fid, season))
        if pfr_id is None or team is None or scheme is None:
            unresolved += 1
            continue
        run_label, pass_label = resolve_secondary(raw_pos, scheme)
        if not run_label:
            unresolved += 1
            continue
        rows.append({
            "pfr_player_id": pfr_id, "team": team, "season": season,
            "scheme": scheme, "run_pos_label": run_label, "pass_pos_label": pass_label,
            "source": "secondary_db",
        })

    out = pd.DataFrame(rows)
    # A player can have duplicate rows across franchise mid-season trades or
    # duplicate classifier entries -- keep first (classifier front7 rows are
    # loaded before secondary, and within each pass insertion order is the
    # source file's order; dedup on the natural key).
    before = len(out)
    out = out.drop_duplicates(subset=["pfr_player_id", "team", "season"], keep="first")
    print(f"Resolved rows: {len(out):,} (deduped from {before:,}); unresolved: {unresolved:,}/{n_total:,} "
          f"({100*unresolved/n_total:.1f}%)")

    OUT_PATH.parent.mkdir(exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}")
    print(out["run_pos_label"].value_counts())
    print(out["pass_pos_label"].value_counts())


if __name__ == "__main__":
    main()
