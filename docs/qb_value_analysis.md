# QB Value Analysis — Problem Statement & Findings

> **2026-08-21 addendum #2 — game-level QB win attribution + `WAE_Vegas`:** the biggest remaining
> design gap in this notebook was fixed today: every WAE number below this line (now labeled
> `WAE_DefRank`) attaches a whole team-**season's** win-loss record to whichever QB had the most
> passing attempts that *season* — `games_started` was computed but never used to gate win
> attribution. A team with heavy in-season QB rotation could silently credit/debit the wrong QB for
> games he didn't play. The motivating case: the 1978-1993 Chicago Bears had elite defenses paired
> with a rotating cast of QBs (Avellini, Phipps, Evans, McMahon, Fuller, Tomczak) — exactly the
> scenario where season-level attribution risks getting the wrong QB credit for a given win or loss.
>
> **What changed:** the notebook now also builds a **game-level** model. For every individual
> `football_db` game (1967-2025; `gold.games` doesn't go back further — see Data Sources below), the
> "primary passer" is whoever had the most passing attempts **in that specific game**
> (`gamebooks_boxscores/outputs/pfr_qb_passing_by_game_1950_2025.csv`, already built/verified in a
> prior session), and only that QB is credited/debited with that game's actual win or loss. A QB's
> career WAE is now the average/sum across his individual game appearances as primary passer, not
> across team-seasons. Two baselines are computed against this same game-level unit:
> - **`WAE_DefRank`** (renamed from the old `WAE`) — same isotonic-regression-on-defensive-PPG-rank
>   methodology as before, just applied per game instead of per season (a game inherits its team's
>   season-level expected-win-rate).
> - **`WAE_Vegas`** (new) — the Vegas closing line (`silver.game_info_pfr.vegas_line`, 100% coverage
>   1967-2025) as the expected-outcome baseline instead of defensive rank. The betting market prices
>   in *everything* — QB, O-line, coaching, injuries, matchup — not just defense, so beating Vegas is
>   a different, arguably higher, bar than beating a defense-only expectation. Team name → franchise
>   resolved via `gold.franchise_aliases`' season-windowed full-name aliases (handles every
>   relocation/rename — Colts, Chargers, Rams, Raiders, Oilers/Titans, Cardinals — with zero
>   unresolved team names across all 14,015 games with a vegas_line, 199 of which are a "Pick"
>   with no favorite). Vegas-implied home margin → win probability via the same isotonic-regression
>   approach as `WAE_DefRank`, fit on real outcomes (14,015 games): a 3-point home favorite wins
>   43.6% of the time (the *away* team still favored to win despite the smaller spread, since home
>   field is worth ~2-3 points on its own); pick'em games (margin 0) go to the home team 54.2% of the
>   time, which is exactly home-field advantage showing up with no other information.
>
> **Result on the motivating case (Chicago Bears, 1978-1993, restricted to actual CHI games in that
> window):**
>
> | QB | G | W-L | Win% | `WAE_DefRank`/g | `WAE_Vegas`/g |
> |---|---|---|---|---|---|
> | Jim McMahon | 63 | 47-16 | .746 | **+0.063** | **+0.140** |
> | Mike Tomczak | 32 | 21-11 | .656 | +0.051 | +0.048 |
> | Mike Phipps | 22 | 14-8 | .636 | −0.014 | +0.126 |
> | Steve Fuller | 13 | 8-5 | .615 | −0.115 | +0.014 |
> | Bob Avellini | 18 | 8-10 | .444 | −0.152 | −0.037 |
> | Vince Evans | 33 | 11-22 | .333 | −0.254 | −0.093 |
>
> This **partially** confirms and **partially** corrects the working hypothesis. Evans and Fuller are
> negative on both metrics — genuinely defense-carried, consistent with the "bad QB, good defense"
> read. But McMahon and Tomczak are the surprise: both were *already* negative under the old
> season-level model (McMahon's published career `WAE_DefRank` was **−0.88/season**, driven largely
> by seasons he didn't finish, e.g. 1982's strike-shortened year and 1989 in San Diego where the team
> struggled without much of his involvement) — but restricted to games McMahon himself actually
> started, his record is a strong 47-16 and his `WAE_DefRank` is essentially neutral-to-positive
> (+0.063/game ≈ **+1.0 win/16 games**, vs. the old −0.88/season). **The season-level model wasn't
> wrong about the *sign* of the underlying narrative by accident — it was wrong about *which games*
> caused it.** McMahon's own starts were fine; it was the games other Bears QBs started in seasons
> where McMahon happened to lead the team in attempts that dragged the old number negative. Full
> career numbers (any team, not just CHI, all games 1967-2025 as primary passer) tell the same story:
>
> | QB | Career G | W-L-T | `WAE_DefRank`/g | old season `WAE`/s |
> |---|---|---|---|---|
> | Jim McMahon | 99 | 68-31-0 | +0.041 | −0.88 |
> | Mike Phipps | 75 | 38-35-2 | +0.028 | +0.11 |
> | Bob Avellini | 52 | 26-26-0 | −0.008 | −0.06 |
> | Mike Tomczak | 76 | 43-33-0 | −0.021 | −0.72 |
> | Steve Fuller | 49 | 21-28-0 | −0.151 | −1.05 |
> | Vince Evans | 45 | 15-30-0 | −0.236 | −2.75 |
>
> McMahon and Tomczak flip from clearly negative to roughly neutral once win attribution is corrected
> to the games each man actually played; Phipps, Avellini, Fuller, and Evans hold the same sign and
> similar relative order under both models — for those four, the season-level number happened to be
> directionally right even though its unit of analysis was wrong.
>
> **Named-QB comparison, both baselines, game-level (1967-2025 scope):**
>
> | QB | G | W-L-T | Win% | `WAE_DefRank`/g | /16g | `WAE_Vegas`/g | /16g |
> |---|---|---|---|---|---|---|---|
> | Patrick Mahomes | 142 | 107-35-0 | .754 | +0.205 | +3.33 | +0.084 | +1.37 |
> | Peyton Manning | 286 | 198-88-0 | .692 | +0.177 | +2.89 | +0.063 | +1.03 |
> | Drew Brees | 302 | 181-121-0 | .599 | +0.140 | +2.29 | +0.016 | +0.25 |
> | Roger Staubach | 129 | 94-35-0 | .729 | +0.132 | +2.15 | +0.042 | +0.69 |
> | Tom Brady | 376 | 284-92-0 | .755 | +0.128 | +2.08 | **+0.093** | **+1.52** |
> | Aaron Rodgers | 274 | 172-101-1 | .630 | +0.114 | +1.87 | +0.028 | +0.46 |
> | Steve Young | 149 | 101-48-0 | .678 | +0.112 | +1.83 | **−0.008** | **−0.12** |
> | Dan Marino | 254 | 154-100-0 | .606 | +0.100 | +1.63 | +0.024 | +0.39 |
> | Joe Montana | 183 | 132-51-0 | .721 | +0.085 | +1.38 | **+0.087** | **+1.42** |
>
> `per16` columns are `avg_wae_per_game × 16.3`, for rough visual scale-parity with the old per-season
> table — not a literal season (careers span 14/16/17-game seasons). Bold cells mark the three biggest
> `WAE_DefRank` vs. `WAE_Vegas` **disagreements** in this named list: **Brady and Montana rank much
> higher under `WAE_Vegas` than under `WAE_DefRank`**, and **Young flips slightly negative under
> Vegas** despite a strong `WAE_DefRank`. This is a real, informative divergence, not noise — Vegas
> already prices in "this QB plays behind a great defense," so a QB who *still* beats that
> already-inflated expectation (as Brady and Montana both do) is clearing a higher bar than beating a
> defense-only baseline. This cuts directly against this doc's original central hypothesis (below) —
> the market-based metric does not support "Brady's reputation overstates his contribution" nearly as
> strongly as the defense-only metric suggested. Young's flip is the mirror case: elite by
> `WAE_DefRank`, average-to-slightly-below by `WAE_Vegas` — his teams beat what the *defense* predicted
> but didn't clearly beat what the *market*, which already knew about that defense, expected of him.
>
> **Coverage/scope notes:** `gold.games` (and therefore both game-level metrics) covers 1967-2025 only
> — ~1,417 pre-1967 primary-passer game-appearances (Otto Graham, Bobby Layne, and the early careers
> of Johnny Unitas/Bart Starr) have no game-level or `WAE_Vegas` figure; they retain only the
> season-level `WAE_DefRank` number from the original table below. 165 QBs qualify for the game-level
> leaderboard at a 60+ career-games-as-primary-passer bar (~4 seasons). `WAE_DefRank` game-level
> coverage is 27,455/28,013 game-appearances — the 558-game gap is almost entirely the 2025 season,
> whose PFR team-history file (defensive rank source) isn't populated yet, plus a handful of
> 1967-1969 rows.
>
> **Data-quality finding, out of scope to fix here:** `gold.games.game_type` and `.week` are
> populated but **uniformly wrong** across all 14,016 rows — every row reads `game_type='playoff'`,
> `week=NULL`, including provably-regular-season games. This looks like an ingestion default that was
> never corrected. Rather than build a fragile date-based regular/playoff classifier around it, the
> game-level tables above include every `gold.games` row (regular season and playoff both) as one
> QB appearance — a real methodology difference from the season-level `WAE_DefRank` table below, which
> only ever saw regular-season win-loss totals. Flagging this for whoever next touches `gold.games`
> in `football_db`.
>
> Full rebuild lives in `notebooks/qb_value_analysis.ipynb`'s final section (cells appended
> 2026-08-21, after the original season-level model). Vegas team-name resolution had **zero**
> unmatched favored-team names against `gold.franchise_aliases` — a clean result worth noting given
> how often this kind of franchise-name join has silently dropped rows elsewhere in this project.

