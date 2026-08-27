#!/usr/bin/env python3
"""
Builds the per-(game, defending team, participant) "ingredients" table that
the new position-weighted TCS mechanism's credit split is computed from.
This is the expensive, I/O-heavy step (re-reads player_defense.csv per game
for raw per-player stat columns not carried in the cached
player_game_defense.parquet) -- run ONCE per season range; the actual
credit computation (dpvs/position_credit.py) just applies weight tables to
this cached table, so the Part 3 decay-ratio grid sweep doesn't need to
redo any of this.

Per participant-game row, computes:
  run_points / pass_points  -- game-level "points earned" vs. that specific
                                OPPONENT OFFENSE's own leave-one-out season
                                average (2026-08-23 rewrite; NOT blended with
                                league average -- a deliberate departure from
                                the original dual-benchmark _compute_tdgs()
                                formula, per this task's explicit spec: "I
                                don't care if those yards allowed are higher
                                than the defense usually gives -- the main
                                thing is they held that offense below what
                                expected"). Multi-metric, empirically
                                validated (ANY/A + sack rate for pass, rush
                                yards allowed alone for run -- comp%/pass-
                                yards/YPC tested and found redundant once
                                those are in the model, not used) -- see
                                dpvs/run_pass_points.py's module docstring
                                for the full candidate analysis and
                                correlation numbers, and
                                scripts/analyze_run_pass_points_candidates.py
                                for the analysis itself. Sourced from
                                gold.team_game_stats (Postgres, 1967-2025,
                                regular+playoff) via
                                dpvs.run_pass_points.compute_run_pass_
                                points_earned(), replacing the earlier
                                CSV-file-based (OFF_STATS_DIR) computation.
  scheme                    -- '3-4'/'4-3' for the player's team-season, from
                                gold.team_scheme_coach_season. None if unknown
                                (that whole game/team side falls back to the
                                flat 1/n split downstream -- see
                                dpvs/position_credit.py).
  run_label / pass_label    -- fine position label keying into the weight
                                tables (dpvs/position_weights.py), from
                                data_output/fine_position_map.parquet
                                (season-level, not per-game -- a player's
                                position is treated as fixed for a season,
                                same granularity the existing 'pos' column in
                                player_game_defense.parquet already uses).
  run_family / pass_family  -- the broader group a player's share is computed
                                within (e.g. LDE/RDE/DE_AVG all share the
                                'DE' run family so a side-unknown player's
                                tackle production still competes fairly
                                against known-side teammates for that game's
                                share of the DE slice).
  run_numerator             -- this game's raw signal for the RUN share:
                                real per-game tackles_combined when the
                                season's player_defense.csv actually carries
                                it (>=1999 confirmed populated; see
                                build_game_defense.py docstring), else a
                                season-level tackle_share proxy (reused
                                directly from dpvs/idi.py's existing,
                                name-resolved compute_idi() output -- NOT
                                re-derived here, see below) applied uniformly
                                across the player's games that season.
  pass_numerator             -- this game's raw signal for the PASS share,
                                built from real per-game sacks/def_int/
                                fumbles_forced (available every era, PFR
                                player_defense.csv confirmed populated
                                1950+) plus real per-game tackles_loss/
                                pass_defended when available (>=1999 only;
                                omitted pre-1999 -- documented gap, not
                                silently zero-filled elsewhere). Position-
                                specific mix (edge / coverage / MLB / DT) is
                                applied in dpvs/position_credit.py, not here
                                -- this script stores the raw component
                                counts so the mix formula can be changed
                                without re-reading any PDFs/CSVs.

Season-level tackle_share reuse (avoids re-deriving 1967-1977/1978-1998 name
resolution, which dpvs/idi.py already solves and validates): builds the
exact same `merged` scaffold build_dpvs_g.py's Step 2/3 does (tcs_df +
wowy_df via the FLAT/legacy team_credit_share -- only used here as a
carrier for pfr_player_id/season/team keys, not as this mechanism's actual
credit) and calls dpvs.idi.compute_idi() on it, keeping only the
`tackle_share` column it computes. This value is "player's share of TEAM
season tackle total" (gamebook/pbp/PFR sourced per era, all inside idi.py) --
renormalized WITHIN the resolved run_family for that team-season at credit
time (dpvs/position_credit.py), not here.

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    PYTHONPATH=~/github/football/football_db/src python3 scripts/build_tcs_ingredients.py --seasons 1967-2024

Writes: data_output/tcs_ingredients.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import numpy as np
import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent))

SILVER_DIR = Path.home() / "data/silver"
BOXSCORES_DIR = Path.home() / "data/pfref/raw/boxscores"
OFF_STATS_DIR = Path.home() / "data/pfref/raw/season/team/offense/team_stats"
DATA_OUT = Path(__file__).parent.parent / "data_output"
FINE_POS_MAP_PATH = DATA_OUT / "fine_position_map.parquet"
OUT_PATH = DATA_OUT / "tcs_ingredients.parquet"

TEAM_TO_FID: dict[str, int] = {
    "atl": 16, "buf": 4, "chi": 2, "cin": 3, "cle": 6, "clt": 11, "crd": 8,
    "dal": 13, "den": 5, "det": 20, "gnb": 21, "kan": 10, "mia": 14,
    "min": 32, "nor": 27, "nwe": 23, "nyg": 17, "nyj": 19, "oti": 31,
    "phi": 15, "pit": 29, "rai": 24, "ram": 25, "sdg": 9, "sea": 28,
    "sfo": 1, "tam": 7, "was": 12, "jax": 18, "car": 22, "rav": 26, "htx": 30,
}

# run_label -> broader family used for within-group share pooling
RUN_FAMILY = {
    "LDE": "DE", "RDE": "DE", "DE_AVG": "DE", "DE": "DE",
    "LOLB": "OLB", "ROLB": "OLB", "OLB_AVG": "OLB", "OLB": "OLB",
    "SS": "SS", "FS+CB": "FS+CB", "SS_FSCB_AVG": "FS+CB",
    "NT": "NT", "DT": "DT", "MLB": "MLB",
}
PASS_FAMILY = {
    "DE": "DE", "OLB": "OLB", "MLB": "MLB", "DT": "DT",
    "CB": "CB_FS", "FS": "CB_FS", "SS": "SS",
    "DB": "DB", "SS_FS_AVG": "SS_CBFS",
}


def _parse_seasons(s: str) -> list[int]:
    if "-" in s and not s.startswith("-"):
        lo, hi = s.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(s)]


def _team_name_map() -> dict[str, str]:
    # Reuse build_game_defense.py's own name map builder.
    from build_game_defense import _load_name_map
    return _load_name_map()


def load_raw_game_stats(seasons: list[int], game_ids: set[str]) -> pd.DataFrame:
    """Re-reads player_defense.csv per game for raw stat columns not carried
    in the cached player_game_defense.parquet (sacks, tackles_combined,
    def_int, fumbles_forced, tackles_loss, pass_defended)."""
    rows = []
    for season in seasons:
        season_dir = BOXSCORES_DIR / str(season)
        if not season_dir.exists():
            continue
        n = 0
        for game_dir in sorted(season_dir.iterdir()):
            if not game_dir.is_dir() or game_dir.name not in game_ids:
                continue
            f = game_dir / "player_defense.csv"
            if not f.exists():
                continue
            df = pd.read_csv(f)
            if df.empty:
                continue
            keep = ["game_id", "pfr_player_id", "team", "def_int", "sacks",
                    "tackles_combined", "fumbles_forced"]
            for opt in ("tackles_loss", "pass_defended"):
                if opt not in df.columns:
                    df[opt] = np.nan
            keep += ["tackles_loss", "pass_defended"]
            rows.append(df[keep])
            n += 1
        print(f"  {season}: read {n} player_defense.csv files", file=sys.stderr)
    if not rows:
        return pd.DataFrame(columns=["game_id", "pfr_player_id", "team", "def_int", "sacks",
                                      "tackles_combined", "fumbles_forced", "tackles_loss", "pass_defended"])
    return pd.concat(rows, ignore_index=True)


def load_scheme_map(conn) -> dict[tuple[str, int], str]:
    cur = conn.cursor()
    cur.execute("SELECT franchise_id, season, defensive_alignment FROM gold.team_scheme_coach_season")
    fid_to_team = {v: k for k, v in TEAM_TO_FID.items()}
    out = {}
    for fid, season, scheme in cur.fetchall():
        team = fid_to_team.get(fid)
        if team and scheme:
            out[(team, season)] = scheme
    return out


PBP_DEFENSIVE_STATS_CORPUS = (
    Path.home() / "github/football/gamebooks_boxscores/outputs"
    / "pfr_pbp_defensive_stats_1978_2025.csv"
)


def load_season_tackle_counts(seasons: list[int]) -> pd.DataFrame:
    """
    Season-level RAW tackle count per (season, team, player NAME) for the two
    eras with no reliable per-game tackle column (1967-1998) -- reuses
    dpvs/idi.py's already-validated 1967-1977 loader directly
    (load_gamebook_tackle_gated(), the same >=70%-completeness-gated corpus
    IDI itself is built from) and mirrors its own load_pbp_run_stuff() pattern for
    1978-1998 (no ready-made tackle-count loader exists in idi.py -- only
    run stuff -- so this is built here directly from the same source CSV's
    'tackles' column, same season/game_type/groupby convention as
    load_pbp_run_stuff()). 1999+ isn't needed here (real per-game tackles_combined
    already used directly -- see build_game_defense.py docstring on the
    per-game data cutover).

    Name-matching (lowercased, stripped player name within season+team) is
    the SAME convention idi.py's own tackle_share/run stuff merges use -- not a
    new risk introduced here.

    Returns: season, team, player_name_key, season_tackle_count.
    """
    from dpvs.idi import load_gamebook_tackle_gated

    frames = []
    gb = load_gamebook_tackle_gated()
    if not gb.empty:
        gb = gb[gb["season"].isin(seasons)]
        gb = gb.rename(columns={"tackle_count": "season_tackle_count"})
        frames.append(gb[["season", "team", "player", "season_tackle_count"]])

    if PBP_DEFENSIVE_STATS_CORPUS.exists():
        pbp = pd.read_csv(PBP_DEFENSIVE_STATS_CORPUS)
        pbp = pbp[(pbp["season"] >= 1978) & (pbp["season"] <= 1998) & (pbp["season"].isin(seasons))]
        if "game_type" in pbp.columns:
            pbp = pbp[pbp["game_type"] == "regular"]
        pbp = pbp.groupby(["season", "franchise_id", "player"], as_index=False).agg(
            season_tackle_count=("tackles", "sum"))
        fid_to_team = {v: k for k, v in TEAM_TO_FID.items()}
        pbp["team"] = pbp["franchise_id"].map(fid_to_team)
        pbp = pbp.dropna(subset=["team"])
        frames.append(pbp[["season", "team", "player", "season_tackle_count"]])

    if not frames:
        return pd.DataFrame(columns=["season", "team", "player_name_key", "season_tackle_count"])
    out = pd.concat(frames, ignore_index=True)
    out["player_name_key"] = out["player"].str.lower().str.strip()
    return out.groupby(["season", "team", "player_name_key"], as_index=False)["season_tackle_count"].sum()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="1967-2024")
    args = ap.parse_args()
    seasons = _parse_seasons(args.seasons)

    print(f"Building TCS ingredients for {seasons[0]}-{seasons[-1]}")

    game_df = pd.read_parquet(SILVER_DIR / "game_defense.parquet")
    player_df = pd.read_parquet(SILVER_DIR / "player_game_defense.parquet")
    game_df = game_df[game_df["season"].isin(seasons)].copy()
    player_df = player_df[player_df["season"].isin(seasons)].copy()
    print(f"  game_defense: {len(game_df):,} rows, player_game_defense: {len(player_df):,} rows")

    # ── run/pass points-earned per (game_id, team) ──────────────────────────
    # New 2026-08-23 mechanism -- multi-metric, opponent-LOO, empirically
    # validated -- see dpvs/run_pass_points.py's module docstring.
    from dpvs.run_pass_points import compute_run_pass_points_earned
    points_df = compute_run_pass_points_earned(seasons)
    points_df = points_df.rename(columns={
        "pass_points_earned": "pass_points", "run_points_earned": "run_points",
    })
    game_df = game_df.merge(
        points_df[["game_id", "team", "run_points", "pass_points"]],
        on=["game_id", "team"], how="left",
    )
    print(f"  run_points/pass_points computed: "
          f"{game_df['run_points'].notna().sum():,}/{len(game_df):,}, "
          f"{game_df['pass_points'].notna().sum():,}/{len(game_df):,} non-null")

    # ── raw per-game participant stats ──────────────────────────────────────
    game_ids = set(game_df["game_id"].unique())
    raw = load_raw_game_stats(seasons, game_ids)
    print(f"  raw per-game stat rows: {len(raw):,}")
    # player_game_defense's `team` is the DEFENDING team's pgd code (lowercase);
    # player_defense.csv's `team` is an NFL/media code (RAI, BAL, ...) needing
    # the same team-code normalization build_game_defense.py's
    # _filter_pdef_team() does. Simpler here: join on (game_id, pfr_player_id)
    # only (team is implied uniquely by pfr_player_id within a game — a player
    # can't appear for both sides), dropping raw's own team column.
    raw = raw.drop(columns=["team"]).drop_duplicates(subset=["game_id", "pfr_player_id"])
    player_df = player_df.merge(raw, on=["game_id", "pfr_player_id"], how="left")

    # ── scheme + fine position ──────────────────────────────────────────────
    conn = psycopg2.connect(dbname="football")
    scheme_map = load_scheme_map(conn)
    conn.close()
    player_df["scheme"] = player_df.apply(lambda r: scheme_map.get((r["team"], r["season"])), axis=1)

    # fine_position_map.parquet's pfr_player_id is the BARE PFR id (as stored
    # in internal.player_xref, e.g. "HayeEd20"); player_game_defense.parquet's
    # pfr_player_id is the full PFR URL form (e.g. "/players/H/HayeEd20.htm").
    # Join on the bare id, same extraction load_dpvs_g_to_db.py already uses.
    import re
    PFR_ID_RE = re.compile(r"/([A-Za-z0-9.]+)\.htm")
    player_df["_bare_pfr_id"] = player_df["pfr_player_id"].fillna("").str.extract(PFR_ID_RE.pattern)[0]

    fine_pos = pd.read_parquet(FINE_POS_MAP_PATH)
    fine_pos = fine_pos.rename(columns={"pfr_player_id": "_bare_pfr_id"})
    player_df = player_df.merge(
        fine_pos[["_bare_pfr_id", "team", "season", "run_pos_label", "pass_pos_label"]],
        on=["_bare_pfr_id", "team", "season"], how="left",
    )
    player_df["run_family"] = player_df["run_pos_label"].map(RUN_FAMILY)
    player_df["pass_family"] = player_df["pass_pos_label"].map(PASS_FAMILY)

    resolved = player_df["run_pos_label"].notna() & player_df["scheme"].notna()
    print(f"  position-resolved participant-games: {resolved.sum():,}/{len(player_df):,} "
          f"({100*resolved.sum()/len(player_df):.1f}%)")

    # ── season-level raw tackle count proxy (pre-1999 RUN numerator) ───────
    print("  loading season tackle count proxy (1967-1998)...")
    season_tk = load_season_tackle_counts(seasons)
    player_df["player_name_key"] = player_df["player_name"].fillna("").str.lower().str.strip()
    player_df = player_df.merge(season_tk, on=["season", "team", "player_name_key"], how="left")
    print(f"  season_tackle_count resolved: {player_df['season_tackle_count'].notna().sum():,} rows "
          f"(pre-1999 seasons only need this)")

    # ── merge run_points/pass_points onto participants ──────────────────────
    player_df = player_df.merge(
        game_df[["game_id", "team", "run_points", "pass_points"]],
        on=["game_id", "team"], how="left",
    )

    # per-game tackle data reliably populated 1999+ only (see module docstring)
    player_df["has_pergame_tackles"] = player_df["season"] >= 1999

    DATA_OUT.mkdir(exist_ok=True)
    player_df.to_parquet(OUT_PATH, index=False)
    print(f"Wrote {len(player_df):,} rows -> {OUT_PATH}")


if __name__ == "__main__":
    main()
