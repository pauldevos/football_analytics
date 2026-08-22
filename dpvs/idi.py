"""
Individual Disruption Index (IDI) — Layer 2 of DPVS-G.

IDI measures a player's individual defensive disruption relative to their
season × position_group peers, across five components: tackle share, TFL,
sack share, INT, FF.

2026-08-21 reweight (TFL added, FR dropped — see docs/framework_decisions.md
§11 for the full YoY-stability evidence trail that motivated this).

2026-08-21 refinement (this pass — see docs/framework_decisions.md §12):
the first TFL/FR reweight attempt (§11) regressed pooled YoY stability
(IDI_z 0.386 → 0.343) for two diagnosed reasons: (1) the 1967-1977 gamebooks
TFL share was computed from tiny observed-game samples with no floor, so a
player with 1 TFL in 1 observed game showed tfl_share = 1.0; (2) tfl_share
and the other rare-event components were *shares of team season total* —
a noisier statistic than a per-game rate, because team TFL/INT/FF totals
are themselves small, rare-event counts. This pass replaces the share-based
treatment of the three rare-event components with three fixes applied
together:

  1. TFL sourcing now spans three eras, all as RAW counts + observed games
     (n_obs), not shares:
       - 1967-1977: gamebooks_boxscores' 28-team corpus, but ONLY from
         game-sides that cleared that corpus's own completeness-ratio test
         (team Solo+Ast / opponent snaps >= 70%, gated at build time in
         scripts/build_tfl_gated_corpus.py — reuses gamebooks_boxscores'
         own build_defensive_leaderboards.py ratio code directly rather
         than re-deriving it) AND that have >= MIN_GAMES_QUALIFIED_FLOOR
         qualifying games observed. Below the floor, TFL is simply
         unavailable for that player-season (falls through the gating
         mechanism below) rather than forced from a 1-2-game sample.
       - 1978-1998: NEWLY WIRED IN this pass. gamebooks_boxscores'
         pfr_pbp_defensive_stats_1978_2025.csv (PFR play-by-play "tackle
         for loss" parsing). This source is a KNOWN UNDERCOUNT relative to
         gamebook-verified ground truth (confirmed ~20%+ low on verified
         elite pass-rusher seasons per that repo's own experiment writeup)
         — used because it's the only source at all for this 15-year gap,
         but every row sourced from it carries the
         "pfr_pbp_undercount_1978_1998" tier tag so it's never silently
         treated as equal-confidence to the other two eras.
       - 1999+: gold parquet's own real PFR 'tfl' column, unchanged.

  2. Empirical-Bayes shrinkage on the per-game RATE (not share) for all
     three rare-event components (TFL, INT, FF):
       shrunk_rate = (n_obs·observed_rate + k·prior_rate) / (n_obs + k)
     prior_rate is the player's own career rate as of the prior season
     (pfr_player_id-keyed cumulative count/games over STRICTLY EARLIER
     seasons in the loaded frame) when that history clears
     MIN_CAREER_OBS_FLOOR games; otherwise the season × position_group
     population rate (sum(count)/sum(n_obs) over all available peers that
     season), with a single dataset-wide scalar as a last-resort fallback
     for the rare case neither exists (a position group's first season in
     the corpus). See _K below for how k was derived from this session's
     measured overdispersion (phi) for each stat.

  3. An explicit volume signal alongside the rate: the raw season count is
     independently z-scored within season × position_group and blended
     50/50 with the z-scored shrunk rate:
       component_z = 0.5·z(shrunk_rate) + 0.5·z(raw_count)
     Rationale for 50/50: the task motivating this rebuild asked for both
     "how efficient" (rate, shrunk for reliability) and "how much" (volume)
     to matter, neither dominating — a 50/50 blend is the direct reading of
     that ask, and nothing measured this session argues for skewing it.

  4. SCALE CONSISTENCY (a judgment call worth flagging explicitly): once
     TFL/INT/FF become z-scored composites (component_z, ~N(0,1)) rather
     than shares (~0.0-0.3), blending them into one weighted sum alongside
     RAW tackle_share/sack_share would let the z-scored components dominate
     numerically before the weights even apply — a scale-mismatch bug, not
     a modeling choice. Fix: tackle_share and sack_share are now ALSO
     z-scored within season × position_group before the weighted blend, so
     all five inputs to IDI live on the same scale and the stated weights
     (0.23/0.26/0.16/0.20/0.16) apply as proportions of comparable
     quantities. This mirrors the pattern the outer DPVS-G composite
     already uses to combine TCS_z/IDI_z/WOWY_z (dpvs/composite.py) — now
     applied one layer down, inside IDI itself. One consequence: IDI's
     raw output ("idi") is now already close to standardized, so
     composite.py's own downstream `idi_z = zscore_within(idi)` step is a
     second, mostly-idempotent re-standardization — harmless (it's a
     strictly increasing linear transform within each season × position
     group, so within-group rank order from this file's "idi" column is
     preserved exactly by that second pass) and left in place unchanged
     rather than touching composite.py.

  Base weights (all five components available) — UNCHANGED from the
  2026-08-21 reweight, now applied to z-scored quantities instead of
  shares:
    IDI = 0.23·tackle_share_z + 0.26·tfl_component_z + 0.16·sack_share_z
          + 0.20·int_component_z + 0.16·ff_component_z

  tackle_share_z and tfl_component_z remain independently gated per
  player-season (may be unavailable); sack_share_z / int_component_z /
  ff_component_z are treated as always-computable (gold parquet covers
  1960+ for sack/int/ff) and default to a neutral 0.0 z when a row is
  missing from gold parquet entirely — the same fallback semantics the
  pre-2026-08-21 code used for these three, just on the new scale.
  Whichever of {tackle_share_z, tfl_component_z} are actually unavailable
  for a row get dropped from the weight dict and the rest renormalize
  proportionally (see _idi_row / _GATED_COMPONENTS).

See docs/framework_decisions.md §12 for the k-value derivation, the
validation re-run, and the honest verdict on whether this version clears
the YoY-stability bar the §11 attempt missed.
"""

from __future__ import annotations

import re
from pathlib import Path
import pandas as pd
import numpy as np

from .positions import map_position

GAMEBOOK_BASE  = Path.home() / "data/gamebooks_processed/teams"
GOLD_PARQUET   = Path.home() / "data/gold/player_season_card.parquet"