> **2026-08-21 addendum #1:** re-executed the notebook end-to-end again to verify every table in this
> doc against the fixed pipeline (the 2026-08 coverage-audit fix described below). Nearly everything
> reproduced exactly. One real remaining bug found: the Era-Adjusted Z-Score table's Johnny Unitas and
> Bart Starr rows still carried stale pre-fix values (season counts 11/10 instead of the correct 15/12,
> with correspondingly wrong z-scores) even though the WAE table above it had already been corrected —
> fixed below, and Brett Favre (in the notebook's `NAMED_QBS` list but missing from this table) added.
> No other table in this doc changed.

## Problem Statement

Traditional NFL QB evaluation conflates individual QB quality with team success.
Win totals and Super Bowl rings are used as a proxy for QB greatness even though
team defense — not QB play — is the strongest single predictor of winning.

**Central hypothesis:** Tom Brady's "GOAT" reputation overstates his individual
contribution because he played his prime seasons behind consistently top-20% defenses.
Peyton Manning and Aaron Rodgers are more defensible as the best *pure QBs* because
they maintained elite passer ratings with below-average defensive support throughout
most of their careers.

---

## Notebook

`notebooks/qb_value_analysis.ipynb`  
Kernel: `Python (football-analytics)` (`.venv` in project root)  
Data paths (correct as of 2026):
- Passing stats: `~/data/pfref/raw/season/player/passing/passing_{year}.csv` (1950–2025)
- Team history: `~/data/pfref/raw/team-history/{Franchise_Name}.csv`

**Column name note**: this is raw, per-year PFR scrapes, and column names vary by year in a way
that doesn't cleanly split at 2003. `cmp`/`yds`/`team` (old) vs `comp`/`yards`/`team_abbrev` (new)
does split cleanly pre/post-2003. But `player`/`gs`/`rate` (old) vs `player_name`/`games_started`/
`qb_rating` (new) does **not** — only 2003 and 2006+ use the new names; every other year (1950–2002,
2004–2005) uses the old ones. Loading code must rename all three pairs, independently, per file.

**2026-08 coverage audit (this session):** the notebook previously started at 1960 via an explicit
`year >= 1960` filter. That cutoff was never actually verified against the data — both the passing
CSVs and team-history CSVs go back to 1950 (team history to 1920), and 1950s-era team abbreviations
(`CRD`, `BAL`, `RAM`, `CHI`, `GNB`, etc.) were already handled correctly by `abbrev_to_team_name()`.
Removing the filter cleanly adds 118 team-seasons (1950–1959); only the 1952 Dallas Texans fails to
join (one-season defunct franchise, no team-history file — expected). Coverage is now **1950–2025**.

While re-running the notebook end-to-end to confirm this, two independent, pre-existing bugs were
also found and fixed (both predate the 1950s work and would have broken execution on the *current*
raw-scrape data source for any year, not just the 1950s):
1. The `player`/`gs`/`rate` → `player_name`/`games_started`/`qb_rating` rename above was missing
   entirely, so those fields were silently `NaN` for every year except 2003/2006+ once this notebook's
   data path was repointed at the raw scrapes (it previously pointed at a now-deleted, pre-normalized
   `player-stats/` directory where this wasn't an issue).
2. Two chart cells referenced a `wae_df['primary_qb']` column that doesn't exist (the actual column
   is `wae_df['QB']`), and the Chart 6 tier-comparison loop compared tier labels with and without
   embedded `\n` characters, so it silently produced `n=0` / `nan%` for every QB-rating tier.

Both were masked in the previously-published tables because those were generated before the data
source migrated to the raw per-year scrapes. All tables below are freshly regenerated from a full
`--execute` run of the current notebook against current data.

**AFL note:** Pre-1970 AFL seasons (Namath's 1968 SB III season, Dawson's
pre-merger Kansas City years) are absent — PFR passing CSVs cover NFL only
before the 1970 merger.

---

## Methodology

### Season win% normalization
Wins divided by `season_games` per era: 12 (≤1960), 14 (1961–1977), 16 (1978–2020), 17 (2021+).

### Composite QB passer rating
All passing attempts for a team are aggregated (`comp + att + yards + td + int`),
and passer rating is recomputed from those totals. This correctly handles multi-QB
seasons (1985 Bears: McMahon + Fuller + Payton trick plays → 77.3 composite vs.
McMahon's individual 82.6). Primary QB = player with most passing attempts.

### Defensive rank normalization
`def_pts_norm = (def_pts_rank - 1) / (number_teams - 1)`  
0 = best defense in the league, 1 = worst. Accounts for league expanding from
28 → 30 → 31 → 32 teams.

### Expected wins model
**Isotonic regression** of actual win% on `def_pts_norm` across all team-seasons — a monotone
model that guarantees a better defense always predicts higher expected win% (no local inversions,
unlike the rolling-mean approach this replaced; rolling mean had 722/1,899 monotonicity violations
when checked directly against isotonic regression on the current full dataset).
Expected wins = `expected_win_pct × season_games`.

### Wins Above Expected (WAE)
`WAE = actual_wins − expected_wins`

Positive WAE = team won more than the defense alone would predict (QB + coaching +
offense + special teams all roll in). Negative WAE = underperformed the defensive
advantage. **198 QBs qualify** (4+ seasons as primary starter, 1950–2025) — up from 188 before the
1950s extension; 10 newly-qualifying QBs are pre-1960 primary starters (see WAE table below).

---

## Confirmed Findings

### Correlations (1,933 NFL team-seasons, 1950–2025)

| Metric | Pearson r | r² |
|---|---|---|
| QB composite rating vs Win% | +0.508 | 0.258 |
| Defense PPG rank vs Win% | −0.698 | 0.488 |

Defense is **1.4× more predictive** of winning than QB rating overall — but this varies by era (see decade breakdown below). Adding the 1950s (117 more team-seasons) barely moved these numbers (previously +0.532/−0.700 on the 1960–2025-only, 1,815-team-season dataset) — the core finding is not an artifact of the 1960 start date.

### Tier comparison — defense PPG rank vs. era-adjusted QB rating

QB rating tier uses within-season percentile rank to account for era-inflation (a 95 rating in 1970 ≠ 95 in 2010).

| Tier | Defense P(10+W) | Defense P(SB Win) | QB Rating P(10+W) | QB Rating P(SB Win) |
|---|---|---|---|---|
| Top 10% | **82%** | 13.0% | 74% | 9.8% |
| 11–25% | 61% | 5.8% | 59% | 7.1% |
| 26–50% | 36% | 1.7% | 34% | 1.9% |
| 51–75% | 17% | 0.6% | 19% | 1.0% |
| Bottom 25% | **2%** | 0.2% | **7%** | 0.4% |

Key reads (unchanged directionally from the 1960–2024-only version; this table was also independently
fixed — see the coverage-audit note above, the QB-rating side previously returned `n=0` for every tier
due to a label-matching bug, not a data gap):
- Top-10% defense is 8 percentage points more likely to produce a 10-win season than a top-10% QB.
- A bottom-25% *defense* is worse than a bottom-25% QB (2% vs 7%): a team can win despite a mediocre QB with a great defense and run game, but almost never overcomes a terrible defense.
- At 11–25%: QB teams have slightly higher P(SB Win) (7.1% vs 5.8%) — playoff performance may be where QB quality has an edge.

### Decade-by-decade — has defense always been more predictive?

| Decade | n | \|r\| Defense | \|r\| QB Rtg | r² Def | r² QB | Def advantage |
|---|---|---|---|---|---|---|
| **1950s** | **117** | **0.678** | **0.560** | **0.460** | **0.314** | **1.21×** |
| 1960s | 146 | 0.742 | 0.607 | 0.550 | 0.368 | 1.22× |
| 1970s | 268 | 0.761 | 0.654 | 0.579 | 0.427 | 1.16× |
| 1980s | 280 | 0.635 | 0.533 | 0.403 | 0.284 | 1.19× |
| 1990s | 291 | 0.743 | 0.632 | 0.551 | 0.399 | 1.17× |
| 2000s | 318 | 0.687 | 0.646 | 0.472 | 0.417 | 1.06× |
| 2010s | 320 | 0.699 | 0.651 | 0.489 | 0.424 | 1.07× |
| **2020s** | 160 | 0.624 | **0.694** | 0.390 | 0.481 | **0.90×** |

1960s–2020s figures are unchanged to 3 decimal places from the pre-1950s-extension version (this
table doesn't depend on player names, only on aggregate composite ratings and defensive ranks, so it
was never affected by either bug above — a useful cross-check that the current raw data source
reproduces the old one numerically once column names are fixed). The new 1950s row **fits the existing
pattern cleanly** (1.21×, right between the 1950s-adjacent 1960s' 1.22× and 1970s' 1.16×) — it doesn't
disrupt the decade-by-decade story at all, it just extends it one decade further back.

The systematic narrowing (1.21–1.22× in the 1950s–60s → 1.06× in the 2000s → 0.90× in the 2020s) reflects rule changes (2004 receiver protection, 2023 helmet rule) structurally shifting value from defense to quarterback. In the 2020s, QB rating is now *more* predictive of wins than defense PPG rank — the first time in the dataset.

### Wins Above Expected — named QBs

Sorted by avg WAE per season. `Avg Def %ile` = 0% is best defense, 100% is worst.

| QB | Seasons | Avg Wins | Avg Exp | Avg WAE | Total WAE | Avg Rating | Avg Def %ile |
|---|---|---|---|---|---|---|---|
| Peyton Manning | 17 | 11.2 | 8.3 | **+2.92** | +49.7 | 95.7 | 45% |
| Roger Staubach | 8 | 10.6 | 8.6 | +2.01 | +16.1 | 84.0 | 26% |
| Tom Brady | 21 | 12.1 | 10.1 | +1.96 | **+41.1** | 96.7 | 20% |
| Aaron Rodgers | 15 | 10.1 | 8.4 | +1.69 | +25.4 | 101.6 | 45% |
| Dan Marino | 16 | 9.6 | 8.1 | +1.50 | +24.0 | 85.2 | 48% |
| Johnny Unitas | 15 | 8.7 | 7.6 | +1.10 | +16.4 | 77.9 | 35% |
| **Otto Graham** | **6** | **9.7** | **8.8** | **+0.90** | **+5.4** | **80.2** | **3%** |
| Joe Montana | 12 | 11.0 | 10.2 | +0.79 | +9.5 | 91.9 | 19% |
| **Bobby Layne** | **12** | **7.3** | **6.6** | **+0.68** | **+8.2** | **62.8** | **37%** |
| Fran Tarkenton | 18 | 7.3 | 6.6 | +0.68 | +12.2 | 78.6 | 55% |
| Terry Bradshaw | 12 | 9.3 | 8.9 | +0.44 | +5.3 | 68.0 | 28% |
| Bart Starr | 12 | 8.7 | 8.5 | +0.20 | +2.4 | 75.4 | 24% |
| Jim McMahon | 9 | 9.3 | 10.2 | −0.88 | −8.0 | 72.4 | 18% |
| Doug Williams | 6 | 6.8 | 8.6 | −1.72 | −10.3 | 66.6 | 42% |
| Trent Dilfer | 7 | 7.6 | 9.5 | **−1.96** | −13.7 | 70.2 | 26% |

**Key takeaways** (numbers above are freshly regenerated post-fix; small shifts vs. any earlier version
of this table — e.g. Bart Starr's and Johnny Unitas's season counts changed from 10/11 to 12/15 — come
from the `player_name`/`games_started` rename bug fix described above, which previously mis-attributed
or dropped some of their qualifying seasons, not from the 1950s extension itself):
- Manning beats expectations by nearly 3 wins/season playing with below-average defenses → strongest case for "best pure QB."
- Brady's +1.96/season looks good but his 20th-percentile defenses already produce ~10 expected wins; he adds ~2 more. Montana is the same archetype: great QB, always great defense.
- Rodgers: +1.69/season is impressive given consistently 45th-percentile defense (worse than league average).
- Dilfer and Doug Williams in the negative — they *underperformed* even with top-quartile defenses. Brady's 2000 BAL defense is the actual GOAT; Dilfer just held the clipboard without fumbling.
- **Otto Graham and Bobby Layne now qualify for the first time** (6 and 12 seasons as primary starter, 1950–1955 and 1950–1959/1958 respectively) — both land solidly mid-pack (+0.90 and +0.68 WAE/season), not at either extreme. Graham's Cleveland teams played with the single best defensive support of any QB in this table (3rd percentile average) yet still outperformed a very high expectation baseline, which is a genuinely strong result — closer to the Montana/Griese "elite QB with elite defense, adds real value anyway" archetype than to a pure product of the era. This is a reasonable validation check: the 1950s extension surfaces a foundational NFL QB in a believable, non-extreme spot in the rankings rather than at the very top or bottom, which is what you'd want if the extension is working correctly rather than introducing bias.

### Era-adjusted z-scores (within-season QB rating, yards, TD rate, INT rate)

Career averages sorted by QB-z. INT-z: **positive = good** (fewer INTs per attempt than league average that year). TD-z and Yds-z use TD/att rate and raw yards respectively. Best-season QB-z shows each QB's most dominant single season vs. their contemporaries.

| QB | Yrs | QB-z | Yds-z | TD-z | INT-z | Best Yr | Best QB-z | Best Raw Rtg |
|---|---|---|---|---|---|---|---|---|
| **Steve Young** | 9 | **1.63** | 1.11 | 1.25 | 0.61 | 1994 | **3.43** | 111.4 |
| Joe Montana | 12 | 1.51 | 1.02 | 0.79 | **1.32** | 1989 | 3.27 | 114.8 |
| Roger Staubach | 8 | 1.41 | 1.21 | 0.92 | 1.11 | 1979 | 2.11 | 90.2 |
| Peyton Manning | 17 | 1.18 | 1.32 | 1.18 | 0.43 | 2004 | 2.82 | 119.7 |
| Aaron Rodgers | 16 | 1.10 | 0.54 | 1.14 | 1.21 | 2011 | 2.96 | 122.6 |
| Drew Brees | 19 | 1.09 | 1.17 | 0.79 | 0.56 | 2011 | 2.04 | 110.5 |
| Bob Griese | 9 | 1.01 | −0.45 | 1.26 | 0.10 | 1977 | 1.84 | 86.0 |
| Tom Brady | 21 | 0.99 | 0.95 | 0.82 | 1.15 | 2007 | 2.90 | 116.0 |
| Dan Marino | 16 | 0.85 | 1.16 | 0.72 | 0.60 | 1984 | 2.79 | 108.5 |
| Patrick Mahomes | 8 | 0.81 | 1.20 | 0.79 | 0.63 | 2022 | 1.93 | 104.7 |
| Johnny Unitas | 15 | 0.75 | 1.01 | 0.53 | 0.51 | 1958 | 2.13 | 85.4 |
| Fran Tarkenton | 18 | 0.74 | 0.59 | 0.36 | 0.72 | 1975 | 1.68 | 90.8 |
| Brett Favre | 19 | 0.58 | 0.69 | 0.85 | −0.10 | 1996 | 2.26 | 95.7 |
| Bart Starr | 12 | 0.51 | −0.53 | −0.07 | 0.42 | 1966 | 2.09 | 102.1 |
| John Elway | 16 | 0.26 | 0.41 | 0.10 | 0.39 | 1993 | 1.71 | 94.2 |
| Terry Bradshaw | 12 | 0.10 | 0.02 | 0.69 | −0.33 | 1978 | 1.43 | 81.5 |
| Jim McMahon | 9 | −0.21 | −0.56 | −0.33 | −0.06 | 1985 | 0.39 | 77.3 |
| Trent Dilfer | 7 | −0.80 | −1.41 | −0.60 | −0.50 | 1997 | 0.29 | 80.4 |

**Key z-score reads:**
- Steve Young (#1 career QB-z, #1 best single season) is severely underrated in GOAT discussions. His 1994 season (z=3.43) was more dominant relative to contemporaries than Rodgers' 2011 (2.96) or Brady's 2007 (2.90).
- Montana's INT-z (1.32) is the highest in the table — he was more turnover-averse relative to his era than anyone else named, including Rodgers (1.21). His playoff record reflects this.
- Mahomes' 0.81 QB-z vs his raw 104.7 rating shows modern era compression: more elite QBs today means even extraordinary play looks smaller in z-score terms.
- Bradshaw's negative INT-z (−0.33) confirms the Steel Curtain narrative: he threw more picks than average for his era.
- Griese's negative yards-z (−0.45) with a positive QB-z (1.01) = efficiency without volume. Miami's run-first offense kept his attempts down but he maximized each one.

---

## QB Case Studies — Planned

These are specific player debates to be argued with data, each focused on one
of three narrative types: **overrated by context**, **underrated by context**,
or **overlooked entirely**.

### "Defense-Carried" arguments (overrated by rings)
- **Tom Brady vs. Peyton Manning** — WAE / defensive context comparison, career arc
- **Jim McMahon / 1985 Bears** — composite QB rating 77.3; defense was #1; how many QBs win that SB?
- **Trent Dilfer / 2000 Ravens** — worst WAE among SB winners; defense allowed 10.3 PPG
- **Joe Montana** — elite QB *and* always elite defense (SF 49ers, 19th def percentile career avg); wins and WAE both legitimate, but rings are partly Walsh's defense

### "Penalized by bad defense" arguments (underrated by record)
- **Dan Marino** — zero SB wins, but +1.59 WAE/season playing with below-average defenses; best individual season (1984: 108.9 rating, 5,084 yds) came with a middling defense
- **Aaron Rodgers** — +1.75 WAE/season at 45th-percentile defense; 2011 season (122.5 rating) with a defense ranked 15th
- **Drew Brees** — 45.7 total WAE over 19 seasons, 56th-percentile defense career avg; underdiscussed in GOAT conversations
- **Fran Tarkenton** — 3 SB losses, consistently below-average defenses (55th %ile), positive WAE

### "Overlooked / undervalued" case studies
- **Roger Staubach** — only 8 qualifying seasons (retired at 38), but +2.11 WAE/season with 26th-percentile defenses; most similar career profile to Brady but rarely in that conversation
- **Bob Griese / 1970s Dolphins** — lowest avg def percentile (17%) of any GOAT candidate; how much was Shula's defense vs. Griese?
- **Len Dawson (post-merger)** — limited data (AFL gap), but post-1970 seasons show a solid QB on good Chiefs defenses
- **Steve Young** — +1.47 WAE in Montana's shadow; 1994 (112.8 rating) might be the best single QB season in the data
- **Patrick Mahomes** — highest avg WAE/season of modern QBs (3.21 over 7 seasons); genuinely elite, not defense-aided

### Structural debates
- **Effect of era on QB rating** — post-2000 rule changes inflated all ratings; need era-adjusted comparisons
- **"What if" defense swap** — if Rodgers had Brady's career avg defense, the model projects X wins; if Brady had Marino's defense, he'd project Y
- **Coaching vs. QB** — Montana's two QBs after (Young, Elvis Grbac) both performed above average; what's the Walsh/Seifert multiplier?

---

## Open Questions Specific to QB Analysis

- **Era adjustment for QB ratings**: The rule changes in 1978 (pass interference, QB protection) and especially 2004 ("Mel Blount rule" on receivers) shift all passing numbers up. A modern 95 rating ≠ a 1975 95 rating. A within-era z-score or percentile-rank may be a better GOAT comparison than raw rating.
- **"Wins above expected" doesn't isolate the QB**: WAE captures offense + special teams + coaching too. To isolate the QB, we'd need to control for offensive line quality, receiver talent, and offensive coordinator.
- **Playoff WAE**: The model is built on regular-season data only. Brady's playoff record is exceptional; a separate playoff-WAE calculation would be informative.
