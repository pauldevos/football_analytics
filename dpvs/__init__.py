"""
DPVS-G — Defensive Player Value Score (Gamebook-Enhanced)

A three-layer individual defensive player metric:

  Layer 1  TCS  — Team Credit Share
           Equal share of team TDGS per game participated.
           Inherits OQA (dual benchmark) and era normalization from TDGS.

  Layer 2  IDI  — Individual Disruption Index
           Weighted share of team's disruptive events: tackles (gamebook),
           sacks, interceptions, fumble recoveries, forced fumbles.

  Layer 3  WOWY — With Or Without You
           Average TDGS in games played vs. games missed.
           Detects individual causal impact beyond team membership.

All three are z-scored within (season × position_group) before combining:

  DPVS-G (with WOWY) = 0.50·TCS_z + 0.30·IDI_z + 0.20·WOWY_z
  DPVS-G (no WOWY)   = 0.60·TCS_z + 0.40·IDI_z

DPVS-G = 0 means league average for that position group that year.
DPVS-G = +2 means historically elite (top 1-2% in that position group).

Quick start:
    from football_analytics.dpvs.composite import build_composite, career_summary
    from football_analytics.dpvs.tcs import load_or_build_player_game, aggregate_tcs
    from football_analytics.dpvs.idi import load_gold_stats, load_all_gamebook_idi, compute_idi
    from football_analytics.dpvs.wowy import compute_wowy
    from football_analytics.dpvs.export import export_all

Or run the pipeline directly:
    python football_analytics/scripts/build_dpvs_g.py --seasons 1967-1981 --teams min pit
"""