# 1967-1977 TFL, gated at build time by gamebooks_boxscores' own >=70%
# completeness-ratio test (see scripts/build_tfl_gated_corpus.py's docstring
# for exactly how — it imports and reuses that repo's own ratio code rather
# than re-deriving the formula). Columns: season, team, player, tfl_sum,
# games_qualified. NOT pre-floored by games_qualified — this file applies
# MIN_GAMES_QUALIFIED_FLOOR at load time.
GAMEBOOK_TFL_GATED_CORPUS = (
    Path(__file__).resolve().parent.parent
    / "data_output" / "tfl_gamebooks_gated_1967_1977.csv"
)

# 1978-1998 TFL, PFR pbp.csv-derived — the ONLY source for this era, but a
# confirmed undercount (see module docstring point 1). Columns include
# season, game_type, franchise_id, player, games, tfl, ...
PBP_TFL_CORPUS = (
    Path.home() / "github/football/gamebooks_boxscores/outputs"
    / "pfr_pbp_defensive_stats_1978_2025.csv"
)

# 1967-1977 tackle_share source (2026-08-21, see docs/framework_decisions.md
# §14): gamebooks_boxscores' completeness-ratio-gated corpus, direct
# structural mirror of GAMEBOOK_TFL_GATED_CORPUS above — same >=70% ratio
# gate, same roster-based name canonicalization, built by
# scripts/build_tackle_gated_corpus.py. Replaces the dead
# ~/data/gamebooks_processed/teams/ read (GAMEBOOK_BASE below) for this era
# only; that path does not exist on this machine, so load_all_gamebook_idi()
# always returned an empty frame and tackle_share_z fell through to
# pfr_tackle_share (essentially unpopulated pre-2001) for nearly all of
# 1967-1977. Columns: season, team, player, tackle_sum, games_qualified.
GAMEBOOK_TACKLE_GATED_CORPUS = (
    Path(__file__).resolve().parent.parent
    / "data_output" / "tackle_gamebooks_gated_1967_1977.csv"
)

# franchise_id -> pgd team code, for PBP_TFL_CORPUS's franchise_id column.
# Primary (non-alias) entries copied from gamebooks_boxscores'
# build_defensive_leaderboards.py ABBR_TO_FID, inverted — same franchise
# identity convention this file already uses everywhere else (_GOLD_TO_PGD,
# _GAMEBOOK_TEAMS), confirmed to cover all 28 franchises seen in that CSV.
_FID_TO_TEAM: dict[int, str] = {
    16: "atl", 4: "buf", 2: "chi", 3: "cin", 6: "cle", 11: "clt", 8: "crd",
    13: "dal", 5: "den", 20: "det", 21: "gnb", 10: "kan", 14: "mia",
    32: "min", 27: "nor", 23: "nwe", 17: "nyg", 19: "nyj", 31: "oti",
    15: "phi", 29: "pit", 24: "rai", 25: "ram", 9: "sdg", 28: "sea",
    1: "sfo", 7: "tam", 12: "was",
    # 2026-08-21 additions: the original 28-entry map above was built for
    # gamebooks_boxscores' 1967-1977 corpus, which never needed these four
    # genuinely-new-since-1977 franchises (not relocations of an existing
    # code the way LAC/LAR/LVR/IND are -- see _GOLD_TO_PGD above, which
    # already uses 'rav'/'htx' for exactly this reason). Needed now because
    # load_gold_stats_from_db() aggregates gold.player_game_stats across the
    # full 1967-2025 range, which does include them. franchise_id values
    # confirmed directly against gold.franchises.
    18: "jax",  # Jacksonville Jaguars (expansion 1995)
    22: "car",  # Carolina Panthers (expansion 1995)
    26: "rav",  # Baltimore Ravens (relocated Cleveland Browns lineage, 1996) -- distinct from clt/ind
    30: "htx",  # Houston Texans (expansion 2002) -- distinct from oti/ten
}

# ── empirical-Bayes shrinkage / gating constants (2026-08-21, see module
#    docstring point 2 and docs/framework_decisions.md §12) ─────────────────

# Floor before a 1967-1977 gamebooks-era player-season's TFL is trusted at
# all (point 2 of this rebuild's brief: "at least 4-6 games" — 4 chosen as
# the floor, not the target, since it already fully eliminates the
# degenerate 1-game/1-TFL=100%-rate cases found in this corpus).
MIN_GAMES_QUALIFIED_FLOOR = 4

# Floor of prior-season games before a player's OWN career rate is trusted
# as the empirical-Bayes prior (else fall back to the season × position
# population rate). Set equal to _K0 below (both anchored to "half a
# 16-game season") so the two floors read as one consistent judgment call,
# not two independently-chosen numbers.
MIN_CAREER_OBS_FLOOR = 8.0

# k derivation: this session's variance-decomposition found overdispersion
# phi (ratio of observed variance to pure-chance/Poisson variance) of 2.69
# (TFL), 1.57 (INT), 1.32 (FF) — TFL is the most reliable, individual-skill-
# driven signal of the three, FF the least (closest to pure chance, same
# reasoning that got FR dropped entirely). phi-1 is the "signal over the
# pure-chance floor of 1.0", so k (how many prior-weighted pseudo-games it
# takes to counterbalance one observed game) is set inversely proportional
# to (phi-1): k = K0 / (phi-1). K0=8.0 is a documented reference constant —
# roughly half an NFL season — chosen as the scale at which a "moderate"
# amount of same-season evidence should already compete with the prior;
# nothing measured this session pins down the absolute scale, only the
# relative ordering (TFL shrinks least, FF shrinks most), so K0 is a
# judgment call, not a fitted value.
# "tackle" phi added 2026-08-21 (§14): same method-of-moments quasi-Poisson
# dispersion estimate (season-pooled population rate as mu, Pearson
# chi-square / (N-1)), computed in scripts/build_tackle_gated_corpus.py's
# main() over the 7,262-row gated tackle corpus -> phi=4.872. Higher than
# TFL's 2.69, i.e. under this same framework tackle counts carry even more
# individual-skill signal relative to pure chance than TFL does (intuitive:
# tackle counts have far more observations per game than a rare event like
# TFL/sack/INT, so less of the season total is noise) -> tackle gets the
# LEAST shrinkage of the four rate components.
_PHI: dict[str, float] = {"tfl": 2.69, "int": 1.57, "ff": 1.32, "tackle": 4.872}
_K0 = 8.0
_K: dict[str, float] = {stat: _K0 / (phi - 1.0) for stat, phi in _PHI.items()}
# -> tfl≈4.73, int≈14.04, ff≈25.00, tackle≈2.07

ZSCORE_WINSOR = 4.0  # matches dpvs/composite.py's winsorization convention

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

