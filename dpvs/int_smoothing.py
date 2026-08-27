"""
INT trailing-window career-average smoothing -- Part B of the 2026-08-24
TCS/INT session (docs/framework_decisions.md's newest dated section).

Problem (user, verbatim): a rare, one-off big INT season (Charlie West's
1971, 7 INT with no sustained track record) shouldn't get full credit the
way a player with a genuinely stable multi-year INT rate does. IDI's
existing empirical-Bayes shrinkage (dpvs/idi.py) already pulls a season's
rate toward a career/population prior, but uses one FIXED population-wide k
per stat -- it can't distinguish "7 years of real 5+ INT/season history"
from "one outlier year with none before or after." This module is scoped to
INT ONLY, per the task -- not applied to sacks/pfr_tfl/FF/FR (this module
tests against fit_idi_additive_weights.py's additive formula, which is fit
on PFR's own official, sack-inclusive tackles_loss stat -- see that
script's STAT_COLS comment -- not dpvs/idi.py's own run_stuff component;
this module never touches idi.py at all, per the next paragraph).

NOT wired into dpvs/idi.py's live _W_BASE or z-score mechanism (out of
scope, same standing as the additive formula in framework_decisions.md
§25) -- this is a standalone alternative, tested by substituting the
smoothed INT count into scripts/fit_idi_additive_weights.py's already-fit
additive formula (score = ... + 0.6808*int) in place of the raw single-
season count, keeping every other weight (including INT's own 0.6808
coefficient) unchanged. This isolates the smoothing's own effect rather
than confounding it with a full refit.

Source: PFR's own official season-defense tables
(~/data/pfref/raw/season/player/defense/defense_{year}.csv), 1950-2025 on
disk -- the same source scripts/fit_idi_additive_weights.py already uses
for the modern-era fit, and the same source
scripts/apply_idi_additive_weights_gamebook_era.py uses for sacks/int/fr in
the three gamebook-era spot-check team-seasons. INT is populated in this
file for every season back to 1950 (confirmed directly), so a real trailing
window -- not a proxy -- is computable for any player-season in this
project's full range, including the three gamebook-era spot checks.

Multi-team ("2TM"/"3TM") dedup: identical convention to
fit_idi_additive_weights.py's load_season_defense() -- keep the season-
aggregate row, drop the per-team split rows.

Trailing window definition: for player-season (player_id, season), average
INT over seasons [season-(N-1), season] -- i.e. this season plus the prior
N-1 -- using ONLY seasons at or before `season` (strictly trailing, no
look-ahead leakage, so this is safe for season-by-season historical
ranking). If fewer than N seasons of real history exist (rookie years,
career start), average over whatever IS available rather than requiring a
full N-season window -- e.g. a player's 3rd season with N=5 requested
averages over 3 real seasons, not 5 (with 2 treated as 0 or padded).
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

PFREF_DEFENSE_DIR = Path.home() / "data/pfref/raw/season/player/defense"
MULTITEAM_RE = re.compile(r"^\d+TM$")


def _load_one_season_int(season: int) -> pd.DataFrame:
    path = PFREF_DEFENSE_DIR / f"defense_{season}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["season", "player_id", "player_name", "int"])
    df = pd.read_csv(path)
    if "team_abbrev" not in df.columns and "team" in df.columns:
        df = df.rename(columns={"team": "team_abbrev", "player": "player_name"})
    df = df[df["player_id"].notna()].copy()

    df["_is_multiteam_agg"] = df["team_abbrev"].astype(str).str.match(MULTITEAM_RE)
    has_agg = df.groupby("player_id")["_is_multiteam_agg"].transform("any")
    df = df[df["_is_multiteam_agg"] | ~has_agg].copy()
    df = df.drop_duplicates(subset=["player_id"])  # belt-and-suspenders

    df["int"] = pd.to_numeric(df["int"], errors="coerce").fillna(0)
    df["season"] = season
    return df[["season", "player_id", "player_name", "int"]]


def load_int_history(season_lo: int = 1950, season_hi: int = 2025) -> pd.DataFrame:
    """One row per (player_id, season) with that season's real official INT
    count, PFR season-defense source, every season with a file on disk in
    [season_lo, season_hi]."""
    frames = [_load_one_season_int(s) for s in range(season_lo, season_hi + 1)]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True)


def add_trailing_int(history: pd.DataFrame, windows: tuple[int, ...] = (5, 7)) -> pd.DataFrame:
    """
    Adds int_smooth{N} columns to `history` (must have season, player_id,
    int) -- the strictly-trailing N-season average described in the module
    docstring, computed per player via a sorted rolling mean (min_periods=1
    so early-career seasons average over whatever's actually available).
    """
    out = history.sort_values(["player_id", "season"]).copy()
    for n in windows:
        out[f"int_smooth{n}"] = (
            out.groupby("player_id")["int"]
               .transform(lambda s: s.rolling(window=n, min_periods=1).mean())
        )
    return out


def player_int_trace(history: pd.DataFrame, player_id: str) -> pd.DataFrame:
    """Convenience: one player's full season-by-season int + smoothed trace."""
    sub = history[history["player_id"] == player_id].sort_values("season")
    return add_trailing_int(sub)
