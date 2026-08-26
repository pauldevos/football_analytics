#!/usr/bin/env python3
"""
Per-position, per-stat noise/skill-rating analysis (docs/deferred/
02_stat_noise_skill_rating_analysis.md).

Extends the single pooled overdispersion (phi) test from
docs/framework_decisions.md Sec12/Sec14 (tackle 4.87, TFL 2.69, INT 1.57,
FF 1.32, FR 1.08 -- pooled across all positions) into a per-position_group
breakdown, adds split-half career reliability and YoY Pearson-r as secondary
signals, computes a per-player z-score "skill distance" from the
position-group mean rate, and runs the PFR-games_played vs.
independently-counted-games integrity check requested alongside it.

Data source: football_db Postgres, gold.player_game_stats (reconciled
PFR 1978-2025 + gamebooks 1967-1977), gated for the 1967-1977 gamebook
portion by silver.player_game_stats_gamebook.completeness_qualified (the
project's established >=70% completeness-ratio gate -- see
gamebooks_boxscores/build_defensive_leaderboards.py and
football_analytics/scripts/build_tfl_gated_corpus.py /
build_tackle_gated_corpus.py for how that gate itself is computed; this
script does not re-derive it, only reads the pre-computed boolean column).

Position grouping copied inline from dpvs/positions.py (same 3-group
mapping: pass_rusher / run_stopper / coverage) rather than importing the
dpvs package, to avoid pulling in that package's heavier IDI-build
dependencies for what is a read-only analysis script.

Read-only: does not modify dpvs/idi.py or any production pipeline table.
Run with football_db's own .venv (needs psycopg2 + pandas + numpy; no
scipy available there, so Pearson r / regression pieces are done directly
with numpy rather than scipy.stats).

Usage:
    cd ~/github/football/football_db && source .venv/bin/activate
    cd ~/github/football/football_analytics
    PYTHONPATH=~/github/football/football_db/src \
        python3 scripts/stat_noise_skill_rating_analysis.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.home() / "github" / "football" / "football_db" / "src"))
from football_db.db import get_connection  # noqa: E402

OUT_JSON = Path(__file__).resolve().parent.parent / "data_output" / "stat_noise_skill_rating_results.json"

# ── position grouping (copied from dpvs/positions.py, see module docstring) ──
POSITION_GROUP: dict[str, str] = {
    "DE": "pass_rusher", "LDE": "pass_rusher", "RDE": "pass_rusher",
    "OLB": "pass_rusher", "LOLB": "pass_rusher", "ROLB": "pass_rusher",
    "DT": "run_stopper", "LDT": "run_stopper", "RDT": "run_stopper",
    "NT": "run_stopper", "DL": "run_stopper",
    "LB": "run_stopper", "ILB": "run_stopper", "MLB": "run_stopper",
    "LILB": "run_stopper", "RILB": "run_stopper", "LLB": "run_stopper", "RLB": "run_stopper",
    "CB": "coverage", "RCB": "coverage", "LCB": "coverage", "DB": "coverage",
    "S": "coverage", "SS": "coverage", "FS": "coverage", "SAF": "coverage",
}


def map_position(pos) -> str:
    if not pos:
        return "unknown"
    return POSITION_GROUP.get(str(pos).strip().upper(), "unknown")


STATS = {
    "tackle": "tackle",
    "sack": "sack",
    "tfl": "tfl",
    "fr": "fr",
    "int": "int",
    "pd": "pd",
    "ff": "ff",
}
POSITION_GROUPS = ["pass_rusher", "run_stopper", "coverage"]

MIN_GAMES_RATE = 4      # floor before a season's rate is trusted for YoY/split-half/skill-rating
MIN_CAREER_GAMES_LB = 16  # floor before a player-career appears on a leaderboard (~1 full season)
K0 = 8.0  # same reference scale idi.py uses (documented judgment call, not re-derived here)


def load_game_level(conn) -> pd.DataFrame:
    """
    One row per (player_id, season, game_id) with position and the 7 stat
    columns, restricted to:
      - current_source='pfr' rows (1978-2025), always included
      - current_source='gamebook' rows (1967-1977) ONLY where the
        corresponding silver.player_game_stats_gamebook row has
        completeness_qualified = true
    This is the >=70% completeness-ratio gate applied at the per-team-side
    level upstream; reading it here as a boolean column, not re-deriving it.
    """
    # pgs.position is only ever populated for gamebook-sourced rows (see
    # dpvs/idi.py's load_gold_stats_from_db() comment: silver.
    # player_game_stats_pfr, the source behind current_source='pfr' rows,
    # carries no position field at all). Backfill from silver.
    # player_team_seasons_pfr (season-level roster/position table) the same
    # way idi.py already does, or every 1978-2025 row falls to
    # position_group='unknown' and silently drops out of this analysis.
    q = """
        SELECT g.season AS season, pgs.player_id AS player_id, pgs.game_id AS game_id,
               pgs.franchise_id AS franchise_id,
               coalesce(pgs.position, pts.position) AS position,
               pgs.comb_tackle AS comb_tackle, pgs.sack AS sack, pgs.run_stuff AS tfl,
               pgs.fr AS fr, pgs.def_int AS def_int, pgs.pd AS pd, pgs.ff AS ff,
               pgs.current_source AS current_source
        FROM gold.player_game_stats pgs
        JOIN gold.games g ON g.game_id = pgs.game_id
        LEFT JOIN silver.player_game_stats_gamebook gb
               ON gb.player_id = pgs.player_id AND gb.game_id = pgs.game_id
        LEFT JOIN silver.player_team_seasons_pfr pts
               ON pts.player_id = pgs.player_id AND pts.franchise_id = pgs.franchise_id
              AND pts.season = g.season
        WHERE pgs.current_source = 'pfr'
           OR (pgs.current_source = 'gamebook' AND gb.completeness_qualified = true)
    """
    df = pd.read_sql(q, conn)
    for c in ["comb_tackle", "sack", "tfl", "fr", "def_int", "pd", "ff"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def load_players(conn) -> pd.DataFrame:
    return pd.read_sql("SELECT player_id, full_name FROM gold.players", conn)


def load_pfr_season_gp(conn) -> pd.DataFrame:
    """PFR's own season-level games_played, summed across franchises for a
    player-season (handles in-season trades additively -- see script
    docstring / final report for how this is interpreted)."""
    q = """
        SELECT player_id, season, sum(games_played) AS pfr_gp,
               sum(games_started) AS pfr_gs
        FROM silver.player_team_seasons_pfr
        GROUP BY player_id, season
    """
    return pd.read_sql(q, conn)


def build_season_frame(game_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the gated game-level frame to one row per
    (player_id, season): position (mode), franchise (mode), games (n distinct
    game_id -- this IS the independent, presence-derived games count used
    both as the rate denominator throughout this script AND as the
    independent side of the games-played integrity check), and stat sums."""
    pos_mode = (
        game_df.groupby(["player_id", "season"])["position"]
        .agg(lambda s: s.dropna().mode().iloc[0] if not s.dropna().empty else None)
    )
    agg = game_df.groupby(["player_id", "season"]).agg(
        games=("game_id", "nunique"),
        tackle=("comb_tackle", "sum"), sack=("sack", "sum"), tfl=("tfl", "sum"),
        fr=("fr", "sum"), int=("def_int", "sum"), pd=("pd", "sum"), ff=("ff", "sum"),
    ).reset_index()
    agg = agg.merge(pos_mode.rename("position").reset_index(), on=["player_id", "season"], how="left")
    agg["position_group"] = agg["position"].apply(map_position)
    return agg


