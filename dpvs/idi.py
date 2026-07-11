"""
Individual Disruption Index (IDI) — Layer 2 of DPVS-G.

IDI measures the fraction of the team's disruptive events this player
accounted for. Two source tiers:

  Tier A (gamebook data, MIN 1967-1981 / PIT 1969-1973):
    tackle_share  from gamebook season CSV  (tkl_pct column / 100)
    sack_share    computed from gamebook CSV
    int_share / fr_share / ff_share  from gold parquet (most reliable source)

  Tier B (no gamebook data):
    tackle_share = NaN  (excluded from formula; weights rebalanced)
    sack/int/fr/ff shares from gold parquet

Formula:
  With gamebook tackles:
    IDI = 0.35*tackle_share + 0.30*sack_share + 0.20*int_share
          + 0.10*fr_share + 0.05*ff_share

  Without gamebook tackles:
    IDI = 0.50*sack_share + 0.30*int_share + 0.15*fr_share + 0.05*ff_share
"""

from __future__ import annotations

from pathlib import Path
import pandas as pd
import numpy as np

GAMEBOOK_BASE  = Path.home() / "data/gamebooks_processed/teams"
GOLD_PARQUET   = Path.home() / "data/gold/player_season_card.parquet"

# Gold parquet uses city-based team codes; player_game_defense uses franchise-based PFR codes.
# This map converts gold → pgd for relocated franchises.
# Format: {gold_code: [(season_start, season_end, pgd_code), ...]}
_GOLD_TO_PGD: dict[str, list[tuple[int, int, str]]] = {
    "ari":  [(1988, 9999, "crd")],
    "pho":  [(1988, 1993, "crd")],
    "stl":  [(1960, 1987, "crd"), (1995, 2015, "ram")],  # St. Louis Cardinals then Rams
    "lar":  [(2016, 9999, "ram")],
    "lac":  [(2017, 9999, "sdg")],
    "oak":  [(1960, 2019, "rai")],
    "lvr":  [(2020, 9999, "rai")],
    "bal":  [(1953, 1983, "clt"), (1996, 9999, "rav")],
    "ind":  [(1984, 9999, "clt")],
    "hou":  [(1960, 1996, "oti"), (2002, 9999, "htx")],  # Oilers then Texans (gap 1997-2001)
    "ten":  [(1997, 9999, "oti")],
}


def _normalize_gold_team(team_code: str, season: int) -> str:
    """Map a gold-parquet team code to the franchise code used in player_game_defense."""
    rules = _GOLD_TO_PGD.get(team_code)
    if rules is None:
        return team_code
    for lo, hi, pgd in rules:
        if lo <= season <= hi:
            return pgd
    return team_code  # no mapping found, keep as-is

_GAMEBOOK_TEAMS: dict[str, tuple[int, int]] = {
    # Original NFL teams — gamebook PDFs available 1967-1977 for most franchises.
    # Year ranges are generous; _load_gamebook_season returns None for missing files.
    "min": (1967, 1981),  # MIN has gamebook + PFR PBP through 1981
    "pit": (1967, 1977),  # extended from 1973: PIT data quality is high through 1977
    "dal": (1967, 1977),
    "cle": (1967, 1977),
    "ram": (1967, 1977),
    "gnb": (1967, 1977),
    "det": (1967, 1977),
    "sfo": (1967, 1977),
    "clt": (1967, 1977),  # Baltimore Colts
    "chi": (1967, 1977),
    "was": (1967, 1977),
    "phi": (1967, 1977),
    "nyg": (1967, 1977),
    "crd": (1967, 1977),  # St. Louis/Chicago Cardinals
    "nor": (1967, 1977),  # expansion 1967
    "atl": (1967, 1977),  # expansion 1966
    # AFL teams — merged into NFL 1970; gamebook data from 1970 on
    "rai": (1970, 1977),  # Oakland Raiders
    "kan": (1970, 1977),
    "sdg": (1970, 1977),
    "mia": (1970, 1977),
    "den": (1970, 1977),
    "oti": (1970, 1977),  # Houston Oilers
    "nwe": (1970, 1977),
    "buf": (1970, 1977),
    "nyj": (1970, 1977),
    "cin": (1970, 1977),
    # Expansion teams (1976)
    "sea": (1976, 1977),
    "tam": (1976, 1977),
}

# Weights when tackle share IS available (gamebook-sourced)
_W_WITH_TACKLES = {
    "tackle_share": 0.35,
    "sack_share":   0.30,
    "int_share":    0.20,
    "fr_share":     0.10,
    "ff_share":     0.05,
}

# Weights when tackle share is NOT available
_W_NO_TACKLES = {
    "sack_share":   0.50,
    "int_share":    0.30,
    "fr_share":     0.15,
    "ff_share":     0.05,
}


