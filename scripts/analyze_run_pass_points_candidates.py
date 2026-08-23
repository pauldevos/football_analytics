#!/usr/bin/env python3
"""
Candidate-metric analysis for the new per-game run/pass "points earned"
mechanism that replaces TCS's yards-only run_points/pass_points
(scripts/build_tcs_ingredients.py's _run_pass_points, built in the 2026-08-23
§21 TCS rebuild). Full spec: docs/framework_decisions.md's newest section.

For every (season, defending team, game), computes how much better/worse
that defense held the SPECIFIC OPPONENT OFFENSE that game, relative to that
same offense's own season average (leave-one-out -- see below) -- for six
candidate metrics:

  PASS: pass_yds_allowed, comp_pct_allowed, any_a_allowed, sack_rate_by_def
  RUN:  rush_yds_allowed, ypc_allowed

Each metric's per-game gap (season_avg - actual, or actual - season_avg for
sack_rate where more sacks = better defense) is z-scored WITHIN SEASON
(same convention as dpvs/composite.py's _zscore_within -- season-relative
normalization, not fixed point values; see this task's own framework_
decisions.md entry for why this was chosen over fixed-point scales).

Leave-one-out vs full-season baseline: LEAVE-ONE-OUT. Tractable at this
scale (28,030 team-games, one vectorized groupby -- not per-row DB calls)
and more defensible (a game's own extreme performance doesn't get baked
into the "expected" bar it's being judged against, avoiding circularity).
Season averages are computed from REGULAR SEASON games only (this is what
"season average" means to a football audience -- a playoff opponent's
"expected" level is still their regular-season established form, and
16-17 games is a large enough LOO base that dropping one game barely moves
the mean anyway); every game (regular + playoff) is SCORED against that
baseline.

Validation targets (per the task's own instruction to test empirically,
not assume):
  1. PRIMARY: team-season points allowed, z-scored within season (negated
     so higher = better defense). This is a real, independent outcome
     measure -- it does not use any of the 6 candidate metrics' own gap
     computation, so it's not circular. Both run and pass defense jointly
     produce points allowed, same logic real published defensive metrics
     (DVOA, PFR's own DSRS) are validated against real scoring outcomes.
  2. SECONDARY: the already-built expected_top_pool.parquet (AP All-Pro
     defensive selections UNION top-10-defense starters) -- team-season
     fraction of defensive participants landing in that pool, correlated
     against each metric's team-season aggregate. Reused directly, not
     rebuilt (build_expected_top_pool.py already exists this session).

No full SRS/DSRS build attempted: points-allowed-z is a simpler, already-
available proxy that does the same job (a real, era-normalized outcome
signal) without needing to derive strength-of-schedule iteration -- see
this task's framework_decisions.md entry for the explicit tradeoff note.

Usage:
    cd ~/github/football/football_analytics && source .venv/bin/activate
    PYTHONPATH=~/github/football/football_db/src python3 \
        scripts/analyze_run_pass_points_candidates.py

Writes: data_output/run_pass_points_candidate_corr.csv
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

DATA_OUT = Path(__file__).parent.parent / "data_output"
POOL_PATH = DATA_OUT / "expected_top_pool.parquet"
SILVER_DIR = Path.home() / "data/silver"

TEAM_TO_FID: dict[str, int] = {
    "atl": 16, "buf": 4, "chi": 2, "cin": 3, "cle": 6, "clt": 11, "crd": 8,
    "dal": 13, "den": 5, "det": 20, "gnb": 21, "kan": 10, "mia": 14,
    "min": 32, "nor": 27, "nwe": 23, "nyg": 17, "nyj": 19, "oti": 31,
    "phi": 15, "pit": 29, "rai": 24, "ram": 25, "sdg": 9, "sea": 28,
    "sfo": 1, "tam": 7, "was": 12, "jax": 18, "car": 22, "rav": 26, "htx": 30,
}
FID_TO_TEAM = {v: k for k, v in TEAM_TO_FID.items()}


def load_team_games(conn) -> pd.DataFrame:
    q = """
        SELECT t.game_id, t.franchise_id, g.season, g.game_type,
               g.home_franchise_id, g.away_franchise_id,
               g.home_score, g.away_score,
               t.rush_attempts, t.rush_yards,
               t.pass_completions, t.pass_attempts, t.pass_yards,
               t.pass_tds, t.pass_ints, t.times_sacked, t.sack_yards_lost
        FROM gold.team_game_stats t
        JOIN gold.games g ON g.game_id = t.game_id
    """
    df = pd.read_sql(q, conn)
    df["team"] = df["franchise_id"].map(FID_TO_TEAM)
    df = df.dropna(subset=["team"]).copy()
    df["points_allowed"] = np.where(
        df["franchise_id"] == df["home_franchise_id"], df["away_score"], df["home_score"]
    )
    return df


def build_offense_actuals(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (game_id, offense_team) = that team's own offensive output
    that game -- this is what the OPPOSING defense allowed."""
    off = df[["game_id", "season", "game_type", "team",
              "rush_attempts", "rush_yards",
              "pass_completions", "pass_attempts", "pass_yards",
              "pass_tds", "pass_ints", "times_sacked", "sack_yards_lost"]].copy()
    off = off.rename(columns={"team": "offense_team"})
    off["cmp_pct"] = off["pass_completions"] / off["pass_attempts"].replace(0, np.nan)
    off["any_a"] = (off["pass_yards"] - off["sack_yards_lost"]
                    + 20 * off["pass_tds"] - 45 * off["pass_ints"]
                    ) / (off["pass_attempts"] + off["times_sacked"]).replace(0, np.nan)
    off["sack_rate"] = off["times_sacked"] / (off["pass_attempts"] + off["times_sacked"]).replace(0, np.nan)
    off["ypc"] = off["rush_yards"] / off["rush_attempts"].replace(0, np.nan)
    return off


