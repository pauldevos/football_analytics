#!/usr/bin/env python3
"""
Build defensive performance stats for career DCs (coordinators who never became HCs).

These coaches appear in team_schemes.csv by name but have no coach_id in our data
because PFR's HC-centric scrape didn't reach them.

Two-step approach:
  Step 1 — Run scrape_coordinator_index.py to get IDs for career DCs from
            /friv/coordinators.fcgi and add them to the manifest.
  Step 2 — Run scrape_coaches.py --pull to fetch their individual pages.
            Their team_ranks rows (coordinator_type='DC') will be appended
            to the consolidated team_ranks.csv automatically.

This script (Step 3) does the post-processing:
  - Joins the newly populated team_ranks DC rows with team_schemes
  - Computes career DC averages per coordinator
  - Updates coach_nodes.csv with the new DC stats

Run after steps 1 and 2 are complete.

Usage:
    .venv/bin/python scripts/scrape_career_dc_stats.py
"""

import pathlib
import sys

import pandas as pd

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

COACHES_DIR = pathlib.Path.home() / "data" / "pfref" / "raw" / "coaches"
SCHEMES_PATH = pathlib.Path.home() / "data" / "pfref" / "team_schemes.csv"
NODES_PATH = COACHES_DIR / "coach_nodes.csv"
COORD_INDEX_PATH = COACHES_DIR / "coordinator_index.csv"


def main():
    team_ranks = pd.read_csv(COACHES_DIR / "team_ranks.csv")
    schemes = pd.read_csv(SCHEMES_PATH)
    nodes = pd.read_csv(NODES_PATH)

    print(f"team_ranks rows: {len(team_ranks)}")
    print(f"DC rows in team_ranks: {(team_ranks['coordinator_type']=='DC').sum()}")

    # Summarize DC performance per coach_id
    dc_rows = team_ranks[team_ranks["coordinator_type"] == "DC"].copy()
    dc_summary = dc_rows.groupby("coach_id").agg(
        dc_seasons=("year_id", "count"),
        dc_rank_def_pts_avg=("rank_def_pts", "mean"),
        dc_rank_def_yds_avg=("rank_def_yds", "mean"),
        dc_rank_def_turnovers_avg=("rank_def_turnovers", "mean"),
        dc_rank_def_pass_yds_avg=("rank_def_pass_yds", "mean"),
        dc_rank_def_rush_yds_avg=("rank_def_rush_yds", "mean"),
        dc_rank_def_pass_int_avg=("rank_def_pass_int", "mean"),
        dc_best_pts_rank=("rank_def_pts", "min"),
    ).reset_index()

    # Merge into nodes (update existing DC columns, add new rows if needed)
    dc_cols = list(dc_summary.columns)
    nodes_no_dc = nodes.drop(columns=[c for c in dc_cols if c in nodes.columns and c != "coach_id"])
    nodes_updated = nodes_no_dc.merge(dc_summary, on="coach_id", how="left")

    nodes_updated.to_csv(NODES_PATH, index=False)
    coaches_with_dc = dc_summary["coach_id"].nunique()
    print(f"Updated coach_nodes.csv. DC data for {coaches_with_dc} coaches.")

    # Report: which career DCs from team_schemes now have IDs?
    if COORD_INDEX_PATH.exists():
        coord_index = pd.read_csv(COORD_INDEX_PATH)
        scheme_dcs = set(schemes["defensive_coordinator"].dropna().str.strip().unique())
        coord_dcs = set(coord_index["dc_name"].dropna().str.strip().unique())
        dc_ids = dict(zip(coord_index["dc_name"].str.strip(), coord_index["dc_id"]))

        matched = {name: dc_ids[name] for name in scheme_dcs if name in dc_ids and dc_ids[name]}
        print(f"\nDCs in team_schemes now matched via coordinator index: {len(matched)}")
        still_missing = scheme_dcs - set(matched.keys()) - {None, ""}
        print(f"Still unmatched: {len(still_missing)}")
        if still_missing:
            print("Sample still unmatched:", sorted(still_missing)[:10])


if __name__ == "__main__":
    main()