# Base weights when ALL five components are available. UNCHANGED from the
# 2026-08-21 reweight (see docs/framework_decisions.md §11); now applied to
# z-scored components rather than raw shares (see module docstring point 4).
_W_BASE = {
    "tackle_share_z":  0.23,
    "tfl_component_z": 0.26,
    "sack_share_z":    0.16,
    "int_component_z": 0.20,
    "ff_component_z":  0.16,
}

# Components that are "presence-gated" per row (may be NaN and get dropped
# from the weighted average, with the remaining weights renormalized).
# sack_share_z/int_component_z/ff_component_z are always treated as
# computable (default to a neutral 0.0 z via _safe() when genuinely absent)
# since gold parquet covers them back to 1960.
_GATED_COMPONENTS = ("tackle_share_z", "tfl_component_z")


# ── gamebook tackle-share loader (unchanged from prior session) ─────────────

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


# ── Postgres-backed sources (2026-08-21 task-3 rewiring) ────────────────────
#
# football_db now has real per-game data behind three of this file's four
# file-based loaders: silver.player_game_stats_gamebook was reloaded this
# session with the same roster-based name resolver + completeness-ratio gate
# GAMEBOOK_TFL_GATED_CORPUS/GAMEBOOK_TACKLE_GATED_CORPUS were already built
# from (see football_db/scripts/ingest_gamebook_boxscores.py), and
# silver.player_game_stats_pfr was populated for the first time (previously
# EMPTY) with the same pbp.csv-derived, per-game data PBP_TFL_CORPUS was
# built from (see football_db/scripts/ingest_pfr_defensive_stats.py). Both
# tables carry the SAME underlying values as their CSV counterparts (same
# ratio gate, same undercount tier tags) — this is a storage-layer swap, not
# a methodology change. gold.player_game_stats (the reconciled merge of
# both) additionally now covers 1967-2025 for sack/int/fr/ff/comb_tackles/
# tfl, letting load_gold_stats() move off the legacy, CLAUDE.md-superseded
# ~/data/gold/player_season_card.parquet for that whole range too.
#
# Each function below queries Postgres first; on ANY connection/query
# failure it prints a warning and falls back to the original file-based
# loader, so a machine without football_db reachable still builds (just
# back on file data, same as before this rewiring). This is a genuine
# fallback for unavailability, not a silent quality trade-off — when
# Postgres IS reachable (the normal case), file data is never used for
# these four sources again.
#
# NOT rewired: dpvs/tcs.py's Team Credit Share (TDGS + opponent-quality
# adjustment) has no Postgres equivalent at all -- it's built from PFR
# team-level game files (team_stats.csv, scoring.csv, drives.csv, ...) via
# scripts/build_game_defense.py, a completely different pipeline from the
# player-level defensive-stat tables this session populated. gold.team_game_stats
# has rush/pass/sack counts (used as this task's own completeness-ratio
# denominator) but not TDGS's point-differential/opponent-adjusted scoring
# methodology. Building that in Postgres is a real, separate undertaking,
# out of this task's scope -- TCS stays 100% file-based. Similarly, seasons
# 1960-1966 (before gamebooks_boxscores' 1967-1977 corpus and before PFR's
# raw per-game files) have no Postgres source at all and always fall
# through load_gold_stats_from_db() to the legacy parquet for that narrow
# range, by design, not as an unhandled gap.

import sys as _sys  # noqa: E402

_FOOTBALL_DB_SRC = Path.home() / "github" / "football" / "football_db" / "src"
if str(_FOOTBALL_DB_SRC) not in _sys.path:
    _sys.path.insert(0, str(_FOOTBALL_DB_SRC))


def _pg_conn():
    """Returns a football_db connection, or None if unreachable (caller
    falls back to file-based loading — see section docstring above)."""
    try:
        from football_db.db import get_connection  # noqa: PLC0415
        return get_connection()
    except Exception as e:  # noqa: BLE001 -- deliberately broad: any failure means "use the file fallback"
        print(f"  [idi] Postgres unavailable ({e}) — falling back to file-based source")
        return None


def load_gamebook_tfl_from_db() -> pd.DataFrame | None:
    """Postgres equivalent of load_gamebook_tfl() (file version, below) --
    same >=70pct completeness-ratio gate (now stored per-row as
    completeness_qualified on silver.player_game_stats_gamebook itself
    rather than recomputed from boxscore.md text), same
    MIN_GAMES_QUALIFIED_FLOOR application at load time, same output shape.
    Returns None (not an empty frame) on connection failure, so the caller
    can distinguish "use the file fallback" from "DB reachable, genuinely
    no qualifying rows"."""
    conn = _pg_conn()
    if conn is None:
        return None
    try:
        df = pd.read_sql("""
            SELECT g.season AS season, gb.franchise_id AS franchise_id,
                   p.full_name AS player, sum(gb.tfl) AS tfl_count, count(*) AS n_obs
            FROM silver.player_game_stats_gamebook gb
            JOIN gold.games g ON g.game_id = gb.game_id
            JOIN gold.players p ON p.player_id = gb.player_id
            WHERE gb.completeness_qualified = true
            GROUP BY g.season, gb.franchise_id, p.full_name
        """, conn)
    finally:
        conn.close()
    df = df[df["n_obs"] >= MIN_GAMES_QUALIFIED_FLOOR].copy()
    df["team"] = df["franchise_id"].map(_FID_TO_TEAM)
    df = df.dropna(subset=["team"]).copy()
    df["tfl_tier"] = "gamebooks_boxscores_gated70pct"
    df["tfl_count"] = df["tfl_count"].fillna(0)
    return df[["season", "team", "player", "tfl_count", "n_obs", "tfl_tier"]]


def load_gamebook_tackle_from_db() -> pd.DataFrame | None:
    """Postgres equivalent of load_gamebook_tackle_gated() (file version,
    below) -- direct structural mirror of load_gamebook_tfl_from_db()."""
    conn = _pg_conn()
    if conn is None:
        return None
    try:
        df = pd.read_sql("""
            SELECT g.season AS season, gb.franchise_id AS franchise_id,
                   p.full_name AS player,
                   sum(coalesce(gb.solo_tackle, 0) + coalesce(gb.ast_tackle, 0)) AS tackle_count,
                   count(*) AS n_obs
            FROM silver.player_game_stats_gamebook gb
            JOIN gold.games g ON g.game_id = gb.game_id
            JOIN gold.players p ON p.player_id = gb.player_id
            WHERE gb.completeness_qualified = true
            GROUP BY g.season, gb.franchise_id, p.full_name
        """, conn)
    finally:
        conn.close()
    df = df[df["n_obs"] >= MIN_GAMES_QUALIFIED_FLOOR].copy()
    df["team"] = df["franchise_id"].map(_FID_TO_TEAM)
    df = df.dropna(subset=["team"]).copy()
    df["tackle_tier"] = "gamebooks_boxscores_gated70pct"
    return df[["season", "team", "player", "tackle_count", "n_obs", "tackle_tier"]]


