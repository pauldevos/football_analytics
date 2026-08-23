"""
Real per-game run/pass defensive "points earned" -- replaces TCS's earlier
yards-only, league+opponent-blended run_points/pass_points (the 2026-08-23
§21 TCS rebuild's `_run_pass_points()` in scripts/build_tcs_ingredients.py).

Full spec + candidate-metric validation: docs/framework_decisions.md's
newest dated section. Analysis script that produced the weights below:
scripts/analyze_run_pass_points_candidates.py (writes
data_output/run_pass_points_candidate_corr.csv and
data_output/run_pass_points_pergame.parquet -- rerun that script if the
underlying team_game_stats data changes and these weights need re-deriving).

── The mechanism ────────────────────────────────────────────────────────────

For a given (game, defending team), "expected" = the SPECIFIC OPPONENT
OFFENSE's own season average for a metric -- not this defense's own typical
level, and NOT blended with a league average (unlike the old TDGS formula
this replaces -- the user's own framing was explicit: "I don't care if
those passing yards and rushing yards per game allowed are higher than the
defense usually gives -- the main thing is they held that offense below
what expected", i.e. purely opponent-relative). Season average is
LEAVE-ONE-OUT (excludes the game being scored) computed from that offense's
REGULAR SEASON games only -- tractable at this scale (one vectorized
groupby over ~28k team-games, not per-row DB calls) and more defensible
than full-season-inclusive (avoids a game's own extreme value partly
defining the bar it's judged against). A playoff game is scored against the
full regular-season average (LOO doesn't apply -- the game itself was never
in the regular-season averaging pool).

Six candidate metrics were built and empirically tested (see the analysis
script + framework_decisions.md for the full correlation table):
  PASS: pass yards allowed, completion % allowed, ANY/A allowed,
        sack rate (by this defense, vs. that offense's own season
        sack-rate-allowed)
  RUN:  rush yards allowed, yards per carry allowed

Each metric's per-game gap (season_avg − actual, or actual − season_avg for
sack rate where MORE sacks = better defense) is z-scored WITHIN SEASON
(same convention as dpvs/composite.py's _zscore_within -- season-relative
normalization, consistent with the rest of this codebase, chosen over an
arbitrary fixed-point scale).

Validated against team-season points allowed (z-scored within season,
negated so higher=better defense) -- a real, independent outcome signal,
not derived from any of the 6 candidates, standard practice for validating
a defensive sub-metric (same idea as DVOA/DSRS validation against real
scoring outcomes). Cross-checked against a secondary target
(data_output/expected_top_pool.parquet's AP-All-Pro/top-10-starter overlap
fraction) -- same ranking of which metrics carry signal, confirming this
isn't an artifact of one target choice.

Results (team-season aggregates, n=1,720, 1967-2025):
  gap_any_a_z      r=0.654 vs pts_allowed_z   (dominant pass predictor)
  gap_rush_yds_z   r=0.491 vs pts_allowed_z   (dominant run predictor)
  gap_pass_yds_z   r=0.391   gap_cmp_pct_z r=0.361   gap_sack_rate_z r=0.336
  gap_ypc_z        r=0.377

All six clear real, positive signal (nothing near TDGS's own historical
r=0.054 "no signal" bar from §1) -- but combining them naively (equal-
weight average) UNDERPERFORMS the single best metric in both phases:
  PASS equal-weight r=0.577 < any_a alone r=0.654 (comp% and pass-yards are
    highly collinear with ANY/A -- pairwise r=0.41-0.55 -- and ANY/A
    already incorporates yards/TDs/INTs/sacks in one number, so adding them
    back separately mostly adds redundant noise, not new signal. OLS
    confirms: comp%'s standardized coefficient is ~0 once ANY/A is in the
    model.)
  RUN equal-weight r=0.461 < rush_yds alone r=0.491 (YPC is 0.80-correlated
    with rush yards allowed and its OLS coefficient goes slightly NEGATIVE
    once rush yards is included -- a suppression artifact, not real
    independent signal.)

2026-08-23 RECALIBRATION -- game-level, single-stat-only, no blend at all.
The team-season combination above (ANY/A+sack_rate blend) was superseded
after a much larger game-level (n=26,876) re-test explicitly requested by
the user, who pushed back hard on two things: (1) don't combine separate
stats into one score before understanding each one's own weight -- test
every candidate individually first; (2) win/loss is a bad target for
isolating DEFENSIVE value specifically, since a defense can play a
shutdown game and still lose (offense is ~50% of the outcome) -- points
allowed below that specific opponent's own expected scoring (same
LOO-opponent-relative convention as everything else here) is the correct
target, since it isolates what the defense actually controls. Re-ran the
full 6-metric test at the game level against BOTH win and points allowed;
results held up directionally on both, with points-allowed as the primary
target used to select the final formula:

  R^2 vs points allowed (26,876 games): any_a=0.320, rush_pct=0.127,
  cmp_pct=0.105, pass_pct=0.085, sack_rate=0.050, ypc=0.028
  (garbage time distortion confirmed directly: pass_pct/ypc were near-zero
  vs WIN (R^2 0.0004 / 0.001) but real vs points allowed (0.085 / 0.028) --
  a trailing/leading team's yardage inflates in prevent/hurry-up situations
  without changing who wins, but points allowed isn't fooled the same way)

Completion% looked like a real third category on its univariate R^2 (0.105)
but a multivariable OLS against points allowed (rush_pct + cmp_pct + any_a
together) shows it's redundant with ANY/A even on THIS target, not just
win: pairwise r(cmp_pct, any_a)=0.544, and adding cmp_pct to a model that
already has any_a moves R^2 from 0.3202 to only 0.3206 -- statistically
nothing. Confirmed directly with the user before dropping it (they'd asked
to keep a "top 3"; the redundancy check is why it's 2, not 3).

Final formula -- single stat per phase, NOT combined, NOT blended:
  pass_points_earned = z(gap_any_a), within season
  run_points_earned  = z(gap_rush_pct), within season
                        (gap_rush_pct = (expected-actual)/expected, i.e.
                        percent held below that opponent's own expected
                        rushing yards -- switched from the raw-yards gap
                        used previously since this is the framing actually
                        validated against both win and points allowed in
                        this pass, and is more directly interpretable:
                        "held X% below expected" rather than a raw-yards z)

sack_rate, cmp_pct, pass_pct, ypc are no longer part of team_credit_share's
run/pass points at all -- not down-weighted, dropped entirely, since with
only one non-redundant stat per phase there is nothing left to blend or
calibrate a relative weight for. points_allowed's role was purely to
select which stats survive (a target, not a scored category -- explicitly
decided against making it its own category: that would double-count value
already captured via the calibrated stats, and it has no clean position-
group attribution the way a sack or a tackle does).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import psycopg2

TEAM_TO_FID: dict[str, int] = {
    "atl": 16, "buf": 4, "chi": 2, "cin": 3, "cle": 6, "clt": 11, "crd": 8,
    "dal": 13, "den": 5, "det": 20, "gnb": 21, "kan": 10, "mia": 14,
    "min": 32, "nor": 27, "nwe": 23, "nyg": 17, "nyj": 19, "oti": 31,
    "phi": 15, "pit": 29, "rai": 24, "ram": 25, "sdg": 9, "sea": 28,
    "sfo": 1, "tam": 7, "was": 12, "jax": 18, "car": 22, "rav": 26, "htx": 30,
}
FID_TO_TEAM = {v: k for k, v in TEAM_TO_FID.items()}

# Final, empirically-derived weights -- see module docstring.
# 2026-08-23 (points-allowed recalibration): single-stat only, no blend.
# pass_points_earned = z(any_a gap) alone; run_points_earned = z(pct-below-
# expected-rush-yards) alone. sack_rate/comp%/pass_yds/ypc all dropped --
# see docstring for why (comp% redundant with ANY/A even against points
# allowed, r=0.544 pairwise, +0.0004 R2 once ANY/A is in the model; sack
# rate/pass_yds/ypc all weak standalone and add nothing once the two
# survivors are in place). Nothing left to blend, so no relative weight
# to calibrate -- points-allowed's role was purely to pick these two.
PASS_WEIGHTS = {"gap_any_a_z": 1.0}
RUN_WEIGHTS = {"gap_rush_pct_z": 1.0}

_METRICS = ["pass_yards", "cmp_pct", "any_a", "sack_rate", "rush_yards", "ypc"]


def _load_team_games(conn) -> pd.DataFrame:
    # game_id here is gold.games' internal serial int. TCS's own game_df
    # (scripts/build_game_defense.py) keys everything on the PFR boxscore-id
    # STRING ("{date}0{home_abbr}", e.g. "197109190atl") instead -- join
    # through internal.game_xref (source_system='pfr') to translate, so the
    # output of this function merges cleanly onto game_df downstream.
    q = """
        SELECT t.game_id, t.franchise_id, g.season, g.game_type,
               g.home_franchise_id, g.away_franchise_id,
               g.home_score, g.away_score,
               t.rush_attempts, t.rush_yards,
               t.pass_completions, t.pass_attempts, t.pass_yards,
               t.pass_tds, t.pass_ints, t.times_sacked, t.sack_yards_lost,
               x.source_game_id AS pfr_game_id
        FROM gold.team_game_stats t
        JOIN gold.games g ON g.game_id = t.game_id
        JOIN internal.game_xref x ON x.game_id = t.game_id AND x.source_system = 'pfr'
    """
    df = pd.read_sql(q, conn)
    df["team"] = df["franchise_id"].map(FID_TO_TEAM)
    return df.dropna(subset=["team"]).copy()


def _offense_actuals(df: pd.DataFrame) -> pd.DataFrame:
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


def _loo_season_avgs(off: pd.DataFrame) -> pd.DataFrame:
    reg = off[off["game_type"] == "regular"].copy()
    grp = reg.groupby(["season", "offense_team"])
    n = grp["game_id"].transform("count")
    sums = {m: grp[m].transform("sum") for m in _METRICS}
    for m in _METRICS:
        reg[f"{m}_loo"] = (sums[m] - reg[m]) / (n - 1).replace(0, np.nan)
    reg_avg = reg.groupby(["season", "offense_team"], as_index=False)[_METRICS].mean()
    reg_avg = reg_avg.rename(columns={m: f"{m}_seasonavg" for m in _METRICS})
    loo_cols = ["game_id", "season", "offense_team"] + [f"{m}_loo" for m in _METRICS]
    out = off.merge(reg[loo_cols], on=["game_id", "season", "offense_team"], how="left")
    out = out.merge(reg_avg, on=["season", "offense_team"], how="left")
    for m in _METRICS:
        out[f"{m}_expected"] = out[f"{m}_loo"].fillna(out[f"{m}_seasonavg"])
    return out


def _zscore_within_season(df: pd.DataFrame, col: str) -> pd.Series:
    out = pd.Series(np.nan, index=df.index)
    for _, idx in df.groupby("season").groups.items():
        s = df.loc[idx, col]
        mu, sigma = s.mean(), s.std(ddof=1)
        out.loc[idx] = 0.0 if not sigma or pd.isna(sigma) else (s - mu) / sigma
    return out


def compute_run_pass_points_earned(seasons: list[int] | None = None) -> pd.DataFrame:
    """
    Returns one row per (game_id, defense team):
      game_id, season, team, pass_points_earned, run_points_earned
    covering every game in gold.team_game_stats (1967-2025, regular +
    playoff). `seasons` filters the season range if given (still computes
    LOO averages only from within-season regular-season games, so no
    cross-season leakage regardless of the filter).
    """
    conn = psycopg2.connect(dbname="football")
    try:
        raw = _load_team_games(conn)
    finally:
        conn.close()

    if seasons:
        season_set = set(seasons)
        raw = raw[raw["season"].isin(season_set)].copy()

    off = _offense_actuals(raw)
    off = _loo_season_avgs(off)

    game_teams = raw[["game_id", "team"]].rename(columns={"team": "defense_team"})
    both = game_teams.merge(game_teams, on="game_id", suffixes=("", "_opp"))
    both = both[both["defense_team"] != both["defense_team_opp"]].rename(
        columns={"defense_team_opp": "offense_team"})

    dgame = both.merge(off, on=["game_id", "offense_team"], how="left")

    dgame["gap_any_a"] = dgame["any_a_expected"] - dgame["any_a"]
    dgame["gap_rush_pct"] = (
        (dgame["rush_yards_expected"] - dgame["rush_yards"])
        / dgame["rush_yards_expected"].replace(0, np.nan)
    )

    for c in ["gap_any_a", "gap_rush_pct"]:
        dgame[f"{c}_z"] = _zscore_within_season(dgame, c)

    dgame["pass_points_earned"] = sum(
        w * dgame[c] for c, w in PASS_WEIGHTS.items()
    ).round(4)
    dgame["run_points_earned"] = sum(
        w * dgame[c] for c, w in RUN_WEIGHTS.items()
    ).round(4)

    # Translate Postgres serial game_id -> PFR boxscore-id string (see
    # _load_team_games docstring note) so this merges cleanly onto game_df.
    id_map = raw[["game_id", "pfr_game_id"]].drop_duplicates()
    dgame = dgame.merge(id_map, on="game_id", how="left")

    out = dgame.rename(columns={"defense_team": "team"})[
        ["pfr_game_id", "season", "team", "pass_points_earned", "run_points_earned"]
    ].rename(columns={"pfr_game_id": "game_id"}).copy()
    out = out.dropna(subset=["game_id"])
    return out
