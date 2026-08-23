#!/usr/bin/env python3
"""
Applies dpvs.position_credit.compute_credit() to data_output/
tcs_ingredients.parquet and writes the resulting `team_credit_share` /
`credit_method` back into ~/data/silver/player_game_defense.parquet --
overwriting the `team_credit_share` column used downstream by
dpvs/tcs.py's aggregate_tcs() (and therefore build_dpvs_g.py).

This is the persisted version of the "apply" step the original 2026-08-23
§21 TCS rebuild did inline (never saved to a script). Re-run this any time
tcs_ingredients.parquet or the credit-computation logic
(dpvs/position_credit.py, dpvs/position_weights.py) changes.

The original flat (tdgs/n_participants) value is preserved forever in
`team_credit_share_flat` (only set once, on first run -- never overwritten
by later reruns of this script, so it stays a stable historical reference
regardless of how many times the weighted mechanism itself changes).
`~/data/silver/player_game_defense_flat_backup.parquet` is the one-time,
full pre-any-rebuild snapshot from the original §21 session -- also never
touched here.

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    python3 scripts/apply_tcs_position_credit.py [--decay 0.65]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from dpvs.position_credit import compute_credit

SILVER_DIR = Path.home() / "data/silver"
PLAYER_GAME_DEF = SILVER_DIR / "player_game_defense.parquet"
INGREDIENTS_PATH = Path(__file__).parent.parent / "data_output" / "tcs_ingredients.parquet"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decay", type=float, default=0.65)
    args = ap.parse_args()

    print(f"Loading ingredients: {INGREDIENTS_PATH}")
    ing = pd.read_parquet(INGREDIENTS_PATH)
    print(f"  {len(ing):,} rows, seasons {ing['season'].min()}-{ing['season'].max()}")

    credited = compute_credit(ing, decay=args.decay)
    print("credit_method breakdown:")
    print(credited["credit_method"].value_counts().to_string())

    pgd = pd.read_parquet(PLAYER_GAME_DEF)
    if "team_credit_share_flat" not in pgd.columns:
        pgd["team_credit_share_flat"] = pgd["team_credit_share"]
        print("  Seeded team_credit_share_flat from the pre-existing (original flat) team_credit_share.")

    key = ["game_id", "team", "pfr_player_id"]
    new_vals = credited.set_index(key)[["team_credit_share", "credit_method"]]

    pgd = pgd.set_index(key)
    update_idx = pgd.index.intersection(new_vals.index)
    print(f"  Updating {len(update_idx):,}/{len(pgd):,} player_game_defense rows "
          f"({len(pgd) - len(update_idx):,} rows outside the ingredients' season range left untouched)")
    pgd.loc[update_idx, "team_credit_share"] = new_vals.loc[update_idx, "team_credit_share"]
    pgd.loc[update_idx, "credit_method"] = new_vals.loc[update_idx, "credit_method"]
    pgd = pgd.reset_index()

    pgd.to_parquet(PLAYER_GAME_DEF, index=False)
    print(f"Wrote {PLAYER_GAME_DEF}  ({len(pgd):,} total rows)")
    print(f"  team_credit_share summary:\n{pgd['team_credit_share'].describe()}")


if __name__ == "__main__":
    main()
