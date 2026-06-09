# Analytical Framework: DPVS — Defensive Player Value Score

## Overview

DPVS is a single-season composite score for an individual defensive player that attempts to capture not just raw statistical production but **contextual contribution** — accounting for team quality, opponent quality, positional matchups, and year-over-year roster changes.

The goal is to produce a number that answers: "How much did this player improve his defense relative to a league-average replacement at the same position?"

---

## The Five Analytical Layers

### Layer 1: Team Defense Context (TDC)

**What it measures:** How good was the team defense overall? This is the baseline before we ask how much of it was due to the individual.

**Inputs:**
- `pts_against_rank` — ordinal rank in pts allowed (1 = best)
- `yds_against_rank` — ordinal rank in yards allowed (1 = best)
- Number of teams in league that season (28 pre-2002, 32 after)

**Computed values:**
```
pts_rank_pct  = (N_teams - pts_against_rank) / (N_teams - 1)   # 1.0 = best, 0.0 = worst
yds_rank_pct  = (N_teams - yds_against_rank) / (N_teams - 1)
tdc_score     = 0.5 * pts_rank_pct + 0.5 * yds_rank_pct
```

**Purpose:** Used as a prior — a player on a great defense gets some of his raw share discounted (others contributed too); a player on a terrible defense who still dominates at the individual level gets credit.

---

### Layer 2: Opponent Quality Adjustment (OQA)

**What it measures:** Was the team defense ranked well because they played weak offenses, or did they actually suppress quality opponents?

**Inputs (per game):**
- `opp_season_pass_yds_pg` — opponent's passing yards per game for the full season
- `opp_game_pass_yds` — passing yards the opponent actually gained in this game
- `opp_season_rush_yds_pg` — opponent's rushing yards per game for the full season
- `opp_game_rush_yds` — rushing yards the opponent actually gained in this game
- `opp_season_pts_pg` — opponent's points per game for the full season
- `opp_game_pts` — points the opponent scored in this game

**Computed per game:**
```
pass_yds_delta  = opp_game_pass_yds - opp_season_pass_yds_pg
rush_yds_delta  = opp_game_rush_yds - opp_season_rush_yds_pg
pts_delta       = opp_game_pts      - opp_season_pts_pg
total_yds_delta = pass_yds_delta + rush_yds_delta
```

Negative delta = defense held opponent below their average = better than expected.

**Seasonal OQA:**
```
oqa_pts_score  = mean(pts_delta)  across all games player participated in
oqa_yds_score  = mean(total_yds_delta) across all games
```

The stronger/weaker the opponents suppressed, the more or less credit the team defense receives.

**Important:** Opponent's season averages must **exclude** games vs. the team being analyzed to avoid circular inflation (the team they're evaluating skewing the opponent's average).

---

### Layer 3: Individual Stat Shares (ISS)

**What it measures:** What fraction of the team's total defensive production did this player account for?

**Why shares instead of raw totals:** Different teams run different amounts of plays; sack totals scale with pass attempts faced; and pre-2001 tackle data varies by team's own tracking methodology. Shares normalize across context.

#### 3a. Sack Share

```
sack_share_season = player_sacks_season / team_sacks_season
sack_share_pg     = mean(player_sacks_game / team_sacks_game) per game played
```

Team sacks per game can be derived from boxscore: sum of `sacked` column on all QB rows for the opponent team in each game.

Sack data is reliable back to at least the mid-1980s on PFR.

#### 3b. Tackle Share

Tackles are unreliable on PFR pre-2001. Sources by era:

| Era | Source |
|-----|--------|
| Pre-2001, gamebook available | Gamebook play counts (solo + assisted) |
| Pre-2001, no gamebook | Season total NOT used; mark as null |
| 2001+ | PFR `solo_tackles + 0.5 * ast_tackles` |

```
tackle_share_season = player_tackles / team_tackles
tackle_share_pg     = mean(player_tackles_game / team_tackles_game) per game played
```

