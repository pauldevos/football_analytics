#!/usr/bin/env python3
"""
Sack WOWY Analysis  (v2)
=========================
Tests whether elite pass rushers elevate teammate sack production.

Two-tier pass rusher classification:
  Tier 1 — Elite:        career avg >= 7 sk/season (in games ≥8g)
                          OR  5+ seasons with 10+ sacks
  Tier 2 — Truly Elite:  3+ seasons with sk/g >= 0.8

Analyses:
  1. Age curve (Option C): quadratic polynomial across elite rusher career arcs
  2. Targeted team-change WOWY: detailed year-by-year view for 15 named players
  3. Aggregate team-change WOWY: all Tier 1+ players who changed teams
  4. Injury WOWY (season-level): injury years vs healthy years on same team
  5. Injury WOWY (game-level): games started vs games missed within a season
  6. Sack share descriptive stats + paradox test

Usage:
  ~/github/football/media_guide_parser/.venv/bin/python sack_wowy_analysis.py

Outputs to: ~/data/sack_wowy_results/
"""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Paths ─────────────────────────────────────────────────────────────────────
GOLD_PATH     = Path.home() / "data/gold/player_season_card.parquet"
BOXSCORE_BASE = Path.home() / "data/pfref/raw/boxscores"
RESULTS_DIR   = Path.home() / "data/sack_wowy_results"

# ── Tunable constants ─────────────────────────────────────────────────────────
TIER1_CAREER_AVG_SK  = 7.0   # career avg sacks/season (in seasons ≥8g played)
TIER1_MIN_10SK_SEAONS = 5    # OR: at least this many 10+ sack seasons
TIER2_SPG_THRESHOLD  = 0.80  # truly elite: sk/game in a season
TIER2_MIN_SEASONS    = 3     # truly elite: need this many such seasons
INJURY_GAME_PCT      = 0.75  # < 75% of schedule = injury season
MAX_GAME_CASES       = 60

STRIKE_SEASONS = {1982: 9, 1987: 15}

# ── Historical team name → lowercase PFR abbreviation ────────────────────────
# Covers every name variant used in the defense passing CSVs (1950-2025).
TEAM_NAME_TO_PFR = {
    # AFC East
    "Buffalo Bills": "buf", "Miami Dolphins": "mia",
    "New England Patriots": "nwe", "Boston Patriots": "nwe",
    "New York Jets": "nyj", "New York Titans": "nyj",
    # AFC North
    "Baltimore Ravens": "rav", "Cincinnati Bengals": "cin",
    "Cleveland Browns": "cle", "Pittsburgh Steelers": "pit",
    # AFC South
    "Houston Texans": "htx", "Indianapolis Colts": "clt",
    "Baltimore Colts": "clt", "Jacksonville Jaguars": "jax",
    "Tennessee Titans": "ten", "Tennessee Oilers": "ten",
    "Houston Oilers": "oti",
    # AFC West
    "Denver Broncos": "den", "Kansas City Chiefs": "kan",
    "Dallas Texans": "kan",
    "Las Vegas Raiders": "lvr", "Oakland Raiders": "rai",
    "Los Angeles Raiders": "rai",
    "Los Angeles Chargers": "lac", "San Diego Chargers": "sdg",
    # NFC East
    "Dallas Cowboys": "dal", "New York Giants": "nyg",
    "Philadelphia Eagles": "phi",
    "Washington Commanders": "was", "Washington Football Team": "was",
    "Washington Redskins": "was",
    # NFC North
    "Chicago Bears": "chi", "Chicago Cardinals": "crd",
    "Detroit Lions": "det", "Green Bay Packers": "gnb",
    "Minnesota Vikings": "min",
    # NFC South
    "Atlanta Falcons": "atl", "Carolina Panthers": "car",
    "New Orleans Saints": "nor", "Tampa Bay Buccaneers": "tam",
    # NFC West
    "Arizona Cardinals": "crd", "Phoenix Cardinals": "crd",
    "St. Louis Cardinals": "crd",
    "Los Angeles Rams": "ram", "St. Louis Rams": "ram",
    "San Francisco 49ers": "sfo", "Seattle Seahawks": "sea",
    # Defunct / historical
    "Boston Yanks": "bos", "Brooklyn Dodgers": "brk",
    "Buffalo All-Americans": "buf",
    "Card-Pitt": "crd", "Pitt-Phil": "phi",
    "Decatur Staleys": "chi",
    "New York Bulldogs": "nyb", "New York Yanks": "nyy",
    "Portsmouth Spartans": "det",
}

# Confirmed player IDs for ambiguous names
PLAYER_ID_OVERRIDES = {
    "Reggie White":   "WhitRe00",
    "Fred Dean":      "DeanFr00",
    "Sean Jones":     "JoneSe00",
}

# The 15 named players for targeted WOWY (name → search terms)
TARGETED_PLAYERS = [
    ("Chris Doleman",   ["Doleman", "Chris"]),
    ("Reggie White",    ["White",   "Reggie"]),
    ("Julius Peppers",  ["Peppers", "Julius"]),
    ("Jared Allen",     ["Allen",   "Jared"]),
    ("Kevin Greene",    ["Greene",  "Kevin"]),
    ("John Abraham",    ["Abraham", "John"]),
    ("Coy Bacon",       ["Bacon",   "Coy"]),
    ("Simeon Rice",     ["Rice",    "Simeon"]),
    ("Danielle Hunter", ["Hunter",  "Danielle"]),
    ("Fred Dean",       ["Dean",    "Fred"]),
    ("Chandler Jones",  ["Jones",   "Chandler"]),
    ("Sean Jones",      ["Jones",   "Sean"]),
    ("Pat Swilling",    ["Swilling","Pat"]),
    ("William Fuller",  ["Fuller",  "William"]),
    ("Charles Haley",   ["Haley",   "Charles"]),
]


def schedule_length(season: int) -> int:
    if season in STRIKE_SEASONS:
        return STRIKE_SEASONS[season]
    if season >= 2021:
        return 17
    if season >= 1978:
        return 16
    if season >= 1961:
        return 14
    return 12


def pfr_id_from_path(raw: str) -> str:
    return str(raw).split("/")[-1].replace(".htm", "")


# ── Data loading ──────────────────────────────────────────────────────────────

