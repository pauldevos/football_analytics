"""
TCS credit computation -- Part A redesign, 2026-08-24 (docs/
framework_decisions.md's newest dated section).

REPLACES the entire individual-production-based share-splitting mechanism
this module used to implement (run_share/pass_share weighted by a player's
own sacks/tackles/run stuff/etc. that game). Per the user's direct instruction
this session: "Now given they are already getting IDI stats for this
game, it's more about how to give the group those points... I know we
discussed trying to attribute these with counting stats too, but that's
double counting. I think we need to probably just stick with the group
stuff." A player's own production is already rewarded by IDI (Layer 2) --
weighting TCS credit by that SAME production a second time double-counts
it across two layers.

NEW mechanism: every player who occupies a tier ROLE in a game gets a
FIXED point value for that role (dpvs/position_weights.py's ROLE_TABLES,
not scaled by anything the player personally did that game), multiplied by
the TEAM's real run/pass defensive performance that game
(dpvs/run_pass_points.py's run_points_earned/pass_points_earned, untouched
by this task) and a role_share:

    player_run_credit  = run_role_points  * run_points_earned  * run_role_share
    player_pass_credit = pass_role_points * pass_points_earned * pass_role_share
    team_credit_share    = player_run_credit + player_pass_credit

role_share -- PRORATION BASIS CHANGED FROM PRODUCTION TO CAPACITY:
    role_share = min(1.0, role_capacity / n_players_sharing_this_exact_
                           resolved_role_label_for_this_team_this_game)
role_capacity is "how many players normally carry this exact resolved
label in one team's one game" (e.g. 1 for a side-specific slot like LDE,
2 for a side-pooled slot like a 3-4's undifferentiated "DE" label or a
4-3's two-CB "CB" label) -- see position_weights.py's ROLE_TABLES
docstring for the exact capacity chosen per role, including two DT-
specific asymmetries (dt_technique.py's "other"/uncited bucket gets
capacity 2, not 1, so two anonymous DTs on the same team don't each get
penalized relative to a team with one confirmed player -- see that
module's docstring for why).

This is the ONLY proration this mechanism applies, and it is the honest
answer to the task's own question ("if real per-game snap counts aren't
available for this era, use games-played-that-week as a coarser proxy...
document whichever proxy you use"): real per-game SNAP counts do not exist
anywhere in this project's data for any era (confirmed by inspection --
gold.player_game_stats/silver.player_game_stats_pfr have no snap-count
column, and neither does the gamebook-era corpus). The available
granularity is coarser still than "games played that week" -- it is
"did this player record a participant row (a stat line or a named starter
credit) in THIS specific game." Equal-split-by-headcount among however
many players carry a role's label in one game (capped by that role's own
physical capacity) is the finest proration this project's actual data
supports; it is not weighted by production (that would reintroduce the
exact double-counting this redesign removes).

Fallback rules (unchanged from the pre-redesign mechanism -- never guess a
weight, see build_tcs_ingredients.py / build_fine_position_map.py for the
sourcing):
  - Unknown scheme for a (team, season): the WHOLE team side that game
    falls back to the original flat split (tdgs / n_participants).
  - Known scheme, unresolved individual position: just that player falls
    back to the flat split for that one game-row.
"""
from __future__ import annotations

import pandas as pd
import numpy as np

from .position_weights import ROLE_TABLES
from .dt_technique import resolve_dt_technique


def _resolve_run_role(row) -> str | None:
    label = row.get("run_pos_label")
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return None
    if label == "DT":
        # Only the 4-3's undifferentiated interior-DT bucket routes through
        # here (a 3-4's sole interior lineman is always labeled "NT", never
        # "DT" -- see build_fine_position_map.py's BUCKET_TO_LABELS). RUN
        # only distinguishes confirmed-1-technique from everyone else (no
        # separate "3-technique" RUN value -- see position_weights.py's
        # ROLE_TABLES docstring, judgment call #2).
        technique = resolve_dt_technique(row.get("_bare_pfr_id"), row.get("team"))
        return "DT_1TECH" if technique == "1-technique" else "DT_OTHER"
    return label