def load_pfr_tfl_from_db() -> pd.DataFrame | None:
    """Postgres equivalent of load_pbp_tfl() (file version, below) --
    silver.player_game_stats_pfr covers 1978-2025 (not just 1978-1998, but
    filtered to that range below since 1999+ TFL comes from load_gold_stats
    instead, matching the file version's own filter)."""
    conn = _pg_conn()
    if conn is None:
        return None
    try:
        df = pd.read_sql("""
            SELECT season, franchise_id, p.full_name AS player,
                   sum(pfr.tfl) AS tfl_count, count(*) AS n_obs
            FROM silver.player_game_stats_pfr pfr
            JOIN gold.players p ON p.player_id = pfr.player_id
            WHERE pfr.season BETWEEN 1978 AND 1998 AND pfr.game_type = 'regular'
            GROUP BY season, franchise_id, p.full_name
        """, conn)
    finally:
        conn.close()
    df["team"] = df["franchise_id"].map(_FID_TO_TEAM)
    df = df.dropna(subset=["team"]).copy()
    df["tfl_tier"] = "pfr_pbp_undercount_1978_1998"
    df["tfl_count"] = df["tfl_count"].fillna(0)
    return df[["season", "team", "player", "tfl_count", "n_obs", "tfl_tier"]]


def load_gold_stats_from_db(seasons: list[int]) -> pd.DataFrame | None:
    """Postgres equivalent of load_gold_stats() (file version, below) for
    the sub-range of `seasons` covered by gold.player_game_stats
    (1967-2025 -- both silver sources combined). Seasons outside that range
    (pre-1967) are NOT included in the returned frame; the caller
    (load_gold_stats(), wrapping this function) fills those in from the
    legacy parquet so the combined result still covers every requested
    season."""
    conn = _pg_conn()
    if conn is None:
        return None
    try:
        # pgs."position" is NULL for every row sourced from
        # silver.player_game_stats_pfr (422,823/422,823 rows -- pbp.csv, its
        # stat source, carries no position field at all; confirmed 2026-08-22
        # while diagnosing the §16 YoY pooled-pair drop, see
        # docs/framework_decisions.md). It's only ever populated for the
        # 'gamebook' source (30,357/30,388). Backfill from
        # silver.player_team_seasons_pfr -- a real, already-populated,
        # season-level roster/position table (118,090 rows, 1921-2025, no
        # dup (player_id, franchise_id, season) keys) this query simply
        # never joined against -- rather than leaving 1978-2025 rows
        # position-less. Without this, any player-season whose TCS-side
        # "pos" is also blank (the 2001-2018 no-starters.csv gap, or a
        # position-split row whose dedup-chosen "primary" happened to be the
        # blank-pos one) falls to position_group="unknown" in
        # composite.py's build_composite() and is DROPPED from the final
        # table entirely -- not merely missing a stat, the whole
        # player-season disappears. This was the entire cause of §16's
        # 14,059->13,657 pooled YoY pair drop (401/402 pairs, zero gained,
        # concentrated 1997-2023 -- exactly this table's absence, not any
        # roster/resolver issue).
        df = pd.read_sql("""
            SELECT g.season AS season, pgs.franchise_id AS franchise_id,
                   p.full_name AS player_name, pgs.player_id AS player_id,
                   coalesce(pgs."position", pts.position) AS pos,
                   count(DISTINCT pgs.game_id) AS g,
                   sum(coalesce(pgs.sack, 0)) AS sk,
                   sum(coalesce(pgs.def_int, 0)) AS int,
                   sum(coalesce(pgs.fr, 0)) AS fr,
                   sum(coalesce(pgs.ff, 0)) AS ff,
                   sum(coalesce(pgs.comb_tackle, 0)) AS comb_tackles,
                   sum(coalesce(pgs.tfl, 0)) AS tfl
            FROM gold.player_game_stats pgs
            JOIN gold.games g ON g.game_id = pgs.game_id
            JOIN gold.players p ON p.player_id = pgs.player_id
            LEFT JOIN silver.player_team_seasons_pfr pts
                   ON pts.player_id = pgs.player_id
                  AND pts.franchise_id = pgs.franchise_id
                  AND pts.season = g.season
            WHERE g.season = ANY(%(seasons)s)
            GROUP BY g.season, pgs.franchise_id, p.full_name, pgs.player_id,
                     coalesce(pgs."position", pts.position)
        """, conn, params={"seasons": list(seasons)})
    finally:
        conn.close()
    if df.empty:
        return df
    df["team"] = df["franchise_id"].map(_FID_TO_TEAM)
    df = df.dropna(subset=["team"]).copy()
    # A player can have multiple `position` strings across a season's games
    # (subs, mid-season position notes) -- collapse to one row per
    # (season, team, player_name), keeping the most-frequent position and
    # summing everything else. This mirrors load_gold_stats()'s own
    # dup-collapse step for relocated franchises appearing twice.
    df = (
        df.sort_values("g", ascending=False)
        .groupby(["season", "team", "player_name"], as_index=False)
        .agg(player_id=("player_id", "first"), pos=("pos", "first"),
             g=("g", "sum"), sk=("sk", "sum"), int=("int", "sum"), fr=("fr", "sum"),
             ff=("ff", "sum"), comb_tackles=("comb_tackles", "sum"), tfl=("tfl", "sum"))
    )
    df = _compute_gold_shares(df)
    keep = ["season", "team", "player_id", "player_name", "pos", "g", "sk", "int", "fr", "ff",
            "comb_tackles", "tfl", "sack_share", "pfr_tackle_share", "pfr_tackle_source", "tackle_source"]
    df["tackle_source"] = "footballdb_gold_pergame"
    return df[[c for c in keep if c in df.columns]].copy()