#### 3c. Disruption Stats

These supplement the shares for players whose primary impact is non-tackle (pass rushers):

```
int_rate     = player_ints / opp_pass_attempts  (season)
ff_rate      = player_forced_fumbles / total_opp_plays  (season)
fr_rate      = player_fumble_recoveries / total_team_fumble_recoveries  (season)
```

#### 3d. Sack Rate vs. Opponent Average

```
opp_sack_rate = team_sacks_vs_opp / opp_pass_attempts_in_game
opp_season_sack_rate = opp_season_sacks_allowed / opp_season_pass_attempts
sack_rate_delta_pg = opp_sack_rate - opp_season_sack_rate
```

Positive delta = opponent gave up sacks at a higher rate than usual in this game.

---

### Layer 4: Opponent Matchup Grade (OMG)

**What it measures:** How strong was the opposition the player faced — both the specific blocker/QB and the broader offensive unit?

#### Position Mapping (default, pre-shift era)

| Defender Position | Primary Blocker | Secondary |
|------------------|-----------------|-----------|
| LDE (Left Defensive End) | RT (Right Tackle) | TE on that side |
| RDE (Right Defensive End) | LT (Left Tackle) | TE on that side |
| DT / NT | RG or LG | C |
| LOLB / ROLB | Off-side TE or FB | — |
| MLB | C (run) or zone coverage | — |
| CB | WR1 or WR2 (coverage) | — |
| S | Slot WR or TE (coverage) | — |

These are generalizations. In modern era (post-1994 with detailed play data) more precise mapping is possible.

#### OL Quality Grade

For the specific opposing OL position:

```
ol_grade = weighted_avg(
    pass_protection_score  * 0.5,   # team passing yds / game that season
    run_blocking_score     * 0.3,   # team rushing yds / game that season
    recognition_score      * 0.2    # Pro Bowl / All-Pro appearances
)
```

Where:
- `pass_protection_score` = opponent's season passing yds pg normalized to 0–1 across league
- `run_blocking_score` = opponent's season rushing yds pg normalized to 0–1 across league
- `recognition_score` = 1.0 if All-Pro, 0.7 if Pro Bowl, 0.3 if starter, 0.0 otherwise

#### QB Quality Grade (for pass rushers)

```
qb_grade = weighted_avg(
    passer_rating          * 0.4,
    inv_sack_rate          * 0.3,   # 1 - (sacks_allowed / pass_attempts)
    pass_yds_per_att       * 0.3
)
```

Normalized across all QBs that season.

#### Full OMG

```
omg_pass_rush = 0.6 * ol_grade + 0.4 * qb_grade    (for DE/DT)
omg_coverage  = wr_grade                             (for CB/S)
omg_run_stop  = ol_grade * rb_quality_grade          (for LB/DT run defense)
```

The OMG acts as a multiplier — a dominant performance against elite opponents earns more credit.

---

### Layer 5: WOWY — With or Without You

**What it measures:** How did the team defense change in the season before vs. the season this player joined, or the season after they departed? This is the most powerful single signal for quantifying a dominant player's effect on a unit.

**Primary WOWY (roster change):**
```
wowy_pts_delta = team_pts_rank_pct(WITH) - team_pts_rank_pct(WITHOUT)
wowy_yds_delta = team_yds_rank_pct(WITH) - team_yds_rank_pct(WITHOUT)
```

Both are OQA-adjusted (the rank percentile used is the opponent-adjusted one, not raw).

**Reference case:** 
- GNB 1992 (without Reggie White): 15th pts, 23rd yds → pts_pct ≈ 0.52, yds_pct ≈ 0.15
- GNB 1993 (with Reggie White): 9th pts, 2nd yds → pts_pct ≈ 0.71, yds_pct ≈ 0.96
- WOWY delta: +0.19 pts, +0.81 yds → very large, strongly attributable to one player

