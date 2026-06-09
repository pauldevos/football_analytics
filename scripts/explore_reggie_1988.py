"""
Quick exploratory script — no database needed.
Validates key data availability for the Reggie White 1988 DPVS prototype.
Run: python scripts/explore_reggie_1988.py
"""

import csv
import os
from pathlib import Path

PFREF = Path("/Users/devos/data/pfref")

# ─── 1. Reggie White's 1988 season stats ────────────────────────────────────

def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))

def reggie_1988():
    rows = load_csv(PFREF / "player-stats/defense/defense_1988.csv")
    reggie = [r for r in rows if "WhitRe00" in r.get("player_link", "")]
    print("=== Reggie White 1988 ===")
    for r in reggie:
        print(f"  Pos: {r['position']}, G: {r['games']}, Sacks: {r['sack']}, Awards: {r['awards']}")
    return reggie


# ─── 2. PHI 1988 team defense rank ─────────────────────────────────────────

def phi_team_defense_1988():
    rows = load_csv(PFREF / "team-defense/team-defense/team-defense-1988.csv")
    phi = [r for r in rows if "Philadelphia" in r.get("team", "")]
    print("\n=== PHI 1988 Team Defense ===")
    for r in phi:
        print(f"  Rank: {r['rank']}, Pts: {r['pts_against']}")
    return phi


# ─── 3. WOWY: GNB 1992 vs 1993 ──────────────────────────────────────────────

def gnb_wowy():
    for year in (1992, 1993):
        rows = load_csv(PFREF / f"team-defense/team-defense/team-defense-{year}.csv")
        gnb = [r for r in rows if "Green Bay" in r.get("team", "")]
        print(f"\n=== GNB {year} Team Defense ===")
        for r in gnb:
            print(f"  Rank: {r['rank']}, Pts: {r['pts_against']}")


# ─── 4. PHI 1988 games — sacks from boxscores ───────────────────────────────

def phi_1988_game_sacks():
    box_dir = PFREF / "boxscores/1988"
    phi_games = sorted(p for p in box_dir.iterdir() if "phi" in p.name)
    print(f"\n=== PHI 1988 Games ({len(phi_games)} home games in boxscore dir) ===")
    print(f"{'Game':<22} {'Opp Sacked':>12} {'Opp PassAtt':>12}")
    print("-" * 48)
    total_sacks = 0
    for game_path in phi_games:
        rows = load_csv(game_path)
        # Opponent team = not PHI
        opp_rows = [r for r in rows if r.get("team") != "PHI"]
        qb_rows = [r for r in opp_rows if float(r.get("pass_att") or 0) > 0]
        game_sacks = sum(float(r.get("sacked") or 0) for r in qb_rows)
        game_pass_att = sum(float(r.get("pass_att") or 0) for r in qb_rows)
        total_sacks += game_sacks
        print(f"  {game_path.stem:<20} {game_sacks:>12.1f} {game_pass_att:>12.0f}")
    print(f"\n  Total PHI home-game sacks (team): {total_sacks:.1f}")
    print("  NOTE: away games are filed under opponent team's directory")


# ─── 5. PHI 1988 sack totals — all defenders ────────────────────────────────

def phi_1988_all_sacks():
    rows = load_csv(PFREF / "player-stats/defense/defense_1988.csv")
    phi_def = [r for r in rows if r.get("team_abbrev") == "PHI"]
    phi_def.sort(key=lambda r: float(r.get("sack") or 0), reverse=True)
    team_sacks = sum(float(r.get("sack") or 0) for r in phi_def)
    print(f"\n=== PHI 1988 Sack Leaders (team total: {team_sacks:.1f}) ===")
    for r in phi_def:
        sacks = float(r.get("sack") or 0)
        if sacks > 0:
            share = sacks / team_sacks if team_sacks else 0
            print(f"  {r['player_name']:<25} {sacks:>5.1f}  share: {share:.1%}")


# ─── 6. GNB 1993 roster — Reggie + teammates ────────────────────────────────

def gnb_1993_roster():
    roster_path = PFREF / "team-rosters/gnb_1993_roster.csv"
    if not roster_path.exists():
        print("\n[gnb_1993_roster.csv not found]")
        return
    rows = load_csv(roster_path)
    defenders = [r for r in rows if any(
        pos in r.get("Pos", "") for pos in ("DE", "DT", "LB", "CB", "S", "DB")
    )]
    print(f"\n=== GNB 1993 Defenders ({len(defenders)} players) ===")
    for r in defenders:
        print(f"  #{r.get('No.',''): <3} {r['Player']:<25} {r['Pos']:<6} G:{r['G']} AV:{r['AV']}")


if __name__ == "__main__":
    reggie_1988()
    phi_team_defense_1988()
    gnb_wowy()
    phi_1988_game_sacks()
    phi_1988_all_sacks()
    gnb_1993_roster()
