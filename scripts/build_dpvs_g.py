#!/usr/bin/env python3
"""
build_dpvs_g.py — DPVS-G pipeline

Builds the full player-season DPVS-G table and career summaries.

Usage:
    # Gamebook era (MIN + PIT) — the primary use case
    python scripts/build_dpvs_g.py --seasons 1967-1981 --teams min pit

    # Modern era (post-2001 PFR tackles)
    python scripts/build_dpvs_g.py --seasons 2001-2024

    # Single team / season for validation
    python scripts/build_dpvs_g.py --seasons 1971 --teams min --report

    # Full history rebuild
    python scripts/build_dpvs_g.py --seasons 1967-2024

Outputs:
    ~/data/silver/dpvs_g_player_season.parquet
    ~/data/silver/dpvs_g_career.parquet
    ~/data/gold/dpvs_export/season_rankings_{year}.csv     (with --export)
    ~/data/gold/dpvs_export/all_time_leaderboard.csv       (with --export)
    ~/data/gold/dpvs_export/players/player_{id}.json       (with --export)
    ~/data/gold/dpvs_export/leaderboards.json              (with --export)
"""

import sys
import argparse
from pathlib import Path

import pandas as pd

# Make the dpvs package importable from this scripts/ directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from dpvs.tcs import load_or_build_player_game, aggregate_tcs
from dpvs.idi import load_gold_stats, load_all_gamebook_idi, load_gamebook_tfl, load_pbp_tfl, load_gamebook_tackle_gated, compute_idi
from dpvs.wowy import compute_wowy
from dpvs.composite import build_composite, career_summary, compute_run_pass_context
from dpvs.export import export_all

SILVER_DIR = Path.home() / "data/silver"
GAME_DEF_PARQUET = SILVER_DIR / "game_defense.parquet"


def _parse_seasons(s: str) -> list[int]:
    if "-" in s and not s.startswith("-"):
        lo, hi = s.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(s)]



def run(
    seasons: list[int],
    teams: list[str] | None,
    export: bool,
    report: bool,
    rebuild_tcs: bool,
    min_games: int = 6,
) -> tuple[pd.DataFrame, pd.DataFrame]:

    print(f"\n{'='*60}")
    print(f"DPVS-G BUILD  seasons={seasons[0]}–{seasons[-1]}  "
          f"teams={teams or 'all'}")
    print(f"{'='*60}\n")

    # ── Step 1: TCS ──────────────────────────────────────────────────────────
    print("Step 1/5 — Team Credit Share (TCS)")
    game_df, player_game_df = load_or_build_player_game(
        seasons, teams=teams, rebuild=rebuild_tcs
    )
    tcs_df = aggregate_tcs(player_game_df)
    print(f"  TCS: {len(tcs_df):,} player-seasons")

    # ── Step 2: WOWY ─────────────────────────────────────────────────────────
    print("Step 2/5 — WOWY (With Or Without You)")
    wowy_df = compute_wowy(player_game_df, game_df)
    print(f"  WOWY: {len(wowy_df):,} rows  "
          f"({(wowy_df['wowy_delta'].notna()).sum()} with delta)")

    # ── Step 3: IDI ──────────────────────────────────────────────────────────
    print("Step 3/5 — Individual Disruption Index (IDI)")
    gold_df = load_gold_stats(seasons)
    gamebook_df = load_all_gamebook_idi(teams=teams)
    gamebook_tfl_df = load_gamebook_tfl()
    pbp_tfl_df = load_pbp_tfl()
    gamebook_tackle_gated_df = load_gamebook_tackle_gated()
    print(f"  Gold stats: {len(gold_df):,} player-seasons")
    print(f"  Gamebook tackle data (legacy dead path): {len(gamebook_df):,} player-seasons")
    print(f"  Gamebook tackle data (gamebooks_boxscores gated corpus, 1967-1977): {len(gamebook_tackle_gated_df):,} player-seasons")
    print(f"  Gamebook TFL data (gamebooks_boxscores gated corpus, 1967-1977): {len(gamebook_tfl_df):,} player-seasons")
    print(f"  PBP TFL data (pfr pbp-derived, 1978-1998, undercount tier): {len(pbp_tfl_df):,} player-seasons")

    # Merge TCS with WOWY
    merged = tcs_df.merge(
        wowy_df[["season", "team", "pfr_player_id", "games_out",
                 "tdgs_with", "tdgs_without", "wowy_delta"]],
        on=["season", "team", "pfr_player_id"],
        how="left",
    )

    # Compute IDI (appends idi, tackle_share, tfl_share, sack_share, etc.)
    merged = compute_idi(merged, gold_df, gamebook_df, gamebook_tfl_df, pbp_tfl_df, gamebook_tackle_gated_df)
    print(f"  IDI: {merged['idi_has_tackles'].sum()} rows with gamebook tackles, "
          f"{merged['idi_has_tfl'].sum()} rows with TFL data")

    # ── Step 4: Composite ────────────────────────────────────────────────────
    print("Step 4/5 — Building composite DPVS-G / DPVS-A / DPVS-P scores")
    run_pass_ctx = compute_run_pass_context(game_df)
    print(f"  Run/pass context: {len(run_pass_ctx):,} team-seasons")
    final_df = build_composite(merged, min_games=min_games, run_pass_ctx=run_pass_ctx)
    career_df = career_summary(final_df)
    print(f"  Final player-seasons: {len(final_df):,}")
    print(f"  Career summaries:     {len(career_df):,} players")

    # ── Step 5: Save ─────────────────────────────────────────────────────────
    print("Step 5/5 — Saving outputs")
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    out_player = SILVER_DIR / "dpvs_g_player_season.parquet"
    out_career  = SILVER_DIR / "dpvs_g_career.parquet"

    # If a team filter was applied, z-scores are computed within that limited pool
    # and should NOT overwrite the full-league parquet (would corrupt other teams'
    # rankings in shared seasons).  Team-filtered builds are display-only.
    if teams:
        print(f"  Skipping parquet save: team-filtered build ({teams}) would corrupt "
              f"full-league z-scores.  Use --report for display only.")
        full_ps = final_df
        full_career = career_summary(final_df)
    else:
        # Player-season: append new seasons, drop any prior rows for rebuilt seasons
        if out_player.exists():
            old_ps = pd.read_parquet(out_player)
            old_ps = old_ps[~old_ps["season"].isin(seasons)]
            full_ps = pd.concat([old_ps, final_df], ignore_index=True)
        else:
            full_ps = final_df
        full_ps.to_parquet(out_player, index=False)
        print(f"  Saved: {out_player}  ({len(full_ps):,} total player-seasons)")

    if not teams:
        # Career: always rebuild from the complete player-season data
        # (never incrementally merge — careers span multiple partial builds)
        full_career = career_summary(full_ps)
        full_career.to_parquet(out_career, index=False)
        print(f"  Saved: {out_career}  ({len(full_career):,} players)")

    if export:
        export_all(
            full_ps, full_career,
            seasons=seasons,
            player_ids=None,
        )

    if report:
        _print_report(final_df, full_career, teams=teams)

    return final_df, full_career