def phi_overdispersion(df: pd.DataFrame, count_col: str, games_col: str = "games") -> tuple[float, int]:
    """Quasi-Poisson method-of-moments overdispersion, same formula
    build_tackle_gated_corpus.py uses: season-pooled population rate as mu,
    Pearson chi-square / (N - n_seasons). Returns (phi, n_rows)."""
    d = df[df[games_col] > 0].copy()
    if len(d) < 5:
        return (float("nan"), len(d))
    season_rate = d.groupby("season").apply(lambda g: g[count_col].sum() / g[games_col].sum())
    d["mu"] = d["season"].map(season_rate) * d[games_col]
    d = d[d["mu"] > 0]
    if len(d) < 5:
        return (float("nan"), len(d))
    resid2 = (d[count_col] - d["mu"]) ** 2 / d["mu"]
    denom = len(d) - d["season"].nunique()
    if denom <= 0:
        return (float("nan"), len(d))
    return (float(resid2.sum() / denom), len(d))


def pearson_r(x: pd.Series, y: pd.Series) -> tuple[float, int]:
    m = x.notna() & y.notna()
    x, y = x[m], y[m]
    n = len(x)
    if n < 5 or x.std(ddof=1) == 0 or y.std(ddof=1) == 0:
        return (float("nan"), n)
    return (float(np.corrcoef(x, y)[0, 1]), n)