def load_and_prep() -> pd.DataFrame:
    df = pd.read_parquet(GOLD_PATH)
    df = df[df["sk"].notna() & df["g"].notna()].copy()
    df["sk"]     = df["sk"].astype(float)
    df["g"]      = df["g"].astype(float)
    df["season"] = df["season"].astype(int)
    df["schedule_len"] = df["season"].apply(schedule_length)

    # Primary team = most games played that season
    df["_rank"] = df.groupby(["player_id", "season"])["g"].rank(
        method="first", ascending=False
    )
    df["is_primary"] = df["_rank"] == 1
    df.drop(columns=["_rank"], inplace=True)

    # Team sack totals (gold splits multi-team seasons by team row, so sum is correct)
    team_sk = (
        df.groupby(["team_pfref", "season"])["sk"]
        .sum()
        .reset_index(name="team_sk_total")
    )
    df = df.merge(team_sk, on=["team_pfref", "season"], how="left")

    df["team_g"]               = df["schedule_len"]
    df["teammate_sk"]          = df["team_sk_total"] - df["sk"]
    df["sk_per_game"]          = df["sk"] / df["g"]
    df["team_sk_per_game"]     = df["team_sk_total"] / df["team_g"]
    df["teammate_sk_per_game"] = df["teammate_sk"] / df["team_g"]
    df["sack_share"]           = np.where(
        df["team_sk_total"] > 0, df["sk"] / df["team_sk_total"], np.nan
    )
    df["g_pct"]            = df["g"] / df["schedule_len"]
    df["is_injury_season"] = df["g_pct"] < INJURY_GAME_PCT
    df["is_strike_season"] = df["season"].isin(STRIKE_SEASONS)

    return df


# ── Team defense rankings ─────────────────────────────────────────────────────

def load_team_defense_ranks() -> pd.DataFrame:
    """
    Load pass defense rankings from per-season team defense files.

    Returns DataFrame indexed by (pfr_abbrev, season) with:
      pass_sk_total   — official sacks credited to the defense (may differ slightly
                        from gold parquet sum due to scoring-call revisions)
      pass_sk_rank    — sack rank: 1 = most sacks in the league that season
      pass_def_rank   — pass yards allowed rank: 1 = fewest yards (best pass D)
      pass_yds_per_g  — opponent passing yards per game allowed (lower = better)
    """
    PASS_DIR = Path.home() / "data/pfref/raw/season/team/defense/passing"
    frames = []
    for csv_file in sorted(PASS_DIR.glob("passing_*.csv")):
        season = int(csv_file.stem.split("_")[1])
        df = pd.read_csv(csv_file, low_memory=False)
        df["season"] = season
        df["pfr_abbrev"] = df["team"].map(TEAM_NAME_TO_PFR)
        frames.append(df[["season", "pfr_abbrev", "pass_sacked", "ranker", "pass_yds_per_g"]])

    all_df = pd.concat(frames, ignore_index=True)
    all_df = all_df.dropna(subset=["pfr_abbrev"])
    all_df["pass_sacked"] = pd.to_numeric(all_df["pass_sacked"], errors="coerce")

    # Sack rank: 1 = most sacks (best pass rush) within season
    # Only compute rank for seasons where sack data exists (1982+)
    has_sk = all_df["pass_sacked"].notna()
    all_df.loc[has_sk, "pass_sk_rank"] = (
        all_df[has_sk].groupby("season")["pass_sacked"]
        .rank(ascending=False, method="min")
        .astype("Int64")
    )
    all_df["pass_sk_rank"] = all_df["pass_sk_rank"].astype("Int64")
    all_df = all_df.rename(columns={
        "pass_sacked": "pass_sk_total",
        "ranker":      "pass_def_rank",
    })
    return all_df.set_index(["pfr_abbrev", "season"])


def load_team_sos() -> pd.DataFrame:
    """
    Load strength of schedule (SOS) from team history files.
    SOS > 0 means harder schedule; < 0 means easier.
    Returns DataFrame indexed by (pfr_abbrev, season).
    """
    HIST_DIR = Path.home() / "data/pfref/raw/team-history"
    abbrev_map = pd.read_csv(
        Path.home() / "data/pfref/franchise_abbrev_map.csv"
    )
    # Map directory → canonical_name (one per directory, deduped)
    dir_to_name = (
        abbrev_map.drop_duplicates("directory")
        .set_index("directory")["canonical_name"]
        .to_dict()
    )
    # Then canonical_name → pfr_abbrev via TEAM_NAME_TO_PFR (same keys as gold parquet)
    dir_to_abbrev = {
        d: TEAM_NAME_TO_PFR[name]
        for d, name in dir_to_name.items()
        if name in TEAM_NAME_TO_PFR
    }

    frames = []
    for csv_file in sorted(HIST_DIR.glob("*.csv")):
        dir_name = csv_file.stem
        abbrev = dir_to_abbrev.get(dir_name)
        if not abbrev:
            continue
        d = pd.read_csv(csv_file, low_memory=False)
        d["pfr_abbrev"] = abbrev
        d = d.rename(columns={"year": "season"})
        frames.append(d[["season", "pfr_abbrev", "sos", "dsrs"]])

    all_df = pd.concat(frames, ignore_index=True).dropna(subset=["sos"])
    return all_df.set_index(["pfr_abbrev", "season"])




