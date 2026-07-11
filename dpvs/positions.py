"""
Position group mapping for DPVS-G.

Three groups allow cross-position-type comparisons:
  pass_rusher  — DE, OLB pass-rush specialist
  run_stopper  — DT, NT, MLB, ILB
  coverage     — CB, S, DB

Z-scores are computed within season × position_group so a DT competes
against other DTs/NTs, not against cornerbacks.
"""

from __future__ import annotations

POSITION_GROUP: dict[str, str] = {
    # Defensive ends → pass rusher
    "DE": "pass_rusher",
    "LDE": "pass_rusher",
    "RDE": "pass_rusher",
    # Outside linebackers default to pass rusher; ILB/MLB are run stoppers
    "OLB": "pass_rusher",
    "LOLB": "pass_rusher",
    "ROLB": "pass_rusher",
    # Defensive tackles / nose tackles → run stopper
    "DT": "run_stopper",
    "LDT": "run_stopper",
    "RDT": "run_stopper",
    "NT": "run_stopper",
    "DL": "run_stopper",
    # Inside / middle linebackers → run stopper
    "LB": "run_stopper",
    "ILB": "run_stopper",
    "MLB": "run_stopper",
    "LILB": "run_stopper",
    "RILB": "run_stopper",
    "LLB": "run_stopper",
    "RLB": "run_stopper",
    # Secondary → coverage
    "CB": "coverage",
    "RCB": "coverage",
    "LCB": "coverage",
    "DB": "coverage",
    "S": "coverage",
    "SS": "coverage",
    "FS": "coverage",
    "SAF": "coverage",
}

KNOWN_GROUPS = frozenset({"pass_rusher", "run_stopper", "coverage"})


def map_position(pos: str | None) -> str:
    """Return position_group for a raw position string. Unknown → 'unknown'."""
    if not pos:
        return "unknown"
    return POSITION_GROUP.get(str(pos).strip().upper(), "unknown")