def yoy_r(df: pd.DataFrame, count_col: str) -> tuple[float, int]:
    d = df[df["games"] >= MIN_GAMES_RATE].copy()
    d["rate"] = d[count_col] / d["games"]
    nxt = d[["player_id", "season", "rate"]].copy()
    nxt["season"] = nxt["season"] - 1
    nxt = nxt.rename(columns={"rate": "rate_next"})
    pairs = d.merge(nxt, on=["player_id", "season"], how="inner")
    return pearson_r(pairs["rate"], pairs["rate_next"])


def split_half_r(df: pd.DataFrame, count_col: str) -> tuple[float, float, int]:
    """Alternate a player's qualifying seasons (games>=MIN_GAMES_RATE) into
    half A / half B by season order, aggregate rate within each half,
    Pearson r across players between halves, Spearman-Brown corrected to a
    full-length-career estimate. Returns (raw_r, sb_corrected_r, n_players)."""
    d = df[df["games"] >= MIN_GAMES_RATE].copy()
    rows = []
    for pid, g in d.groupby("player_id"):
        g = g.sort_values("season")
        if len(g) < 2:
            continue
        a = g.iloc[0::2]
        b = g.iloc[1::2]
        if a["games"].sum() == 0 or b["games"].sum() == 0:
            continue
        rows.append({
            "player_id": pid,
            "rate_a": a[count_col].sum() / a["games"].sum(),
            "rate_b": b[count_col].sum() / b["games"].sum(),
        })
    half = pd.DataFrame(rows)
    if half.empty:
        return (float("nan"), float("nan"), 0)
    r, n = pearson_r(half["rate_a"], half["rate_b"])
    if pd.isna(r) or r <= -1:
        return (r, float("nan"), n)
    sb = (2 * r) / (1 + r) if (1 + r) != 0 else float("nan")
    return (r, sb, n)


def skill_leaderboard(df: pd.DataFrame, count_col: str, phi: float, players: pd.DataFrame,
                       top_n: int = 15) -> list[dict]:
    """Career-level shrunk-rate z-score leaderboard for one (stat,
    position_group). Simplified vs. idi.py's sequential career-to-date prior
    (this is a career-aggregate snapshot, not a per-season build): prior is
    the pooled population rate across all qualifying player-seasons in this
    slice; shrinkage k = K0/(phi-1) using this stat+position_group's own
    measured phi (not idi.py's pooled-across-all-positions phi)."""
    d = df[df["games"] >= MIN_GAMES_RATE].copy()
    if d.empty or pd.isna(phi) or phi <= 1.0:
        return []
    career = d.groupby("player_id").agg(games=("games", "sum"), count=(count_col, "sum")).reset_index()
    career = career[career["games"] >= MIN_CAREER_GAMES_LB]
    if career.empty:
        return []
    pop_rate = career["count"].sum() / career["games"].sum()
    k = K0 / (phi - 1.0)
    career["obs_rate"] = career["count"] / career["games"]
    career["shrunk_rate"] = (career["games"] * career["obs_rate"] + k * pop_rate) / (career["games"] + k)
    mu = career["shrunk_rate"].mean()
    sd = career["shrunk_rate"].std(ddof=1)
    if not sd or pd.isna(sd) or sd == 0:
        return []
    career["z"] = (career["shrunk_rate"] - mu) / sd
    career = career.merge(players, on="player_id", how="left")
    top = career.sort_values("z", ascending=False).head(top_n)
    return [
        {
            "player": r["full_name"], "player_id": int(r["player_id"]),
            "career_games": int(r["games"]), "career_count": float(r["count"]),
            "rate_per_game": round(float(r["obs_rate"]), 3),
            "shrunk_rate_per_game": round(float(r["shrunk_rate"]), 3),
            "z": round(float(r["z"]), 2),
        }
        for _, r in top.iterrows()
    ]