def loo_season_avgs(off: pd.DataFrame) -> pd.DataFrame:
    """Leave-one-out season averages per (season, offense_team), computed
    from REGULAR SEASON games only. Returns off with *_loo columns merged in
    (LOO value only valid/used for regular season rows; playoff rows get the
    full regular-season average, i.e. n excludes nothing since the game
    itself isn't in the regular-season pool)."""
    reg = off[off["game_type"] == "regular"].copy()
    metrics = ["pass_yards", "cmp_pct", "any_a", "sack_rate", "rush_yards", "ypc"]

    grp = reg.groupby(["season", "offense_team"])
    n = grp["game_id"].transform("count")
    sums = {m: grp[m].transform("sum") for m in metrics}
    # cmp_pct/any_a/sack_rate/ypc are per-game RATES, not counts -- LOO mean
    # of a rate = (sum of rates - this game's rate) / (n-1); this is the
    # standard, simplest LOO-mean treatment (ratio-of-sums would need raw
    # numerator/denominator carried separately, a refinement not needed at
    # this n -- games/season is large enough (14-17) this makes negligible
    # difference vs a full ratio-of-sums LOO).
    for m in metrics:
        reg[f"{m}_loo"] = (sums[m] - reg[m]) / (n - 1).replace(0, np.nan)

    reg_avg = reg.groupby(["season", "offense_team"], as_index=False)[metrics].mean()
    reg_avg = reg_avg.rename(columns={m: f"{m}_seasonavg" for m in metrics})

    loo_cols = ["game_id", "season", "offense_team"] + [f"{m}_loo" for m in metrics]
    out = off.merge(reg[loo_cols], on=["game_id", "season", "offense_team"], how="left")
    out = out.merge(reg_avg, on=["season", "offense_team"], how="left")
    for m in metrics:
        # regular season game -> LOO value; playoff game -> full season avg
        out[f"{m}_expected"] = out[f"{m}_loo"].fillna(out[f"{m}_seasonavg"])
    return out


def _zscore_within_season(df: pd.DataFrame, col: str) -> pd.Series:
    out = pd.Series(np.nan, index=df.index)
    for season, idx in df.groupby("season").groups.items():
        s = df.loc[idx, col]
        mu, sigma = s.mean(), s.std(ddof=1)
        if not sigma or pd.isna(sigma):
            out.loc[idx] = 0.0
        else:
            out.loc[idx] = (s - mu) / sigma
    return out