# ── gamebook loader ────────────────────────────────────────────────────────────

def _load_gamebook_season(team: str, season: int) -> pd.DataFrame | None:
    """
    Load ~/data/gamebooks_processed/teams/{team}/seasons/{season}_defense.csv.
    Columns: player, pos, games, solo, asst, tkl, sack, tfl, fr, int_, pd, tkl_pct
    Returns None if file not found.
    """
    path = GAMEBOOK_BASE / team / "seasons" / f"{season}_defense.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["team"] = team
    df["season"] = season
    df["tackle_share"] = df["tkl_pct"].astype(float) / 100.0
    return df


def load_all_gamebook_idi(
    teams: list[str] | None = None,
) -> pd.DataFrame:
    """
    Load all available gamebook season CSVs.
    Returns rows with: team, season, player, pos, tackle_share, sack (raw count).
    """
    frames: list[pd.DataFrame] = []
    check_teams = teams if teams else list(_GAMEBOOK_TEAMS.keys())
    for team in check_teams:
        if team not in _GAMEBOOK_TEAMS:
            continue
        lo, hi = _GAMEBOOK_TEAMS[team]
        for season in range(lo, hi + 1):
            df = _load_gamebook_season(team, season)
            if df is not None:
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ── gold parquet loader ────────────────────────────────────────────────────────