def classify_players(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a player-level summary DataFrame with tier assignments.

    Tier 1 (elite):
      career_avg_sk >= TIER1_CAREER_AVG_SK   (seasons with g >= 8 only)
      OR  n_seasons_10plus >= TIER1_MIN_10SK_SEAONS

    Tier 2 (truly elite):
      n_seasons_08_per_game >= TIER2_MIN_SEASONS   (seasons where sk/g >= TIER2_SPG_THRESHOLD)
    """
    primary = df[df["is_primary"] & ~df["is_strike_season"]].copy()
    primary["spg"] = primary["sk"] / primary["g"]

    grp = primary.groupby("player_id")

    summary = pd.DataFrame(
        {
            "player_name":         grp["player_name"].last(),
            "seasons_played":      grp["season"].count(),
            "career_total_sk":     grp["sk"].sum(),
            "career_peak_sk":      grp["sk"].max(),
            # career avg only in seasons with ≥8g (removes cameos)
            "career_avg_sk": primary[primary["g"] >= 8].groupby("player_id")["sk"].mean(),
            "n_seasons_10plus":    (primary["sk"] >= 10).groupby(primary["player_id"]).sum(),
            "n_seasons_08_spg":    (primary["spg"] >= TIER2_SPG_THRESHOLD).groupby(primary["player_id"]).sum(),
            "first_season":        grp["season"].min(),
            "last_season":         grp["season"].max(),
            "teams":               grp["team_pfref"].apply(lambda x: "/".join(dict.fromkeys(x))),
        }
    ).reset_index()

    summary["career_avg_sk"] = summary["career_avg_sk"].fillna(0)

    summary["tier1_by_avg"]    = summary["career_avg_sk"] >= TIER1_CAREER_AVG_SK
    summary["tier1_by_10seasons"] = summary["n_seasons_10plus"] >= TIER1_MIN_10SK_SEAONS
    summary["is_tier1"]        = summary["tier1_by_avg"] | summary["tier1_by_10seasons"]
    summary["is_tier2"]        = summary["n_seasons_08_spg"] >= TIER2_MIN_SEASONS
    summary["tier"]            = np.select(
        [summary["is_tier2"], summary["is_tier1"]],
        ["Truly Elite", "Elite"],
        default="—",
    )

    return summary.sort_values("career_total_sk", ascending=False)


# ── Age Curve (Option C) ──────────────────────────────────────────────────────

def fit_age_curve(df: pd.DataFrame, tier_ids: set):
    """Quadratic polynomial fit on (age, sacks) for Tier 1+ players."""
    elite = df[df["player_id"].isin(tier_ids) & df["age"].notna()].copy()
    fit_data = elite[elite["is_primary"] & (elite["gs"].fillna(0) >= 6)].copy()

    ages  = fit_data["age"].astype(float).values
    sacks = fit_data["sk"].astype(float).values

    coeffs = np.polyfit(ages, sacks, 2)
    poly   = np.poly1d(coeffs)
    a, b, _ = coeffs
    peak_age = -b / (2 * a) if a < 0 else None

    elite["expected_sk"] = elite["age"].apply(
        lambda a: max(0.0, float(poly(a))) if pd.notna(a) else np.nan
    )
    elite["sk_residual"] = elite["sk"] - elite["expected_sk"]

    curve_table = pd.DataFrame({"age": range(20, 41)})
    curve_table["expected_sk"] = curve_table["age"].apply(
        lambda a: max(0.0, float(poly(a)))
    )
    return elite, poly, peak_age, curve_table


# ── Targeted WOWY (named players) ────────────────────────────────────────────

def resolve_targeted_player(df: pd.DataFrame, label: str, search_terms: list) -> tuple:
    """
    Find the player_id for a named player. Returns (player_id, player_df) or (None, None).
    Handles ID overrides for ambiguous names.
    """
    if label in PLAYER_ID_OVERRIDES:
        pid = PLAYER_ID_OVERRIDES[label]
        sub = df[df["player_id"] == pid]
        return pid, sub

    mask = df["player_name"].str.contains(search_terms[0], na=False)
    for term in search_terms[1:]:
        mask &= df["player_name"].str.contains(term, na=False)
    found = df[mask]
    if found.empty:
        return None, None

    ids = found["player_id"].unique()
    if len(ids) == 1:
        pid = ids[0]
    else:
        # Pick the one with the highest career sacks
        pid = found.groupby("player_id")["sk"].sum().idxmax()

    return pid, found[found["player_id"] == pid]


def team_lookup_fn(df: pd.DataFrame):
    """Returns a fast (team, season) → stats lookup function."""
    tbl = (
        df[["team_pfref", "season", "team_sk_per_game", "team_sk_total", "team_g"]]
        .drop_duplicates(subset=["team_pfref", "season"])
        .set_index(["team_pfref", "season"])
    )
    def lookup(team, season):
        try:
            r = tbl.loc[(team, season)]
            return r["team_sk_per_game"], r["team_sk_total"], r["team_g"]
        except KeyError:
            return None, None, None
    return lookup


def analyze_one_player(df: pd.DataFrame, label: str, search_terms: list,
                        get_ts, rank_lkp, sos_lkp) -> dict:
    """
    Full year-by-year WOWY analysis for one named player across all their team changes.
    Returns dict with player info, career table, and per-change results.
    """
    pid, pdata = resolve_targeted_player(df, label, search_terms)
    if pid is None:
        return {"label": label, "error": "not found"}

    primary = pdata[pdata["is_primary"]].sort_values("season").copy()
    primary["spg"] = primary["sk"] / primary["g"]

    # Detect team changes (consecutive seasons with different primary team)
    primary["prev_team"]   = primary["team_pfref"].shift(1)
    primary["prev_season"] = primary["season"].shift(1)
    primary["is_change"]   = (
        primary["prev_team"].notna()
        & (primary["team_pfref"] != primary["prev_team"])
        & (primary["season"] == primary["prev_season"] + 1)
    )
    # Also flag mid-season moves (same season, two rows)
    midseason = pdata[pdata["is_primary"] == False].copy()

    def get_rank(team, season):
        """Return (sk_rank, pass_def_rank, pass_yds_per_g, n_teams)."""
        try:
            key = (str(team).lower(), int(season))
            r = rank_lkp.loc[key]
            n = rank_lkp.xs(int(season), level="season").shape[0]
            sk_r = r["pass_sk_rank"]
            pd_r = r["pass_def_rank"]
            sk_i = int(sk_r) if pd.notna(sk_r) else None
            pd_i = int(pd_r) if pd.notna(pd_r) else None
            return sk_i, pd_i, r["pass_yds_per_g"], n
        except (KeyError, TypeError, ValueError):
            return None, None, None, None

    def get_sos(team, season):
        """Return (sos, dsrs) for opponent quality context."""
        try:
            key = (str(team).lower(), int(season))
            r = sos_lkp.loc[key]
            return r["sos"], r["dsrs"]
        except (KeyError, TypeError):
            return None, None

    changes = []
    for _, row in primary[primary["is_change"]].iterrows():
        old_team  = row["prev_team"]
        new_team  = row["team_pfref"]
        arr_year  = row["season"]
        player_sk = row["sk"]
        player_g  = row["team_g"]

        # ── Gaining team ──────────────────────────────────────────────────────
        nt_bef_spg, nt_bef_tot, _  = get_ts(new_team, arr_year - 1)
        nt_aft_spg, nt_aft_tot, _  = get_ts(new_team, arr_year)

        # Teammate sacks = total minus star's own (the key "did teammates improve?" number)
        nt_teammate_spg = (nt_aft_tot - player_sk) / player_g if nt_aft_tot is not None else None
        # Player's additive contribution = star's own sacks per schedule game
        nt_star_spg  = player_sk / player_g if player_g else None
        # How much did total team sacks change (includes additive + teammate change)?
        nt_total_delta = (nt_aft_spg - nt_bef_spg) if (nt_aft_spg and nt_bef_spg) else None
        # Teammate-only change vs prior year team total (pure teammate effect)
        nt_lift = (
            (nt_teammate_spg - nt_bef_spg)
            if (nt_teammate_spg is not None and nt_bef_spg is not None)
            else None
        )

        # Ranks for new team
        nt_sk_rank_bef,  nt_pd_rank_bef,  nt_ypg_bef,  nt_n_bef  = get_rank(new_team, arr_year - 1)
        nt_sk_rank_arr,  nt_pd_rank_arr,  nt_ypg_arr,  nt_n_arr   = get_rank(new_team, arr_year)
        nt_sos_arr, nt_dsrs_arr = get_sos(new_team, arr_year)

        # ── Losing team ───────────────────────────────────────────────────────
        star_on_old = primary[(primary["team_pfref"] == old_team) & (primary["season"] == arr_year - 1)]
        star_sk_old = star_on_old["sk"].values[0] if len(star_on_old) else None

        ot_with_spg, ot_with_tot, ot_with_g = get_ts(old_team, arr_year - 1)
        ot_aft_spg, ot_aft_tot, _            = get_ts(old_team, arr_year)

        # Old team: what teammates were getting while star was there
        ot_teammate_spg_with = (
            (ot_with_tot - star_sk_old) / ot_with_g
            if (ot_with_tot is not None and star_sk_old is not None and ot_with_g)
            else None
        )
        # Old team total change: year with star → year without star (all team sacks, apples to apples)
        ot_total_delta = (ot_aft_spg - ot_with_spg) if (ot_aft_spg and ot_with_spg) else None
        # Teammate-only drag: after departure vs teammate rate while star was there
        ot_drag = (
            (ot_aft_spg - ot_teammate_spg_with)
            if (ot_aft_spg is not None and ot_teammate_spg_with is not None)
            else None
        )

        # Ranks for old team
        ot_sk_rank_with, ot_pd_rank_with, ot_ypg_with, ot_n_with = get_rank(old_team, arr_year - 1)
        ot_sk_rank_aft,  ot_pd_rank_aft,  ot_ypg_aft,  _         = get_rank(old_team, arr_year)
        ot_sos_aft, ot_dsrs_aft = get_sos(old_team, arr_year)

        changes.append(
            {
                "arrival_season":          arr_year,
                "player_age":              row.get("age"),
                "player_sk":               player_sk,
                "player_spg":              row["spg"],
                "old_team":                old_team,
                "new_team":                new_team,
                # ── Gaining team ───────────────────────────────────────────
                "nt_total_spg_before":     nt_bef_spg,    # year N-1: all team sk/g (no star)
                "nt_total_spg_arrival":    nt_aft_spg,    # year N:   all team sk/g (with star)
                "nt_star_spg":             nt_star_spg,   # star's own contribution per sched game
                "nt_teammate_spg_arrival": nt_teammate_spg,  # year N: team sk/g MINUS star's own
                "nt_total_delta":          nt_total_delta,   # total change (additive + teammate)
                "nt_lift":                 nt_lift,           # teammate-only delta vs year before
                "nt_sk_rank_before":       nt_sk_rank_bef,
                "nt_sk_rank_arrival":      nt_sk_rank_arr,
                "nt_pd_rank_before":       nt_pd_rank_bef,
                "nt_pd_rank_arrival":      nt_pd_rank_arr,
                "nt_n_teams":              nt_n_arr,
                "nt_sos":                  nt_sos_arr,
                "nt_dsrs":                 nt_dsrs_arr,
                # ── Losing team ────────────────────────────────────────────
                "ot_total_spg_with_star":  ot_with_spg,        # year N-1: all team sk/g (star is there)
                "ot_teammate_spg_with":    ot_teammate_spg_with,  # year N-1: team sk/g MINUS star
                "ot_star_spg_old":         (star_sk_old / ot_with_g) if (star_sk_old and ot_with_g) else None,
                "ot_total_spg_after":      ot_aft_spg,         # year N: all team sk/g (star gone)
                "ot_total_delta":          ot_total_delta,      # total change including losing star
                "ot_drag":                 ot_drag,             # teammate-only drag after star left
                "ot_sk_rank_with":         ot_sk_rank_with,
                "ot_sk_rank_after":        ot_sk_rank_aft,
                "ot_pd_rank_with":         ot_pd_rank_with,
                "ot_pd_rank_after":        ot_pd_rank_aft,
                "ot_n_teams":              ot_n_with,
                "ot_sos":                  ot_sos_aft,
                "ot_dsrs":                 ot_dsrs_aft,
            }
        )

    # Career table for readability
    career = primary[["season", "team_pfref", "sk", "g", "spg",
                       "team_sk_total", "teammate_sk", "teammate_sk_per_game",
                       "sack_share"]].copy()
    career.columns = ["season", "team", "sk", "g", "sk_per_g",
                      "team_total_sk", "teammate_sk", "teammate_sk/g", "sack_share"]

    # Player tier
    n_elite_spg = (primary["spg"] >= TIER2_SPG_THRESHOLD).sum()
    n_10plus    = (primary["sk"] >= 10).sum()
    avg_sk = primary[primary["g"] >= 8]["sk"].mean()
    tier = "Truly Elite" if n_elite_spg >= TIER2_MIN_SEASONS else (
           "Elite" if (avg_sk >= TIER1_CAREER_AVG_SK or n_10plus >= TIER1_MIN_10SK_SEAONS)
           else "Sub-Elite")

    return {
        "label":        label,
        "player_id":    pid,
        "tier":         tier,
        "n_10plus_seasons": n_10plus,
        "n_08spg_seasons":  n_elite_spg,
        "career_avg_sk":    round(avg_sk, 2),
        "career_table": career,
        "changes":      changes,
    }


def run_targeted_wowy(df: pd.DataFrame, rank_lkp: pd.DataFrame, sos_lkp: pd.DataFrame) -> list:
    get_ts = team_lookup_fn(df)
    results = []
    for label, terms in TARGETED_PLAYERS:
        r = analyze_one_player(df, label, terms, get_ts, rank_lkp, sos_lkp)
        results.append(r)
        if "error" not in r:
            n_ch = len(r["changes"])
            tier = r["tier"]
            print(f"  {label:<22} ({r['player_id']})  [{tier}]  {n_ch} team change(s)")
        else:
            print(f"  {label:<22} — NOT FOUND")
    return results


# ── Aggregate team-change WOWY (Tier 1+) ──────────────────────────────────────

def aggregate_team_change_wowy(df: pd.DataFrame, tier1_ids: set) -> pd.DataFrame:
    """Same logic as targeted WOWY but across all Tier 1+ players."""
    primary = df[df["is_primary"]].copy().sort_values(["player_id", "season"])
    ep = primary[primary["player_id"].isin(tier1_ids)].copy()

    ep["prev_team"]   = ep.groupby("player_id")["team_pfref"].shift(1)
    ep["prev_season"] = ep.groupby("player_id")["season"].shift(1)

    changes = ep[
        ep["prev_team"].notna()
        & (ep["team_pfref"] != ep["prev_team"])
        & (ep["season"] == ep["prev_season"] + 1)
    ].copy()

    get_ts = team_lookup_fn(df)
    rows = []
    for _, c in changes.iterrows():
        pid      = c["player_id"]
        new_team = c["team_pfref"]
        old_team = c["prev_team"]
        arr_yr   = c["season"]
        p_sk     = c["sk"]
        p_g      = c["team_g"]

        nt_bef_spg, nt_bef_tot, _  = get_ts(new_team, arr_yr - 1)
        nt_aft_spg, nt_aft_tot, _  = get_ts(new_team, arr_yr)
        nt_teammate_spg = (nt_aft_tot - p_sk) / p_g if nt_aft_tot is not None else None
        nt_lift = (
            (nt_teammate_spg - nt_bef_spg)
            if (nt_teammate_spg is not None and nt_bef_spg is not None)
            else None
        )

        star_on_old = primary[(primary["player_id"] == pid) & (primary["season"] == arr_yr - 1)]
        star_sk_old = star_on_old["sk"].values[0] if len(star_on_old) else None
        ot_with_spg, ot_with_tot, ot_with_g = get_ts(old_team, arr_yr - 1)
        ot_aft_spg, _, _                    = get_ts(old_team, arr_yr)

        ot_teammate_spg_with = (
            (ot_with_tot - star_sk_old) / ot_with_g
            if (ot_with_tot is not None and star_sk_old is not None and ot_with_g)
            else None
        )
        ot_drag = (
            (ot_aft_spg - ot_teammate_spg_with)
            if (ot_aft_spg is not None and ot_teammate_spg_with is not None)
            else None
        )

        rows.append({
            "player_name":               c["player_name"],
            "player_id":                 pid,
            "arrival_season":            arr_yr,
            "player_age":                c.get("age"),
            "player_sk":                 p_sk,
            "player_spg":                round(p_sk / c["g"], 3) if c["g"] > 0 else None,
            "old_team":                  old_team,
            "new_team":                  new_team,
            "nt_team_spg_before":        nt_bef_spg,
            "nt_teammate_spg_arrival":   nt_teammate_spg,
            "nt_lift":                   nt_lift,
            "ot_teammate_spg_with_star": ot_teammate_spg_with,
            "ot_team_spg_after":         ot_aft_spg,
            "ot_drag":                   ot_drag,
        })

    return pd.DataFrame(rows)


# ── Injury WOWY — Season Level ────────────────────────────────────────────────

def injury_wowy_season(df: pd.DataFrame, tier1_ids: set) -> pd.DataFrame:
    primary = df[df["is_primary"]].copy().sort_values(["player_id", "season"])
    ep = primary[primary["player_id"].isin(tier1_ids)].copy()
    inj = ep[ep["is_injury_season"] & ~ep["is_strike_season"]].copy()

    rows = []
    for _, case in inj.iterrows():
        pid    = case["player_id"]
        season = case["season"]
        team   = case["team_pfref"]

        healthy = ep[
            (ep["player_id"] == pid)
            & (ep["team_pfref"] == team)
            & ~ep["is_injury_season"]
            & ~ep["is_strike_season"]
            & (ep["season"] != season)
            & (abs(ep["season"] - season) <= 3)
        ]
        if len(healthy) == 0:
            continue

        rows.append({
            "player_name":             case["player_name"],
            "player_id":               pid,
            "injury_season":           season,
            "team":                    team,
            "games_played":            case["g"],
            "schedule_len":            case["schedule_len"],
            "g_pct":                   round(case["g_pct"], 2),
            "player_sk_per_g_injury":  round(case["sk_per_game"], 3),
            "player_sk_per_g_healthy": round(healthy["sk_per_game"].mean(), 3),
            "player_sk_delta":         round(case["sk_per_game"] - healthy["sk_per_game"].mean(), 3),
            "teammate_spg_injury":     round(case["teammate_sk_per_game"], 3),
            "teammate_spg_healthy":    round(healthy["teammate_sk_per_game"].mean(), 3),
            "teammate_sk_delta":       round(
                case["teammate_sk_per_game"] - healthy["teammate_sk_per_game"].mean(), 3
            ),
            "n_ref_seasons":           len(healthy),
        })

    return pd.DataFrame(rows)


# ── Injury WOWY — Game Level ──────────────────────────────────────────────────

def _load_team_game_sacks(team_pfr: str, season: int) -> pd.DataFrame:
    season_dir = BOXSCORE_BASE / str(season)
    if not season_dir.exists():
        return pd.DataFrame()
    team_upper = team_pfr.upper()
    records = []
    for game_dir in sorted(season_dir.iterdir()):
        if not game_dir.is_dir():
            continue
        defense_file = game_dir / "player_defense.csv"
        if not defense_file.exists():
            continue
        ddf = pd.read_csv(defense_file, low_memory=False)
        team_rows = ddf[ddf["team"].str.upper() == team_upper]
        if len(team_rows) == 0:
            continue
        records.append({
            "game_id":    game_dir.name,
            "team_sacks": team_rows["sacks"].fillna(0).sum(),
        })
    return pd.DataFrame(records)


def _load_player_starts(pfr_id: str, season: int) -> set:
    season_dir = BOXSCORE_BASE / str(season)
    if not season_dir.exists():
        return set()
    started = set()
    for game_dir in sorted(season_dir.iterdir()):
        if not game_dir.is_dir():
            continue
        sf = game_dir / "starters.csv"
        if not sf.exists():
            continue
        starters = pd.read_csv(sf, low_memory=False)
        ids = starters["pfr_player_id"].apply(pfr_id_from_path)
        if pfr_id in ids.values:
            started.add(game_dir.name)
    return started


def injury_wowy_game(df: pd.DataFrame, tier1_ids: set) -> pd.DataFrame:
    primary = df[df["is_primary"]].copy()
    ep = primary[primary["player_id"].isin(tier1_ids)].copy()

    career_peak = (
        ep.groupby("player_id")["sk"].max().rename("career_peak").reset_index()
    )
    injury_cases = (
        ep[ep["is_injury_season"] & ~ep["is_strike_season"]]
        .merge(career_peak, on="player_id")
        .sort_values("career_peak", ascending=False)
        .head(MAX_GAME_CASES)
    )

    rows = []
    for i, (_, case) in enumerate(injury_cases.iterrows(), 1):
        pid    = case["player_id"]
        team   = case["team_pfref"]
        season = case["season"]
        label  = f"{case['player_name']} {season} {team.upper()} ({int(case['g'])}g)"
        print(f"  [{i}/{len(injury_cases)}] {label}", flush=True)

        team_games = _load_team_game_sacks(team, season)
        if team_games.empty:
            print(f"    → no boxscore data"); continue

        started = _load_player_starts(pid, season)
        team_games["player_started"] = team_games["game_id"].isin(started)

        n_started = int(team_games["player_started"].sum())
        n_missed  = int((~team_games["player_started"]).sum())

        if n_started == 0 or n_missed == 0:
            print(f"    → {n_started} starts, {n_missed} missed — no contrast"); continue

        spg_started = team_games.loc[ team_games["player_started"], "team_sacks"].mean()
        spg_missed  = team_games.loc[~team_games["player_started"], "team_sacks"].mean()
        delta = spg_started - spg_missed
        print(f"    → started {n_started}g ({spg_started:.2f} sk/g), "
              f"missed {n_missed}g ({spg_missed:.2f} sk/g), delta {delta:+.2f}")

        rows.append({
            "player_name":      case["player_name"],
            "player_id":        pid,
            "season":           season,
            "team":             team,
            "player_sk":        case["sk"],
            "player_g":         case["g"],
            "schedule_len":     case["schedule_len"],
            "games_started":    n_started,
            "games_missed":     n_missed,
            "team_spg_started": round(spg_started, 3),
            "team_spg_missed":  round(spg_missed, 3),
            "team_spg_delta":   round(delta, 3),
        })

    return pd.DataFrame(rows)


# ── Sack Share ────────────────────────────────────────────────────────────────

def sack_share_analysis(df: pd.DataFrame, tier1_ids: set) -> pd.DataFrame:
    primary = df[df["is_primary"]].copy()
    elite   = primary[primary["player_id"].isin(tier1_ids)].copy()

    career_peak = elite.groupby("player_id")["sk"].max().rename("career_peak")
    elite = elite.merge(career_peak, on="player_id", how="left")
    elite["peak_delta"]    = elite["sk"] - elite["career_peak"]
    elite["career_phase"]  = np.select(
        [elite["peak_delta"] >= -2, elite["sk"] >= 7],
        ["peak", "prime"],
        default="decline",
    )
    return elite[
        ["player_name", "player_id", "season", "team_pfref", "age",
         "sk", "team_sk_total", "sack_share", "teammate_sk",
         "teammate_sk_per_game", "career_peak", "career_phase"]
    ].copy()


# ── Printing ──────────────────────────────────────────────────────────────────

def fmt(val, dec=3, sign=False):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "   N/A"
    fmt_str = f"{val:+.{dec}f}" if sign else f"{val:.{dec}f}"
    return fmt_str


def _rk(rank, n_teams):
    """Format rank as '#3 of 28'."""
    if rank is None or n_teams is None:
        return "N/A"
    return f"#{rank} of {n_teams}"


def print_targeted_results(results: list) -> str:
    lines = []
    lines.append("\n" + "=" * 76)
    lines.append("TARGETED TEAM-CHANGE WOWY — 15 NAMED PLAYERS")
    lines.append("=" * 76)
    lines.append(
        "\nColumns: total sk/g = all team sacks / schedule games"
        "\n         star sk/g  = star's own sacks / schedule games  (additive)"
        "\n         tm sk/g    = (team total − star's sacks) / schedule games  (teammate effect)"
        "\n         sk rank    = sack rank among all teams that season (1=most)"
        "\n         pd rank    = pass defense rank by yds allowed (1=fewest yds)"
        "\n         SOS        = strength of schedule (opp quality proxy; + = harder)"
    )

    for r in results:
        if "error" in r:
            lines.append(f"\n{r['label']}: NOT FOUND")
            continue

        label = r["label"]
        tier  = r["tier"]
        lines.append(f"\n{'─'*76}")
        lines.append(
            f"{label.upper()}  ({r['player_id']})  [{tier}]  "
            f"career avg: {r['career_avg_sk']} sk/season  |  "
            f"10+sk seasons: {r['n_10plus_seasons']}  |  "
            f"≥0.8 sk/g seasons: {r['n_08spg_seasons']}"
        )

        # Career table with sack share
        ct = r["career_table"]
        lines.append(
            "\n  Season  Team  PlayerSK   g  sk/g  TeamTotalSK  TmmateSK/g  SackShare"
        )
        for _, row in ct.iterrows():
            spg   = f"{row['sk_per_g']:.2f}"   if pd.notna(row['sk_per_g'])       else "  N/A"
            tm_sk = f"{row['team_total_sk']:5.1f}" if pd.notna(row['team_total_sk']) else "  N/A"
            tm_spg= f"{row['teammate_sk/g']:.2f}"  if pd.notna(row['teammate_sk/g']) else "  N/A"
            share = f"{row['sack_share']:.3f}"  if pd.notna(row['sack_share'])     else "  N/A"
            lines.append(
                f"  {int(row['season'])}   {row['team'].upper():<5} "
                f"{row['sk']:7.1f}  {row['g']:3.0f}  {spg}  "
                f"{tm_sk:>10}  {tm_spg:>10}  {share:>9}"
            )

        if not r["changes"]:
            lines.append("\n  (No consecutive-season team changes detected)")
            continue

        for ch in r["changes"]:
            old  = ch["old_team"].upper()
            new  = ch["new_team"].upper()
            yr   = ch["arrival_season"]
            age  = f", age {int(ch['player_age'])}" if ch.get("player_age") else ""
            lines.append(f"\n  {'▶ MOVE: ' + old + ' → ' + new + '  (' + str(yr) + age + ')'}")
            lines.append(f"    Player this season: {ch['player_sk']:.0f} sk  ({ch['player_spg']:.2f}/g)")

            # ── Gaining team block ─────────────────────────────────────────
            n = ch.get("nt_n_teams")
            lines.append(f"\n    GAINING TEAM ({new}):")
            lines.append(
                f"      Year {yr-1} BEFORE (no star) : "
                f"total={fmt(ch['nt_total_spg_before'])} sk/g  |  "
                f"sk rank {_rk(ch.get('nt_sk_rank_before'), n)}  "
                f"pd rank {_rk(ch.get('nt_pd_rank_before'), n)}"
            )
            lines.append(
                f"      Year {yr}  ARRIVAL (w/ star) : "
                f"total={fmt(ch['nt_total_spg_arrival'])} sk/g  |  "
                f"sk rank {_rk(ch.get('nt_sk_rank_arrival'), n)}  "
                f"pd rank {_rk(ch.get('nt_pd_rank_arrival'), n)}  "
                f"SOS={fmt(ch.get('nt_sos'), 2, sign=True)}"
            )
            lines.append(
                f"        ├─ total delta      : {fmt(ch['nt_total_delta'], sign=True)} sk/g  (additive + teammate)"
            )
            lines.append(
                f"        ├─ star's addition  : {fmt(ch['nt_star_spg'], sign=False)} sk/g  "
                f"← player's own {ch['player_sk']:.0f} sacks"
            )
            lines.append(
                f"        └─ teammate delta   : {fmt(ch['nt_lift'], sign=True)} sk/g  "
                f"(did star ELEVATE teammates?  +pos=yes  -neg=no)"
            )

            # ── Losing team block ──────────────────────────────────────────
            n2 = ch.get("ot_n_teams")
            lines.append(f"\n    LOSING TEAM ({old}):")
            lines.append(
                f"      Year {yr-1} WITH star        : "
                f"total={fmt(ch['ot_total_spg_with_star'])} sk/g  "
                f"(star's share={fmt(ch.get('ot_star_spg_old'))} sk/g)  "
                f"→ teammate={fmt(ch['ot_teammate_spg_with'])} sk/g  |  "
                f"sk rank {_rk(ch.get('ot_sk_rank_with'), n2)}"
            )
            lines.append(
                f"      Year {yr}  WITHOUT star      : "
                f"total={fmt(ch['ot_total_spg_after'])} sk/g  "
                f"(all are now teammate sacks)  |  "
                f"sk rank {_rk(ch.get('ot_sk_rank_after'), n2)}  "
                f"SOS={fmt(ch.get('ot_sos'), 2, sign=True)}"
            )
            lines.append(
                f"        ├─ total delta      : {fmt(ch['ot_total_delta'], sign=True)} sk/g  "
                f"(team lost star PLUS any teammate change)"
            )
            lines.append(
                f"        └─ teammate delta   : {fmt(ch['ot_drag'], sign=True)} sk/g  "
                f"(did losing star HURT teammates?  -neg=yes  +pos=no)"
            )

    return "\n".join(lines)


def print_aggregate_summary(tc, inj_s, inj_g, ss, curve_table, peak_age) -> str:
    lines = []
    sep = "=" * 72

    lines += ["", sep, "AGGREGATE SUMMARY (Tier 1 + Tier 2 players)", sep]

    # Age curve
    lines.append(
        f"\n[AGE CURVE]  Peak for elite pass rushers: "
        + (f"{peak_age:.1f} years old" if peak_age else "N/A")
    )
    lines.append("  Age  Expected SK")
    for _, r in curve_table[curve_table["age"].between(22, 38)].iterrows():
        marker = " ← peak" if abs(r["age"] - (peak_age or 0)) < 0.6 else ""
        lines.append(f"  {int(r['age'])}   {r['expected_sk']:5.2f}{marker}")

    # Aggregate WOWY
    lines.append(f"\n[TEAM-CHANGE WOWY]  N cases: {len(tc)}")
    if len(tc) > 0:
        tc_v = tc.dropna(subset=["nt_lift", "ot_drag"])
        lines.append(
            f"  Gaining-team teammate lift:  "
            f"mean={tc_v['nt_lift'].mean():+.3f}/g  "
            f"median={tc_v['nt_lift'].median():+.3f}/g  "
            f"pct positive={((tc_v['nt_lift']>0).mean()*100):.1f}%"
        )
        lines.append(
            f"  Losing-team sack drag:       "
            f"mean={tc_v['ot_drag'].mean():+.3f}/g  "
            f"median={tc_v['ot_drag'].median():+.3f}/g  "
            f"pct negative={((tc_v['ot_drag']<0).mean()*100):.1f}%"
        )
        lines.append("\n  Top 10 gaining-team teammate lifts:")
        for _, r in tc.dropna(subset=["nt_lift"]).nlargest(10, "nt_lift").iterrows():
            lines.append(
                f"    {r['player_name']:<22} → {r['new_team'].upper()}  "
                f"{int(r['arrival_season'])}  [{r['player_sk']:.0f} sk, {r['player_spg']:.2f}/g]  "
                f"lift: {r['nt_lift']:+.3f} sk/g"
            )
        lines.append("\n  Top 10 losing-team sack drags:")
        for _, r in tc.dropna(subset=["ot_drag"]).nsmallest(10, "ot_drag").iterrows():
            lines.append(
                f"    {r['player_name']:<22} left {r['old_team'].upper()}  "
                f"{int(r['arrival_season'])}  "
                f"drag: {r['ot_drag']:+.3f} sk/g"
            )

    # Injury — season level
    lines.append(f"\n[INJURY WOWY — SEASON]  N cases: {len(inj_s)}")
    if len(inj_s) > 0:
        lines.append(f"  Avg player sk/g drop:         {inj_s['player_sk_delta'].mean():+.3f}")
        lines.append(f"  Avg teammate sk/g change:     {inj_s['teammate_sk_delta'].mean():+.3f}")
        lines.append(f"  % injury seasons: fewer teammate sacks: {(inj_s['teammate_sk_delta']<0).mean()*100:.1f}%")
        lines.append("\n  Cases with biggest teammate sk drops:")
        for _, r in inj_s.nsmallest(10, "teammate_sk_delta").iterrows():
            lines.append(
                f"    {r['player_name']:<22} {int(r['injury_season'])} {r['team'].upper()} "
                f"({r['games_played']:.0f}g)  teammate delta: {r['teammate_sk_delta']:+.3f}/g"
            )

    # Injury — game level
    if len(inj_g) > 0:
        lines.append(f"\n[INJURY WOWY — GAME LEVEL]  N cases: {len(inj_g)}")
        lines.append(f"  Mean team sacks/g started: {inj_g['team_spg_started'].mean():.3f}")
        lines.append(f"  Mean team sacks/g missed:  {inj_g['team_spg_missed'].mean():.3f}")
        lines.append(f"  Mean delta:                {inj_g['team_spg_delta'].mean():+.3f}")
        lines.append(f"  % positive (team better w/ star): {(inj_g['team_spg_delta']>0).mean()*100:.1f}%")
        lines.append("\n  All cases (sorted by delta):")
        for _, r in inj_g.sort_values("team_spg_delta", ascending=False).iterrows():
            lines.append(
                f"    {r['player_name']:<22} {int(r['season'])} {r['team'].upper()}  "
                f"{r['games_started']}g started / {r['games_missed']}g missed  "
                f"delta: {r['team_spg_delta']:+.3f}"
            )

    # Sack share
    lines.append(f"\n[SACK SHARE]  By career phase:")
    for phase in ["peak", "prime", "decline"]:
        grp = ss[ss["career_phase"] == phase].dropna(subset=["sack_share"])
        if len(grp) == 0:
            continue
        lines.append(
            f"  {phase:<8}  n={len(grp):4d}  "
            f"avg_sk={grp['sk'].mean():.1f}  "
            f"avg_team_sk={grp['team_sk_total'].mean():.1f}  "
            f"avg_share={grp['sack_share'].mean():.3f}"
        )
    peak_ss = ss[ss["career_phase"] == "peak"].dropna(subset=["sack_share", "sk"])
    if len(peak_ss) > 10:
        corr = peak_ss["sk"].corr(peak_ss["sack_share"])
        lines.append(
            f"\n  Sack share paradox test (peak seasons, n={len(peak_ss)}):  "
            f"corr(sk, sack_share) = {corr:.3f}"
        )
        note = ("→ PARADOX: more sacks = lower share" if corr < -0.05
                else "→ NO PARADOX: more sacks = higher share")
        lines.append(f"  {note}")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading gold parquet...")
    df = load_and_prep()
    print(f"  {len(df):,} rows  ({int(df['season'].min())}–{int(df['season'].max())})")

    # Tier classification
    print("\nClassifying players into tiers...")
    tiers = classify_players(df)
    tiers.to_csv(RESULTS_DIR / "player_tiers.csv", index=False)

    tier1_ids = set(tiers[tiers["is_tier1"]]["player_id"])
    tier2_ids = set(tiers[tiers["is_tier2"]]["player_id"])
    all_elite_ids = tier1_ids | tier2_ids

    n1 = len(tier1_ids)
    n2 = len(tier2_ids)
    print(f"  Tier 1 (Elite):        {n1} players  (career avg ≥{TIER1_CAREER_AVG_SK} OR {TIER1_MIN_10SK_SEAONS}+ seasons of 10+)")
    print(f"  Tier 2 (Truly Elite):  {n2} players  ({TIER2_MIN_SEASONS}+ seasons at ≥{TIER2_SPG_THRESHOLD} sk/g)")
    print(f"  Combined pool:         {len(all_elite_ids)} players")

    # Show tier 2 players
    t2 = tiers[tiers["is_tier2"]][["player_name","player_id","n_seasons_08_spg",
                                    "career_peak_sk","first_season","last_season","teams"]]
    print(f"\n  TRULY ELITE players ({TIER2_MIN_SEASONS}+ seasons ≥{TIER2_SPG_THRESHOLD} sk/g):")
    for _, r in t2.sort_values("n_seasons_08_spg", ascending=False).iterrows():
        print(f"    {r['player_name']:<22} {r['player_id']}  "
              f"{r['n_seasons_08_spg']:.0f} seasons  "
              f"peak {r['career_peak_sk']:.1f} sk  "
              f"({int(r['first_season'])}–{int(r['last_season'])})")

    # Age curve
    print("\n[1] Fitting age curve...")
    elite_df, poly, peak_age, curve_table = fit_age_curve(df, all_elite_ids)
    curve_table.to_csv(RESULTS_DIR / "age_curve.csv", index=False)
    elite_df[["player_name","player_id","season","team_pfref","age","sk","expected_sk","sk_residual"]]\
        .sort_values(["player_id","season"])\
        .to_csv(RESULTS_DIR / "elite_age_residuals.csv", index=False)
    print(f"  Peak age: {peak_age:.1f}" if peak_age else "  Could not determine peak")

    # Load defense rank and SOS lookup tables
    print("\nLoading team defense ranks and SOS data...")
    try:
        rank_lkp = load_team_defense_ranks()
        print(f"  Defense ranks: {len(rank_lkp)} team-season rows")
    except Exception as e:
        print(f"  WARNING: could not load defense ranks: {e}")
        rank_lkp = pd.DataFrame()

    try:
        sos_lkp = load_team_sos()
        print(f"  SOS data:      {len(sos_lkp)} team-season rows")
    except Exception as e:
        print(f"  WARNING: could not load SOS data: {e}")
        sos_lkp = pd.DataFrame()

    # Targeted WOWY
    print("\n[2] Targeted WOWY for named players...")
    targeted = run_targeted_wowy(df, rank_lkp, sos_lkp)
    targeted_text = print_targeted_results(targeted)
    # Save flat CSV of targeted changes
    flat_changes = []
    for r in targeted:
        if "error" in r or not r["changes"]:
            continue
        for ch in r["changes"]:
            flat_changes.append({"player": r["label"], "tier": r["tier"], **ch})
    if flat_changes:
        pd.DataFrame(flat_changes).to_csv(RESULTS_DIR / "targeted_wowy.csv", index=False)

    # Aggregate WOWY
    print("\n[3] Aggregate team-change WOWY (all Tier 1+)...")
    tc = aggregate_team_change_wowy(df, all_elite_ids)
    tc.sort_values("nt_lift", ascending=False, na_position="last")\
      .to_csv(RESULTS_DIR / "aggregate_team_change_wowy.csv", index=False)
    print(f"  {len(tc)} team-change cases")

    # Injury WOWY — season
    print("\n[4] Injury WOWY (season-level)...")
    inj_s = injury_wowy_season(df, all_elite_ids)
    inj_s.sort_values("teammate_sk_delta")\
         .to_csv(RESULTS_DIR / "injury_wowy_season.csv", index=False)
    print(f"  {len(inj_s)} injury-season cases")

    # Injury WOWY — game
    print(f"\n[5] Injury WOWY (game-level, up to {MAX_GAME_CASES} cases)...")
    inj_g = injury_wowy_game(df, all_elite_ids)
    if len(inj_g) > 0:
        inj_g.sort_values("team_spg_delta", ascending=False)\
             .to_csv(RESULTS_DIR / "injury_wowy_game.csv", index=False)
    print(f"  {len(inj_g)} resolved")

    # Sack share
    print("\n[6] Sack share analysis...")
    ss = sack_share_analysis(df, all_elite_ids)
    ss.to_csv(RESULTS_DIR / "sack_share.csv", index=False)

    # Write outputs
    agg_text = print_aggregate_summary(tc, inj_s, inj_g, ss, curve_table, peak_age)
    full_text = targeted_text + "\n\n" + agg_text
    print(full_text)
    (RESULTS_DIR / "summary.txt").write_text(full_text)
    print(f"\nAll results written to {RESULTS_DIR}/")


if __name__ == "__main__":
    main()
