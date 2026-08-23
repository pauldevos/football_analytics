#!/usr/bin/env python3
"""
Award-recognition-vs-INT-value study (2026-08-22).

Builds the top-15 (by count, ties included, capped at 15) individual INT
leaders for every season 1971-2025 from PFR's own locally-scraped season
defense stat pages, then cross-references each leader-season against real
recognition: AP All-Pro tier, full AP DPOY voting rank (scraped fresh via
scripts/scrape_dpoy_award_voting.py), and three independent DPOY-style
awards (NEA, PFWA, 101 Awards -- loaded into football_db's
gold.player_awards by football_db/scripts/ingest_{nea,pfwa,101awards}_dpoy.py).

Full writeup: docs/deferred/04_award_recognition_vs_int_value_20260822.md

Source data:
  ~/data/pfref/raw/season/player/defense/defense_{year}.csv
    -- PFR's column schema changes at 2006 (rk/player/team/pos/... ->
       rank/player_name/team_abbrev/position/...); both eras handled here.
  ~/data/pfref/ap_dpoy_voting.csv
    -- full AP DPOY voting (rank/votes/share), scraped from
       pro-football-reference.com/awards/awards_{year}.htm, one page per
       year, 1971-2025 (see scrape_dpoy_award_voting.py).
  football_db Postgres (local, no auth): gold.player_awards (org=AP for
    All-Pro tier; org in NEA/PFWA/101AWARDS for the three independent DPOY
    bodies), internal.player_xref (pfr id <-> internal player_id).

Output: data_output/int_leaders_full_recognition.csv
"""
import csv
import subprocess
from pathlib import Path
from collections import defaultdict

DEF_DIR = Path("/Users/devos/data/pfref/raw/season/player/defense")
AP_DPOY_CSV = Path("/Users/devos/data/pfref/ap_dpoy_voting.csv")
OUT_DIR = Path(__file__).resolve().parent.parent / "data_output"
OUT_CSV = OUT_DIR / "int_leaders_full_recognition.csv"

SEASON_MIN = 1971  # first AP DPOY voting year
SEASON_MAX = 2025
TOP_N = 15


def col_map(fieldnames):
    """PFR's local defense_{year}.csv schema changes at 2006."""
    fs = set(fieldnames)
    if "rk" in fs:
        return {"rk": "rk", "player": "player", "team": "team", "pos": "pos",
                "int": "int", "inttd": "inttd", "player_id": "player_id", "awards": "awards"}
    return {"rk": "rank", "player": "player_name", "team": "team_abbrev", "pos": "position",
            "int": "int", "inttd": "int_td", "player_id": "player_id", "awards": "awards"}


def load_year(year: int) -> list[dict]:
    fn = DEF_DIR / f"defense_{year}.csv"
    if not fn.exists():
        return []
    rows = []
    with open(fn) as f:
        reader = csv.DictReader(f)
        cm = col_map(reader.fieldnames)
        for r in reader:
            rk = (r.get(cm["rk"]) or "").strip()
            if not rk.isdigit():
                continue  # repeated header row (PFR table pagination artifact)
            player = (r.get(cm["player"]) or "").strip()
            if not player or player.lower() in ("player", "player_name"):
                continue
            try:
                inte = int((r.get(cm["int"]) or "0") or 0)
            except ValueError:
                inte = 0
            try:
                inttd = int((r.get(cm["inttd"]) or "0") or 0)
            except ValueError:
                inttd = 0
            rows.append({
                "player_id": (r.get(cm["player_id"]) or "").strip(),
                "player": player,
                "team": (r.get(cm["team"]) or "").strip(),
                "pos": (r.get(cm["pos"]) or "").strip(),
                "int": inte,
                "inttd": inttd,
            })
    return rows


def build_top_int_leaders() -> list[dict]:
    out = []
    for year in range(SEASON_MIN, SEASON_MAX + 1):
        rows = load_year(year)
        rows_sorted = sorted([r for r in rows if r["int"] > 0], key=lambda r: -r["int"])
        if not rows_sorted:
            continue
        cutoff_val = rows_sorted[-1]["int"] if len(rows_sorted) <= 10 else rows_sorted[9]["int"]
        top_leaders = [r for r in rows_sorted if r["int"] >= cutoff_val][:TOP_N]
        for rank, r in enumerate(top_leaders, start=1):
            out.append({**r, "season": year, "int_rank_in_season": rank})
    return out


def pg_query_csv(sql: str) -> list[dict]:
    """Run a SQL query against the local `football` Postgres DB via psql, CSV out."""
    result = subprocess.run(
        ["psql", "-d", "football", "-A", "-F,", "-t", "-c", f"COPY ({sql}) TO STDOUT WITH CSV HEADER"],
        capture_output=True, text=True, check=True,
    )
    return list(csv.DictReader(result.stdout.splitlines()))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    leaders = build_top_int_leaders()
    print(f"Top-{TOP_N} INT leaders: {len(leaders)} rows across "
          f"{len({r['season'] for r in leaders})} seasons ({SEASON_MIN}-{SEASON_MAX})")

    allpro = {}
    for r in pg_query_csv("""
        SELECT px.source_player_id AS pfr_id, pa.season, pa.designation
        FROM gold.player_awards pa
        JOIN internal.player_xref px ON px.player_id = pa.player_id AND px.source_system='pfr'
        WHERE pa.org='AP' AND pa.designation IN ('1st Tm','2nd Tm')
          AND pa.season BETWEEN 1971 AND 2025
    """):
        allpro[(r["pfr_id"], int(r["season"]))] = r["designation"]

    ap_dpoy = {}
    if AP_DPOY_CSV.exists():
        for r in csv.DictReader(open(AP_DPOY_CSV)):
            ap_dpoy[(r["player_id"], int(r["season"]))] = {
                "rank": r["dpoy_voting_rank"], "votes": r["votes"], "share": r["share_pct"],
            }

    other = defaultdict(list)
    for r in pg_query_csv("""
        SELECT px.source_player_id AS pfr_id, pa.season, pa.org, pa.designation
        FROM gold.player_awards pa
        JOIN internal.player_xref px ON px.player_id = pa.player_id AND px.source_system='pfr'
        WHERE pa.org IN ('NEA','PFWA','101AWARDS') AND pa.designation LIKE 'DPOY%'
    """):
        other[(r["pfr_id"], int(r["season"]))].append(f"{r['org']}:{r['designation']}")

    out_rows = []
    for l in leaders:
        key = (l["player_id"], l["season"])
        ap_tier = allpro.get(key, "")
        dpoy = ap_dpoy.get(key, {})
        others = other.get(key, [])
        out_rows.append({
            "season": l["season"], "player_name": l["player"], "player_id": l["player_id"],
            "team": l["team"], "pos": l["pos"], "int": l["int"], "inttd": l["inttd"],
            "int_rank_in_season": l["int_rank_in_season"],
            "ap_all_pro_tier": ap_tier, "ap_dpoy_rank": dpoy.get("rank", ""),
            "ap_dpoy_votes": dpoy.get("votes", ""), "ap_dpoy_share_pct": dpoy.get("share", ""),
            "other_dpoy_awards": ";".join(others),
            "zero_recognition": (not ap_tier) and (not dpoy.get("rank")) and (not others),
        })

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    print(f"Wrote {len(out_rows)} rows -> {OUT_CSV}")

    total = len(out_rows)
    zero = sum(1 for r in out_rows if r["zero_recognition"])
    print(f"\nZero-recognition top-15-INT-leader-seasons: {zero}/{total} ({100*zero/total:.1f}%)")


if __name__ == "__main__":
    main()
