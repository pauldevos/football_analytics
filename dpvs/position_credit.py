"""
Position-weighted TCS credit computation -- takes the cached ingredients
table (scripts/build_tcs_ingredients.py) and a tier-decay ratio, and
produces the new `team_credit_share` value per (game, team, participant):

  player_run_credit  = run_weight  * (player's share of run_family's  RUN
                        numerator, within this game/team)  * game run_points
  player_pass_credit = pass_weight * (player's share of pass_family's PASS
                        numerator, within this game/team)  * game pass_points
  team_credit_share   = player_run_credit + player_pass_credit

Fallback rules (never guess a weight -- see module docstring in
build_tcs_ingredients.py and build_fine_position_map.py for the sourcing):
  - Unknown scheme for a (team, season): the WHOLE team side that game falls
    back to the original flat split (tdgs / n_participants) for every
    participant -- there is no weight table to use without knowing 3-4/4-3.
  - Known scheme, unresolved individual position: just that player falls
    back to the flat split (tdgs / n_participants) for that one game-row;
    teammates with a resolved position still get the weighted computation.
  - A family's numerator sums to 0 for a game (nobody in the group recorded
    a qualifying event): equal split of that family's credit across its
    members present that game (never a forced 0, never a guessed
    attribution to one player).

PASS numerator mix by family (documented judgment call, per the task's own
"use judgement, document your choice" instruction) -- event-point weights:
  sack=1.0, tfl=1.0, ff=1.0, int=3.0 (rare/high-value), pd=1.0,
  tackle=0.25 (common/low marginal value, but still real pass-down
  responsibility signal for coverage/MLB positions):
    DE / OLB (edge)    = sack + tfl + ff                  (task-specified)
    CB_FS / SS / DB    = 0.25*tackle + 3*int + pd          (task-specified)
    MLB                = 0.25*tackle + 1*sack + 3*int      (reasonable mix)
    DT                 = 1*sack + 0.1*tackle               (reasonable mix)
RUN numerator is always just the tackle count (game-level when the season's
player_defense.csv reliably carries tackles_combined, i.e. season>=1999;
else the season_tackle_count proxy, applied uniformly across the player's
games that season -- see build_tcs_ingredients.py's module docstring for
why: pre-1999 PFR boxscores don't carry per-game tackle counts at all).

DB-GROUP DYNAMIC PASS SUB-SPLIT -- BUILT 2026-08-23, REVERTED SAME DAY.
A prior version of this module scaled the DB tier's TOTAL share of a game's
pass credit up/down by that game's real DB activity + team pass performance
(with the rest of the pass tier rescaled to compensate). The user corrected
this directly: position-group weights (NT/MLB/DE/OLB/DB/etc.) are meant to
stay fixed and consistent across all teams and all seasons -- what should
move with real per-game stats is only which INDIVIDUAL players within a
fixed-weight group split that group's share, never the group's share itself.
That individual-level split is exactly what `run_share`/`pass_share` below
already do (an individual's numerator over their family's summed numerator,
within game/team/family) -- it was already correct before this addition and
needed no dynamic group-weight layer on top of it. Removed; `_pass_w` is
used unadjusted, same as `_run_w`.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from .position_weights import get_weights

RUN_LABEL_TO_FAMILY_WEIGHT_KEY = {
    # run_pos_label -> the literal weight-table key for THIS player (side-
    # specific where known); run_family (see build_tcs_ingredients.py) is
    # the broader pooling group used for share computation, kept separate.
    "LDE": "LDE", "RDE": "RDE", "DE_AVG": None,   # None -> average at lookup time
    "LOLB": "LOLB", "ROLB": "ROLB", "OLB_AVG": None,
    "DE": "DE", "OLB": "OLB", "MLB": "MLB", "NT": "NT", "DT": "DT",
    "SS": "SS", "FS+CB": "FS+CB", "SS_FSCB_AVG": None,
}
PASS_LABEL_DIRECT = {"DE", "OLB", "MLB", "DT", "CB", "FS", "SS", "DB"}


def _run_weight(scheme: str, run_pos_label: str, weights: dict[str, float]) -> float | None:
    key = RUN_LABEL_TO_FAMILY_WEIGHT_KEY.get(run_pos_label)
    if key is not None:
        return weights.get(key)
    # side/role-unknown -> average of the two side weights
    if run_pos_label == "DE_AVG":
        vals = [weights.get(k) for k in (("LDE", "RDE") if scheme == "4-3" else ("DE",))]
    elif run_pos_label == "OLB_AVG":
        vals = [weights.get(k) for k in (("LOLB", "ROLB") if scheme == "4-3" else ("OLB",))]
    elif run_pos_label == "SS_FSCB_AVG":
        vals = [weights.get("SS"), weights.get("FS+CB")]
    else:
        return None
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def _pass_weight(scheme: str, pass_pos_label: str, weights: dict[str, float]) -> float | None:
    if pass_pos_label in PASS_LABEL_DIRECT:
        return weights.get(pass_pos_label)
    if pass_pos_label == "SS_FS_AVG":  # secondary, side unknown, 4-3 scheme
        vals = [weights.get("SS"), weights.get("FS")]
        vals = [v for v in vals if v is not None]
        return sum(vals) / len(vals) if vals else None
    return None


def _num(v) -> float:
    return 0.0 if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


def _pass_numerator(row) -> float:
    fam = row.get("pass_family")
    tackle = _num(row.get("_tackle_signal"))
    sack = _num(row.get("sacks"))
    ff = _num(row.get("fumbles_forced"))
    tfl = _num(row.get("tackles_loss"))
    intc = _num(row.get("def_int"))
    pd_ = _num(row.get("pass_defended"))
    if fam == "DE" or fam == "OLB":
        return sack + tfl + ff
    if fam in ("CB_FS", "SS", "SS_CBFS", "DB"):
        return 0.25 * tackle + 3.0 * intc + pd_
    if fam == "MLB":
        return 0.25 * tackle + sack + 3.0 * intc
    if fam == "DT":
        return sack + 0.1 * tackle
    return 0.0


def compute_credit(ingredients: pd.DataFrame, decay: float = 0.65) -> pd.DataFrame:
    """
    Returns a copy of `ingredients` with two new columns:
      team_credit_share       -- the new position-weighted credit (or flat
                                  fallback where scheme/position unresolved)
      credit_method            -- 'weighted' / 'flat_no_scheme' / 'flat_unresolved_pos'
    """
    df = ingredients.copy()

    # RUN numerator: real per-game tackles when reliable, else season proxy.
    df["_tackle_signal"] = np.where(
        df["has_pergame_tackles"] & df["tackles_combined"].notna(),
        df["tackles_combined"],
        df["season_tackle_count"],
    )
    df["_tackle_signal"] = df["_tackle_signal"].fillna(0.0)

    df["_pass_numerator"] = df.apply(_pass_numerator, axis=1)

    # Cache weight tables per scheme (avoid rebuilding per-row)
    wt_cache: dict[tuple[str, str], dict[str, float]] = {}

    def _weights(scheme, phase):
        key = (scheme, phase)
        if key not in wt_cache:
            wt_cache[key] = get_weights(scheme, phase, decay=decay)
        return wt_cache[key]

    resolved = df["scheme"].notna() & df["run_pos_label"].notna() & df["pass_pos_label"].notna()
    df["credit_method"] = np.where(df["scheme"].isna(), "flat_no_scheme",
                            np.where(~resolved, "flat_unresolved_pos", "weighted"))

    # Per-row weight lookups (small df per season, acceptable cost)
    def _row_weights(r):
        if r["credit_method"] != "weighted":
            return pd.Series({"_run_w": np.nan, "_pass_w": np.nan})
        rw = _weights(r["scheme"], "run")
        pw = _weights(r["scheme"], "pass")
        return pd.Series({
            "_run_w": _run_weight(r["scheme"], r["run_pos_label"], rw),
            "_pass_w": _pass_weight(r["scheme"], r["pass_pos_label"], pw),
        })

    wcols = df.apply(_row_weights, axis=1)
    df["_run_w"], df["_pass_w"] = wcols["_run_w"], wcols["_pass_w"]

    # Family-share denominators, within (game_id, team, family), weighted rows only
    wdf = df[df["credit_method"] == "weighted"].copy()

    run_denom = wdf.groupby(["game_id", "team", "run_family"])["_tackle_signal"].transform("sum")
    run_n = wdf.groupby(["game_id", "team", "run_family"])["_tackle_signal"].transform("count")
    run_share = np.where(run_denom > 0, wdf["_tackle_signal"] / run_denom, 1.0 / run_n)

    pass_denom = wdf.groupby(["game_id", "team", "pass_family"])["_pass_numerator"].transform("sum")
    pass_n = wdf.groupby(["game_id", "team", "pass_family"])["_pass_numerator"].transform("count")
    pass_share = np.where(pass_denom > 0, wdf["_pass_numerator"] / pass_denom, 1.0 / pass_n)

    # Group weights (_run_w, _pass_w) are static per (scheme, position) --
    # see module docstring for why no per-game group-level adjustment is
    # applied here. Only the individual's share WITHIN their fixed-weight
    # family (run_share / pass_share above) moves with real game stats.
    run_credit = wdf["_run_w"].fillna(0) * run_share * wdf["run_points"].fillna(0)
    pass_credit = wdf["_pass_w"].fillna(0) * pass_share * wdf["pass_points"].fillna(0)

    df.loc[wdf.index, "team_credit_share"] = (run_credit + pass_credit).round(5)
    df.loc[wdf.index, "_run_share"] = run_share
    df.loc[wdf.index, "_pass_share"] = pass_share

    # Flat fallback rows (unknown scheme or unresolved position)
    flat_mask = df["credit_method"] != "weighted"
    df.loc[flat_mask, "team_credit_share"] = (
        df.loc[flat_mask, "tdgs"] / df.loc[flat_mask, "n_participants"]
    ).round(5)

    return df