def _resolve_pass_role(row) -> str | None:
    label = row.get("pass_pos_label")
    if label is None or (isinstance(label, float) and pd.isna(label)):
        return None
    if label == "DT":
        technique = resolve_dt_technique(row.get("_bare_pfr_id"), row.get("team"))
        if technique == "1-technique":
            return "DT_1TECH"
        if technique == "3-technique":
            return "DT_3TECH"
        return "DT_OTHER"
    return label


def compute_credit(ingredients: pd.DataFrame, decay: float = 0.65) -> pd.DataFrame:
    """
    Returns a copy of `ingredients` with two new columns:
      team_credit_share  -- the new fixed-role-points credit (or flat
                             fallback where scheme/position unresolved)
      credit_method       -- 'weighted' / 'flat_no_scheme' / 'flat_unresolved_pos'

    `decay` is accepted for call-signature compatibility with the pre-
    redesign version (scripts/apply_tcs_position_credit.py's --decay flag)
    but is UNUSED here -- ROLE_TABLES' point values are literal, given/
    derived constants, not decay-regenerated at compute time (see
    position_weights.py's ROLE_TABLES docstring). A non-default decay is
    a no-op; kept only so the calling script doesn't need to change.
    """
    df = ingredients.copy()

    resolved = df["scheme"].notna() & df["run_pos_label"].notna() & df["pass_pos_label"].notna()
    df["credit_method"] = np.where(df["scheme"].isna(), "flat_no_scheme",
                            np.where(~resolved, "flat_unresolved_pos", "weighted"))

    wdf = df[df["credit_method"] == "weighted"].copy()
    if not wdf.empty:
        wdf["_run_role"] = wdf.apply(_resolve_run_role, axis=1)
        wdf["_pass_role"] = wdf.apply(_resolve_pass_role, axis=1)

        def _lookup(scheme, phase, role):
            if role is None:
                return (np.nan, np.nan)
            table = ROLE_TABLES.get((scheme, phase), {})
            return table.get(role, (np.nan, np.nan))

        run_lu = wdf.apply(lambda r: _lookup(r["scheme"], "run", r["_run_role"]), axis=1)
        wdf["_run_points_val"] = [v[0] for v in run_lu]
        wdf["_run_capacity"] = [v[1] for v in run_lu]

        pass_lu = wdf.apply(lambda r: _lookup(r["scheme"], "pass", r["_pass_role"]), axis=1)
        wdf["_pass_points_val"] = [v[0] for v in pass_lu]
        wdf["_pass_capacity"] = [v[1] for v in pass_lu]

        # Capacity-based role_share: min(1.0, capacity / n_sharing_this_role
        # for this (game_id, team) this game) -- see module docstring.
        run_n = wdf.groupby(["game_id", "team", "_run_role"])["_run_role"].transform("count")
        wdf["_run_role_share"] = np.minimum(1.0, wdf["_run_capacity"] / run_n)

        pass_n = wdf.groupby(["game_id", "team", "_pass_role"])["_pass_role"].transform("count")
        wdf["_pass_role_share"] = np.minimum(1.0, wdf["_pass_capacity"] / pass_n)

        run_credit = (wdf["_run_points_val"].fillna(0)
                      * wdf["run_points"].fillna(0)
                      * wdf["_run_role_share"].fillna(0))
        pass_credit = (wdf["_pass_points_val"].fillna(0)
                       * wdf["pass_points"].fillna(0)
                       * wdf["_pass_role_share"].fillna(0))

        df.loc[wdf.index, "team_credit_share"] = (run_credit + pass_credit).round(5)
        df.loc[wdf.index, "_run_role"] = wdf["_run_role"]
        df.loc[wdf.index, "_pass_role"] = wdf["_pass_role"]
        df.loc[wdf.index, "_run_role_share"] = wdf["_run_role_share"]
        df.loc[wdf.index, "_pass_role_share"] = wdf["_pass_role_share"]

    # Flat fallback rows (unknown scheme or unresolved position) -- unchanged.
    flat_mask = df["credit_method"] != "weighted"
    df.loc[flat_mask, "team_credit_share"] = (
        df.loc[flat_mask, "tdgs"] / df.loc[flat_mask, "n_participants"]
    ).round(5)

    return df