**Caveats:**
- Must account for other roster changes (additions/subtractions of other significant players)
- Injury-shortened seasons need flagging
- Coaching changes can affect scheme and thus the comparison
- The year-pair must involve a relatively static rest-of-roster; flag if >3 other significant defenders changed

**Teammate stability check:**
```
roster_overlap_score = (defenders retained) / (total defenders fielded in reference year)
```

If `roster_overlap_score < 0.75`, treat WOWY as lower confidence.

---

## Composite Score: DPVS

### Component Weights (initial, to be tuned)

| Component | Weight | Rationale |
|-----------|--------|-----------|
| Sack Share (ISS) | 0.20 | Most reliable stat across eras |
| Tackle Share (ISS) | 0.15 | Reliable 2001+; gamebook-sourced pre-2001 |
| Disruption stats (ISS) | 0.10 | INT/FF/FR rates supplement the shares |
| OQA season | 0.15 | Opponent schedule strength, normalized |
| OMG | 0.15 | Quality of blockers/coverage opponents faced |
| WOWY delta | 0.25 | Strongest holistic signal of player impact |

Weights are an initial estimate. As data accumulates, correlation analysis between components and known ground truth (All-Pro/DPOY seasons) will allow weight calibration.

### Normalization

All components are normalized to a 0–100 scale within that season's defensive population at the player's position group:

```
position_groups = {
    'pass_rusher': ['LDE', 'RDE', 'OLB pass rush', 'DT pass rush'],
    'run_stopper': ['NT', 'DT', 'MLB', 'ILB'],
    'coverage':    ['CB', 'SS', 'FS', 'OLB coverage']
}
```

Some positions contribute to multiple groups with split weights (e.g., a versatile LB who rushes and covers).

### Final DPVS

```
dpvs_raw = sum(weight_i * component_i)  for all components
dpvs_100 = 100 * (dpvs_raw - position_min) / (position_max - position_min)
```

A score of 100 = best in position group that season. A score of 50 = league average.

---

## Career DPVS

```
career_dpvs = weighted_avg(season_dpvs, weight=games_started)
peak_dpvs   = max(season_dpvs) over career
prime_dpvs  = mean(season_dpvs) for seasons in top-3 position group
```

Three numbers tell the story: peak (best single season), prime (sustained excellence), career (volume-weighted).

---

## Known Limitations & Future Enhancements

| Limitation | Impact | Potential Fix |
|-----------|--------|--------------|
| No per-game defensive stats pre-2001 (PFR) | Seasonal ISS only; no game-by-game | Scrape PFR player game log pages |
| Gamebook coverage sparse and only MIN/PIT | Tackle share unavailable for most pre-2001 players | Expand gamebook OCR pipeline to more teams |
| OL individual quality hard to measure before awards data | OMG is approximate | Use Pro Bowl/All-Pro data for OL recognition |
| Shadow effect (plays called away from great player) not captured | Undervalues dominant players | Would need play-by-play direction data (post-2009) |
| Pre-1975 data very sparse | Early eras have wider confidence intervals | Flag era in all outputs |
| Media guide data not yet fully parsed into CSVs | Pre-1995 gaps in some defensive stats | Prioritize media guide pipeline completion |

---

## Validation Approach

Use known consensus DPOY/All-Pro seasons as ground truth:

| Player | Year | Expected Rank |
|--------|------|--------------|
| Reggie White | 1988 | Top 3 DE |
| Reggie White | 1987 | Top 3 DE (strike-shortened, adjust) |
| Lawrence Taylor | 1986 | #1 overall |
| Deacon Jones | 1967–68 | Top 3 overall |
| Alan Page | 1971 | Top 3 overall (won NFL MVP) |
| Mean Joe Greene | 1972–74 | Top 3 overall |
| Jack Lambert | 1976 | Top 3 LB |

If DPVS places these players in the right tier relative to peers, the weights are in the right ballpark. If not, revisit component weights.