def main():
    conn = psycopg2.connect(dbname="football")
    raw = load_team_games(conn)
    conn.close()
    print(f"team-game rows: {len(raw):,}  seasons {raw['season'].min()}-{raw['season'].max()}")

    off = build_offense_actuals(raw)
    off = loo_season_avgs(off)

    # Attach: for a DEFENSE's game row, "opponent" = the other team in that
    # game_id. Build defense-side table by joining raw (defense side) to
    # off (indexed by offense_team) via game_id + "the other team".
    game_teams = raw[["game_id", "team"]].rename(columns={"team": "defense_team"})
    both = game_teams.merge(game_teams, on="game_id", suffixes=("", "_opp"))
    both = both[both["defense_team"] != both["defense_team_opp"]].rename(
        columns={"defense_team_opp": "offense_team"})

    dgame = both.merge(off, left_on=["game_id", "offense_team"],
                        right_on=["game_id", "offense_team"], how="left")
    dgame = dgame.merge(raw[["game_id", "team", "points_allowed"]],
                         left_on=["game_id", "defense_team"], right_on=["game_id", "team"], how="left")

    # ── gaps: positive = defense did BETTER than the offense's own expected level ──
    dgame["gap_pass_yds"]  = dgame["pass_yards_expected"]  - dgame["pass_yards"]
    dgame["gap_cmp_pct"]   = dgame["cmp_pct_expected"]     - dgame["cmp_pct"]
    dgame["gap_any_a"]     = dgame["any_a_expected"]       - dgame["any_a"]
    dgame["gap_sack_rate"] = dgame["sack_rate"]            - dgame["sack_rate_expected"]  # more sacks=better D
    dgame["gap_rush_yds"]  = dgame["rush_yards_expected"]  - dgame["rush_yards"]
    dgame["gap_ypc"]       = dgame["ypc_expected"]         - dgame["ypc"]

    candidate_cols = ["gap_pass_yds", "gap_cmp_pct", "gap_any_a", "gap_sack_rate",
                       "gap_rush_yds", "gap_ypc"]
    for c in candidate_cols:
        dgame[f"{c}_z"] = _zscore_within_season(dgame, c)

    # ── target 1: points allowed, season z (negated so higher=better D) ──
    season_pts = dgame.groupby(["season", "defense_team"], as_index=False)["points_allowed"].sum()
    season_pts["pts_allowed_z"] = -_zscore_within_season(season_pts, "points_allowed")

    # ── team-season aggregates of each candidate ──
    agg = dgame.groupby(["season", "defense_team"], as_index=False)[
        [f"{c}_z" for c in candidate_cols]].mean()
    agg = agg.merge(season_pts[["season", "defense_team", "pts_allowed_z"]],
                     on=["season", "defense_team"], how="left")

    # ── target 2: expected_top_pool overlap fraction, team-season ──
    pool_corr = {}
    if POOL_PATH.exists() and (SILVER_DIR / "player_game_defense.parquet").exists():
        pool = pd.read_parquet(POOL_PATH)
        pgd = pd.read_parquet(SILVER_DIR / "player_game_defense.parquet")
        participants = pgd[["season", "team", "pfr_player_id"]].drop_duplicates()
        participants["in_pool"] = participants.set_index(
            ["season", "pfr_player_id"]).index.isin(
            pool.set_index(["season", "pfr_player_id"]).index)
        team_frac = participants.groupby(["season", "team"], as_index=False)["in_pool"].mean()
        team_frac = team_frac.rename(columns={"team": "defense_team", "in_pool": "pool_frac"})
        agg = agg.merge(team_frac, on=["season", "defense_team"], how="left")

    print(f"\nteam-season rows: {len(agg):,}\n")
    print(f"{'metric':16s} {'r vs pts_allowed_z':>20s} {'n':>8s}", end="")
    if "pool_frac" in agg.columns:
        print(f" {'r vs pool_frac':>16s}")
    else:
        print()

    results = []
    for c in candidate_cols:
        col = f"{c}_z"
        sub = agg[[col, "pts_allowed_z"]].dropna()
        r_pts = sub[col].corr(sub["pts_allowed_z"])
        row = {"metric": c, "r_vs_pts_allowed_z": round(r_pts, 4), "n": len(sub)}
        if "pool_frac" in agg.columns:
            sub2 = agg[[col, "pool_frac"]].dropna()
            r_pool = sub2[col].corr(sub2["pool_frac"])
            row["r_vs_pool_frac"] = round(r_pool, 4)
        results.append(row)
        extra = f" {row.get('r_vs_pool_frac', float('nan')):16.4f}" if "pool_frac" in agg.columns else ""
        print(f"{c:16s} {r_pts:20.4f} {len(sub):8d}{extra}")

    res_df = pd.DataFrame(results)
    DATA_OUT.mkdir(exist_ok=True)
    res_df.to_csv(DATA_OUT / "run_pass_points_candidate_corr.csv", index=False)
    print(f"\nWrote {DATA_OUT / 'run_pass_points_candidate_corr.csv'}")

    # Save the full per-game candidate table too (used to build the final
    # production run/pass points formula without re-querying Postgres).
    keep = ["game_id", "season", "defense_team", "offense_team", "game_type"] + \
           candidate_cols + [f"{c}_z" for c in candidate_cols]
    dgame[keep].to_parquet(DATA_OUT / "run_pass_points_pergame.parquet", index=False)
    print(f"Wrote {DATA_OUT / 'run_pass_points_pergame.parquet'}  ({len(dgame):,} rows)")


if __name__ == "__main__":
    main()
