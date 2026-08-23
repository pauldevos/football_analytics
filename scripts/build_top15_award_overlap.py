#!/usr/bin/env python3
"""
Top-15-by-dpvs_g vs. real AP All-Pro / DPOY-voting-board overlap -- the
first-class validation check the user explicitly asked for (persisted
version of the ad hoc analysis that produced data_output/
top15_vs_award_overlap_20260823.csv in the §22 session; same method,
reusable for future rebuilds instead of redone inline each time).

For every season in range, takes the model's own top-15 dpvs_g finishers
(season_overall_rank <= 15) and checks:
  n_1st / n_2nd / n_either  -- how many were real AP 1st/2nd-Team All-Pro
                                (gold.player_awards, org='AP')
  n_board                   -- how many appeared on that season's real AP
                                DPOY voting board (~/data/pfref/
                                ap_dpoy_voting.csv)
  winner_in_top15/winner_name -- did the real DPOY winner land in the
                                model's own top-15 at all

Player-id resolution: parquet's pfr_player_id -> bare PFR id ->
internal.player_xref (source_system='pfr') -> gold.players.player_id
(matches §22.4's own resolution path).

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    PYTHONPATH=~/github/football/football_db/src python3 \
        scripts/build_top15_award_overlap.py [--seasons 1970-2024] [--out PATH]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
import psycopg2

SILVER_DIR = Path.home() / "data/silver"
DPOY_PATH = Path.home() / "data/pfref/ap_dpoy_voting.csv"
DATA_OUT = Path(__file__).parent.parent / "data_output"
PFR_ID_RE = re.compile(r"/([A-Za-z0-9.]+)\.htm")

DEF_POS = {
    "CB", "DB", "DE", "DL", "DT", "EDGE", "FS", "ILB", "LB", "LCB", "LDE",
    "LDE/RDT", "LDT", "LE", "LILB", "LLB", "LOLB", "MLB", "NT", "OLB",
    "RCB", "RCB/SS", "RDE", "RDT", "RDT/LDE", "RILB", "RLB", "RLB/MLB",
    "ROLB", "ROLB/RILB", "S", "SAF", "SS",
}


def _parse_seasons(s: str) -> list[int]:
    if "-" in s and not s.startswith("-"):
        lo, hi = s.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(s)]


def load_ap_all_pro(conn) -> pd.DataFrame:
    q = """
        SELECT pa.season, pa.designation, pa.position, x.source_player_id AS pfr_player_id
        FROM gold.player_awards pa
        JOIN internal.player_xref x ON x.player_id = pa.player_id AND x.source_system='pfr'
        WHERE pa.org = 'AP' AND pa.designation IN ('1st Tm', '2nd Tm')
    """
    df = pd.read_sql(q, conn)
    return df[df["position"].isin(DEF_POS)].copy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="1970-2024")
    ap.add_argument("--out", default=str(DATA_OUT / "top15_vs_award_overlap.csv"))
    args = ap.parse_args()
    seasons = set(_parse_seasons(args.seasons))

    df = pd.read_parquet(SILVER_DIR / "dpvs_g_player_season.parquet")
    df["_bare_pfr_id"] = df["pfr_player_id"].fillna("").str.extract(PFR_ID_RE.pattern)[0]
    df.loc[df["_bare_pfr_id"].isna() & df["pfr_player_id"].notna(), "_bare_pfr_id"] = df["pfr_player_id"]
    top15 = df[(df["season"].isin(seasons)) & (df["season_overall_rank"] <= 15)].copy()

    conn = psycopg2.connect(dbname="football")
    all_pro = load_ap_all_pro(conn)
    conn.close()

    dpoy = pd.read_csv(DPOY_PATH) if DPOY_PATH.exists() else pd.DataFrame(
        columns=["season", "dpoy_voting_rank", "player_id", "player_name"])

    rows = []
    for season in sorted(seasons):
        t15 = top15[top15["season"] == season]
        if t15.empty:
            continue
        ids = set(t15["_bare_pfr_id"].dropna())

        ap_s = all_pro[all_pro["season"] == season]
        first_ids = set(ap_s[ap_s["designation"] == "1st Tm"]["pfr_player_id"])
        second_ids = set(ap_s[ap_s["designation"] == "2nd Tm"]["pfr_player_id"])
        n_1st = len(ids & first_ids)
        n_2nd = len(ids & second_ids)
        n_either = len(ids & (first_ids | second_ids))

        board_s = dpoy[dpoy["season"] == season]
        board_ids = set(board_s["player_id"].dropna())
        n_board = len(ids & board_ids)

        winner_row = board_s[board_s["dpoy_voting_rank"] == 1]
        winner_in = False
        winner_name = None
        if not winner_row.empty:
            winner_id = winner_row.iloc[0]["player_id"]
            winner_name = winner_row.iloc[0]["player_name"]
            winner_in = winner_id in ids

        rows.append({
            "season": season, "n_1st": n_1st, "n_2nd": n_2nd, "n_either": n_either,
            "n_board": n_board, "winner_in_top15": winner_in, "winner_name": winner_name,
        })

    res = pd.DataFrame(rows)
    DATA_OUT.mkdir(exist_ok=True)
    res.to_csv(args.out, index=False)
    print(res.to_string(index=False))
    print(f"\nMean n_either/15: {res['n_either'].mean():.2f} ({100*res['n_either'].mean()/15:.1f}%)")
    print(f"Mean n_board/15: {res['n_board'].mean():.2f} ({100*res['n_board'].mean()/15:.1f}%)")
    print(f"Real DPOY winner in top-15: {res['winner_in_top15'].mean()*100:.1f}% "
          f"({res['winner_in_top15'].sum()}/{len(res)})")
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
