"""
TCS position-responsibility weight tables (run defense / pass defense, by scheme).

Production weights are given directly by the user (2026-08-23 session), NOT
derived from a fit:

  3-4 RUN:  NT 0.284, MLB 0.284, DE 0.184, OLB 0.120, SS 0.078, FS+CB 0.051
  4-3 RUN:  DT 0.246, MLB 0.246, LDE 0.160, LOLB 0.104, RDE 0.104,
            ROLB 0.068, SS 0.044, FS+CB 0.029
  3-4 PASS: OLB 0.4, DB 0.3, DE 0.2, MLB 0.1
  4-3 PASS: DE 0.301, DT 0.196, CB 0.127, FS 0.127, SS 0.083, MLB 0.083,
            OLB 0.083

Reverse-engineered structure (checked by hand, 2026-08-23): three of the four
tables are an exact geometric tier-decay at ratio r=0.65 -- positions are
grouped into ordered tiers (top tier = most responsibility), all positions
within one tier share equal weight, and each successive tier's weight is
r times the tier above it:

  3-4 RUN:  T1={NT,MLB}  T2={DE}  T3={OLB}  T4={SS}  T5={FS+CB}
  4-3 RUN:  T1={DT,MLB}  T2={LDE}  T3={LOLB,RDE}  T4={ROLB}  T5={SS}  T6={FS+CB}
  4-3 PASS: T1={DE}  T2={DT}  T3={CB,FS}  T4={SS,MLB,OLB}

  weight(tier i) = r^(i-1) / sum_j( n_j * r^(j-1) )   where n_j = tier j's size

3-4 PASS (OLB 0.4/DB 0.3/DE 0.2/MLB 0.1) does NOT fit this geometric pattern
(ratios 0.75/0.667/0.5, not 0.65) -- it reads as a simple round-number
assignment instead. Its tier ORDER (OLB > DB > DE > MLB, one position per
tier) is still used for the grid-search regeneration at other decay ratios
(build_weight_table(decay=r) for r != 0.65), for a consistent sweep
methodology across all four tables -- but this means build_weight_table's
3-4/pass output at r=0.65 does NOT exactly reproduce the literal production
numbers above (0.426/0.277/0.180/0.117 vs 0.4/0.3/0.2/0.1). This is a known,
disclosed discrepancy, not a bug: PRODUCTION_TABLES (used for the real
1967-2024 build) always uses the literal user-given numbers verbatim;
build_weight_table() (used only for the Part 3 grid sweep) uses the
formula-regenerated numbers so the sweep has one consistent generative
mechanism across all four tables.
"""

from __future__ import annotations

# ── literal production tables (verbatim from the user, r=0.65) ──────────────

PRODUCTION_TABLES: dict[tuple[str, str], dict[str, float]] = {
    ("3-4", "run"): {
        "NT": 0.284, "MLB": 0.284, "DE": 0.184, "OLB": 0.120,
        "SS": 0.078, "FS+CB": 0.051,
    },
    ("4-3", "run"): {
        "DT": 0.246, "MLB": 0.246, "LDE": 0.160, "LOLB": 0.104,
        "RDE": 0.104, "ROLB": 0.068, "SS": 0.044, "FS+CB": 0.029,
    },
    ("3-4", "pass"): {
        "OLB": 0.4, "DB": 0.3, "DE": 0.2, "MLB": 0.1,
    },
    ("4-3", "pass"): {
        "DE": 0.301, "DT": 0.196, "CB": 0.127, "FS": 0.127,
        "SS": 0.083, "MLB": 0.083, "OLB": 0.083,
    },
}

# ── tier structure used to regenerate tables at other decay ratios ─────────

TIER_STRUCTURE: dict[tuple[str, str], list[list[str]]] = {
    ("3-4", "run"):  [["NT", "MLB"], ["DE"], ["OLB"], ["SS"], ["FS+CB"]],
    ("4-3", "run"):  [["DT", "MLB"], ["LDE"], ["LOLB", "RDE"], ["ROLB"],
                       ["SS"], ["FS+CB"]],
    ("3-4", "pass"): [["OLB"], ["DB"], ["DE"], ["MLB"]],
    ("4-3", "pass"): [["DE"], ["DT"], ["CB", "FS"], ["SS", "MLB", "OLB"]],
}

DEFAULT_DECAY = 0.65


def build_weight_table(scheme: str, phase: str, decay: float = DEFAULT_DECAY
                        ) -> dict[str, float]:
    """
    Regenerate a position-weight table from TIER_STRUCTURE at an arbitrary
    decay ratio. Used for the Part 3 grid sweep. At decay=0.65 this
    reproduces PRODUCTION_TABLES exactly for ('3-4','run'), ('4-3','run'),
    and ('4-3','pass'); ('3-4','pass') is a documented near-miss (see module
    docstring) since that literal table wasn't built this way.
    """
    tiers = TIER_STRUCTURE[(scheme, phase)]
    denom = sum(len(tier) * (decay ** i) for i, tier in enumerate(tiers))
    out: dict[str, float] = {}
    for i, tier in enumerate(tiers):
        w = (decay ** i) / denom
        for pos in tier:
            out[pos] = w
    return out


def get_weights(scheme: str, phase: str, decay: float = DEFAULT_DECAY
                 ) -> dict[str, float]:
    """
    Return the weight table to actually use. decay==DEFAULT_DECAY (0.65) ->
    literal PRODUCTION_TABLES (guarantees production fidelity). Any other
    decay -> formula-regenerated table (grid sweep only).
    """
    if decay == DEFAULT_DECAY:
        return dict(PRODUCTION_TABLES[(scheme, phase)])
    return build_weight_table(scheme, phase, decay)


if __name__ == "__main__":
    for decay in (0.5, 0.6, 0.65, 0.7, 0.8):
        print(f"\n=== decay={decay} ===")
        for key in TIER_STRUCTURE:
            w = get_weights(*key, decay=decay)
            total = sum(w.values())
            print(f"  {key}: {[(k, round(v, 4)) for k, v in w.items()]}  sum={total:.4f}")
