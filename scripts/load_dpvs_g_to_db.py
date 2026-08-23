#!/usr/bin/env python3
"""
Loads the validated ~/data/silver/dpvs_g_player_season.parquet (built by
scripts/build_dpvs_g.py) into football_db's gold.dpvs_g_player_season table
-- see football_db/schema/dpvs_g.sql for the table design rationale and
football_analytics/docs/framework_decisions.md §16 for the full migration
writeup this is part of.

player_id is resolved from the parquet's pfr_player_id (e.g.
'/players/B/BuffDo20.htm') via internal.player_xref -- the only place an
external source id belongs, per this project's standing schema convention
(see football_db/schema/players.sql's header comment). Rows whose
pfr_player_id doesn't cross-reference (no PFR id in the source parquet, or
no matching internal.player_xref row) still load, with player_id NULL --
player_name always carries through so those rows stay identifiable.

franchise_id is resolved from the parquet's `team` column (a constant
PFR-style historic code, e.g. 'sdg' for the Chargers regardless of season
-- see dpvs/idi.py's _FID_TO_TEAM) via a plain Python-side reverse of that
same dict, kept here as its own copy (not a cross-package import) exactly
like football_analytics/scripts/build_tackle_gated_corpus.py's own
FID_TO_TEAM copy already does, for the same reason stated there.

Full TRUNCATE + re-INSERT every run -- this table has no state of its own,
it's a straight load of whatever the parquet currently holds.

Usage (needs football_analytics' own .venv -- has pyarrow for the parquet
read -- AND football_db importable on PYTHONPATH for the DB connection):
    cd ~/github/football/football_analytics && source .venv/bin/activate
    PYTHONPATH=~/github/football/football_db/src python3 scripts/load_dpvs_g_to_db.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from football_db.db import get_connection

PARQUET_PATH = Path.home() / "data" / "silver" / "dpvs_g_player_season.parquet"
PFR_ID_RE = re.compile(r"/([A-Za-z0-9]+)\.htm")

# Team code -> franchise_id, inverse of dpvs/idi.py's _FID_TO_TEAM (32
# entries as of the 2026-08-21 rewiring -- see that file for how the four
# post-1977 additions were confirmed against gold.franchises).
TEAM_TO_FID: dict[str, int] = {
    "atl": 16, "buf": 4, "chi": 2, "cin": 3, "cle": 6, "clt": 11, "crd": 8,
    "dal": 13, "den": 5, "det": 20, "gnb": 21, "kan": 10, "mia": 14,
    "min": 32, "nor": 27, "nwe": 23, "nyg": 17, "nyj": 19, "oti": 31,
    "phi": 15, "pit": 29, "rai": 24, "ram": 25, "sdg": 9, "sea": 28,
    "sfo": 1, "tam": 7, "was": 12,
    "jax": 18, "car": 22, "rav": 26, "htx": 30,
}

INSERT_COLS = (
    "season", "team", "franchise_id", "player_id", "player_name", "pos", "position_group",
    "games_played", "tcs_z", "idi", "idi_z", "wowy_z", "dpvs_g", "dpvs_a", "dpvs_p",
    # sack_share_z -> sack_component_z, 2026-08-22: sack no longer has any
    # team-share treatment at all (see dpvs/idi.py module docstring) --
    # sack_share itself (the raw team-share number) is REMOVED from this
    # list too, not just renamed; there is no replacement raw column for it
    # (sack_component_z is a rate+shrinkage+volume composite, not a share).
    # fr_component_z ADDED 2026-08-22 (§20): FR reinstated as a sixth IDI
    # component (rate+shrinkage-treated, phi=1.08/k≈100 -- see
    # dpvs/idi.py's module docstring). fr_share (below) stays unused/NULL,
    # same reasoning as sack_share's removal -- no un-standardized raw
    # share exists for a rate+shrinkage+volume composite.
    "tackle_share_z", "tfl_component_z", "sack_component_z", "int_component_z", "ff_component_z",
    "fr_component_z",
    "tackle_share",
    # int_share/ff_share/fr_share REMOVED 2026-08-22: found, while wiring up
    # this session's sack/tackle changes, that no code path in dpvs/idi.py
    # has computed these three in a long time (pre-dating this session) --
    # they only survived this far because a season-scoped incremental
    # rebuild concatenates onto the OLD parquet, which still carried these
    # columns (100% NaN) from whatever much earlier version last populated
    # them; a from-scratch full rebuild (this session's --seasons 1967-2024,
    # run after deleting the old parquet) exposed the gap immediately as a
    # hard "parquet is missing expected column" failure. Dropped from this
    # list rather than re-implemented -- nothing in this project currently
    # reads them from gold.dpvs_g_player_season, and the schema columns stay
    # in place (unused, always NULL going forward) rather than requiring a
    # DB migration for an unrelated pre-existing gap.
    "idi_tackle_source", "idi_tfl_source", "tackle_source", "data_confidence",
    "season_pos_rank", "season_overall_rank",
)

PARQUET_COL_MAP = {c: c for c in INSERT_COLS}  # 1:1 except franchise_id/player_id, resolved below


def load_pfr_id_cache(conn) -> dict[str, int]:
    cur = conn.cursor()
    cur.execute("SELECT source_player_id, player_id FROM internal.player_xref WHERE source_system='pfr'")
    return dict(cur.fetchall())


def main() -> None:
    df = pd.read_parquet(PARQUET_PATH)
    print(f"Loaded {len(df)} rows from {PARQUET_PATH}")

    conn = get_connection()
    id_cache = load_pfr_id_cache(conn)

    df["_pfr_id"] = df["pfr_player_id"].fillna("").str.extract(PFR_ID_RE.pattern)[0]
    df["player_id"] = df["_pfr_id"].map(id_cache)
    unresolved = df["player_id"].isna().sum()
    print(f"player_id resolved for {len(df) - unresolved}/{len(df)} rows "
          f"({unresolved} stay NULL -- no pfr_player_id or no player_xref match)")

    df["franchise_id"] = df["team"].map(TEAM_TO_FID)
    no_fid = df["franchise_id"].isna().sum()
    if no_fid:
        missing_teams = sorted(df.loc[df["franchise_id"].isna(), "team"].unique())
        print(f"WARNING: {no_fid} rows have a team code with no franchise_id mapping: {missing_teams}")

    for col in INSERT_COLS:
        if col not in df.columns and col not in ("franchise_id", "player_id"):
            raise SystemExit(f"parquet is missing expected column: {col}")

    # NaN -> None for psycopg2; numpy/pandas NA types don't adapt cleanly.
    records = df[list(INSERT_COLS)].astype(object).where(pd.notnull(df[list(INSERT_COLS)]), None)

    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE gold.dpvs_g_player_season")

    placeholders = ", ".join(["%s"] * len(INSERT_COLS))
    col_list = ", ".join(INSERT_COLS)
    sql = f"INSERT INTO gold.dpvs_g_player_season ({col_list}) VALUES ({placeholders})"

    rows = [tuple(r) for r in records.itertuples(index=False, name=None)]
    cur.executemany(sql, rows)
    conn.commit()

    cur.execute("SELECT count(*), count(player_id), count(franchise_id) FROM gold.dpvs_g_player_season")
    total, with_pid, with_fid = cur.fetchone()
    print(f"Loaded {total} rows into gold.dpvs_g_player_season "
          f"({with_pid} with player_id, {with_fid} with franchise_id)")

    cur.execute("SELECT min(season), max(season) FROM gold.dpvs_g_player_season")
    print("Season range:", cur.fetchone())

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