def _compute_gold_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Team-total sack_share / pfr_tackle_share, factored out of
    load_gold_stats() so both the parquet path and the new DB path
    (load_gold_stats_from_db()) apply the identical share formula."""
    team_totals = df.groupby(["season", "team"], as_index=False).agg(
        team_sk=("sk", "sum"), team_comb_tkl=("comb_tackles", "sum"))
    df = df.merge(team_totals, on=["season", "team"], how="left")
    denom_sk = df["team_sk"].replace(0, np.nan)
    df["sack_share"] = (df["sk"] / denom_sk).clip(0, 1)
    meaningful = df["team_comb_tkl"] >= 50
    df["pfr_tackle_share"] = np.where(
        meaningful, (df["comb_tackles"] / df["team_comb_tkl"].replace(0, np.nan)).clip(0, 1), np.nan)
    if "pfr_tackle_source" not in df.columns:
        df["pfr_tackle_source"] = df.get("tackle_source", pd.Series("footballdb_gold_pergame", index=df.index))
    return df


# ── TFL raw-count loaders (2026-08-21 rebuild — three eras, all counts not
#    shares; see module docstring point 1) ──────────────────────────────────

def load_gamebook_tfl() -> pd.DataFrame:
    """
    1967-1977 TFL: gamebooks_boxscores' completeness-ratio-gated corpus
    (GAMEBOOK_TFL_GATED_CORPUS), floor-filtered at MIN_GAMES_QUALIFIED_FLOOR.

    Returns: season, team, player, tfl_count, n_obs, tfl_tier.
    2026-08-21: tries Postgres first (load_gamebook_tfl_from_db()) --
    see the "Postgres-backed sources" section above. Empty DataFrame
    (with a warning) if neither Postgres nor the corpus file is available.
    """
    db_df = load_gamebook_tfl_from_db()
    if db_df is not None:
        return db_df
    if not GAMEBOOK_TFL_GATED_CORPUS.exists():
        print(f"  [idi] WARNING: {GAMEBOOK_TFL_GATED_CORPUS} not found — "
              f"run scripts/build_tfl_gated_corpus.py first. 1967-1977 TFL "
              f"will be unavailable this build.")
        return pd.DataFrame(columns=["season", "team", "player", "tfl_count", "n_obs", "tfl_tier"])

    df = pd.read_csv(GAMEBOOK_TFL_GATED_CORPUS)
    df = df[df["games_qualified"] >= MIN_GAMES_QUALIFIED_FLOOR].copy()
    df = df.rename(columns={"tfl_sum": "tfl_count", "games_qualified": "n_obs"})
    df["tfl_tier"] = "gamebooks_boxscores_gated70pct"
    return df[["season", "team", "player", "tfl_count", "n_obs", "tfl_tier"]]


def load_gamebook_tackle_gated() -> pd.DataFrame:
    """
    1967-1977 tackle_share: gamebooks_boxscores' completeness-ratio-gated
    tackle corpus (GAMEBOOK_TACKLE_GATED_CORPUS), floor-filtered at
    MIN_GAMES_QUALIFIED_FLOOR — direct structural mirror of
    load_gamebook_tfl(). See docs/framework_decisions.md §14.

    Returns: season, team, player, tackle_count, n_obs, tackle_tier.
    2026-08-21: tries Postgres first (load_gamebook_tackle_from_db()) --
    see the "Postgres-backed sources" section above. Empty DataFrame
    (with a warning) if neither Postgres nor the corpus file is available.
    """
    db_df = load_gamebook_tackle_from_db()
    if db_df is not None:
        return db_df
    if not GAMEBOOK_TACKLE_GATED_CORPUS.exists():
        print(f"  [idi] WARNING: {GAMEBOOK_TACKLE_GATED_CORPUS} not found — "
              f"run scripts/build_tackle_gated_corpus.py first. 1967-1977 "
              f"tackle_share will fall through to pfr_tackle_share (essentially "
              f"unpopulated that far back) this build.")
        return pd.DataFrame(columns=["season", "team", "player", "tackle_count", "n_obs", "tackle_tier"])

    df = pd.read_csv(GAMEBOOK_TACKLE_GATED_CORPUS)
    df = df[df["games_qualified"] >= MIN_GAMES_QUALIFIED_FLOOR].copy()
    df = df.rename(columns={"tackle_sum": "tackle_count", "games_qualified": "n_obs"})
    df["tackle_tier"] = "gamebooks_boxscores_gated70pct"
    return df[["season", "team", "player", "tackle_count", "n_obs", "tackle_tier"]]


def load_pbp_tfl() -> pd.DataFrame:
    """
    1978-1998 TFL: gamebooks_boxscores' PFR pbp.csv-derived corpus — the
    ONLY source for this 21-season gap, but a confirmed undercount (see
    module docstring point 1). Every row is tagged tfl_tier=
    "pfr_pbp_undercount_1978_1998" so downstream consumers can filter or
    flag it rather than treat it as equal-confidence to the other two eras.

    Returns: season, team, player, tfl_count, n_obs, tfl_tier.
    2026-08-21: tries Postgres first (load_pfr_tfl_from_db()) -- see the
    "Postgres-backed sources" section above. Empty DataFrame (with a
    warning) if neither Postgres nor the corpus file is available.
    """
    db_df = load_pfr_tfl_from_db()
    if db_df is not None:
        return db_df
    if not PBP_TFL_CORPUS.exists():
        print(f"  [idi] WARNING: {PBP_TFL_CORPUS} not found — "
              f"1978-1998 TFL will be unavailable this build.")
        return pd.DataFrame(columns=["season", "team", "player", "tfl_count", "n_obs", "tfl_tier"])

    df = pd.read_csv(PBP_TFL_CORPUS)
    df = df[(df["season"] >= 1978) & (df["season"] <= 1998)]
    if "game_type" in df.columns:
        df = df[df["game_type"] == "regular"]
    df = df.groupby(["season", "franchise_id", "player"], as_index=False).agg(
        tfl_count=("tfl", "sum"), n_obs=("games", "sum"),
    )
    df["team"] = df["franchise_id"].map(_FID_TO_TEAM)
    df = df.dropna(subset=["team"]).copy()
    df["tfl_tier"] = "pfr_pbp_undercount_1978_1998"
    return df[["season", "team", "player", "tfl_count", "n_obs", "tfl_tier"]]


# ── gold parquet loader ────────────────────────────────────────────────────────

def load_gold_stats(seasons: list[int]) -> pd.DataFrame:
    """
    Load individual defensive stats from gold parquet.
    Returns per-player-season: sacks, ints, frs, ffs, games, tfl, plus
    sack_share (still a team-total share — sack reliability didn't motivate
    moving off shares the way TFL/INT/FF did).
    Also computes PFR tackle_share for seasons where comb_tackles is available
    (primarily 2001+, plus media-guide-patched seasons for earlier years).
    Gold team codes are uppercase (MIN, PIT); we lowercase them to match
    gamebook convention.

    2026-08-21: seasons within Postgres's now-populated range (1967-2025)
    are served by load_gold_stats_from_db(); any remaining requested
    seasons (only 1960-1966 in practice) fall back to this legacy parquet
    read, so the returned frame always covers every season requested --
    see the "Postgres-backed sources" section above for why 1960-1966
    can't be moved off the parquet yet.
    """
    db_df = load_gold_stats_from_db(seasons)
    file_seasons = seasons if db_df is None else sorted(set(seasons) - set(db_df["season"].unique()))
    if not file_seasons:
        return db_df

    df = pd.read_parquet(GOLD_PARQUET)
    df = df[df["season"].isin(file_seasons)].copy()
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
    for col in ("sk", "int", "fr", "ff", "comb_tackles", "tfl"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Team totals per season for sack_share only (TFL/INT/FF moved off
    # team-share in the 2026-08-21 rebuild — see module docstring).
    agg = {"team_sk": ("sk", "sum")}
    if "comb_tackles" in df.columns:
        agg["team_comb_tkl"] = ("comb_tackles", "sum")

    team_totals = df.groupby(["season", "team"], as_index=False).agg(**agg)
    df = df.merge(team_totals, on=["season", "team"], how="left")

    def _share(num_col: str, den_col: str) -> pd.Series:
        denom = df[den_col].replace(0, np.nan)
        return (df[num_col] / denom).clip(0, 1)

    df["sack_share"] = _share("sk", "team_sk")

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
        "g", "sk", "int", "fr", "ff", "comb_tackles", "tfl",
        "sack_share",
        "pfr_tackle_share", "pfr_tackle_source", "tackle_source",
    ]
    file_df = df[[c for c in keep if c in df.columns]].copy()
    if db_df is None or db_df.empty:
        return file_df
    # Combine Postgres-backed seasons (1967-2025) with whatever legacy
    # parquet seasons were actually requested (only 1960-1966 in practice
    # -- see this function's docstring).
    return pd.concat([db_df[[c for c in keep if c in db_df.columns]], file_df], ignore_index=True)


# ── z-score / empirical-Bayes helpers ────────────────────────────────────────

def _zscore_within_groups(df: pd.DataFrame, value_col: str, group_cols: list[str]) -> pd.Series:
    """Z-score value_col within each combination of group_cols. NaN stays NaN."""
    out = pd.Series(np.nan, index=df.index, dtype=float)
    for _, idx in df.groupby(group_cols, dropna=False).groups.items():
        sub = df.loc[idx, value_col]
        valid = sub.dropna()
        if len(valid) < 2:
            continue
        mu, sigma = valid.mean(), valid.std(ddof=1)
        if sigma == 0 or pd.isna(sigma):
            out.loc[valid.index] = 0.0
            continue
        out.loc[valid.index] = ((valid - mu) / sigma).clip(-ZSCORE_WINSOR, ZSCORE_WINSOR)
    return out


def _resolve_position_group(df: pd.DataFrame) -> pd.Series:
    """
    Same pos → gold_pos fallback pattern dpvs/composite.py uses downstream
    (needed here too, earlier in the pipeline, purely for within-IDI
    z-scoring — composite.py still computes its own authoritative
    position_group later, after multi-position dedup; the two can disagree
    on the small number of players who split time across positions within
    a season, which is an accepted, minor limitation of z-scoring inside
    compute_idi() rather than after dedup).
    """
    pos = df["pos"].fillna("") if "pos" in df.columns else pd.Series("", index=df.index)
    if "gold_pos" in df.columns:
        empty = pos.str.strip() == ""
        pos = pos.where(~empty, df["gold_pos"].fillna(""))
    return pos.apply(map_position)


def _add_rate_component(
    merged: pd.DataFrame,
    stat: str,
    count_col: str,
    nobs_col: str,
    tier_col: str | None,
) -> pd.DataFrame:
    """
    Build `{stat}_component_z` = 0.5·z(shrunk per-game rate) + 0.5·z(raw
    season count), both z-scored within season × _idi_pos_group, using
    empirical-Bayes shrinkage (k = _K[stat]) toward a career-to-date prior
    (falling back to season × position_group population rate, then a
    dataset-wide scalar). See module docstring points 2-3.

    merged must already have count_col, nobs_col, and _idi_pos_group.
    count_col/nobs_col are NaN where the stat is unavailable for that row.
    """
    df = merged
    avail = df[nobs_col].notna() & (df[nobs_col] > 0)

    # observed rate (NaN where unavailable)
    obs_rate = pd.Series(np.nan, index=df.index, dtype=float)
    obs_rate.loc[avail] = df.loc[avail, count_col] / df.loc[avail, nobs_col]

    # career-to-date prior: cumulative count/n_obs over strictly earlier
    # seasons in THIS loaded frame, keyed by pfr_player_id.
    sort_idx = df.sort_values(["pfr_player_id", "season"]).index
    count_sorted = df.loc[sort_idx, count_col].fillna(0)
    nobs_sorted = df.loc[sort_idx, nobs_col].fillna(0)
    grp = count_sorted.groupby(df.loc[sort_idx, "pfr_player_id"])
    prior_count = grp.transform(lambda s: s.shift(1).fillna(0).cumsum())
    grp_n = nobs_sorted.groupby(df.loc[sort_idx, "pfr_player_id"])
    prior_nobs = grp_n.transform(lambda s: s.shift(1).fillna(0).cumsum())
    prior_count = prior_count.reindex(df.index)
    prior_nobs = prior_nobs.reindex(df.index)

    career_prior_rate = pd.Series(np.nan, index=df.index, dtype=float)
    has_career = prior_nobs >= MIN_CAREER_OBS_FLOOR
    career_prior_rate.loc[has_career] = (
        prior_count.loc[has_career] / prior_nobs.loc[has_career]
    )

    # season × position_group population rate fallback
    pop = df.loc[avail].groupby(["season", "_idi_pos_group"]).apply(
        lambda g: g[count_col].sum() / g[nobs_col].sum() if g[nobs_col].sum() > 0 else np.nan
    )
    pop_rate = df.set_index(["season", "_idi_pos_group"]).index.map(pop)
    pop_rate = pd.Series(pop_rate, index=df.index, dtype=float)

    # dataset-wide scalar, last resort
    global_rate = (
        df.loc[avail, count_col].sum() / df.loc[avail, nobs_col].sum()
        if df.loc[avail, nobs_col].sum() > 0 else 0.0
    )

    prior_rate = career_prior_rate.fillna(pop_rate).fillna(global_rate)

    n_obs = df[nobs_col].fillna(0)
    k = _K[stat]
    shrunk_rate = pd.Series(np.nan, index=df.index, dtype=float)
    shrunk_rate.loc[avail] = (
        n_obs.loc[avail] * obs_rate.loc[avail] + k * prior_rate.loc[avail]
    ) / (n_obs.loc[avail] + k)

    tmp = df[["season", "_idi_pos_group"]].copy()
    tmp["_rate"] = shrunk_rate
    tmp["_count"] = df[count_col].where(avail)
    rate_z = _zscore_within_groups(tmp, "_rate", ["season", "_idi_pos_group"])
    count_z = _zscore_within_groups(tmp, "_count", ["season", "_idi_pos_group"])

    component_z = pd.Series(np.nan, index=df.index, dtype=float)
    both = rate_z.notna() & count_z.notna()
    component_z.loc[both] = 0.5 * rate_z.loc[both] + 0.5 * count_z.loc[both]

    df[f"{stat}_component_z"] = component_z
    df[f"{stat}_n_obs"] = df[nobs_col]
    df[f"{stat}_shrunk_rate"] = shrunk_rate
    if tier_col:
        df[f"idi_{stat}_source"] = df[tier_col].fillna("none")
    return df


def _safe(row: pd.Series, col: str) -> float:
    v = row.get(col)
    return float(v) if pd.notna(v) else 0.0


def _idi_row(row: pd.Series) -> float:
    """
    Compute IDI for a single player-season row from five z-scored
    components (see module docstring point 4 for why all five are z-scores,
    not a mix of shares and z-scores).

    tackle_share_z and tfl_component_z are each independently
    present-or-absent. Whichever are missing get dropped from _W_BASE and
    the remaining weights renormalize proportionally.
    """
    weights = dict(_W_BASE)
    for comp in _GATED_COMPONENTS:
        if pd.isna(row.get(comp)):
            weights.pop(comp, None)
    total_w = sum(weights.values())
    if total_w == 0:
        return np.nan

    score = 0.0
    for comp, w in weights.items():
        val = float(row[comp]) if comp in _GATED_COMPONENTS else _safe(row, comp)
        score += w * val
    return score / total_w


# ── IDI computation ────────────────────────────────────────────────────────────

def compute_idi(
    tcs_df: pd.DataFrame,
    gold_df: pd.DataFrame,
    gamebook_df: pd.DataFrame,
    gamebook_tfl_df: pd.DataFrame | None = None,
    pbp_tfl_df: pd.DataFrame | None = None,
    gamebook_tackle_gated_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Merge TCS player-season list with gold stats, gamebook tackle shares,
    and the three-era TFL raw-count sources, then compute IDI per
    player-season.

    Tackle share priority (highest → lowest):
      1. gamebook_tackle_gated_df — 2026-08-21 (§14): gamebooks_boxscores'
         completeness-ratio-gated 1967-1977 tackle corpus, floor-filtered.
         Unlike layers 2/3 below (a plain share, z-scored directly), this
         layer gets the SAME rate+shrinkage+volume treatment as
         TFL/INT/FF (_add_rate_component) — see module docstring point 1
         and docs/framework_decisions.md §14 for why: raw per-game rate
         shrunk toward a career/population prior, blended 50/50 with a
         z-scored raw count, is the pattern already established this
         session for exactly this kind of small-sample rare(ish)-event
         gamebook data. The resulting tackle_component_z is written
         directly into tackle_share_z for the rows it covers (still one
         scale, since z-scoring happens within season × position_group
         either way — no 1967-1977 row mixes the two treatments).
      2. gamebook_df — legacy ~/data/gamebooks_processed/teams/ read (a
         plain share). Kept for backward compatibility; in practice this
         path does not exist on this machine so gamebook_df is always
         empty and this layer never fires (see GAMEBOOK_BASE).
      3. PFR/media-guide comb_tackles (2001+ and some earlier seasons)
      4. No tackle data → tackle_share_z dropped from the IDI formula,
         weights rebalanced

    TFL source by era (mutually exclusive by season range, no priority
    conflict — see module docstring point 1):
      1967-1977: gamebook_tfl_df (gated corpus, floor-filtered)
      1978-1998: pbp_tfl_df (PFR pbp-derived, confirmed undercount, tagged)
      1999+:     gold parquet 'tfl' column

    gamebook_tfl_df / pbp_tfl_df / gamebook_tackle_gated_df are optional
    (default None → that source is simply unavailable) so existing callers
    keep working.

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
                 "sack_share", "g", "int", "ff", "tfl",
                 "pfr_tackle_share", "pfr_tackle_source", "tackle_source",
                 "gold_pos"]
    merged = tcs_df.merge(
        gold_df[[c for c in gold_cols if c in gold_df.columns]],
        on=["season", "team", "_name_key"],
        how="left",
    )

    # position_group for within-IDI z-scoring (see _resolve_position_group)
    merged["_idi_pos_group"] = _resolve_position_group(merged)

    # Layer 0: 1967-1977 gated gamebook tackle corpus (highest precision,
    # rate+shrinkage treatment — see compute_idi docstring and module
    # docstring point 1). Only marks idi_tackle_source here so Layer 2
    # (PFR fallback) below correctly skips rows this layer already covers;
    # the actual tackle_share_z value for these rows is written further
    # down, after tackle_component_z is computed by _add_rate_component.
    merged["tackle_share"] = np.nan
    merged["idi_tackle_source"] = "none"
    merged["_tackle_count"] = np.nan
    merged["_tackle_nobs"] = np.nan

    if gamebook_tackle_gated_df is not None and not gamebook_tackle_gated_df.empty:
        gtk = gamebook_tackle_gated_df.copy()
        gtk["_name_key"] = gtk["player"].str.lower().str.strip()
        gtk = gtk.rename(columns={"tackle_count": "_c3", "n_obs": "_n3", "tackle_tier": "_t3"})
        merged = merged.merge(
            gtk[["season", "team", "_name_key", "_c3", "_n3", "_t3"]],
            on=["season", "team", "_name_key"], how="left",
        )
        hit = merged["_n3"].notna()
        merged.loc[hit, "_tackle_count"] = merged.loc[hit, "_c3"]
        merged.loc[hit, "_tackle_nobs"] = merged.loc[hit, "_n3"]
        merged.loc[hit, "idi_tackle_source"] = merged.loc[hit, "_t3"]
        merged.drop(columns=["_c3", "_n3", "_t3"], inplace=True)

    # Layer 1: legacy gamebook tackle share (dead path on this machine —
    # gamebook_df is always empty in practice; kept for compatibility).
    if not gamebook_df.empty:
        gamebook_df = gamebook_df.copy()
        gamebook_df["_name_key"] = gamebook_df["player"].str.lower().str.strip()
        gb_key = gamebook_df[["season", "team", "_name_key", "tackle_share"]].copy()
        gb_key = gb_key.rename(columns={"tackle_share": "_gb_ts"})
        merged = merged.merge(gb_key, on=["season", "team", "_name_key"], how="left")
        no_tackle = merged["idi_tackle_source"] == "none"
        has_gb = no_tackle & pd.notna(merged["_gb_ts"])
        merged.loc[has_gb, "tackle_share"] = merged.loc[has_gb, "_gb_ts"]
        merged.loc[has_gb, "idi_tackle_source"] = "gamebook"
        merged.drop(columns=["_gb_ts"], inplace=True)

    # Layer 2: PFR / media-guide tackle share (fills gaps not covered by
    # layers 0/1)
    if "pfr_tackle_share" in merged.columns:
        no_tackle = merged["idi_tackle_source"] == "none"
        has_pfr = no_tackle & pd.notna(merged["pfr_tackle_share"])
        merged.loc[has_pfr, "tackle_share"] = merged.loc[has_pfr, "pfr_tackle_share"]
        merged.loc[has_pfr, "idi_tackle_source"] = merged.loc[has_pfr, "pfr_tackle_source"].fillna("pfr")

    merged["tackle_share_z"] = _zscore_within_groups(
        merged.assign(_ts=merged["tackle_share"]), "_ts", ["season", "_idi_pos_group"]
    )

    # Layer 0 (cont'd): overwrite tackle_share_z for gated-corpus rows with
    # the rate+shrinkage+volume component_z, same _add_rate_component
    # machinery as TFL/INT/FF (module docstring point 1). tier_col=None
    # here deliberately -- _add_rate_component would otherwise overwrite
    # idi_tackle_source (already set above) for every row, including the
    # non-1967-1977 rows this layer doesn't cover.
    merged = _add_rate_component(merged, "tackle", "_tackle_count", "_tackle_nobs", None)
    has_gated_tackle = merged["_tackle_nobs"].notna()
    merged.loc[has_gated_tackle, "tackle_share_z"] = merged.loc[has_gated_tackle, "tackle_component_z"]

    merged["sack_share_z"] = _zscore_within_groups(
        merged, "sack_share", ["season", "_idi_pos_group"]
    )

    # ── TFL raw count + n_obs, by era (mutually exclusive season ranges) ───
    merged["_tfl_count"] = np.nan
    merged["_tfl_nobs"] = np.nan
    # object dtype (not np.nan/float64) -- this column later receives string
    # tier labels via .loc assignment; a float64-initialized column raises
    # pandas.errors.LossySetitemError under this environment's pandas/Arrow
    # string-dtype defaults (pre-existing latent bug, hit and fixed here
    # 2026-08-21 while wiring in the §14 tackle_share wiring -- unrelated to
    # that change but blocked being able to run/test it).
    merged["_tfl_tier"] = pd.Series(pd.NA, index=merged.index, dtype="object")

    if gamebook_tfl_df is not None and not gamebook_tfl_df.empty:
        gb = gamebook_tfl_df.copy()
        gb["_name_key"] = gb["player"].str.lower().str.strip()
        gb = gb.rename(columns={"tfl_count": "_c1", "n_obs": "_n1", "tfl_tier": "_t1"})
        merged = merged.merge(
            gb[["season", "team", "_name_key", "_c1", "_n1", "_t1"]],
            on=["season", "team", "_name_key"], how="left",
        )
        hit = merged["_n1"].notna()
        merged.loc[hit, "_tfl_count"] = merged.loc[hit, "_c1"]
        merged.loc[hit, "_tfl_nobs"] = merged.loc[hit, "_n1"]
        merged.loc[hit, "_tfl_tier"] = merged.loc[hit, "_t1"]
        merged.drop(columns=["_c1", "_n1", "_t1"], inplace=True)

    if pbp_tfl_df is not None and not pbp_tfl_df.empty:
        pb = pbp_tfl_df.copy()
        pb["_name_key"] = pb["player"].str.lower().str.strip()
        pb = pb.rename(columns={"tfl_count": "_c2", "n_obs": "_n2", "tfl_tier": "_t2"})
        merged = merged.merge(
            pb[["season", "team", "_name_key", "_c2", "_n2", "_t2"]],
            on=["season", "team", "_name_key"], how="left",
        )
        hit = merged["_tfl_nobs"].isna() & merged["_n2"].notna()
        merged.loc[hit, "_tfl_count"] = merged.loc[hit, "_c2"]
        merged.loc[hit, "_tfl_nobs"] = merged.loc[hit, "_n2"]
        merged.loc[hit, "_tfl_tier"] = merged.loc[hit, "_t2"]
        merged.drop(columns=["_c2", "_n2", "_t2"], inplace=True)

    if "tfl" in merged.columns and "g" in merged.columns:
        gold_hit = merged["_tfl_nobs"].isna() & merged["season"].ge(1999) & merged["g"].notna() & (merged["g"] > 0)
        merged.loc[gold_hit, "_tfl_count"] = merged.loc[gold_hit, "tfl"]
        merged.loc[gold_hit, "_tfl_nobs"] = merged.loc[gold_hit, "g"]
        merged.loc[gold_hit, "_tfl_tier"] = "gold_1999plus"

    merged = _add_rate_component(merged, "tfl", "_tfl_count", "_tfl_nobs", "_tfl_tier")

    # ── INT / FF raw count + n_obs (gold parquet, all eras 1960+) ──────────
    merged["_int_nobs"] = merged["g"] if "g" in merged.columns else np.nan
    merged["_ff_nobs"] = merged["g"] if "g" in merged.columns else np.nan
    merged = _add_rate_component(merged, "int", "int", "_int_nobs", None)
    merged = _add_rate_component(merged, "ff", "ff", "_ff_nobs", None)

    merged["idi"] = merged.apply(_idi_row, axis=1)
    merged["idi_has_tackles"] = pd.notna(merged["tackle_share_z"])
    merged["idi_has_tfl"] = pd.notna(merged["tfl_component_z"])
    merged.drop(columns=[
        "_name_key", "_idi_pos_group", "_tfl_count", "_tfl_nobs", "_tfl_tier",
        "_int_nobs", "_ff_nobs", "_tackle_count", "_tackle_nobs",
    ], inplace=True, errors="ignore")
    return merged
