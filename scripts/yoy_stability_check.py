#!/usr/bin/env python3
"""
Pooled year-over-year stability check for IDI_z and the no-WOWY DPVS-G
composite, matching this session's established methodology: pool every
(season N, season N+1) pair for the same pfr_player_id across the whole
dataset (not season-by-season averaged), compute one Pearson r per metric.

Composite is recomputed directly as 0.60*tcs_z + 0.40*idi_z (the no-WOWY
formula) from the saved parquet's own tcs_z/idi_z columns, rather than using
the parquet's dpvs_g column (which uses WOWY weights when available) — this
matches how the earlier baseline/§11 numbers in framework_decisions.md were
computed.

Usage: python3 scripts/yoy_stability_check.py
"""
from pathlib import Path
import pandas as pd

PARQUET = Path.home() / "data/silver/dpvs_g_player_season.parquet"

df = pd.read_parquet(PARQUET)
df = df[["season", "pfr_player_id", "tcs_z", "idi_z"]].dropna(subset=["tcs_z", "idi_z"]).copy()
df["composite_no_wowy"] = 0.60 * df["tcs_z"] + 0.40 * df["idi_z"]

nxt = df.copy()
nxt["season"] = nxt["season"] - 1  # shift so a row at season S holds season S+1's values
nxt = nxt.rename(columns={
    "idi_z": "idi_z_next", "composite_no_wowy": "composite_no_wowy_next",
    "tcs_z": "tcs_z_next",
})

pairs = df.merge(
    nxt[["season", "pfr_player_id", "idi_z_next", "composite_no_wowy_next"]],
    on=["season", "pfr_player_id"], how="inner",
)

print(f"Pooled pairs: n={len(pairs):,}")
r_idi = pairs["idi_z"].corr(pairs["idi_z_next"])
r_comp = pairs["composite_no_wowy"].corr(pairs["composite_no_wowy_next"])
print(f"IDI_z pooled YoY Pearson r:                {r_idi:.3f}")
print(f"Composite (no-WOWY) pooled YoY Pearson r:  {r_comp:.3f}")

print("\n— by era —")
for lo, hi, label in [(1967, 1977, "1967-1977 (gamebooks TFL)"),
                       (1978, 1998, "1978-1998 (pbp TFL, undercount)"),
                       (1999, 2024, "1999-2024 (gold TFL)")]:
    sub = pairs[(pairs["season"] >= lo) & (pairs["season"] <= hi)]
    if sub.empty:
        continue
    r_i = sub["idi_z"].corr(sub["idi_z_next"])
    r_c = sub["composite_no_wowy"].corr(sub["composite_no_wowy_next"])
    print(f"{label:38s} n={len(sub):6,}  IDI_z r={r_i:.3f}  composite r={r_c:.3f}")