def games_played_integrity_check(conn, game_df: pd.DataFrame) -> dict:
    """Compare PFR's own season games_played (silver.player_team_seasons_pfr)
    against an independent count: distinct game_id appearing for that
    player+season in gold.player_game_stats, UNGATED (any current_source,
    including gamebook rows that failed the completeness gate -- presence in
    a boxscore is a different question from whether that box score's stats
    are trustworthy, and gating here would conflate the two)."""
    q = """
        SELECT g.season AS season, pgs.player_id AS player_id,
               count(DISTINCT pgs.game_id) AS indep_gp
        FROM gold.player_game_stats pgs
        JOIN gold.games g ON g.game_id = pgs.game_id
        GROUP BY g.season, pgs.player_id
    """
    indep = pd.read_sql(q, conn)
    pfr_gp = load_pfr_season_gp(conn)
    merged = pfr_gp.merge(indep, on=["player_id", "season"], how="inner")
    merged = merged[merged["pfr_gp"] > 0]
    merged["diff"] = merged["pfr_gp"] - merged["indep_gp"]
    merged["abs_diff"] = merged["diff"].abs()
    merged["pct_diff"] = merged["abs_diff"] / merged["pfr_gp"]

    total = len(merged)
    exact = int((merged["diff"] == 0).sum())
    within1 = int((merged["abs_diff"] <= 1).sum())
    big = merged[merged["abs_diff"] >= 3]

    by_era = []
    for lo, hi, label in [(1967, 1977, "1967-1977"), (1978, 1998, "1978-1998"),
                           (1999, 2025, "1999-2025")]:
        sub = merged[(merged["season"] >= lo) & (merged["season"] <= hi)]
        if sub.empty:
            continue
        by_era.append({
            "era": label, "n": len(sub),
            "exact_match_pct": round(100 * (sub["diff"] == 0).mean(), 1),
            "within_1_pct": round(100 * (sub["abs_diff"] <= 1).mean(), 1),
            "mean_abs_diff": round(float(sub["abs_diff"].mean()), 2),
            "pfr_gt_indep_by_ge3": int((sub["diff"] >= 3).sum()),
            "indep_gt_pfr_by_ge3": int((sub["diff"] <= -3).sum()),
        })

    return {
        "n_player_seasons": total,
        "exact_match_pct": round(100 * exact / total, 1) if total else None,
        "within_1_game_pct": round(100 * within1 / total, 1) if total else None,
        "mean_abs_diff": round(float(merged["abs_diff"].mean()), 2) if total else None,
        "n_big_discrepancy_ge3": len(big),
        "by_era": by_era,
    }


def main():
    conn = get_connection()
    try:
        print("Loading gated game-level frame from Postgres...")
        game_df = load_game_level(conn)
        print(f"  {len(game_df):,} gated (player,season,game) rows")
        players = load_players(conn)

        print("Running games-played integrity check...")
        integrity = games_played_integrity_check(conn, game_df)
    finally:
        pass  # keep conn open for integrity check above; close after

    season_df = build_season_frame(game_df)
    print(f"Built {len(season_df):,} player-season rows, "
          f"position_group counts:\n{season_df['position_group'].value_counts()}")

    results = {"stats": {}, "games_played_integrity": integrity}

    for stat, col in STATS.items():
        results["stats"][stat] = {}
        for grp in POSITION_GROUPS:
            sub = season_df[season_df["position_group"] == grp]
            phi, n_phi = phi_overdispersion(sub, col)
            r_yoy, n_yoy = yoy_r(sub, col)
            r_half, r_half_sb, n_half = split_half_r(sub, col)
            lb = skill_leaderboard(sub, col, phi, players)
            results["stats"][stat][grp] = {
                "n_player_seasons": int(len(sub)),
                "n_player_seasons_ge_min_games": int((sub["games"] >= MIN_GAMES_RATE).sum()),
                "phi": None if pd.isna(phi) else round(phi, 3),
                "phi_n_rows": n_phi,
                "yoy_pearson_r": None if pd.isna(r_yoy) else round(r_yoy, 3),
                "yoy_n_pairs": n_yoy,
                "split_half_r_raw": None if pd.isna(r_half) else round(r_half, 3),
                "split_half_r_spearman_brown": None if pd.isna(r_half_sb) else round(r_half_sb, 3),
                "split_half_n_players": n_half,
                "leaderboard_top15": lb,
            }
            print(f"{stat:8s} {grp:12s} phi={phi if pd.isna(phi) else round(phi,2):>6} "
                  f"yoy_r={r_yoy if pd.isna(r_yoy) else round(r_yoy,3):>7} "
                  f"split_half_sb={r_half_sb if pd.isna(r_half_sb) else round(r_half_sb,3):>7} "
                  f"n_seasons={len(sub):>6}")

    conn.close()

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
