#!/usr/bin/env python3
"""
MLB WOWY Analysis
=================
Tests whether elite interior linebackers improve team rush defense and total
defense when they join a new team — the positional analogue to the sack
gravity hypothesis tested for pass rushers in sack_wowy_analysis.py.

Key differences vs. DE analysis:
  - Elite threshold: era-normalized z-score (tackles vary wildly by decade)
  - Primary outcome: rush defense rank + total defense rank (not sack rank)
  - "Additive" is harder to isolate — tackles don't map cleanly like sacks do
  - Many elite MLBs were one-team players → heavier reliance on injury WOWY

Tier definitions:
  Tier 1 (Elite MLB):       career avg z-score ≥ 1.0  AND  ≥ 4 qualifying seasons
  Tier 2 (Truly Elite MLB): career avg z-score ≥ 1.5  AND  3+ seasons with z ≥ 1.5

Usage:
  ~/github/football/media_guide_parser/.venv/bin/python mlb_wowy_analysis.py

Outputs to: ~/data/mlb_wowy_results/
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────
GOLD_PATH     = Path.home() / "data/gold/player_season_card.parquet"
BOXSCORE_BASE = Path.home() / "data/pfref/raw/boxscores"
RESULTS_DIR   = Path.home() / "data/mlb_wowy_results"
RUSH_DIR      = Path.home() / "data/pfref/raw/season/team/defense/rushing"
HIST_DIR      = Path.home() / "data/pfref/raw/team-history"

# ── Tier thresholds ───────────────────────────────────────────────────────────
TIER1_Z_MIN      = 1.0   # career avg z-score
TIER1_MIN_SEASONS = 4    # qualifying seasons (≥8g, tackles known)
TIER2_Z_MIN      = 1.5   # career avg z-score for truly elite
TIER2_Z_SEASONS  = 3     # seasons with z ≥ TIER2_Z_MIN for truly elite

STRIKE_SEASONS   = {1982: 9, 1987: 15}
MIN_GAMES        = 8

# ── Interior LB positions (exclude all OLB/edge variants) ────────────────────
INTERIOR_LB = {"MLB", "ILB", "LB", "LLB", "RLB", "LILB", "RILB"}
EDGE_LABELS = {"LOLB", "ROLB", "OLB", "DE", "LDE", "RDE"}

# ── Team name → PFR abbreviation (matches gold parquet casing when lowercased) ─
TEAM_NAME_TO_PFR = {
    "Buffalo Bills": "buf", "Miami Dolphins": "mia",
    "New England Patriots": "nwe", "Boston Patriots": "nwe",
    "New York Jets": "nyj", "New York Titans": "nyj",
    "Baltimore Ravens": "rav", "Cincinnati Bengals": "cin",
    "Cleveland Browns": "cle", "Pittsburgh Steelers": "pit",
    "Houston Texans": "htx", "Indianapolis Colts": "clt",
    "Baltimore Colts": "clt", "Jacksonville Jaguars": "jax",
    "Tennessee Titans": "ten", "Tennessee Oilers": "ten",
    "Houston Oilers": "oti",
    "Denver Broncos": "den", "Kansas City Chiefs": "kan",
    "Dallas Texans": "kan",
    "Las Vegas Raiders": "lvr", "Oakland Raiders": "rai",
    "Los Angeles Raiders": "rai",
    "Los Angeles Chargers": "lac", "San Diego Chargers": "sdg",
    "Dallas Cowboys": "dal", "New York Giants": "nyg",
    "Philadelphia Eagles": "phi",
    "Washington Commanders": "was", "Washington Football Team": "was",
    "Washington Redskins": "was",
    "Chicago Bears": "chi", "Detroit Lions": "det",
    "Green Bay Packers": "gnb", "Minnesota Vikings": "min",
    "Atlanta Falcons": "atl", "Carolina Panthers": "car",
    "New Orleans Saints": "nor", "Tampa Bay Buccaneers": "tam",
    "Arizona Cardinals": "crd", "Phoenix Cardinals": "crd",
    "St. Louis Cardinals": "crd", "Chicago Cardinals": "crd",
    "Los Angeles Rams": "ram", "St. Louis Rams": "ram",
    "San Francisco 49ers": "sfo", "Seattle Seahawks": "sea",
    "Boston Yanks": "bos", "Brooklyn Dodgers": "brk",
}

# ── Named targeted players (interior LB, changed teams at least once) ─────────
TARGETED_PLAYERS = [
    ("London Fletcher",   ["Fletcher", "London"]),
    ("Bobby Wagner",      ["Wagner",   "Bobby"]),
    ("Zach Thomas",       ["Thomas",   "Zach"]),
    ("Paul Posluszny",    ["Posluszny","Paul"]),
    ("C.J. Mosley",       ["Mosley",   "C.J.", "CJ"]),
    ("NaVorro Bowman",    ["Bowman",   "NaVorro"]),
    ("Blake Martinez",    ["Martinez", "Blake"]),
    ("D'Qwell Jackson",   ["Jackson",  "DQwell", "D'Qwell"]),
    ("Chris Spielman",    ["Spielman", "Chris"]),
    ("Donnie Edwards",    ["Edwards",  "Donnie"]),
    ("Daryl Smith",       ["Smith",    "Daryl"]),
    ("Jon Beason",        ["Beason",   "Jon"]),
    ("Foyesade Oluokun",  ["Oluokun",  "Foye"]),
    ("Curtis Lofton",     ["Lofton",   "Curtis"]),
    ("Eric Kendricks",    ["Kendricks","Eric"]),
]

# ── Player ID overrides (disambiguation) ─────────────────────────────────────
PLAYER_ID_OVERRIDES = {
    "Daryl Smith":    "SmitDa24",
    "Donnie Edwards": "EdwaDo20",
    "Jon Beason":     "BeasJo99",
    "C.J. Mosley":    "MoslC.00",
    "D'Qwell Jackson":"JackDQ20",
}


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────────────────

def is_interior_lb(pos: str) -> bool:
    if not isinstance(pos, str):
        return False
    parts = set(pos.replace("/", " ").replace("-", " ").split())
    return bool(parts & INTERIOR_LB) and not bool(parts & EDGE_LABELS)


def load_and_prep() -> pd.DataFrame:
    full = pd.read_parquet(GOLD_PATH)
    full["is_ilb"] = full["pos"].apply(is_interior_lb)
    full = full[full["is_ilb"] & full["comb_tackles"].notna()].copy()

    # Apply game threshold first
    df = full[full["g"] >= MIN_GAMES].copy()

    # Era-normalized z-score of combined tackles within each season
    df["tk_zscore"] = df.groupby("season")["comb_tackles"].transform(
        lambda x: (x - x.mean()) / (x.std() if x.std() > 0 else 1.0)
    )
    df["sched_g"] = df["season"].map(STRIKE_SEASONS).fillna(16).astype(int)
    df["tk_per_g"] = df["comb_tackles"] / df["g"]

    # Team total tackles per season
    team_tk = (
        df.groupby(["team_pfref", "season"])["comb_tackles"]
        .sum()
        .reset_index()
        .rename(columns={"comb_tackles": "team_total_tk"})
    )
    df = df.merge(team_tk, on=["team_pfref", "season"], how="left")
    df["tk_share"] = df["comb_tackles"] / df["team_total_tk"]

    # Team-change detection from qualifying seasons only (≥8g), allowing
    # multi-year gaps (injury, opt-out, suspension) up to 4 seasons.
    df = df.sort_values(["player_id", "season"])
    df["prev_team"]   = df.groupby("player_id")["team_pfref"].shift(1)
    df["prev_season"] = df.groupby("player_id")["season"].shift(1)
    df["is_change"] = (
        (df["team_pfref"] != df["prev_team"]) &
        df["prev_team"].notna() &
        (df["season"] - df["prev_season"] <= 4)
    )

    return df


def load_rush_defense_ranks() -> pd.DataFrame:
    """
    Loads rushing_YYYY.csv files.
    Returns DataFrame indexed by (pfr_abbrev, season) with:
      rush_yds_per_g   — opponent rushing yards per game allowed
      rush_def_rank    — rank 1 = fewest rush yards allowed (best run defense)
      n_teams          — number of teams ranked that season
    """
    frames = []
    for csv_file in sorted(RUSH_DIR.glob("rushing_*.csv")):
        season = int(csv_file.stem.split("_")[1])
        df = pd.read_csv(csv_file, low_memory=False)
        df["season"] = season
        df["pfr_abbrev"] = df["team"].map(TEAM_NAME_TO_PFR)
        frames.append(df[["season", "pfr_abbrev", "rush_yds", "rush_yds_per_g", "ranker"]])

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.dropna(subset=["pfr_abbrev"])
    all_df["rush_yds"] = pd.to_numeric(all_df["rush_yds"], errors="coerce")

    # Rank: 1 = fewest rush yards allowed = best run defense
    all_df["rush_def_rank"] = (
        all_df.groupby("season")["rush_yds"]
        .rank(ascending=True, method="min")
        .astype("Int64")
    )
    all_df["n_teams"] = all_df.groupby("season")["pfr_abbrev"].transform("count")
    all_df = all_df.rename(columns={"ranker": "rush_yds_rank_orig"})
    return all_df.set_index(["pfr_abbrev", "season"])


def load_total_defense_ranks() -> pd.DataFrame:
    """
    Loads team history CSVs for total defense rank, points rank, and SOS.
    Returns DataFrame indexed by (pfr_abbrev, season).
    """
    abbrev_map = pd.read_csv(Path.home() / "data/pfref/franchise_abbrev_map.csv")
    dir_to_name = (
        abbrev_map.drop_duplicates("directory")
        .set_index("directory")["canonical_name"]
        .to_dict()
    )
    dir_to_abbrev = {
        d: TEAM_NAME_TO_PFR[name]
        for d, name in dir_to_name.items()
        if name in TEAM_NAME_TO_PFR
    }

    frames = []
    for csv_file in sorted(HIST_DIR.glob("*.csv")):
        abbrev = dir_to_abbrev.get(csv_file.stem)
        if not abbrev:
            continue
        d = pd.read_csv(csv_file, low_memory=False)
        d["pfr_abbrev"] = abbrev
        d = d.rename(columns={"year": "season"})
        keep = ["season", "pfr_abbrev", "def_yds_rank", "def_pts_rank",
                "number_teams", "sos", "dsrs"]
        frames.append(d[[c for c in keep if c in d.columns]])

    all_df = pd.concat(frames, ignore_index=True)
    all_df["season"] = pd.to_numeric(all_df["season"], errors="coerce")
    all_df = all_df.dropna(subset=["season", "pfr_abbrev"])
    all_df["season"] = all_df["season"].astype(int)
    return all_df.set_index(["pfr_abbrev", "season"])


# ─────────────────────────────────────────────────────────────────────────────
# TIER CLASSIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def classify_mlbs(df: pd.DataFrame) -> pd.DataFrame:
    career = df.groupby("player_id").agg(
        player_name=("player_name", "first"),
        n_seasons=("season", "count"),
        career_avg_tk=("comb_tackles", "mean"),
        career_avg_z=("tk_zscore", "mean"),
        n_z15=("tk_zscore", lambda x: (x >= 1.5).sum()),
        n_z10=("tk_zscore", lambda x: (x >= 1.0).sum()),
        career_peak_tk=("comb_tackles", "max"),
        first_season=("season", "min"),
        last_season=("season", "max"),
        teams=("team_pfref", lambda x: "/".join(sorted(set(x)))),
    ).reset_index()

    career["is_tier1"] = (
        (career["career_avg_z"] >= TIER1_Z_MIN) &
        (career["n_seasons"] >= TIER1_MIN_SEASONS)
    )
    career["is_tier2"] = (
        (career["career_avg_z"] >= TIER2_Z_MIN) &
        (career["n_z15"] >= TIER2_Z_SEASONS)
    )
    career["tier"] = "Sub-Elite"
    career.loc[career["is_tier1"], "tier"] = "Elite"
    career.loc[career["is_tier2"], "tier"] = "Truly Elite"

    return career


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def fmt(val, dec=2, sign=False) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "N/A"
    fmt_str = f"{'+' if sign else ''}{val:.{dec}f}"
    return fmt_str


def _rk(rank, n_teams) -> str:
    if rank is None or n_teams is None:
        return "N/A"
    return f"#{rank} of {n_teams}"


def team_rush_lookup_fn(rush_lkp: pd.DataFrame):
    """Returns a function: (team_upper, season) → (rush_yds_per_g, rush_def_rank, n_teams)."""
    def get(team, season):
        try:
            key = (str(team).lower(), int(season))
            r = rush_lkp.loc[key]
            rk = r["rush_def_rank"]
            n  = r["n_teams"]
            return r["rush_yds_per_g"], int(rk) if pd.notna(rk) else None, int(n) if pd.notna(n) else None
        except (KeyError, TypeError, ValueError):
            return None, None, None
    return get


def team_total_def_lookup_fn(tot_lkp: pd.DataFrame):
    """Returns a function: (team_upper, season) → (def_yds_rank, def_pts_rank, n_teams, sos)."""
    def get(team, season):
        try:
            key = (str(team).lower(), int(season))
            r = tot_lkp.loc[key]
            dy = r.get("def_yds_rank") if "def_yds_rank" in r else None
            dp = r.get("def_pts_rank") if "def_pts_rank" in r else None
            nt = r.get("number_teams") if "number_teams" in r else None
            so = r.get("sos") if "sos" in r else None
            return (
                int(dy) if pd.notna(dy) else None,
                int(dp) if pd.notna(dp) else None,
                int(nt) if pd.notna(nt) else None,
                float(so) if pd.notna(so) else None,
            )
        except (KeyError, TypeError, ValueError):
            return None, None, None, None
    return get


# ─────────────────────────────────────────────────────────────────────────────
# YEAR-OVER-YEAR RELIABILITY
# ─────────────────────────────────────────────────────────────────────────────

def yoy_reliability(df: pd.DataFrame, tier_ids: set, tier2_ids: set) -> dict:
    """Compute YoY tackle correlation and CV for elite MLBs."""
    elite = df[df["player_id"].isin(tier_ids)].copy()

    pairs_all, pairs_t2 = [], []
    for pid, grp in elite.sort_values("season").groupby("player_id"):
        grp = grp.sort_values("season")
        is_t2 = pid in tier2_ids
        for i in range(len(grp) - 1):
            r0, r1 = grp.iloc[i], grp.iloc[i + 1]
            if r1["season"] - r0["season"] == 1 and r1["season"] not in STRIKE_SEASONS:
                entry = {"pid": pid, "tk0": r0["comb_tackles"], "tk1": r1["comb_tackles"]}
                pairs_all.append(entry)
                if is_t2:
                    pairs_t2.append(entry)

    pa = pd.DataFrame(pairs_all)
    pt = pd.DataFrame(pairs_t2)

    r_all = pa[["tk0", "tk1"]].corr().iloc[0, 1] if len(pa) >= 5 else np.nan
    r_t2  = pt[["tk0", "tk1"]].corr().iloc[0, 1] if len(pt) >= 5 else np.nan

    # CV per player
    cv_rows = []
    for pid, grp in elite[elite["g"] >= MIN_GAMES].groupby("player_id"):
        tk = grp["comb_tackles"].values
        if len(tk) >= 4:
            cv = tk.std() / tk.mean() if tk.mean() > 0 else np.nan
            cv_rows.append({
                "pid": pid, "name": grp["player_name"].iloc[0],
                "tier": "T2" if pid in tier2_ids else "T1",
                "n_seasons": len(tk), "mean_tk": tk.mean(),
                "std_tk": tk.std(), "cv": cv,
                "min_tk": tk.min(), "max_tk": tk.max(),
            })
    cv_df = pd.DataFrame(cv_rows)

    return {
        "r_all": r_all, "n_pairs_all": len(pa),
        "r_t2": r_t2,  "n_pairs_t2": len(pt),
        "cv_df": cv_df,
    }


# ─────────────────────────────────────────────────────────────────────────────
# TEAM-CHANGE WOWY
# ─────────────────────────────────────────────────────────────────────────────

def analyze_one_mlb(df: pd.DataFrame, label: str, search_terms: list,
                    get_rush, get_tot, tiers: pd.DataFrame) -> dict:
    """
    Find this player in the gold, return career table + team-change analysis.
    """
    # Locate player
    pid_override = PLAYER_ID_OVERRIDES.get(label)
    if pid_override:
        primary = df[df["player_id"] == pid_override]
    else:
        mask = df["player_name"].str.contains(search_terms[0], case=False, na=False)
        for term in search_terms[1:]:
            mask &= df["player_name"].str.contains(term, case=False, na=False)
        primary = df[mask]

    if primary.empty:
        return {"label": label, "error": "not found"}

    # Use most-common player_id if multiple matches
    pid = primary["player_id"].value_counts().index[0]
    primary = df[df["player_id"] == pid].copy().sort_values("season")

    tier_row = tiers[tiers["player_id"] == pid]
    tier = tier_row["tier"].iloc[0] if not tier_row.empty else "Unclassified"
    career_avg_z = tier_row["career_avg_z"].iloc[0] if not tier_row.empty else np.nan

    # Career table
    ct = primary[["season", "team_pfref", "comb_tackles", "g", "tk_per_g",
                  "tk_zscore", "tk_share", "team_total_tk"]].copy()
    ct = ct.rename(columns={"team_pfref": "team", "team_total_tk": "team_total_tk"})

    # Team changes
    changes = []
    for _, row in primary[primary["is_change"]].iterrows():
        old_team  = row["prev_team"]
        new_team  = row["team_pfref"]
        arr_year  = int(row["season"])
        player_tk = row["comb_tackles"]
        player_g  = row["g"]

        # ── Rush defense ranks ────────────────────────────────────────────────
        nt_rush_ypg_bef, nt_rush_rk_bef, nt_n_rush = get_rush(new_team, arr_year - 1)
        nt_rush_ypg_arr, nt_rush_rk_arr, _         = get_rush(new_team, arr_year)
        ot_rush_ypg_wit, ot_rush_rk_wit, ot_n_rush = get_rush(old_team, arr_year - 1)
        ot_rush_ypg_aft, ot_rush_rk_aft, _         = get_rush(old_team, arr_year)

        # ── Total defense + points ranks ──────────────────────────────────────
        nt_tdy_bef, nt_pts_bef, nt_n_tot, nt_sos = get_tot(new_team, arr_year - 1)
        nt_tdy_arr, nt_pts_arr, _,         _      = get_tot(new_team, arr_year)
        ot_tdy_wit, ot_pts_wit, ot_n_tot, ot_sos = get_tot(old_team, arr_year - 1)
        ot_tdy_aft, ot_pts_aft, _,         _      = get_tot(old_team, arr_year)

        # ── Rush rank deltas (positive = improved, lower rank number = better) ─
        rush_rank_delta_nt = (
            (nt_rush_rk_bef - nt_rush_rk_arr)
            if nt_rush_rk_bef is not None and nt_rush_rk_arr is not None
            else None
        )
        rush_rank_delta_ot = (
            (ot_rush_rk_wit - ot_rush_rk_aft)
            if ot_rush_rk_wit is not None and ot_rush_rk_aft is not None
            else None
        )

        # ── Rush yards per game delta ─────────────────────────────────────────
        rush_ypg_delta_nt = (
            (nt_rush_ypg_bef - nt_rush_ypg_arr)  # positive = fewer yards = better
            if nt_rush_ypg_bef is not None and nt_rush_ypg_arr is not None
            else None
        )

        # ── Total defense rank deltas ─────────────────────────────────────────
        tot_rank_delta_nt = (
            (nt_tdy_bef - nt_tdy_arr)
            if nt_tdy_bef is not None and nt_tdy_arr is not None
            else None
        )

        # Player age
        age_rows = primary[primary["season"] == arr_year]["age"]
        player_age = age_rows.iloc[0] if not age_rows.empty else np.nan

        changes.append({
            "old_team": old_team, "new_team": new_team,
            "arrival_season": arr_year,
            "player_age": player_age,
            "player_tk": player_tk,
            "player_tk_per_g": player_tk / player_g if player_g else np.nan,
            "player_zscore": row["tk_zscore"],

            # Gaining team rush defense
            "nt_rush_ypg_before":  nt_rush_ypg_bef,
            "nt_rush_rk_before":   nt_rush_rk_bef,
            "nt_rush_ypg_arrival": nt_rush_ypg_arr,
            "nt_rush_rk_arrival":  nt_rush_rk_arr,
            "nt_rush_rank_delta":  rush_rank_delta_nt,
            "nt_rush_ypg_delta":   rush_ypg_delta_nt,
            "nt_n_teams":          nt_n_rush,
            "nt_sos":              nt_sos,

            # Gaining team total defense
            "nt_tot_yds_rk_before":  nt_tdy_bef,
            "nt_tot_yds_rk_arrival": nt_tdy_arr,
            "nt_pts_rk_before":      nt_pts_bef,
            "nt_pts_rk_arrival":     nt_pts_arr,
            "nt_tot_rank_delta":     tot_rank_delta_nt,
            "nt_n_teams_tot":        nt_n_tot,

            # Losing team rush defense
            "ot_rush_ypg_with":   ot_rush_ypg_wit,
            "ot_rush_rk_with":    ot_rush_rk_wit,
            "ot_rush_ypg_after":  ot_rush_ypg_aft,
            "ot_rush_rk_after":   ot_rush_rk_aft,
            "ot_rush_rank_delta": rush_rank_delta_ot,
            "ot_n_teams":         ot_n_rush,
            "ot_sos":             ot_sos,

            # Losing team total defense
            "ot_tot_yds_rk_with":  ot_tdy_wit,
            "ot_tot_yds_rk_after": ot_tdy_aft,
            "ot_pts_rk_with":      ot_pts_wit,
            "ot_pts_rk_after":     ot_pts_aft,
        })

    return {
        "label": label, "player_id": pid, "tier": tier,
        "career_avg_z": round(career_avg_z, 3) if not np.isnan(career_avg_z) else "N/A",
        "career_table": ct,
        "changes": changes,
    }


def run_targeted_wowy(df: pd.DataFrame, rush_lkp: pd.DataFrame,
                      tot_lkp: pd.DataFrame, tiers: pd.DataFrame) -> list:
    get_rush = team_rush_lookup_fn(rush_lkp)
    get_tot  = team_total_def_lookup_fn(tot_lkp)
    results = []
    for label, terms in TARGETED_PLAYERS:
        r = analyze_one_mlb(df, label, terms, get_rush, get_tot, tiers)
        n_ch = len(r.get("changes", []))
        if "error" in r:
            print(f"  {label:<24} NOT FOUND")
        else:
            print(f"  {label:<24} ({r['player_id']})  [{r['tier']}]  {n_ch} team change(s)")
        results.append(r)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# AGGREGATE WOWY (all Tier 1+ who changed teams)
# ─────────────────────────────────────────────────────────────────────────────

def aggregate_team_change_wowy(df: pd.DataFrame, elite_ids: set,
                                rush_lkp: pd.DataFrame,
                                tot_lkp: pd.DataFrame) -> pd.DataFrame:
    get_rush = team_rush_lookup_fn(rush_lkp)
    get_tot  = team_total_def_lookup_fn(tot_lkp)
    rows = []
    elite = df[df["player_id"].isin(elite_ids)]

    for _, row in elite[elite["is_change"]].iterrows():
        pid      = row["player_id"]
        old_team = row["prev_team"]
        new_team = row["team_pfref"]
        yr       = int(row["season"])

        _, nt_rush_rk_bef, nt_n = get_rush(new_team, yr - 1)
        _, nt_rush_rk_arr, _    = get_rush(new_team, yr)
        nt_tdy_bef, _, nt_nt, _ = get_tot(new_team, yr - 1)
        nt_tdy_arr, _, _, _     = get_tot(new_team, yr)

        rush_delta = (
            (nt_rush_rk_bef - nt_rush_rk_arr)
            if nt_rush_rk_bef is not None and nt_rush_rk_arr is not None
            else np.nan
        )
        tot_delta = (
            (nt_tdy_bef - nt_tdy_arr)
            if nt_tdy_bef is not None and nt_tdy_arr is not None
            else np.nan
        )

        rows.append({
            "player_id": pid,
            "player_name": row["player_name"],
            "season": yr,
            "old_team": old_team,
            "new_team": new_team,
            "player_tk": row["comb_tackles"],
            "player_zscore": row["tk_zscore"],
            "nt_rush_rk_before":  nt_rush_rk_bef,
            "nt_rush_rk_arrival": nt_rush_rk_arr,
            "rush_rank_delta":    rush_delta,
            "nt_tot_rk_before":   nt_tdy_bef,
            "nt_tot_rk_arrival":  nt_tdy_arr,
            "tot_rank_delta":     tot_delta,
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# INJURY WOWY (season-level)
# ─────────────────────────────────────────────────────────────────────────────

def injury_wowy_season(df: pd.DataFrame, elite_ids: set,
                       rush_lkp: pd.DataFrame) -> pd.DataFrame:
    """
    For each elite MLB who missed significant time in a season, compare the
    team's rush yards/g allowed in that season vs their healthy-season baseline.
    """
    get_rush = team_rush_lookup_fn(rush_lkp)
    rows = []
    elite = df[df["player_id"].isin(elite_ids)].copy()

    for pid, grp in elite.groupby("player_id"):
        grp = grp.sort_values("season")
        for _, row in grp.iterrows():
            yr    = int(row["season"])
            team  = row["team_pfref"]
            g     = row["g"]
            sched = int(STRIKE_SEASONS.get(yr, 16))
            if yr in STRIKE_SEASONS:
                continue
            pct = g / sched

            # Healthy baseline: same team, same player, seasons with ≥90% games
            baseline_seasons = grp[
                (grp["team_pfref"] == team) &
                (grp["g"] / grp["sched_g"] >= 0.90) &
                (grp["season"] != yr)
            ]
            if len(baseline_seasons) < 2:
                continue

            # Rush yards/g for injury year vs baseline
            rush_inj_ypg, _, _ = get_rush(team, yr)
            rush_base_ypg = np.mean([
                get_rush(team, int(s))[0]
                for s in baseline_seasons["season"]
                if get_rush(team, int(s))[0] is not None
            ]) if True else None
            if rush_inj_ypg is None or rush_base_ypg is None:
                continue

            # Only report seasons where player missed ≥25% of games
            if pct >= 0.75:
                continue

            rows.append({
                "player_id": pid,
                "player_name": row["player_name"],
                "season": yr,
                "team": team,
                "g_played": g,
                "g_schedule": sched,
                "pct_played": round(pct, 2),
                "rush_ypg_injury_yr": rush_inj_ypg,
                "rush_ypg_baseline":  rush_base_ypg,
                "rush_ypg_delta":     rush_inj_ypg - rush_base_ypg,  # + = worse when absent
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# PRINT FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def print_targeted_results(results: list) -> str:
    lines = []
    lines.append("\n" + "=" * 76)
    lines.append("TARGETED TEAM-CHANGE WOWY — ELITE INTERIOR LINEBACKERS")
    lines.append("=" * 76)
    lines.append(
        "\nOutcome variables (all are RANKS — lower number = better defense):"
        "\n  rush_def_rank   = rush yards allowed rank among all teams (1 = fewest)"
        "\n  tot_def_rank    = total yards allowed rank (1 = fewest)"
        "\n  pts_def_rank    = points allowed rank (1 = fewest)"
        "\n  rush_ypg delta  = change in opp rush yds/g (negative = improvement)"
        "\n  SOS             = strength of schedule proxy for OQA"
    )

    for r in results:
        if "error" in r:
            lines.append(f"\n{r['label']}: NOT FOUND")
            continue

        label = r["label"]
        lines.append(f"\n{'─'*76}")
        lines.append(
            f"{label.upper()}  ({r['player_id']})  [{r['tier']}]  "
            f"career avg z-score: {r['career_avg_z']}"
        )

        ct = r["career_table"]
        lines.append(
            "\n  Season  Team  CombTk   g  tk/g  z-score  TkShare  TeamTotalTk"
        )
        for _, row in ct.iterrows():
            tpg  = f"{row['tk_per_g']:.1f}" if pd.notna(row['tk_per_g']) else " N/A"
            z    = f"{row['tk_zscore']:+.2f}" if pd.notna(row['tk_zscore']) else "  N/A"
            shr  = f"{row['tk_share']:.3f}" if pd.notna(row['tk_share']) else "  N/A"
            ttk  = f"{row['team_total_tk']:.0f}" if pd.notna(row['team_total_tk']) else "N/A"
            lines.append(
                f"  {int(row['season'])}   {row['team'].upper():<5} "
                f"{row['comb_tackles']:5.0f}  {row['g']:3.0f}  {tpg}  "
                f"{z}    {shr}    {ttk}"
            )

        if not r["changes"]:
            lines.append("\n  (No consecutive-season team changes detected)")
            continue

        for ch in r["changes"]:
            old = ch["old_team"].upper()
            new = ch["new_team"].upper()
            yr  = ch["arrival_season"]
            age = f", age {int(ch['player_age'])}" if pd.notna(ch.get("player_age")) else ""
            lines.append(
                f"\n  ▶ MOVE: {old} → {new}  ({yr}{age})"
                f"  player: {ch['player_tk']:.0f} tk  "
                f"({ch['player_tk_per_g']:.1f}/g)  z={ch['player_zscore']:+.2f}"
            )

            # ── Gaining team ──────────────────────────────────────────────────
            n_r = ch.get("nt_n_teams")
            n_t = ch.get("nt_n_teams_tot")
            lines.append(f"\n    GAINING TEAM ({new}):")
            lines.append(
                f"      Year {yr-1} BEFORE : "
                f"rush rank {_rk(ch.get('nt_rush_rk_before'), n_r)}  "
                f"({fmt(ch.get('nt_rush_ypg_before'))} rush yds/g)  "
                f"| tot rank {_rk(ch.get('nt_tot_yds_rk_before'), n_t)}  "
                f"pts rank {_rk(ch.get('nt_pts_rk_before'), n_t)}"
            )
            lines.append(
                f"      Year {yr}  ARRIVAL: "
                f"rush rank {_rk(ch.get('nt_rush_rk_arrival'), n_r)}  "
                f"({fmt(ch.get('nt_rush_ypg_arrival'))} rush yds/g)  "
                f"| tot rank {_rk(ch.get('nt_tot_yds_rk_arrival'), n_t)}  "
                f"pts rank {_rk(ch.get('nt_pts_rk_arrival'), n_t)}  "
                f"SOS={fmt(ch.get('nt_sos'), sign=True)}"
            )
            rd = ch.get("nt_rush_rank_delta")
            yd = ch.get("nt_rush_ypg_delta")
            td = ch.get("nt_tot_rank_delta")
            lines.append(
                f"        rush rank Δ: {fmt(rd, 0, sign=True) if rd is not None else 'N/A':>7} spots  "
                f"rush yds/g Δ: {fmt(yd, 1, sign=False) if yd is not None else 'N/A':>6} yds  "
                f"tot rank Δ: {fmt(td, 0, sign=True) if td is not None else 'N/A':>7} spots  "
                f"(+spots = improved)"
            )

            # ── Losing team ───────────────────────────────────────────────────
            no_r = ch.get("ot_n_teams")
            no_t = ch.get("nt_n_teams_tot")
            lines.append(f"\n    LOSING TEAM ({old}):")
            lines.append(
                f"      Year {yr-1} WITH star : "
                f"rush rank {_rk(ch.get('ot_rush_rk_with'), no_r)}  "
                f"({fmt(ch.get('ot_rush_ypg_with'))} rush yds/g)  "
                f"| tot rank {_rk(ch.get('ot_tot_yds_rk_with'), no_t)}"
            )
            lines.append(
                f"      Year {yr}  AFTER star : "
                f"rush rank {_rk(ch.get('ot_rush_rk_after'), no_r)}  "
                f"({fmt(ch.get('ot_rush_ypg_after'))} rush yds/g)  "
                f"| tot rank {_rk(ch.get('ot_tot_yds_rk_after'), no_t)}  "
                f"SOS={fmt(ch.get('ot_sos'), sign=True)}"
            )
            ord_ = ch.get("ot_rush_rank_delta")
            lines.append(
                f"        rush rank Δ: {fmt(ord_, 0, sign=True) if ord_ is not None else 'N/A':>7} spots  "
                f"(+pos = run D improved without star — no dependency)"
            )

    return "\n".join(lines)


def print_aggregate_summary(tc: pd.DataFrame, rel: dict,
                             inj: pd.DataFrame, tiers: pd.DataFrame) -> str:
    lines = []

    # ── Tier summary ──────────────────────────────────────────────────────────
    t2 = tiers[tiers["is_tier2"]]
    t1 = tiers[tiers["is_tier1"] & ~tiers["is_tier2"]]
    lines.append("\n" + "=" * 70)
    lines.append("SUMMARY: ELITE MLB ANALYSIS")
    lines.append("=" * 70)
    lines.append(f"\nTier 2 (Truly Elite) — {len(t2)} players "
                 f"(career avg z ≥ {TIER2_Z_MIN}, {TIER2_Z_SEASONS}+ seasons at z ≥ {TIER2_Z_MIN}):")
    for _, r in t2.sort_values("career_avg_z", ascending=False).iterrows():
        lines.append(
            f"  {r['player_name']:<22} {r['player_id']}  "
            f"avg_z={r['career_avg_z']:.2f}  avg_tk={r['career_avg_tk']:.0f}  "
            f"n_z15={r['n_z15']:.0f}  "
            f"({int(r['first_season'])}–{int(r['last_season'])})"
        )

    # ── YoY reliability ───────────────────────────────────────────────────────
    lines.append(f"\n{'─'*70}")
    lines.append("YEAR-OVER-YEAR TACKLE RELIABILITY")
    lines.append(
        f"  All Tier 1+: r = {rel['r_all']:.3f}  (n={rel['n_pairs_all']} consecutive-season pairs)"
    )
    lines.append(
        f"  Tier 2 only: r = {rel['r_t2']:.3f}  (n={rel['n_pairs_t2']} pairs)"
    )
    cv_df = rel["cv_df"]
    lines.append(f"\n  Avg CV — Tier 2:       {cv_df[cv_df['tier']=='T2']['cv'].mean():.3f}")
    lines.append(f"  Avg CV — Tier 1 only:  {cv_df[cv_df['tier']=='T1']['cv'].mean():.3f}")
    lines.append("\n  Most consistent Tier 2 MLBs (lowest CV):")
    for _, r in cv_df[cv_df["tier"]=="T2"].sort_values("cv").head(8).iterrows():
        lines.append(
            f"    {r['name']:<22} CV={r['cv']:.3f}  mean={r['mean_tk']:.0f}  "
            f"range=[{r['min_tk']:.0f},{r['max_tk']:.0f}]  n={r['n_seasons']:.0f}seasons"
        )

    # ── Aggregate team-change WOWY ────────────────────────────────────────────
    lines.append(f"\n{'─'*70}")
    lines.append("AGGREGATE TEAM-CHANGE WOWY (all Tier 1+ who changed teams)")
    valid_r = tc.dropna(subset=["rush_rank_delta"])
    valid_t = tc.dropna(subset=["tot_rank_delta"])
    if len(valid_r) > 0:
        lines.append(f"  Cases with rush rank data: {len(valid_r)}")
        lines.append(f"  Avg rush defense rank BEFORE arrival: {valid_r['nt_rush_rk_before'].mean():.1f}")
        lines.append(f"  Avg rush defense rank AFTER  arrival: {valid_r['nt_rush_rk_arrival'].mean():.1f}")
        lines.append(f"  Avg rush rank improvement: {valid_r['rush_rank_delta'].mean():.1f} spots  (+ = improved)")
        lines.append(f"  % gaining teams that improved rush rank: {(valid_r['rush_rank_delta'] > 0).mean()*100:.0f}%")
    if len(valid_t) > 0:
        lines.append(f"\n  Cases with total def rank data: {len(valid_t)}")
        lines.append(f"  Avg total def rank BEFORE: {valid_t['nt_tot_rk_before'].mean():.1f}")
        lines.append(f"  Avg total def rank AFTER : {valid_t['nt_tot_rk_arrival'].mean():.1f}")
        lines.append(f"  Avg total rank improvement: {valid_t['tot_rank_delta'].mean():.1f} spots")
        lines.append(f"  % that improved total def rank: {(valid_t['tot_rank_delta'] > 0).mean()*100:.0f}%")

    # ── Injury WOWY ───────────────────────────────────────────────────────────
    if len(inj) > 0:
        lines.append(f"\n{'─'*70}")
        lines.append(f"INJURY WOWY — SEASON LEVEL  ({len(inj)} cases, missing ≥25% of games)")
        lines.append("  rush_ypg_delta > 0 means MORE rush yards allowed when star was hurt")
        inj_s = inj.sort_values("rush_ypg_delta", ascending=False)
        for _, r in inj_s.head(10).iterrows():
            lines.append(
                f"  {r['player_name']:<22} {int(r['season'])} {r['team'].upper()}  "
                f"({int(r['g_played'])}g played)  "
                f"rush Δ: {r['rush_ypg_delta']:+.1f} yds/g  "
                f"({r['rush_ypg_injury_yr']:.1f} injured vs {r['rush_ypg_baseline']:.1f} baseline)"
            )
        lines.append("  ...")
        for _, r in inj_s.tail(5).iterrows():
            lines.append(
                f"  {r['player_name']:<22} {int(r['season'])} {r['team'].upper()}  "
                f"({int(r['g_played'])}g played)  "
                f"rush Δ: {r['rush_ypg_delta']:+.1f} yds/g"
            )

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading gold parquet (interior LBs only)...")
    df = load_and_prep()
    print(f"  {len(df):,} rows  ({int(df['season'].min())}–{int(df['season'].max())})")
    print(f"  {df['player_id'].nunique()} unique interior LBs")

    print("\nClassifying MLB tiers...")
    tiers = classify_mlbs(df)
    tiers.to_csv(RESULTS_DIR / "mlb_tiers.csv", index=False)
    tier1_ids = set(tiers[tiers["is_tier1"]]["player_id"])
    tier2_ids = set(tiers[tiers["is_tier2"]]["player_id"])
    all_elite  = tier1_ids | tier2_ids
    print(f"  Tier 1 (Elite):        {len(tier1_ids)} players")
    print(f"  Tier 2 (Truly Elite):  {len(tier2_ids)} players")

    print("\nLoading rush defense ranks...")
    try:
        rush_lkp = load_rush_defense_ranks()
        print(f"  {len(rush_lkp)} team-season rows")
    except Exception as e:
        print(f"  WARNING: {e}")
        rush_lkp = pd.DataFrame()

    print("Loading total defense ranks (team history)...")
    try:
        tot_lkp = load_total_defense_ranks()
        print(f"  {len(tot_lkp)} team-season rows")
    except Exception as e:
        print(f"  WARNING: {e}")
        tot_lkp = pd.DataFrame()

    print("\n[1] Targeted WOWY for named players...")
    targeted = run_targeted_wowy(df, rush_lkp, tot_lkp, tiers)
    targeted_text = print_targeted_results(targeted)
    flat = []
    for r in targeted:
        if "error" in r or not r["changes"]:
            continue
        for ch in r["changes"]:
            flat.append({"player": r["label"], "tier": r["tier"], **ch})
    if flat:
        pd.DataFrame(flat).to_csv(RESULTS_DIR / "targeted_mlb_wowy.csv", index=False)

    print("\n[2] Aggregate WOWY (all Tier 1+)...")
    tc = aggregate_team_change_wowy(df, all_elite, rush_lkp, tot_lkp)
    tc.to_csv(RESULTS_DIR / "aggregate_mlb_wowy.csv", index=False)
    print(f"  {len(tc)} team-change cases")

    print("\n[3] YoY reliability...")
    rel = yoy_reliability(df, all_elite, tier2_ids)

    print("\n[4] Injury WOWY (season-level)...")
    inj = injury_wowy_season(df, all_elite, rush_lkp)
    inj.sort_values("rush_ypg_delta", ascending=False)\
       .to_csv(RESULTS_DIR / "mlb_injury_wowy_season.csv", index=False)
    print(f"  {len(inj)} injury-season cases")

    agg_text = print_aggregate_summary(tc, rel, inj, tiers)
    full_text = targeted_text + "\n\n" + agg_text
    print(full_text)
    (RESULTS_DIR / "mlb_summary.txt").write_text(full_text)
    print(f"\nAll results written to {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