def load_gold_stats(seasons: list[int]) -> pd.DataFrame:
    """
    Load individual defensive stats from gold parquet.
    Returns per-player-season: sacks, ints, frs, ffs, games, plus shares.
    Also computes PFR tackle_share for seasons where comb_tackles is available
    (primarily 2001+, plus media-guide-patched seasons for earlier years).
    Gold team codes are uppercase (MIN, PIT); we lowercase them to match
    gamebook convention.
    """
    df = pd.read_parquet(GOLD_PARQUET)
    df = df[df["season"].isin(seasons)].copy()
    # Normalize gold team codes → franchise codes used in player_game_defense
    df["_raw_team"] = df["team_pfref"].str.lower()
    df["team"] = df.apply(
        lambda r: _normalize_gold_team(r["_raw_team"], int(r["season"])), axis=1
    )
    df.drop(columns=["_raw_team"], inplace=True)

    # Some relocated franchises appear twice after normalization (e.g. gold has
    # both LAC and SDG rows for 2017+ Chargers; both map to 'sdg').
    # Keep the row with more data: prioritise non-null g, then non-null comb_tackles.
    dup_key = ["season", "team", "player_name"]
    if df.duplicated(subset=dup_key).any():
        has_g = df["g"].notna().astype(int) if "g" in df.columns else pd.Series(0, index=df.index)
        has_tkl = df["comb_tackles"].notna().astype(int) if "comb_tackles" in df.columns else pd.Series(0, index=df.index)
        df["_priority"] = has_g * 2 + has_tkl
        df = df.sort_values("_priority", ascending=False).drop_duplicates(subset=dup_key, keep="first")
        df.drop(columns=["_priority"], inplace=True)

    # fill NaN stats with 0 for summing
    for col in ("sk", "int", "fr", "ff", "comb_tackles"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Team totals per season for share computation
    agg = {"team_sk": ("sk", "sum"), "team_int": ("int", "sum"),
           "team_fr": ("fr", "sum"), "team_ff": ("ff", "sum")}
    if "comb_tackles" in df.columns:
        agg["team_comb_tkl"] = ("comb_tackles", "sum")

    team_totals = df.groupby(["season", "team"], as_index=False).agg(**agg)
    df = df.merge(team_totals, on=["season", "team"], how="left")

    def _share(num_col: str, den_col: str) -> pd.Series:
        denom = df[den_col].replace(0, np.nan)
        return (df[num_col] / denom).clip(0, 1)

    df["sack_share"] = _share("sk",  "team_sk")
    df["int_share"]  = _share("int", "team_int")
    df["fr_share"]   = _share("fr",  "team_fr")
    df["ff_share"]   = _share("ff",  "team_ff")

    # PFR / media-guide tackle share (used when gamebook data is unavailable)
    if "comb_tackles" in df.columns and "team_comb_tkl" in df.columns:
        # Only use where team has meaningful total (avoid divide-by-tiny)
        meaningful = df["team_comb_tkl"] >= 50
        df["pfr_tackle_share"] = np.where(
            meaningful,
            (df["comb_tackles"] / df["team_comb_tkl"].replace(0, np.nan)).clip(0, 1),
            np.nan,
        )
        df["pfr_tackle_source"] = df.get("tackle_source", pd.Series("none", index=df.index))
    else:
        df["pfr_tackle_share"] = np.nan
        df["pfr_tackle_source"] = "none"

    keep = [
        "season", "team", "player_id", "player_name", "pos",
        "g", "sk", "int", "fr", "ff", "comb_tackles",
        "sack_share", "int_share", "fr_share", "ff_share",
        "pfr_tackle_share", "pfr_tackle_source", "tackle_source",
    ]
    return df[[c for c in keep if c in df.columns]].copy()


# ── IDI computation ────────────────────────────────────────────────────────────

def _idi_row(row: pd.Series) -> float:
    """Compute IDI for a single player-season row."""
    has_tackles = pd.notna(row.get("tackle_share"))
    if has_tackles:
        return (
            _W_WITH_TACKLES["tackle_share"] * row["tackle_share"]
            + _W_WITH_TACKLES["sack_share"]  * _safe(row, "sack_share")
            + _W_WITH_TACKLES["int_share"]   * _safe(row, "int_share")
            + _W_WITH_TACKLES["fr_share"]    * _safe(row, "fr_share")
            + _W_WITH_TACKLES["ff_share"]    * _safe(row, "ff_share")
        )
    # Rebalance weights when tackle share unavailable
    total_w = sum(_W_NO_TACKLES.values())
    return (
        _W_NO_TACKLES["sack_share"] * _safe(row, "sack_share")
        + _W_NO_TACKLES["int_share"]  * _safe(row, "int_share")
        + _W_NO_TACKLES["fr_share"]   * _safe(row, "fr_share")
        + _W_NO_TACKLES["ff_share"]   * _safe(row, "ff_share")
    ) / total_w  # already sums to 1.0


def _safe(row: pd.Series, col: str) -> float:
    v = row.get(col)
    return float(v) if pd.notna(v) else 0.0


def compute_idi(
    tcs_df: pd.DataFrame,
    gold_df: pd.DataFrame,
    gamebook_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge TCS player-season list with gold stats and gamebook tackle shares,
    then compute IDI per player-season.

    Tackle share priority (highest → lowest):
      1. Gamebook OCR data (most precise, game-level sourced)
      2. PFR/media-guide comb_tackles (2001+ and some earlier seasons)
      3. No tackle data → reduced IDI formula (sack/int/fr/ff only)

    tcs_df must have: season, team, pfr_player_id, player_name, pos.
    Returns tcs_df with idi-related columns appended.
    """
    gold_df = gold_df.copy()
    gold_df["_name_key"] = gold_df["player_name"].str.lower().str.strip()
    tcs_df = tcs_df.copy()
    tcs_df["_name_key"] = tcs_df["player_name"].str.lower().str.strip()

    # Bring in gold_pos so build_composite can fill missing positions
    # (critical for 2001-2018 where starters.csv is absent)
    gold_df["gold_pos"] = gold_df["pos"]
    gold_cols = ["season", "team", "_name_key",
                 "sack_share", "int_share", "fr_share", "ff_share",
                 "pfr_tackle_share", "pfr_tackle_source", "tackle_source",
                 "gold_pos"]
    merged = tcs_df.merge(
        gold_df[[c for c in gold_cols if c in gold_df.columns]],
        on=["season", "team", "_name_key"],
        how="left",
    )

    # Layer 1: gamebook tackle share (highest precision)
    merged["tackle_share"] = np.nan
    merged["idi_tackle_source"] = "none"

    if not gamebook_df.empty:
        gamebook_df = gamebook_df.copy()
        gamebook_df["_name_key"] = gamebook_df["player"].str.lower().str.strip()
        gb_key = gamebook_df[["season", "team", "_name_key", "tackle_share"]].copy()
        gb_key = gb_key.rename(columns={"tackle_share": "_gb_ts"})
        merged = merged.merge(gb_key, on=["season", "team", "_name_key"], how="left")
        has_gb = pd.notna(merged["_gb_ts"])
        merged.loc[has_gb, "tackle_share"] = merged.loc[has_gb, "_gb_ts"]
        merged.loc[has_gb, "idi_tackle_source"] = "gamebook"
        merged.drop(columns=["_gb_ts"], inplace=True)

    # Layer 2: PFR / media-guide tackle share (fills gaps not covered by gamebook)
    if "pfr_tackle_share" in merged.columns:
        no_tackle = merged["idi_tackle_source"] == "none"
        has_pfr = no_tackle & pd.notna(merged["pfr_tackle_share"])
        merged.loc[has_pfr, "tackle_share"] = merged.loc[has_pfr, "pfr_tackle_share"]
        merged.loc[has_pfr, "idi_tackle_source"] = merged.loc[has_pfr, "pfr_tackle_source"].fillna("pfr")

    merged["idi"] = merged.apply(_idi_row, axis=1)
    merged["idi_has_tackles"] = pd.notna(merged["tackle_share"])
    merged.drop(columns=["_name_key"], inplace=True, errors="ignore")
    return merged
