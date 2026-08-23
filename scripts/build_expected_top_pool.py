#!/usr/bin/env python3
"""
Part 2 validation proxy: per-season "expected top" pool =
  AP 1st/2nd-team All-Pro DEFENSIVE selections (gold.player_awards)
  UNION
  starters from that season's top-10 defenses (by points-allowed rank,
  reusing gamebooks_boxscores/outputs/pass_rush_srs_1967_2025.csv's
  ppg_allowed_rank -- already-built team-rank infra, per the task's own
  instruction to check for reusable ranking work before rebuilding it;
  "starter" = is_starter=True in player_game_defense.parquet, i.e. named on
  starters.csv at least once that season -- the same participation signal
  build_game_defense.py already uses).

This is a SOFT validation target (see docs/deferred/04_award_recognition_
vs_int_value_20260822.md and the Joe Greene vs Jack Lambert 1974 case) --
used only to compute "what fraction of the grid's actual top-15 falls in
this pool," never as a thing to optimize against directly.

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    python3 scripts/build_expected_top_pool.py

Writes: data_output/expected_top_pool.parquet
    columns: season, pfr_player_id, source ('ap_all_pro' / 'top10_def_starter')
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg2

OUT_PATH = Path(__file__).parent.parent / "data_output" / "expected_top_pool.parquet"
SRS_PATH = Path.home() / "github/football/gamebooks_boxscores/outputs/pass_rush_srs_1967_2025.csv"
SILVER_DIR = Path.home() / "data/silver"

DEF_POS = {
    "CB", "DB", "DE", "DL", "DT", "EDGE", "FS", "ILB", "LB", "LCB", "LDE",
    "LDE/RDT", "LDT", "LE", "LILB", "LLB", "LOLB", "MLB", "NT", "OLB",
    "RCB", "RCB/SS", "RDE", "RDT", "RDT/LDE", "RILB", "RLB", "RLB/MLB",
    "ROLB", "ROLB/RILB", "S", "SAF", "SS",
}

TEAM_TO_FID: dict[str, int] = {
    "atl": 16, "buf": 4, "chi": 2, "cin": 3, "cle": 6, "clt": 11, "crd": 8,
    "dal": 13, "den": 5, "det": 20, "gnb": 21, "kan": 10, "mia": 14,
    "min": 32, "nor": 27, "nwe": 23, "nyg": 17, "nyj": 19, "oti": 31,
    "phi": 15, "pit": 29, "rai": 24, "ram": 25, "sdg": 9, "sea": 28,
    "sfo": 1, "tam": 7, "was": 12, "jax": 18, "car": 22, "rav": 26, "htx": 30,
}


def load_ap_all_pro(conn) -> pd.DataFrame:
    query = """
        SELECT pa.player_id, pa.season, x.source_player_id AS pfr_player_id
        FROM gold.player_awards pa
        JOIN internal.player_xref x ON x.player_id = pa.player_id AND x.source_system='pfr'
        WHERE pa.org = 'AP' AND pa.designation IN ('1st Tm', '2nd Tm')
    """
    df = pd.read_sql(query, conn)
    df = df.drop(columns=["player_id"])
    df["source"] = "ap_all_pro"
    return df


def main():
    conn = psycopg2.connect(dbname="football")
    full = pd.read_sql("""
        SELECT pa.season, pa.position, x.source_player_id AS pfr_player_id
        FROM gold.player_awards pa
        JOIN internal.player_xref x ON x.player_id = pa.player_id AND x.source_system='pfr'
        WHERE pa.org = 'AP' AND pa.designation IN ('1st Tm', '2nd Tm')
    """, conn)
    conn.close()
    full = full[full["position"].isin(DEF_POS)].copy()
    full["source"] = "ap_all_pro"
    full = full[["season", "pfr_player_id", "source"]]
    print(f"AP All-Pro defensive selections resolved to pfr_player_id: {len(full):,}")

    # top-10 defenses' starters
    srs = pd.read_csv(SRS_PATH)
    top10 = srs[srs["ppg_allowed_rank"] <= 10][["season", "team"]].copy()
    print(f"Top-10-defense team-seasons: {len(top10):,}")

    pgd = pd.read_parquet(SILVER_DIR / "player_game_defense.parquet")
    pgd = pgd[pgd["is_starter"] == True][["season", "team", "pfr_player_id"]].drop_duplicates()
    starters = pgd.merge(top10, on=["season", "team"], how="inner")
    starters = starters[["season", "pfr_player_id"]].drop_duplicates()
    starters["source"] = "top10_def_starter"
    print(f"Top-10-defense starters: {len(starters):,}")

    out = pd.concat([full, starters], ignore_index=True)
    out = out.drop_duplicates(subset=["season", "pfr_player_id"], keep="first")
    print(f"Combined pool: {len(out):,} (season, pfr_player_id) rows, "
          f"seasons {out['season'].min()}-{out['season'].max()}")

    OUT_PATH.parent.mkdir(exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
