#!/usr/bin/env python3
"""
enrich_tackle_events.py
-----------------------
Enriches tackle_events.parquet and re-saves as tackle_events_enriched.parquet.

New / corrected columns:
  pos_filled / pos_group_filled  — resolves positions via three-pass roster lookup
  abs_yard / field_zone_fixed    — correct field zone from offense's perspective
  game_result                    — W / L / ? per tackler's team (no false ties)

Position group values:
  DL     — defensive line
  LB     — linebackers
  DB     — defensive backs
  OFFENSE— non-defensive player making a tackle (turnover return, ST block)
  SPEC   — kicker / punter / long snapper
  OTHER  — truly unresolvable after all lookup passes

Lookup strategy (applied in order, stops at first hit):
  Pass 1: short player_id + season   (from /players/X/XxxxXx00.htm in pfr_player_id)
  Pass 2: norm_name + team + season   (direct, for rows where team is known)
  Pass 3: norm_name vs both game teams (for rows where team is empty)

Also produces win_loss_variance.parquet — EPA split by W vs L.

Usage:
  python scripts/enrich_tackle_events.py
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

SILVER_DIR  = Path("/Users/devos/data/silver")
ROSTER_DIR  = Path("/Users/devos/data/pfref/raw/season/rosters")
EVENTS_PATH = SILVER_DIR / "tackle_events.parquet"
OUT_EVENTS  = SILVER_DIR / "tackle_events_enriched.parquet"
OUT_WL      = SILVER_DIR / "win_loss_variance.parquet"

# ---------------------------------------------------------------------------
# Position classification
# ---------------------------------------------------------------------------
DL_POS  = {"DE","DT","NT","LDE","RDE","LDT","RDT","NOSE","DG","LE","RE","LT","RT",
            "DL","MG"}          # DL=generic modern tag; MG=middle guard (pre-1960)
LB_POS  = {"LB","ILB","OLB","MLB","SLB","WLB","LOLB","ROLB","LILB","RILB",
            "RLB","LLB","LIB","RIB","LOB","ROB"}
DB_POS  = {"CB","FS","SS","DB","LCB","RCB","NCB","S","LC","RC","SCB","WCB",
           "LS","RS","LFS","RFS","LHS","RHS","LHSS","RHSS",
           "LDH","RDH"}         # LDH/RDH = defensive halfback (pre-1960)
OFF_POS = {"QB","RB","HB","FB","WR","TE","FL","SE",
           "T","G","C","OT","OG","OL","OC",
           "LT","LG","RG","RT","LH","RH","BB",  # old-style
           "E","BB","TB","BB"}   # pre-modern positions
SPE_POS = {"K","P","LS","KR","PR"}


def classify(pos: str) -> str:
    p = (pos or "").upper().strip()
    if "-" in p or "/" in p:
        p = re.split(r"[-/]", p)[0]
    if p in DL_POS:  return "DL"
    if p in LB_POS:  return "LB"
    if p in DB_POS:  return "DB"
    if p in OFF_POS: return "OFFENSE"
    if p in SPE_POS: return "SPEC"
    return "OTHER"


FIELD_ZONES = [
    (1,  20,  "own_1-20"),
    (21, 40,  "own_21-40"),
    (41, 59,  "mid"),
    (60, 79,  "opp_21-40"),
    (80, 99,  "opp_1-20"),
]

def abs_to_zone(y: pd.Series) -> pd.Series:
    result = pd.Series("unknown", index=y.index)
    for lo, hi, label in FIELD_ZONES:
        result[(y >= lo) & (y <= hi)] = label
    return result


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


_PID_PAT = re.compile(r"/players/[A-Z]/([A-Za-z0-9]+)\.htm")


def extract_short_id(url: str) -> str:
    m = _PID_PAT.search(str(url or ""))
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------

_SUFFIX_PAT = re.compile(r"\s+(?:jr\.?|sr\.?|ii|iii|iv)$")
_MIDDLE_PAT = re.compile(r"\b[a-z]\. +")


def _strip_roster_name(name_norm: str) -> str:
    """Strip middle initial and suffix from a roster-side normalized name."""
    s = _MIDDLE_PAT.sub("", name_norm).strip()
    s = _SUFFIX_PAT.sub("", s).strip()
    return s


def build_roster_lookups(roster_dir: Path) -> tuple[dict, dict, dict]:
    """
    Returns:
      lookup_pid:      {(short_player_id, season_int): pos}
      lookup_name:     {(norm_name, team_lower, season_int): {pos, player_id}}
      lookup_lastname: {(last_name, team_lower, season_int): pos}
                       — only populated when that last name is unique on the team/season
    """
    dfs = []
    for f in roster_dir.glob("*_roster.csv"):
        parts = f.stem.rsplit("_", 2)
        if len(parts) < 2:
            continue
        try:
            year = int(parts[1])
        except ValueError:
            continue
        try:
            df = pd.read_csv(f, dtype=str)[["Player","Pos","player_id"]].copy()
            df.columns = ["player_name","pos","player_id"]
            df["team"]   = parts[0]
            df["season"] = year
            dfs.append(df)
        except Exception:
            continue

    full = pd.concat(dfs, ignore_index=True)
    full = full.dropna(subset=["player_name","pos"])
    full["pos"] = full["pos"].str.strip()
    full = full[full["pos"] != ""]
    full["name_norm"] = full["player_name"].apply(_norm)
    full["team_norm"] = full["team"].str.lower()
    full["season"]    = full["season"].astype(int)
    full["player_id"] = full["player_id"].fillna("").str.strip()
    full = full.drop_duplicates(subset=["name_norm","team_norm","season"], keep="first")

    # player_id + season → pos
    pid_rows = full[full["player_id"] != ""]
    pid_rows = pid_rows.drop_duplicates(subset=["player_id","season"], keep="first")
    lookup_pid = pid_rows.set_index(["player_id","season"])["pos"].to_dict()

    # name + team + season → {pos, player_id}
    # Include both original name AND suffix/initial-stripped variant as keys
    name_rows = full[["name_norm","team_norm","season","pos","player_id"]].copy()
    stripped = name_rows.copy()
    stripped["name_norm"] = stripped["name_norm"].apply(_strip_roster_name)
    stripped = stripped[stripped["name_norm"] != name_rows["name_norm"]]  # only real changes
    combined = pd.concat([name_rows, stripped], ignore_index=True)
    combined = combined.drop_duplicates(subset=["name_norm","team_norm","season"], keep="first")
    lookup_name = combined.set_index(["name_norm","team_norm","season"])[
        ["pos","player_id"]].to_dict("index")

    # last_name + team + season → pos  (only if unique per team-season)
    full["last_name"] = full["name_norm"].apply(
        lambda n: _SUFFIX_PAT.sub("", n).strip().split()[-1] if n.strip() else ""
    )
    ln_counts = full.groupby(["last_name","team_norm","season"]).size()
    unique_keys = set(ln_counts[ln_counts == 1].index)
    ln_rows = full[full.apply(
        lambda r: (r["last_name"], r["team_norm"], r["season"]) in unique_keys, axis=1
    )]
    lookup_lastname = ln_rows.set_index(["last_name","team_norm","season"])["pos"].to_dict()

    return lookup_pid, lookup_name, lookup_lastname


def _name_variants(name_norm: str) -> list[str]:
    """
    Generate lookup-friendly variants of a normalized name.
    Handles PBP quirks like 'derrick o. johnson' or 'willie j. williams jr'.
    """
    variants = [name_norm]
    # Strip middle initial: 'derrick o. johnson' → 'derrick johnson'
    stripped = re.sub(r"\b[a-z]\. +", "", name_norm).strip()
    if stripped != name_norm:
        variants.append(stripped)
    # Strip suffix (jr/sr/ii/iii/iv): 'antoine winfield jr' → 'antoine winfield'
    no_suf = re.sub(r"\s+(?:jr\.?|sr\.?|ii|iii|iv)$", "", name_norm).strip()
    if no_suf != name_norm:
        variants.append(no_suf)
    # Both: strip initial AND suffix
    both = re.sub(r"\s+(?:jr\.?|sr\.?|ii|iii|iv)$", "", stripped).strip()
    if both not in variants:
        variants.append(both)
    return variants


def _lookup_one(name: str, team: str, home: str, vis: str,
                season: int, lookup_name: dict,
                lookup_lastname: dict | None = None) -> tuple[str, str]:
    """
    Try to resolve (pos, resolved_team) for a single name + season.
    Falls back to last-name-only lookup when full-name lookup fails.
    Returns ('', '') on failure.
    """
    # Full name
    if team:
        hit = lookup_name.get((name, team, season))
        if hit:
            return hit["pos"], team
    h_hit = lookup_name.get((name, home, season))
    v_hit = lookup_name.get((name, vis,  season))
    if h_hit and not v_hit:
        return h_hit["pos"], home
    if v_hit and not h_hit:
        return v_hit["pos"], vis

    # Last-name fallback (only when PBP name is unique on that team in that season)
    if lookup_lastname:
        last = name.split()[-1] if name else ""
        if last:
            if team:
                pos = lookup_lastname.get((last, team, season))
                if pos:
                    return pos, team
            lh = lookup_lastname.get((last, home, season))
            lv = lookup_lastname.get((last, vis,  season))
            if lh and not lv:
                return lh, home
            if lv and not lh:
                return lv, vis

    return "", ""


def resolve_pos(name_norm: str, url_pid: str, team: str, home: str, vis: str,
                season: int, lookup_pid: dict, lookup_name: dict,
                lookup_lastname: dict) -> tuple[str, str, str]:
    """
    Returns (pos, pos_group, resolved_team).  Passes in order:

    Pass 1 — short player_id + season
    Pass 2 — full name variants × exact season
    Pass 3 — full name variants × ±1 year
    Pass 4 — last name + team/season (unique-last-name fallback for nicknames)
    """
    # Pass 1: short player_id + season
    short = extract_short_id(url_pid)
    if short:
        pos = lookup_pid.get((short, season))
        if pos:
            return pos, classify(pos), team

    # Pass 2: name variants × exact year; Pass 3: ±1 year
    variants = _name_variants(name_norm)
    for s in [season, season - 1, season + 1]:
        for name in variants:
            pos, res_team = _lookup_one(name, team, home, vis, s, lookup_name)
            if pos:
                return pos, classify(pos), res_team or team

    # Pass 4: last-name-only fallback (handles nickname mismatches)
    for s in [season, season - 1, season + 1]:
        pos, res_team = _lookup_one(
            name_norm, team, home, vis, s, lookup_name={}, lookup_lastname=lookup_lastname
        )
        if pos:
            return pos, classify(pos), res_team or team

    return "", "OTHER", team


# ---------------------------------------------------------------------------

def main():
    print("Loading tackle_events...")
    df = pd.read_parquet(EVENTS_PATH)
    print(f"  {len(df):,} rows, {df['season'].nunique()} seasons")

    # ── Build roster lookups ──────────────────────────────────────────────────
    print("\nBuilding roster lookups from CSV files...")
    lookup_pid, lookup_name, lookup_lastname = build_roster_lookups(ROSTER_DIR)
    print(f"  pid lookup:      {len(lookup_pid):,} entries")
    print(f"  name lookup:     {len(lookup_name):,} entries")
    print(f"  lastname lookup: {len(lookup_lastname):,} entries (unique per team/season)")

    # ── 1. Position backfill (three-pass) ────────────────────────────────────
    print("\nBackfilling positions (three-pass lookup)...")
    df["season_int"] = pd.to_numeric(df["season"], errors="coerce").astype("Int64")
    df["name_norm"]  = df["tackler_name"].apply(_norm)

    pos_out  = df["pos"].values.copy().astype(object)
    grp_out  = df["pos_group"].values.copy().astype(object)
    team_out = df["team"].values.copy().astype(object)

    other_idx = np.where(df["pos_group"].values == "OTHER")[0]

    for i in other_idx:
        row = df.iloc[i]
        s   = int(row["season_int"]) if pd.notna(row["season_int"]) else None
        if s is None:
            continue
        pos, grp, resolved_team = resolve_pos(
            name_norm     = row["name_norm"],
            url_pid       = str(row["pfr_player_id"] or ""),
            team          = str(row["team"] or ""),
            home          = str(row["home_team"] or ""),
            vis           = str(row["vis_team"] or ""),
            season        = s,
            lookup_pid    = lookup_pid,
            lookup_name   = lookup_name,
            lookup_lastname = lookup_lastname,
        )
        if grp != "OTHER":
            pos_out[i]  = pos
            grp_out[i]  = grp
            if not team_out[i]:
                team_out[i] = resolved_team

    df["pos_filled"]       = pos_out
    df["pos_group_filled"] = grp_out
    df["team_filled"]      = team_out

    orig_other = len(other_idx)
    new_other  = (pd.Series(grp_out) == "OTHER").sum()
    dist = pd.Series(grp_out).value_counts()
    print(f"  OTHER: {orig_other:,} → {new_other:,}  "
          f"(resolved {orig_other - new_other:,} = "
          f"{100*(orig_other-new_other)/orig_other:.1f}%)")
    print("  Final position distribution:")
    for pg, cnt in dist.items():
        print(f"    {pg:8s}: {cnt:>8,}  ({100*cnt/len(df):.1f}%)")

    # ── 2. Corrected field zones ──────────────────────────────────────────────
    print("\nComputing corrected field zones...")
    ht = df["home_team"].str.upper()
    vt = df["vis_team"].str.upper()
    dt = df["team_filled"].str.upper()
    lt = df["loc_team"].str.upper()
    ly = pd.to_numeric(df["loc_yard"], errors="coerce")

    off = pd.Series("", index=df.index, dtype=str)
    off[dt == ht] = vt[dt == ht]
    off[dt == vt] = ht[dt == vt]

    in_own    = (lt == off) & (off != "")
    in_opp    = (lt != off) & (off != "")
    abs_y     = pd.Series(np.nan, index=df.index)
    abs_y[in_own] = ly[in_own]
    abs_y[in_opp] = 100 - ly[in_opp]
    abs_y[abs_y.isna()] = ly[abs_y.isna()]    # fallback

    df["abs_yard"]         = abs_y.round(0).astype("Int64")
    df["field_zone_fixed"] = abs_to_zone(abs_y)

    zone_counts = df["field_zone_fixed"].value_counts()
    print("  Zone distribution (corrected):")
    for z, c in zone_counts.items():
        print(f"    {z:14s}: {c:>8,}  ({100*c/len(df):.1f}%)")

    # ── 3. Game outcomes ──────────────────────────────────────────────────────
    print("\nDeriving game outcomes...")
    df["_sh"] = pd.to_numeric(df["score_home"], errors="coerce")
    df["_sa"] = pd.to_numeric(df["score_away"], errors="coerce")

    gs = df.groupby("game_id", sort=False).agg(
        home_team  = ("home_team",  "first"),
        vis_team   = ("vis_team",   "first"),
        final_home = ("_sh",        "max"),
        final_away = ("_sa",        "max"),
    ).reset_index()

    # pbp_score is pre-play; walk-off scores never appear in a following row,
    # so equal max scores do NOT reliably indicate ties — treat as unknown.
    gs["winner"] = np.where(
        gs["final_home"] > gs["final_away"], gs["home_team"].str.upper(),
        np.where(
            gs["final_away"] > gs["final_home"], gs["vis_team"].str.upper(),
            "?"
        ),
    )

    w_map = gs.set_index("game_id")["winner"].to_dict()
    df["_w"] = df["game_id"].map(w_map).fillna("?")
    t = df["team_filled"].str.upper()
    w = df["_w"].str.upper()
    df["game_result"] = np.where(w == "?",  "?",
                        np.where(t == "",   "?",
                        np.where(t == w,    "W", "L")))

    dist_gr = df["game_result"].value_counts()
    print(f"  W: {dist_gr.get('W',0):,}  L: {dist_gr.get('L',0):,}  "
          f"?: {dist_gr.get('?',0):,}")

    # ── Save ──────────────────────────────────────────────────────────────────
    df = df.drop(columns=["season_int","name_norm","_sh","_sa","_w"])
    df.to_parquet(OUT_EVENTS, index=False)
    print(f"\nSaved → {OUT_EVENTS}  ({len(df):,} rows)")

    # ── 4. Win-Loss variance ──────────────────────────────────────────────────
    print("\n" + "="*60)
    print("WIN-LOSS VARIANCE ANALYSIS")
    print("="*60)

    ev = df[df["game_result"].isin(["W","L"])].copy()
    ev = ev[ev["pos_group_filled"].isin(["DL","LB","DB"])]  # defensive only
    ev["season_int"] = pd.to_numeric(ev["season"], errors="coerce")
    ev["epa"]        = pd.to_numeric(ev["epa_def_share"], errors="coerce")
    ev["yards"]      = pd.to_numeric(ev["yards_gained"], errors="coerce")

    overall = ev.groupby("game_result").agg(
        n=("epa","count"), epa_mean=("epa","mean"),
        avg_yards=("yards","mean"), solo_rate=("is_solo","mean"),
    ).round(4)
    print("\n── Overall: defensive EPA by W vs L ──")
    print(overall.to_string())

    by_pos = ev.groupby(["pos_group_filled","game_result"]).agg(
        n=("epa","count"), epa_mean=("epa","mean"), avg_yards=("yards","mean")
    ).round(4).unstack("game_result")
    print("\n── EPA by position group × W/L ──")
    print(by_pos.to_string())

    by_type = ev.groupby(["play_type","game_result"]).agg(
        n=("epa","count"), epa_mean=("epa","mean"), avg_yards=("yards","mean")
    ).round(4).unstack("game_result")
    print("\n── EPA by play type × W/L ──")
    print(by_type.to_string())

    # Player-season W/L split (≥25 tackles each side)
    player_wl = ev.groupby(
        ["pfr_player_id","tackler_name","season_int","pos_group_filled","game_result"]
    ).agg(
        tackles=("epa","count"), epa_mean=("epa","mean"),
        epa_total=("epa","sum"), avg_yards=("yards","mean"),
    ).reset_index()

    pw = player_wl[player_wl.game_result=="W"].drop(columns="game_result").add_suffix("_W").rename(
        columns={c+"_W":c for c in ["pfr_player_id","tackler_name","season_int","pos_group_filled"]})
    pl = player_wl[player_wl.game_result=="L"].drop(columns="game_result").add_suffix("_L").rename(
        columns={c+"_L":c for c in ["pfr_player_id","tackler_name","season_int","pos_group_filled"]})

    joined = pd.merge(pw, pl,
                      on=["pfr_player_id","tackler_name","season_int","pos_group_filled"],
                      how="inner")
    joined = joined[(joined.tackles_W >= 25) & (joined.tackles_L >= 25)].copy()
    joined["epa_delta"]   = (joined.epa_mean_W - joined.epa_mean_L).round(4)
    joined["yards_delta"] = (joined.avg_yards_W - joined.avg_yards_L).round(2)

    cols = ["tackler_name","season_int","pos_group_filled",
            "tackles_W","tackles_L","epa_mean_W","epa_mean_L","epa_delta","yards_delta"]
    print("\n── Top 20: highest EPA in wins ──")
    print(joined.sort_values("epa_delta", ascending=False).head(20)[cols].to_string(index=False))
    print("\n── Bottom 20: biggest EPA drop in wins ──")
    print(joined.sort_values("epa_delta").head(20)[cols].to_string(index=False))
    print(f"\n── epa_delta distribution ({len(joined):,} player-seasons) ──")
    print(joined["epa_delta"].describe().round(4).to_string())

    joined.to_parquet(OUT_WL, index=False)
    print(f"\nSaved → {OUT_WL}  ({len(joined):,} player-seasons)")

    # ── Summary of remaining OTHER ────────────────────────────────────────────
    still_other = df[df["pos_group_filled"] == "OTHER"]
    print(f"\n── Remaining OTHER ({len(still_other):,} rows, {100*len(still_other)/len(df):.1f}%) ──")
    top_names = still_other["tackler_name"].value_counts().head(20)
    print("Top unresolved names:")
    print(top_names.to_string())


if __name__ == "__main__":
    main()