def _print_report(
    df: pd.DataFrame,
    career_df: pd.DataFrame,
    teams: list[str] | None,
) -> None:
    print("\n" + "=" * 72)
    print("DPVS-G SEASON REPORT")
    print("=" * 72)

    for season in sorted(df["season"].unique()):
        sdf = df[df["season"] == season]
        if teams:
            sdf = sdf[sdf["team"].isin(teams)]
        if sdf.empty:
            continue

        print(f"\n{season}")
        print(f"  {'Player':<24} {'Team':5} {'Pos':6} {'Grp':12} "
              f"{'TCS_z':>7} {'IDI_z':>7} {'WOWY_z':>7} {'DPVS-G':>8} "
              f"{'Rnk':>4} {'Conf':8}")
        print(f"  {'-'*100}")

        shown = sdf.sort_values("dpvs_g", ascending=False).head(20)
        for _, r in shown.iterrows():
            wowy_str = f"{r['wowy_z']:+.2f}" if pd.notna(r.get("wowy_z")) else "  n/a"
            print(
                f"  {r['player_name']:<24} {r['team']:5} {r['pos']:6} "
                f"{r['position_group']:12} "
                f"{r.get('tcs_z', float('nan')):+7.2f} "
                f"{r.get('idi_z', float('nan')):+7.2f} "
                f"{wowy_str:>7} "
                f"{r['dpvs_g']:+8.3f} "
                f"{int(r['season_overall_rank']):>4} "
                f"{r.get('data_confidence','?'):8}"
            )

    print("\n— Career Summaries (qualified players — ≥3 seasons above avg, career avg ≥0.30) —")
    print(f"  {'Player':<24} {'Team':5} {'Grp':12} "
          f"{'Peak':>8} {'Year':>5} {'Prime':>8} {'Career avg':>10} {'Seasons':>7}")
    print(f"  {'-'*90}")
    qualified = career_df[career_df.get("qualified_career", True)].head(25)
    for _, r in qualified.iterrows():
        print(
            f"  {r['player_name']:<24} {r['primary_team']:5} "
            f"{r['primary_pos_group']:12} "
            f"{r['peak_dpvs_g']:+8.3f} {r['peak_season']:>5} "
            f"{r['prime_dpvs_g']:+8.3f} {r['career_avg_dpvs_g']:+10.3f}"
            f" {r.get('seasons_in_data', '?'):>7}"
        )


def main():
    ap = argparse.ArgumentParser(description="Build DPVS-G player ratings")
    ap.add_argument("--seasons", default="1967-1981",
                    help="Season range, e.g. 1967-1981 or single year 1971")
    ap.add_argument("--teams", nargs="*", default=None,
                    help="Lowercase PFR team codes to filter (e.g. min pit)")
    ap.add_argument("--export", action="store_true",
                    help="Export CSV/JSON files to ~/data/gold/dpvs_export/")
    ap.add_argument("--report", action="store_true",
                    help="Print season/career report to stdout")
    ap.add_argument("--rebuild-tcs", action="store_true",
                    help="Force rebuild of player_game_defense.parquet")
    ap.add_argument("--min-games", type=int, default=6,
                    help="Minimum games played to include in DPVS-G (default: 6)")
    args = ap.parse_args()

    seasons = _parse_seasons(args.seasons)
    run(
        seasons=seasons,
        teams=args.teams,
        export=args.export,
        report=args.report,
        rebuild_tcs=args.rebuild_tcs,
        min_games=args.min_games,
    )


if __name__ == "__main__":
    main()
