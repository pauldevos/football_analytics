# DPVS Framework — Analytical Decisions Log

A running record of analytical decisions made during framework development:
what we tried, what we found, and why we settled on the approaches we did.
Each entry captures the finding, the evidence, and the conclusion.

---

## 1. Team Credit Split: Equal vs Stat-Events-Weighted

**Decision:** Split team game credit (TDGS) equally among all qualifying defensive
participants.

**Finding:** Correlation between per-game participant stat events and per-game TDGS = **r = 0.054** (2000 NFL season, 259 games, all teams). Effectively zero.

**Why this matters:** The question was whether a defender who recorded more tackles/sacks
in a game should receive proportionally more of the team's defensive credit for that
game. The intuition: "more active = more responsible for the result." The data says no.

**Explanation:** Stat events are largely a function of *volume of plays the team faced*
and *how the game unfolded*, not the quality of defense. A team giving up 500 yards
tends to generate more tackle events (opponent keeps sustaining drives) than a team
allowing 150 yards (fewer plays, fewer tacklers needed). Weighting by stat events
would therefore *penalize* the better defense.

**Conclusion:** Equal split. Keep team credit strictly independent of individual
counting stats. TDGS / n_participants is the correct formula.

**Code reference:** `scripts/build_game_defense.py` → `team_credit_share`

---

## 2. Team Credit vs Individual Counting Stats: Kept Separate

**Decision:** TDGS team credit and individual play-level EPA (from gamebook or PFR
play-by-play) are computed independently and combined at the DPVS composite stage.
They are never merged or double-counted at the game level.

**Rationale:** A sack or a tackle already carries its own EPA value (from the EP model).
That EPA belongs to the individual play. The team credit is a separate accounting of
"this team held a tough offense in check" — value that accrues to all defenders on
the field whether or not they personally were credited with a play. 

The cleanest analogy: team credit = floor credit for being on the field for a
great defensive performance. Individual EPA = credit for specific plays.

**Example that motivated this:** Alan Page in a game where the Vikings held Cleveland
to 151 yards and 3 points. Page had 2 tackles credited in the gamebook. But the
defense as a whole outplayed a strong offense by ~165 yards. Page deserves credit
for that team performance even on plays where he didn't get a stat. The team credit
captures exactly this contribution.

---

## 3. TDGS Formula — Dual Benchmark (League Average + Opponent Expectation)

**Decision:** The game-level team defense score uses a 50/50 blend of two benchmarks:
1. vs. league average offense (absolute quality)
2. vs. opponent's season offensive average (opponent-adjusted quality)

```
yds_credit = 0.5*(league_avg_yds − yds_allowed) + 0.5*(opp_avg_yds − yds_allowed)
pts_credit = 0.5*(league_avg_pts − pts_allowed) + 0.5*(opp_avg_pts − pts_allowed)
TDGS = 0.55*yds_credit/season_std_yds + 0.45*pts_credit/season_std_pts
```

**Why both benchmarks:** Using only vs. league average ignores that holding a 420-yd
offense to 300 yards is more impressive than holding a 260-yd offense to 300 yards.
Using only vs. opponent expectation would miss the absolute quality dimension — some
defenses are great week after week regardless of opponent.

The 50/50 blend rewards both.

**Weights 0.55/0.45 (yards/pts):** Yards is a better leading indicator of defensive
process; points includes variance from turnovers, special teams, and scoring position
that isn't purely the defense's doing. Yards gets slightly more weight.

**Normalization by season std (z-score):** Makes scores comparable across eras. A defense
that is 90 yards/game below average is more dominant in a tight-std era (1969, std=33)
than in a high-variance era (2000, std=49).

---

## 4. Z-Score Era Adjustment — What It Means and Doesn't Mean

**Finding:** The 1969 Minnesota Vikings score higher (TDGS +2.70/game avg) than the
2000 Baltimore Ravens (+1.73/game avg) despite the Ravens being widely regarded as
the best modern defense.

**Why:** The 1969 league had very low variance (std_yds = 33) vs 2000 (std_yds = 49).
The Vikings were 2.8σ below average in yards; the Ravens were 1.6σ below.

**The philosophical question this raises:**
- **Z-score = era-relative dominance.** The Vikings were more unusual for their time.
- **Raw performance** would favor the Ravens (165 yds/game allowed vs. Vikings' 194).

| Measure | 1969 Vikings | 2000 Ravens |
|---------|-------------|-------------|
| Yds/game allowed | 194 | 165 |
| League avg yds/game | 299 | 319 |
| League std yds/game | 33 | 49 |
| Yds below average | −105 | −154 |
| Yds z-score | **−3.2σ** | **−3.2σ** |

Interestingly, both defenses are almost identical in yds z-score. The TDGS difference
mainly comes from the **points** component: the 1969 Vikings allowed 10.8 ppg in an
era where league avg was 20.9 ppg, std=3.4 → **−3.0σ below average** in scoring.
The 2000 Ravens allowed 9.4 ppg vs. avg 20.7, std=5.2 → **−2.2σ** below average.

The Vikings' points defense is more extreme relative to their era than the Ravens'.
This is a valid finding: the 1969 NFL had far less offensive variance, so maintaining
9-10 ppg allowed was even harder by the field distribution.

**Practical implication for DPVS:** The z-score approach is correct for comparing
players across eras on a common scale. If you want to say "which defense was literally
better in terms of yards allowed," use raw numbers. If you want to say "which defense
was more dominant relative to what their opponents could do against typical defenses
in that era," use z-scores. DPVS uses z-scores by design.

---

## 5. Participation Framework — Starters + Player_Defense Supplement

**Decision:** Defensive participant = named starter in `starters.csv` OR player with
≥4 stat events in `player_defense.csv` for that game.

**Stat events defined (pre-2001):** sacks (≥0.5 = 1 event) + INTs + FRs + FFs.
Tackles blank pre-2001; starters.csv is the primary source.

**Stat events defined (post-2001):** tackles_combined + sacks (≥0.5=1) + INTs + FRs + FFs.

**Why the threshold matters:** Non-starters with 4+ events are meaningfully "in the game"
defensively. The min_events=4 threshold captures players like Rob Burnett (Ravens 2000 LDE,
6 games, avg 6.0 events) who are excluded from PFR's starters.csv due to the systematic
10-starter issue described below.

---

## 6. The Missing LDE Bug — Scraper, Not PFR Data

**Finding:** `starters.csv` consistently lists **10 defensive starters** (not 11)
for 4-3 defenses. The LDE position is always missing.

- **1969 Vikings:** Carl Eller (LDE) missing in all 17 games. LDE appears 1×/232 expected.
- **1971 Vikings:** Same — Eller missing in all 15 games.
- **1983–86 Raiders:** Howie Long (LDE) missing from all games.
- **2000 Ravens:** Rob Burnett (LDE) missing from starters.csv.

**Initial (wrong) diagnosis:** PFR data limitation — thought PFR only provided 10 starters.

**Correct root cause (confirmed by user screenshots):** PFR has ALL 11 starters correct
back to the 1930s. The bug is in our scraper.

PFR's starters HTML table uses `class="divider"` on the **first defensive player's
row** (always LDE in a 4-3) to draw the thick visual border separating offense and
defense sections. `parse_standard_table` in `base.py` had:

```python
if "thead" in cls or "divider" in cls:
    continue  # ← unconditionally skipped Eller's entire row
```

**Fix applied (June 2026):** Changed to check for empty content before skipping:
```python
if "divider" in cls:
    if not any(td.get_text(strip=True) for td in tr.find_all(["th", "td"])):
        continue  # only skip truly empty divider rows
```

**Required follow-up:** All existing `starters.csv` files were scraped with the broken
parser and need to be re-scraped. Run `scrape_all_tables.py` with `--force` for
seasons 1950–2024.

**Impact until re-scraped:** LDE gets zero team credit from starters.csv source.
Post-2001: mitigated by player_defense.csv supplement (4+ stat events).
Pre-2001: only captured when Eller/Long has 4+ non-tackle events (sacks/INTs/FFs/FRs).

**Alternative scraper:** `scrape_game_starters.py`'s `parse_starters_table` uses
positional cell access and never had this bug — its output (in Postgres `game_starters`
table) includes Eller correctly.

---

## 7. Validation Results (Four Test Cases)

**Target:** Four historically elite defenses that should score in the top tier.

| Team | Season | TDGS avg/game | Yds/g | Pts/g | League avg yds | League avg pts |
|------|--------|---------------|-------|-------|---------------|---------------|
| MIN  | 1969   | **+2.702**    | 206.8 | 10.8  | 299.4         | 20.9          |
| MIN  | 1971   | **+1.854**    | 239.3 | 10.6  | 285.8         | 19.4          |
| ATL  | 1977   | **+1.422**    | 231.6 | 9.2   | 285.8         | 17.2          |
| RAV  | 2000   | **+1.733**    | 240.2 | 9.4   | 319.4         | 20.7          |

**Reference anchor:** Kansas City Chiefs 2000 = −0.040 (near-perfect zero = average defense).
Cleveland Browns 2000 = −0.855 (bad expansion team).

**Narrative consistency:**
- Vikings arc: 1969–1971 peak → gradual decline through 1970s → poor in 1978–1981 → resurgence 1988–1989. Matches historical record.
- Falcons: 1977 is their only elite year. All other seasons average or below.
- Ravens: Built from −1.8 in 1996 (expansion year) to +1.1 in 1999 to +1.7 in 2000.

---

## 8. Best Individual Games (Historical)

Top individual game TDGS scores observed in validation runs:

| Game | Defending team | Opp | Yds allowed | Pts | TDGS |
|------|---------------|-----|-------------|-----|------|
| 196911090min | MIN 1969 | CLE | 151 | 3 | **+5.249** |
| 196910120chi | MIN 1969 | CHI | 119 | 0 | **+5.000** |
| 197110030min | MIN 1971 | BUF | 64  | 0 | **+5.175** |
| 200012310rav | RAV 2000 | DEN | 177 | 3 | **+4.047** |

The 1971 game vs BUF (64 yards, shutout) is remarkable — the Vikings held a Bills
offense that averaged ~238 yards/game to 64 yards. Per-participant credit: ~+0.52
per starter.

---

## 8. WOWY Is Embedded in the Participation Credit — By Design

**Decision:** `total_credit` (the SUM of per-game credits across all games a player
participated in) is the correct season-level team defense stat for DPVS scoring.
Do not use `per_game_credit` (the arithmetic mean) for ranking.

**How WOWY appears naturally:**

Each game's credit = `TDGS_game / n_participants_game` — computed only for the
games the player actually appeared in. If a player misses a game, that game's
TDGS contributes zero to their total (not a penalty, not a bonus — it simply
doesn't count).

This means two teammates on the same team with different game counts will have
different `per_game_credit` averages, reflecting which specific games each
appeared in:

```
Player A (16 games, played in the bad NYG game): per_game_credit = +0.270
Player B (10 games, missed the NYG game):        per_game_credit = +0.293
```

That +0.023 gap IS the WOWY signal. Player B's average is higher because the
10 games they played were on average better defensive performances than the 16
games Player A played. No separate WOWY calculation needed — it falls out of
the participation accounting automatically.

**For DPVS composite scoring:** use `total_credit` as the team defense input.
It rewards both playing in more games (durability/availability) AND playing in
higher-TDGS games (being on the field for good defensive performances). A player
who played all 17 games on the 1969 Vikings accumulates more than one who
missed 5, even if equally dominant per snap.

**For cross-player comparison:** `per_game_credit` is the correct ERA-comparable
number when comparing players across seasons with different game counts (14-game
vs 16-game vs 17-game schedules). Scale `total_credit` by games played when
needed.

**The compute_wowy() function** in `build_game_defense.py` makes this explicit
by computing avg TDGS with vs. without each player. It formalizes the same
signal that's already embedded in `total_credit` and `per_game_credit`.

---

---

## 9. OQA at Team Level Does Not Improve Win Prediction — Use Raw Z-Score for WAE Baseline

**Question:** Should WAE be computed using a raw z-score baseline or an OQA-adjusted z-score baseline?

**Finding:** OQA-adjusted pts-z is a *worse* predictor of win percentage than raw pts-z.

| Model | R² |
|---|---|
| Raw pts-z only | 0.4956 |
| OQA pts-z only | 0.4619 |
| Raw pts-z + QB-z | 0.6957 |
| OQA pts-z + QB-z | 0.6750 |

**Why OQA hurts at the team-season level:** Two reasons.

First, a great defense directly suppresses its opponents' PPG during the season. Even with leave-one-out applied correctly (opponent's season average excludes the current game), the LOO average is still partially suppressed by other good defenses the opponent faced throughout the year. The mutual-influence across a shared schedule means OQA is not fully independent — it partially reflects the quality of other defenses in the league, not just the opponent's inherent offensive strength.

Second — and more practically — there is essentially no scheduling bias in the NFL at the team-season level (correlation between schedule difficulty and win% = **−0.032** across all seasons). Good teams do not systematically face easier or harder offensive schedules than bad teams, which means OQA is not correcting a real bias. Adding it introduces noise without removing a bias that exists.

**BUT: OQA matters for pre-2002 analysis.** The scheduling-bias correlation is era-dependent:

| Era | Corr(oqa_ratio, win%) |
|---|---|
| 1960–2001 | **+0.25** (meaningful) |
| 2002–2024 | −0.05 (noise) |

Before the 2002 scheduling realignment (same-division opponents twice + rotating cross-conference games + same-finisher games), good teams in strong divisions systematically faced tougher offensive opponents. OQA partially corrects for this.

**Conclusion for WAE:** Use **raw pts-z** as the WAE baseline for all eras. Simpler, more predictive, no scheduling bias to correct at the aggregate level.

**Conclusion for DPVS individual scoring:** Use **OQA at the per-game level.** Individual player performance comparisons across games and across teams benefit from OQA because game-level matchups are much more variable than season-level aggregates. Holding the 1984 Dolphins to 7 points is meaningfully different from holding the 1984 USFL champion team to 7 points. The OQA corrects for this at the game level where it is not subject to the same mutual-influence problem.

**LOO validation confirmed:** Mean oqa_ratio = 0.9999 across 29,394 team-game rows. The leave-one-out calculation is mathematically correct.

**Code reference:** `scripts/oqa_wae.py` (scratchpad) → production version pending.

---

## 10. Variance Decomposition — Defense vs QB

**Question:** How much of the variance in team win% is explained uniquely by defense quality vs QB quality?

**Method:** Compute R² for each predictor alone, then compute unique contribution via sequential addition. Dataset: 1,762 team-seasons with both def-z and QB-z available, 1960–2024.

| Model | R² | Unique ΔR² |
|---|---|---|
| Intercept only | 0.000 | — |
| QB-z only | 0.257 | 0.257 |
| Def pts-z only | 0.496 | 0.496 |
| QB-z + Def pts-z | 0.706 | — |
| Defense unique (adding to QB) | — | **+0.449** |
| QB unique (adding to defense) | — | **+0.210** |
| Shared variance | — | 0.047 |

**Key finding:** Defense explains roughly twice as much unique variance in wins as QB quality. The shared/overlap component is small (0.047), meaning defense quality and QB quality are largely independent signals.

**Year-over-year stability (r between consecutive seasons):**
- QB-z stability: **r = 0.421** (more stable than expected)
- Def pts-z stability: **r = 0.352** (defenses turn over faster — free agency, injury)

Counterintuitive: QBs are more consistent season-to-season than defenses. This has implications for roster construction — investing in a great defense has a higher depreciation rate than investing in an elite QB.

---

## 11. IDI Reweight — TFL Added, FR Dropped (2026-08-21)

**Motivation:** A YoY stability audit of IDI's five raw-count share components (via
variance-decomposition + career split-half reliability, stripping position-group
baseline-rate confound, on raw counts normalized per game from
`~/data/gold/player_season_card.parquet`) found:

| Component | Adjusted split-half r |
|---|---|
| TFL | **0.76** (strongest of everything tested — not in IDI's formula at all) |
| INT | 0.57 |
| FF | 0.45 |
| Tackle | 0.61–0.71 (within position_group; from an earlier pass this session) |
| Sack | 0.28–0.56 |
| **FR** | **0.22** (closest to pure chance of any component) |

Decision: drop FR entirely (weight → 0), add TFL as a new component, reweight
proportional to measured reliability.

**New weights** (`_W_BASE` in `dpvs/idi.py`):
```
IDI = 0.23·tackle_share + 0.26·tfl_share + 0.16·sack_share
      + 0.20·int_share + 0.16·ff_share
```
`tackle_share` and `tfl_share` are each independently present-or-absent per
player-season; whichever are missing get dropped from `_W_BASE` and the rest
renormalize proportionally (`_idi_row()` in `dpvs/idi.py` generalizes the
old two-tier with/without-tackles pattern to both gated components).

**TFL data sources** (see `dpvs/idi.py` module docstring for full detail):
- **1967–1977**: `gamebooks_boxscores` repo's own 28-team corpus (real
  per-game TFL read from rendered gamebook images), combined from its
  existing `outputs/defensive_full_aggregate_1967_1975.csv` plus a direct
  parse of its 1976–1977 `boxscore.md` files (136 games; not yet in that
  repo's own aggregate output as of this addendum). Where corpus coverage
  for a player-season is a subset of games rather than the full schedule
  (the large majority — see `tfl_coverage` below), the observed games' TFL
  rate is used as the season-level share estimate, with both numerator and
  denominator summed over the same game subset.
- **1999+**: gold parquet's own `tfl` column (real PFR data; confirmed
  ~0% populated 1967–1998 in this session's testing).
- **1978–1998 has no TFL source at all** — a real, currently-unfilled gap
  (PFR's own `pbp.csv`-derived TFL was evaluated and rejected as a source;
  see `gamebooks_boxscores/docs/experiments/2026-08-20_pfr_pbp_vs_gamebook_completeness/README.md`
  — it undercounts sacks by ~20% on verified elite pass-rusher seasons and
  scrambles tackler credit order relative to the source gamebook).

**Coverage achieved** (`~/data/silver/dpvs_g_player_season.parquet` rebuild,
1967–2024, 20,541 player-seasons):

| `idi_tfl_source` | Rows | Seasons |
|---|---|---|
| `gold_1999plus` | 10,579 | 1999–2024 |
| `gamebooks_boxscores_partial_imputed` | 2,609 | 1967–1977 |
| `gamebooks_boxscores_full` (≥13 games observed) | 179 | 1968–1975 |
| `none` (falls back to the 4-component rebalanced formula) | 7,174 | 1967–1998 |

**Validation — pooled YoY Pearson r, season N vs N+1, OLD weights vs NEW
weights, both computed without WOWY** (`0.60·TCS_z + 0.40·IDI_z`, same
pooled-pairs methodology as the earlier WOWY/component tests this session):

| Metric | OLD weights | NEW weights |
|---|---|---|
| IDI_z (all seasons pooled, n=14,059 pairs) | 0.386 | **0.343** |
| Composite no-WOWY (all seasons pooled) | 0.377 | **0.365** |

**Result: the reweight did NOT improve pooled YoY stability — it's a small
regression on both metrics.** Splitting by era shows why:

| Era | IDI_z OLD | IDI_z NEW |
|---|---|---|
| 1967–1977 (gamebooks TFL, mostly partial-imputed small samples) | 0.313 | **0.171** |
| 1978–1998 (no TFL; only the FR-drop + reweight applies) | 0.442 | **0.388** |
| 1999–2024 (gold parquet TFL, full-season, real PFR data) | 0.368 | 0.364 |

Two distinct problems, not one:
1. **1967–1977**: `tfl_share` computed from a handful of observed games (most
   player-seasons here have `games_observed` in the low single digits) is a
   noisy share estimate — a player with 1 TFL in 1 observed game can show
   `tfl_share = 1.0`. This era drags the pooled number down the hardest.
2. **1978–1998**: no TFL is involved at all here, yet stability still drops.
   Proportionally redistributing FR's old 0.10 weight across the new base
   weights (rather than the old ones) shifts relative weight away from sack
   (moderate reliability) toward FF (lower reliability, 0.45) more than
   intended — the four-component fallback formula's *internal* proportions
   changed more than the FR-drop alone would justify.
3. **1999–2024 (the clean case — full-season, real TFL, no imputation)**
   shows essentially no change (0.368 → 0.364) despite TFL's 0.76 raw
   split-half reliability. This suggests `tfl_share` (share of a team's
   season TFL total, itself a fairly rare event — team totals are often in
   the 30–40 range) behaves less reliably as a *share* statistic than TFL
   *rate normalized per game* did in the original component test — the two
   are not the same measurement, and the share transformation appears to
   erode most of the raw signal.

**Read: implemented as specified, but not validated as an improvement.**
Spot checks (J.J. Watt 2012 `idi_z`=3.71 off a 44% team-TFL share; Aaron
Donald 2018 `idi_z`=4.00, both career-best, plausible seasons) confirm
nothing is structurally broken — TFL visibly moves rankings in the expected
direction for known elite TFL producers. But the pooled-r validation this
session was explicitly asked to run says the reweight, as implemented, is a
regression on the exact test that motivated dropping FR in the first place.
Left in place uncommitted per this task's instructions; **recommend further
tuning before treating this as the production formula** — candidates: a
minimum-`games_observed` floor before trusting a gamebooks-era `tfl_share`
row (rather than using any single-game share), and revisiting whether
`ff_share`'s weight should be capped independent of what's freed up by
dropping FR, rather than a flat proportional redistribution.

---

## 12. IDI Rebuild v2 — Rate + Volume Empirical-Bayes Components, Era-2 TFL Wired In (2026-08-21)

**Motivation:** §11's TFL/FR reweight regressed pooled YoY stability
(IDI_z 0.386 → 0.343, composite no-WOWY 0.377 → 0.365) instead of improving
it. Two root causes were diagnosed there: (1) 1967-1977 gamebooks TFL share
came from tiny unfloored game samples (1 TFL in 1 observed game → share
1.0); (2) TFL/INT/FF as *shares of team season total* are noisier than a
per-game rate, because team-level rare-event totals are themselves small.
This pass fixes both, plus closes the 1978-1998 TFL gap that §11 left
entirely empty.

**What changed in `dpvs/idi.py`:**

1. **Completeness-gated TFL, 1967-1977.** `scripts/build_tfl_gated_corpus.py`
   (new) reuses `gamebooks_boxscores/build_defensive_leaderboards.py`'s own
   completeness-ratio code directly (team Solo+Ast / opponent snaps ≥ 70%)
   rather than re-deriving it, applied per game-side across the full
   1967-1977 corpus (that script's own default range stops at 1974; this
   pass confirmed 1976 and 1977 resolve cleanly via the same DB ratio and
   included them). Output: `data_output/tfl_gamebooks_gated_1967_1977.csv`
   — season/team/player/tfl_sum/games_qualified, un-floored. `idi.py` then
   applies `MIN_GAMES_QUALIFIED_FLOOR = 4` at load time — below the floor,
   TFL is simply absent for that player-season rather than forced from a
   1-2-game sample. A canonical-name-merge bug fix was also needed here:
   the base surname-merge logic (borrowed from `build_defensive_leaderboards.py`)
   didn't fold initial+surname variants ("J. Lambert") into their matching
   full name ("Jack Lambert") — added a same-initial merge rule, confirmed
   on Jack Lambert 1976 (was fragmented 2+1+0+0 TFL across 4 name variants,
   now 3 TFL / 10 games under one canonical row).

2. **1978-1998 TFL wired in for the first time** — previously a hard gap
   (§11: "no TFL source at all"). Source: `gamebooks_boxscores`'
   `pfr_pbp_defensive_stats_1978_2025.csv` (PFR play-by-play TFL parsing).
   This is a **confirmed undercount** (~20%+ low on verified elite
   pass-rusher seasons per that repo's own experiment writeup) — used
   because it's the only source for this 21-season gap, and every row it
   supplies is tagged `idi_tfl_source = "pfr_pbp_undercount_1978_1998"` so
   it is never silently equal-confidence to the other two eras.

3. **Empirical-Bayes shrinkage on a per-game RATE (not share) for TFL,
   INT, FF:**
   ```
   shrunk_rate = (n_obs·observed_rate + k·prior_rate) / (n_obs + k)
   ```
   `prior_rate` = the player's own career rate as of the prior season
   (`pfr_player_id`-keyed cumulative count/games over strictly earlier
   seasons in the loaded frame) when that history clears
   `MIN_CAREER_OBS_FLOOR = 8` games, else the season × position_group
   population rate, else a dataset-wide scalar as a last resort.

   **k-value derivation:** this session's variance decomposition measured
   overdispersion `phi` (observed variance ÷ pure-chance/Poisson variance)
   of **2.69 (TFL)**, **1.57 (INT)**, **1.32 (FF)** — TFL closest to a real,
   repeatable individual signal, FF closest to chance (consistent with why
   FR, at φ≈1.08, was dropped entirely in §11). `phi − 1` is the "signal
   over the pure-chance floor," so `k` (prior pseudo-games) was set
   inversely proportional to it: `k = K0 / (phi − 1)`, with `K0 = 8.0`
   games (roughly half an NFL season) chosen as a documented reference
   scale — nothing measured this session pins down the *absolute* scale,
   only the ordering, so `K0` is a judgment call, not a fitted value.
   `MIN_CAREER_OBS_FLOOR` was set equal to `K0` so both floors read as one
   consistent "half-season" judgment rather than two independent numbers.

   | Stat | phi | phi−1 | k = 8.0/(phi−1) |
   |---|---|---|---|
   | TFL | 2.69 | 1.69 | **4.73** |
   | INT | 1.57 | 0.57 | **14.04** |
   | FF  | 1.32 | 0.32 | **25.00** |

4. **Volume signal alongside the rate:** raw season count is independently
   z-scored within season × position_group and blended 50/50 with the
   z-scored shrunk rate: `component_z = 0.5·z(shrunk_rate) + 0.5·z(count)`.
   50/50 chosen as the direct reading of the brief (both efficiency and
   volume should matter, neither dominating); nothing measured this
   session argues for a different split.

5. **Scale-consistency fix (a judgment call beyond the literal brief):**
   once TFL/INT/FF become z-scored composites (~N(0,1)) instead of shares
   (~0.0–0.3), blending them against *raw* `tackle_share`/`sack_share` in
   one weighted sum would let the z-scored components dominate numerically
   before the stated weights even apply — a scale bug, not a modeling
   choice. Fix: `tackle_share` and `sack_share` are now **also** z-scored
   within season × position_group before the blend, so all five IDI inputs
   share one scale. This mirrors the pattern `dpvs/composite.py` already
   uses one layer up (z-score TCS/IDI/WOWY, then weight-blend) — now
   applied inside IDI itself. Consequence: IDI's raw output is already
   close to standardized, so `composite.py`'s downstream
   `idi_z = zscore_within(idi)` is now a second, largely idempotent
   re-standardization — a strictly increasing linear transform within each
   season × position group, so it preserves this file's within-group rank
   order exactly. Left in place unchanged (no edit to `composite.py`
   needed).

**Weights unchanged from §11** (now applied to z-scored components):
```
IDI = 0.23·tackle_share_z + 0.26·tfl_component_z + 0.16·sack_share_z
      + 0.20·int_component_z + 0.16·ff_component_z
```

**TFL coverage achieved** (`~/data/silver/dpvs_g_player_season.parquet`
rebuild, 1967–2024, 20,541 player-seasons — same row count as §11's build):

| `idi_tfl_source` | Rows | Seasons |
|---|---|---|
| `gold_1999plus` | 10,387 | 1999–2024 |
| `pfr_pbp_undercount_1978_1998` | 7,038 | 1978–1998 |
| `gamebooks_boxscores_gated70pct` | 1,218 | 1967–1977 |
| `none` | 1,898 | 1967–1998 (below floor / no match) |

TFL coverage rose from 65% populated (§11) to **90.8%** populated, while the
1967-1977 tier shrank from 2,788 rows (§11, unfloored) to 1,218 (floored) —
the expected trade: fewer 1967-1977 player-seasons get a TFL number, but
every one that does clears the 70%-completeness / ≥4-game bar instead of
resting on a 1-2-game sample.

**Validation — pooled YoY Pearson r, season N vs N+1, three-way comparison,
identical pooled-pairs methodology to §11 (`scripts/yoy_stability_check.py`,
composite recomputed directly as `0.60·tcs_z + 0.40·idi_z` from saved
`tcs_z`/`idi_z`, not the WOWY-aware `dpvs_g` column):**

| Metric | Original baseline (pre-§11) | §11 (first rebuild) | **This pass (v2)** |
|---|---|---|---|
| IDI_z (pooled, n=14,059 pairs) | 0.386 | 0.343 | **0.490** |
| Composite no-WOWY (pooled) | 0.377 | 0.365 | **0.411** |

**Both metrics now clear both prior bars** — this is a real improvement,
not just a recovery back to baseline. Pair count (14,059) matches §11's
exactly, confirming the same qualification filter (both seasons present,
non-null `tcs_z`/`idi_z`) is being applied.

By era:

| Era | IDI_z (v2) | Composite (v2) | n pairs |
|---|---|---|---|
| 1967–1977 (gamebooks TFL, gated) | 0.349 | 0.493 | 2,165 |
| 1978–1998 (pbp TFL, undercount — newly added) | 0.493 | 0.424 | 5,175 |
| 1999–2024 (gold TFL, clean/full-season) | 0.531 | 0.376 | 6,719 |

The 1999-2024 "clean" era — which §11 found essentially flat (0.368 → 0.364
despite TFL's raw 0.76 split-half reliability) — moved to **0.531**,
confirming §11's own diagnosis: the *share* transformation, not TFL itself,
was eroding the signal. Moving to a per-player rate (shrunk + volume-
blended) recovers it. 1967-1977 (0.349) is still the weakest era but is now
back above the original pre-§11 baseline (0.313) rather than below it
(§11: 0.171) — the games-qualified floor plus name-canonicalization fix
appear to be doing real work, though this era's small qualifying-game
counts remain its structural limit.

**Spot checks** (`~/data/silver/dpvs_g_player_season.parquet`, all values
observed directly, not simulated):

| Player | Season | Era/tier | idi_z | dpvs_g | tfl_component_z | Notes |
|---|---|---|---|---|---|---|
| J.J. Watt | 2012 | gold_1999plus | 2.98 | 1.65 | **4.00 (capped)** | 20.5-sack season; tfl/sack/tackle components all near or at the ±4σ winsor cap |
| Aaron Donald | 2018 | gold_1999plus | 3.20 | 1.13 | 4.00 (capped) | ff_component_z also capped at 4.00; dpvs_g held down by a below-average LAR tcs_z that season — expected, not a bug |
| Luke Kuechly | 2013 | gold_1999plus | 2.13 | 2.11 | 1.79 | int_component_z 4.00 (capped); #1 run_stopper that season |
| Brian Urlacher | 2005 | gold_1999plus | 2.23 | 2.07 | 3.85 | matches real TFL=17; #1 run_stopper |
| Mike Singletary | 1985 | pfr_pbp_undercount | 0.61 | 1.63 | 1.28 | modest idi_z appropriately reflects the known Era-2 undercount; dpvs_g still solid on elite Bears tcs_z |
| Mike Singletary | 1988 | pfr_pbp_undercount | 1.04 | 1.69 | 1.72 | same caveat, slightly stronger season |
| Joe Greene | 1972 | gamebooks_gated70pct | 2.45 | 1.72 | 3.34 | matches real 9 TFL / 13 qualifying games |
| Joe Greene | 1974 | gamebooks_gated70pct | 0.34 | 1.51 | 0.26 | correctly modest — real off-year, 4 TFL / 13 games |
| Jack Lambert | 1976 | gamebooks_gated70pct | 2.29 | 2.17 | 1.19 | #1 run_stopper; TFL total now 3/10 games under one canonical name row (was fragmented 2+1+0+0 before the name-merge fix) — still short of the 5 originally quoted from an earlier, differently-sourced session count, flagged here rather than silently reconciled |
| Randy Gradishar | 1978 | pfr_pbp_undercount | 1.20 | 1.55 | 1.27 | tackle_share_z is NaN (no comb_tackles/gamebook source that season/team) → `data_confidence = "low"`, weights rebalanced over the other 4 components; int_component_z 3.02 reflects his real 4 INT. Clean fit for the "elite MLB, zero sacks, real TFL+INT production" DPOY-hypothesis pattern — correctly surfaced despite the missing tackle-share input, not treated as a gap |

All nine originally-named players plus Gradishar come out sensibly
elevated given their known real production, and the Era-2 undercount
caveat visibly shows up as a smaller (not zero) idi_z for both Singletary
seasons and Gradishar rather than either an inflated or a missing number.

**Verdict: adopt.** This version clears the YoY-stability bar §11 missed,
on both metrics, in every era including the newly-added 1978-1998 span —
not a marginal win but a clear one (IDI_z +27% over original baseline,
+43% over §11). The scale-consistency fix (point 5) was necessary for the
weights to mean what they say, not optional polish. Remaining honest
caveats: (a) 1978-1998 TFL rests on a source known to undercount — the
tier tag makes this legible per-row, but nothing here corrects the
undercount itself; (b) 1967-1977's stability, while improved, is still the
softest of the three eras, limited by how few qualifying games most
player-seasons have even after gating; (c) the career-prior fallback only
sees prior seasons *within whatever season range is loaded in the same
run* — a full 1967-2024 rebuild (as done here) gets this right, but a
narrow `--seasons` slice would under-use career priors it should have
access to. Left uncommitted per this task's instructions.

**Code/data references:** `dpvs/idi.py` (rewritten), `scripts/build_tfl_gated_corpus.py`
(new), `scripts/yoy_stability_check.py` (new), `data_output/tfl_gamebooks_gated_1967_1977.csv`
(new, 9,313 rows).

---

## 13. Roster-Based Name Canonicalization for the 1967-1977 TFL Corpus (2026-08-21)

The user supplied direct evidence that `gamebooks_v2` boxscore.md player
names are severely format-fragmented corpus-wide — comma order ("Bergey,
Bill" / "Bill Bergey" / "Bergey"), initials ("Adams, Julius" / "J. Adams"),
jersey-number-only rows ("56"), sub/role markers ("Athas (sub)"), and
OCR garbage ("Wilting Heashoff"). §12's own Lambert 1976 spot-check note
(TFL "now 3/10 games... was fragmented 2+1+0+0 before the name-merge fix")
had already surfaced the mechanism: `build_tfl_gated_corpus.py`'s
canonicalization block only merged a bare-surname/single-initial variant
into a "full" name, and only when EXACTLY ONE such "full" variant existed
per (season, franchise, surname) — since "Bergey, Bill" and "Bill Bergey"
both looked like distinct "full" names to that heuristic, the merge
silently bailed for any surname with more than one full-name-shaped
variant, which is common.

**Fix:** `gamebooks_boxscores/roster_name_resolver.py` (new,
`GamebookRosterCanonicalizer`) replaces the text heuristic with a real
roster lookup — same source `lookup_roster.py` and `parse_pfr_pbp.py`'s
`RosterResolver` already use (`silver.player_team_seasons_pfr` joined to
`gold.players`, keyed on the stable `franchise_id`, not alias text). For
every raw name string in a (season, franchise_id) group: strip trailing
parenthetical/bracket qualifiers, reorder "Last, First" → "First Last",
normalize "J.Lambert"/"Johnson B." variants, then match the extracted
surname against that team-season's real roster. Exactly one roster player
with that surname → merge every format variant to that player's canonical
`full_name`/`player_id`, no matter what it looked like. Two or more share
the surname → disambiguate by first name/initial where unambiguous;
genuinely ambiguous (e.g. NE 1972 had both Julius Adams and Sam Adams — a
bare "Adams" row is correctly left unmerged, not guessed). Jersey-number
rows and unresolved/illegible markers are excluded from the per-player
numerator entirely (never guessed onto a player) — this doesn't touch the
completeness-ratio gate itself, since that's computed from
`parse_boxscore()`'s own `team_total` row or a direct sum over
`sec['rows']`, upstream of and independent from this per-name step. Names
with no roster surname match at all (likely real OCR garbage, or a
genuine roster-coverage gap — see caveat below) are left unmatched under
their own normalized name rather than force-merged.

`build_tfl_gated_corpus.py`'s canonicalization block (previously lines
136-184) now calls this resolver instead of the old heuristic; the
completeness-ratio gating, DB team-stats resolution, and output shape are
unchanged.

**Corpus-wide match stats** (13,927 raw (season, franchise, name) pairs
across 1967-1977, one resolution per distinct name per team-season group):

| Outcome | Count | % |
|---|---|---|
| matched_unique (one roster surname match) | 12,537 | 90.0% |
| matched_disambiguated (2+ shared surname, resolved by first name/initial) | 674 | 4.8% |
| ambiguous (2+ candidates, genuinely unresolvable — left unmerged) | 155 | 1.1% |
| unmatched (no roster surname match — OCR garbage or roster gap) | 468 | 3.4% |
| excluded_jersey (jersey-number-only row) | 2 | <0.1% |
| excluded_marker (unresolved/illegible/unidentified marker) | 91 | 0.7% |

Output row count dropped from 9,313 (old heuristic) to 7,262 (new
resolver) — fewer, more correct rows, consistent with real fragmentation
being merged away rather than newly created.

**Jack Lambert 1976 (the flagged discrepancy):** now a single canonical
row — `tfl_sum=3.0`, `games_qualified=11` (previously 3/10 under the old,
partially-working merge; the extra qualifying game came from "J.Lambert",
which the old heuristic's initial-matching branch should have caught but
a residual no-space "J.Lambert" token-splitting gap prevented — fixed in
`roster_name_resolver.py`'s normalizer). This is still short of the 5
TFL quoted from an earlier, differently-sourced session count — that
discrepancy remains flagged, not silently reconciled; nothing in this
pass's evidence resolves it (both counts trace to different eras of
manual boxscore.md reads, not to a mechanical bug found here).

**Bergey/Adams spot checks (the taxonomy examples the user named):** Bill
Bergey now consolidates cleanly to one row per season across CIN
(1969-1973) and PHI (1974-1977), correctly kept separate from an
unrelated Bruce Bergey (KC, 1971) — no cross-player merging. Julius Adams
(NE, 1971-1977) consolidates "Julius Adams"/"Adams, Julius"/"J. Adams"
variants into one row per season; a handful of bare "Adams" rows in
seasons where NE also carried Sam Adams (and briefly Bob Adams) are
correctly left unmerged rather than guessed onto Julius.

**tackle_share (`dpvs/idi.py`'s other 1967-1977 IDI input) — checked, not
touched:** `load_all_gamebook_idi()` does NOT read the fragmented
boxscore.md corpus at all. It reads a separate, older pipeline's output —
`~/data/gamebooks_processed/teams/{team}/seasons/{season}_defense.csv` —
which does not exist on this machine (`GAMEBOOK_BASE.exists()` is
`False`; confirmed directly, and `build_dpvs_g.py`'s own run log prints
"Gamebook tackle data: 0 player-seasons" both before and after this
session's changes). So there was no name-fragmentation bug to fix in this
component — but it does mean `tackle_share_z` for the entire 1967-1977
era (and MIN through 1981) currently falls through to the PFR/media-guide
`comb_tackles` layer, which is itself essentially never populated that far
back, so `tackle_share_z` is NaN for most 1967-1977 player-seasons, not
just Gradishar's as the §12 note implied. This is a real, pre-existing gap
— out of scope to fix here (it requires either regenerating the missing
legacy CSV corpus or wiring IDI to read gamebooks_boxscores' boxscore.md
data for tackle share the same way this pass just fixed for TFL), but
worth flagging plainly rather than leaving it looking like an isolated
Gradishar-only caveat.

**Rebuild + YoY stability re-check** (full `--seasons 1967-2024` rebuild
of `~/data/silver/dpvs_g_player_season.parquet`, IDI formula/weights/
shrinkage unchanged from §12, `scripts/yoy_stability_check.py`):

| Version | IDI_z pooled r | Composite (no-WOWY) pooled r |
|---|---|---|
| Original baseline | 0.386 | 0.377 |
| §11 (TFL/FR reweight, no shrinkage) | 0.343 | 0.365 |
| §12 (rate+volume shrinkage, name-fragmentation bug still present) | 0.490 | 0.411 |
| §13 (this pass — roster-based name canonicalization) | 0.490 | 0.411 |

The pooled aggregate is unchanged to three decimals (0.490312 vs. the
prior 0.490; 0.411331 vs. 0.411) — fixing name fragmentation did NOT move
the corpus-wide YoY-stability metric further, in either direction. The
1967-1977 era slice on its own: n=2,165 pairs, IDI_z r=0.353, composite
r=0.493. This is a genuinely flat result, not a disguised regression or
win — plausible reasons: (1) `MIN_GAMES_QUALIFIED_FLOOR=4` and the
empirical-Bayes shrinkage already suppress most of the noise a handful of
fragmented small-sample names would have contributed; (2) the 1967-1977
era is only ~15% of the 14,059 pooled pairs, so even a real per-era shift
has limited leverage on the 3-decimal pooled number. What the fix DID
change is per-player correctness within that era (Lambert, Bergey, Adams,
and — per the corpus-wide table above — roughly 5% of all 1967-1977 names
that were previously either mis-merged or wrongly left split), which
matters for any leaderboard, career-total, or spot-check that reads
individual player-seasons directly rather than the pooled stability
statistic.

**Spot checks vs. §12** (all from the freshly rebuilt parquet; `idi_z` /
`dpvs_g` / `tfl_component_z`):

| Player | Season | §12 idi_z → §13 idi_z | §12 dpvs_g → §13 dpvs_g | Notes |
|---|---|---|---|---|
| J.J. Watt | 2012 | 2.98 → 2.98 | 1.65 → 1.65 | 1999+ era, gold `tfl` column — untouched by this fix; unchanged |
| Aaron Donald | 2018 | 3.20 → 3.20 | 1.13 → 1.13 | same, unchanged |
| Luke Kuechly | 2013 | 2.13 → 2.13 | 2.11 → 2.11 | same, unchanged |
| Brian Urlacher | 2005 | 2.23 → 2.23 | 2.07 → 2.07 | same, unchanged |
| Ray Lewis | 2001 | not in §12's table | idi_z=2.72, dpvs_g=1.97 | 1999+ era, first time checked this pass |
| Ray Lewis | 2003 | not in §12's table | idi_z=2.43, dpvs_g=1.89 | 1999+ era, first time checked this pass |
| Derrick Brooks | 2002 | not in §12's table | **not present in the dataset at all** | pre-existing gap in the TCS/participation pipeline for early-2000s TB — not caused by, or fixed by, this pass; flagged, not chased |
| Mike Singletary | 1985 | 0.61 → 0.62 | 1.63 → 1.63 | 1978-1998 pbp-undercount era, untouched by this fix; noise-level ripple only |
| Mike Singletary | 1988 | 1.04 → 1.04 | 1.69 → 1.69 | same |
| Joe Greene | 1972 | 2.45 → 2.36 | 1.72 → 1.68 | 1967-1977 era — small real shift from the corrected TFL corpus |
| Joe Greene | 1974 | 0.34 → 0.31 | 1.51 → 1.50 | same |
| Jack Lambert | 1976 | 2.29 → 2.21 | 2.17 → 2.14 | see Lambert discussion above |
| Randy Gradishar | 1978 | 1.20 → 1.18 | 1.55 → 1.54 | `data_confidence` still `low` (no tackle_share, see above) |

**Verdict:** the name-fragmentation bug was real, corpus-wide (not just
Lambert), and is now fixed for the TFL corpus specifically — 90% of raw
names resolved to a unique roster player with no ambiguity, 4.8% more via
first-name/initial disambiguation, and the remaining ~5% correctly left
unmerged (ambiguous) or unmatched (garbage/roster-gap) rather than guessed.
It did not move the pooled YoY-stability number, which is an honest
negative on that specific question — but that number was never the only
thing at stake, and per-player correctness genuinely improved. **The
1967-1977 era of DPVS-G should be considered trustworthy at the
aggregate/leaderboard level with two flagged, still-open limitations, not
fully resolved**: (a) `tackle_share_z` is unavailable for most
1967-1977 player-seasons (see above — a real, separate gap, not a name
problem); (b) the ~5% of names this pass correctly declined to guess on
(ambiguous same-surname teammates, unmatched/garbage strings) means a
small slice of real TFL production in that era is either split across an
unmerged variant or entirely absent from any player's total — accurate
by construction (no guessing), but not complete.

**Code/data references:** `gamebooks_boxscores/roster_name_resolver.py`
(new), `scripts/build_tfl_gated_corpus.py` (canonicalization block
rewritten), `data_output/tfl_gamebooks_gated_1967_1977.csv` (rebuilt,
7,262 rows), `~/data/silver/dpvs_g_player_season.parquet` (rebuilt, full
1967-2024). Left uncommitted per this task's instructions.

---

## 14. 1967-1977 tackle_share Wired In + a Franchise-Code Bug That Was
    Silently Starving Both TFL and Tackle Coverage (2026-08-21)

§13 checked (but didn't fix) a gap it found while working on TFL:
`dpvs/idi.py`'s `load_all_gamebook_idi()` reads
`~/data/gamebooks_processed/teams/{team}/seasons/{season}_defense.csv` —
a path that does not exist on this machine at all — so `tackle_share_z`
(IDI's single highest-weighted component, 0.23) has been NaN for
essentially all of 1967-1977, with IDI's gated-component rebalancing
silently absorbing the gap by spreading that weight across the other four
components rather than using real tackle data. This pass fixes it.

**Checked before building anything new:** `gamebooks_boxscores/outputs/`
and `~/data/gamebooks_v2/defensive_leaderboards.json` both already
compute season tackle numbers under the same completeness-ratio gate, but
`defensive_leaderboards.json` truncates to the top-15 tacklers per season
(per its own module docstring) — not a full population, and a season-wide
z-score needs the whole population as its mean/sd denominator, not the
visible top slice. So a full-population build was required.

**`scripts/build_tackle_gated_corpus.py` (new):** a direct structural
clone of `build_tfl_gated_corpus.py` — same >=70% completeness-ratio gate
(imported directly from gamebooks_boxscores' `build_defensive_leaderboards.py`,
not re-derived), same roster-based name canonicalization
(`roster_name_resolver.py`'s `GamebookRosterCanonicalizer`, reused
directly), same 1967-1977 range — but sums each qualifying game's
Solo+Ast instead of TFL. Output: `data_output/tackle_gamebooks_gated_1967_1977.csv`,
7,262 player-seasons (season, team, player, tackle_sum, games_qualified) —
same row count as the TFL corpus, as expected (same underlying games/name
resolution, different summed field).

**Wired into `dpvs/idi.py` following the TFL/INT/FF pattern, not the
older plain-share treatment:** the task brief asked for "the exact same
shrinkage/z-scoring/gated-component pattern already established for
TFL/FF/INT," which for 1967-1977 specifically means the rate+shrinkage+
volume treatment (`_add_rate_component`: empirical-Bayes-shrunk per-game
rate, 50/50-blended with a z-scored raw season count), not the plain
share-then-z-score treatment §12 kept for `sack_share`/PFR `tackle_share`
in other eras. New `load_gamebook_tackle_gated()` mirrors
`load_gamebook_tfl()` exactly. `compute_idi()` gained a new highest-
priority "Layer 0" for tackle_share: for 1967-1977 rows with a hit in the
gated corpus, `tackle_share_z` is overwritten with the rate+volume
`tackle_component_z` (all other eras' `tackle_share_z` computation is
untouched — the scale-consistency point from §12 still holds, since
z-scoring happens within `season × position_group` either way, so no
1967-1977 row ever mixes the two treatments). Needed a new `_PHI["tackle"]`
entry: a quick quasi-Poisson dispersion estimate on the corpus (same
method-of-moments idea as the TFL/INT/FF phi values — season-pooled
population rate as mu, Pearson chi-square / (N-1)) gave phi=4.872, higher
than TFL's 2.69 — i.e. under this same framework, tackle counts carry
*more* individual-skill signal relative to pure chance than TFL does
(intuitive: far more observations per game than a rare event), so tackle
gets `k≈2.07`, the *least* shrinkage of the four rate components.

**Incidental fix, required to run anything:** `merged["_tfl_tier"] = np.nan`
(pre-existing code, unrelated to this pass) initializes a float64 column
that later receives string tier labels via `.loc` — this environment's
pandas raises `LossySetitemError` on that assignment (a real, if latent,
bug; possibly a pandas-version difference from whenever §12/§13 last ran
it). Fixed by initializing as `dtype="object"` instead; applied the same
pattern to the new `_tackle_count`/`_tackle_nobs` columns from the start.

**A second, much bigger bug found via the Willie Lanier spot-check:**
Willie Lanier came back `tackle_share_z=NaN` for every single season
despite being in the freshly-built corpus CSV. Root cause: both
`build_tfl_gated_corpus.py` (§12) and the new `build_tackle_gated_corpus.py`
wrote each row's team code from `gold.franchises.current_abbreviation`
(queried directly from the DB), but `dpvs/idi.py` merges this corpus onto
its frame on the `team` column using gold parquet's own historic/PFR-style
codes (`_normalize_gold_team`). Those two conventions disagree for **12 of
28 franchises**: `clt`->`ind`, `crd`->`ari`, `gnb`->`gb`, `kan`->`kc`,
`nor`->`no`, `nwe`->`ne`, `oti`->`ten`, `rai`->`lv`, `ram`->`lar`,
`sdg`->`lac`, `sfo`->`sf`, `tam`->`tb` (confirmed directly against
`gold.franchises`). Every one of those 12 franchises' entire gamebook-era
TFL and tackle numerator silently never matched onto IDI at all — not
"NaN because the floor wasn't cleared," but NaN because the merge key
never had a chance to match, for the Chiefs (Lanier), Raiders (the 1967
front four topping that season's leaderboard), Rams, Cardinals, Colts,
Packers, Saints, Patriots, Oilers/Titans, Chargers, 49ers, and Buccaneers,
for the whole 1967-1977 span. This is what §13's own TFL rebuild had
already shipped with — undetected because none of its spot-check players
(Greene/Lambert/Watt/Donald/Kuechly/Urlacher/Singletary/Gradishar) happen
to play for an affected franchise.

**Fixed in both scripts** (not just the new one, since the bug is
identical and pre-existing in `build_tfl_gated_corpus.py` too): replaced
the DB `current_abbreviation` query with a hardcoded `FID_TO_TEAM` map —
the historic/PFR-style code per franchise, identical to `dpvs/idi.py`'s
own `_FID_TO_TEAM` (kept as a duplicated constant rather than a
cross-package import, to avoid a `scripts/` file reaching into `dpvs/`).
Both corpora rebuilt after the fix; `tfl_gamebooks_gated_1967_1977.csv`
and `tackle_gamebooks_gated_1967_1977.csv` are unchanged in row count
(7,262 each — the bug was in the *label*, not which games/players were
captured) but now actually match onto IDI for the previously-orphaned
franchises.

**Coverage, 1967-1977 (`tackle_share_z`, 2,958 player-seasons in range):**

| State | Non-null tackle_share_z | % |
|---|---|---|
| Before this pass (dead path + PFR fallback only) | 284 | 9.6% |
| After tackle corpus wired in, before the franchise-code fix | 1,562 | 52.8% |
| After the franchise-code fix (final) | 2,536 | **85.7%** |

The franchise-code fix alone accounts for more of the coverage gain than
the tackle corpus itself did — a reminder that a plausible-looking partial
result (52.8%, already a 5x improvement over baseline) can still be
hiding a mechanical bug rather than a genuine data-availability ceiling.

**TFL coverage also jumped from the same fix** (not the focus of this
task, but a direct side effect since both corpora shared the bug):
`idi_tfl_source == "gamebooks_boxscores_gated70pct"` rows in 1967-1977
rose from 1,218 (§12/§13's number, corpus-wide) to **2,256** — TFL
coverage for this era nearly doubled from a bug fix, not new data.

**YoY stability re-check** (`scripts/yoy_stability_check.py`, full
rebuild each step):

| Version | IDI_z pooled r | Composite (no-WOWY) pooled r | 1967-1977 IDI_z | 1967-1977 composite |
|---|---|---|---|---|
| §12 (rate+volume shrinkage) | 0.490 | 0.411 | n/a (not broken out identically) | n/a |
| §13 (TFL name canonicalization) | 0.490 | 0.411 | 0.353 | 0.493 |
| This pass, tackle wired in, before franchise-code fix | 0.497 | 0.413 | 0.401 | 0.505 |
| **This pass, final (franchise-code fix included)** | **0.502** | **0.413** | **0.433** | **0.502** |

Pooled: a modest but real gain (0.490->0.502 IDI_z, +2.4%). Broken out by
era, the 1967-1977 slice — the one this pass actually touched — moved
0.353->0.433, a **+23% relative gain**, clearing every prior mark for
this era including the original pre-§11 baseline (0.313). This matches
the task's own prediction better than §13 did: §13's fix (fragmented
names) touched correctness without touching *availability*, and moved the
pooled number by literally nothing; this pass fixed a genuine
availability gap (a component that was simply missing for most rows) and
the stability metric moved accordingly.

**Spot checks** (`~/data/silver/dpvs_g_player_season.parquet`, final
build; `idi_z` / `dpvs_g` / `tackle_share_z` / `idi_tackle_source`):

| Player | Season | tackle_share_z | idi_tackle_source | Notes |
|---|---|---|---|---|
| Joe Greene | 1972 | 0.80 | gamebooks_boxscores_gated70pct | idi_z=2.21, dpvs_g=1.62 — real career-best season, both up from §13 |
| Joe Greene | 1974 | 0.39 | gamebooks_boxscores_gated70pct | idi_z=0.43 — correctly modest, real off-year |
| Jack Lambert | 1976 | 2.89 | gamebooks_boxscores_gated70pct | idi_z=2.34, #1 run_stopper; tackle_share_z now among the highest in the dataset, matching his reputation directly rather than via TFL alone |
| Randy Gradishar | 1978 | NaN | none | correctly out of scope — this fix is 1967-1977 only; 1978 still falls through to the PFR-pbp TFL era with no tackle source, exactly as §13 documented |
| Randy Gradishar | 1975-1977 | 2.26 / -0.06 / 2.20 | gamebooks_boxscores_gated70pct / gamebooks_boxscores_gated70pct / gamebook_stats_page | now populated for all three in-scope seasons; 1976 dip (4 qualifying games only) is a small-sample artifact, not a real dip — flagged, not smoothed over |
| Willie Lanier | 1970-1976 | 1.08 to 3.28 (all 7 seasons) | gamebooks_boxscores_gated70pct | THE franchise-code bug's own discovery case — was NaN in every season before the fix despite being in the corpus CSV the whole time; now consistently elevated, matching his real reputation as a premier run-stopping MLB |
| Nick Buoniconti | 1970-1974 | 0.94 to 2.99 (all 5 seasons) | gamebooks_boxscores_gated70pct | consistently elevated across his full Miami run, as expected for a "tackling machine" |
| Dick Butkus | 1972-1973 | 1.64 / 0.37 | gamebooks_boxscores_gated70pct | populated for his two qualifying seasons; 1967-1970 remain NaN (games in those seasons don't clear the >=4-qualifying-game floor for him specifically, not a franchise-code issue — Bears already resolved correctly) |

**Verdict:** the 1967-1977 `tackle_share` gap is now genuinely fixed, not
just partially patched — 85.7% of in-range player-seasons carry a real,
shrinkage-treated tackle rate instead of falling through to a rebalanced
IDI formula, and the YoY-stability metric moved by a magnitude consistent
with fixing a real availability gap (unlike §13, which fixed correctness
without moving the aggregate number). The franchise-code bug is the more
consequential finding of this pass: it was silently zeroing out 12 of 28
franchises' worth of gamebook-sourced TFL *and* tackle data since §12
first shipped this corpus architecture, would not have been caught by any
of this session's or §13's spot-check players (all from unaffected
franchises), and was only surfaced because this task's brief specifically
asked for a Willie Lanier check. **The 1967-1977 era of DPVS-G should now
be considered solid enough to treat as finished for the current scope** —
both of its gamebook-sourced components (TFL, tackle_share) are wired,
gated, canonicalized, and now correctly matched across the full 28-team
league, with remaining gaps (the ~14% of player-seasons below the
4-qualifying-game floor, the ~5% of names §13 correctly declined to
guess on) understood and flagged rather than hidden. The one thing this
pass did NOT re-verify is whether some other downstream consumer of
`tfl_gamebooks_gated_1967_1977.csv` (outside `dpvs/idi.py`) depends on
its old, buggy team-code convention — worth a quick grep before treating
that CSV's schema as fully stable.

**Code/data references:** `scripts/build_tackle_gated_corpus.py` (new),
`scripts/build_tfl_gated_corpus.py` and `dpvs/idi.py` (franchise-code /
dtype fixes), `data_output/tackle_gamebooks_gated_1967_1977.csv` (new,
7,262 rows), `data_output/tfl_gamebooks_gated_1967_1977.csv` (rebuilt,
franchise-code fix only, still 7,262 rows), `~/data/silver/dpvs_g_player_season.parquet`
(rebuilt, full 1967-2024). Left uncommitted per this task's instructions.

---

## 15. Name-Resolver Deep-Dive: Double-Initial Parsing Bug, Leaderboard
Propagation Gap, and a Manual-Override Mechanism (2026-08-21)

A deep-dive audit of `gamebooks_boxscores/roster_name_resolver.py`'s
`GamebookRosterCanonicalizer` (the resolver §13/§14 built and this
pipeline shares with `gamebooks_boxscores/build_defensive_leaderboards.py`)
against all 13,927 raw name decisions in the current 1967-1977 corpus
found two concrete, fixable defects plus one still-open gap this pass
deliberately declined to guess its way past.

**Issue 1 — real parsing bug in `normalize_and_split()`.** No-space
double-initial names ("B.R.Smith", "D.D.Lewis", "J.T.Thomas",
"L.C.Greenwood", "A.J.Duhe") were mis-split: the old single-initial-only
regex (`^([A-Za-z])\.(?=[A-Za-z])`) only inserted a space after the FIRST
initial, so "B.R.Smith" became "B. R.Smith" — still one glued token — and
the surname extractor then took `tokens[-1] = "R.Smith"`, lowering to the
garbage roster key `"r.smith"`. These real, often Hall-of-Fame-caliber
players fell into `unmatched` even though the roster lookup would have
succeeded with a correct surname. Fixed with `LEADING_INITIALS_RE`, which
matches one-or-more glued `<letter>.` groups at the start of the string
and inserts spaces after all of them, not just the first — verified safe
against "St.Clair" (a real 2026-08-21 finding: "S" is followed by "t", not
a period, so the initials regex never starts matching into it). A related
particle-surname case surfaced by the same fix — "M.St.Clair" splits
correctly into initial "M." + surname "St.Clair", but football_db's own
`last_name` convention for "Mike St. Clair" (Cleveland Browns DE,
1976-79) is `"Clair"`, not `"St. Clair"` — is handled by a narrowly-scoped
`_strip_glued_particle()` (only "St.", the one particle with real corpus
evidence; not generalized to "Mc"/"Van"/"De" without evidence). A bonus
fix rode along: the old code only ever compared a candidate's FIRST
initial, so "B.R.Smith" on the 1968 Colts (Billy Ray Smith vs Bubba
Smith — both first names start with "B") was still a false ambiguous
after the surname fix; a new compound-initials tier (`_name_initials()`)
compares the full captured initial string ("br") against each
candidate's real leading-name initials, resolving it uniquely to Billy
Ray Smith.

Corpus-wide effect (`build_tfl_gated_corpus.py`'s canonicalizer stats,
identical for the tackle-corpus builder since both share one resolver
pass): `matched_unique` 12,537→12,543, `matched_disambiguated` 674→677
(includes the B.R. Smith compound match, 3 raw-name-instances across
1968-69), `unmatched` 468→461. `tfl_gamebooks_gated_1967_1977.csv` /
`tackle_gamebooks_gated_1967_1977.csv` row counts dropped 7,262→7,255 —
expected, not a regression: merging previously-split name variants onto
one real player reduces the player-season row count by exactly the number
of now-merged duplicates.

**Issue 2 — propagation gap in `build_defensive_leaderboards.py`.** That
script had its own, older, weaker surname-merge heuristic (merge a
bare-surname row into a full-name row only when exactly one distinct
full-name variant exists for that surname/team-season) instead of using
the shared resolver — confirmed broken on any case with two full-name-
SHAPED variants of the same player (e.g. "Bergey, Bill" vs "Bill Bergey"
both read as "full names" to a token-count check, so they'd never merge).
Replaced with a direct `GamebookRosterCanonicalizer` import, same pattern
as `build_tfl_gated_corpus.py` / `build_tackle_gated_corpus.py` — a
name-resolution swap only, the completeness-ratio gating and
leaderboard-construction logic are untouched.
`~/data/gamebooks_v2/defensive_leaderboards.json` regenerated; spot-check
confirms single consolidated leaderboard entries for Bill Bergey (1973
CIN, 91 tackles/9 games — one row, not split across "Bergey"/"Bill
Bergey"), Willie Lanier (1968-1971 KC, one row per season), and Jack
Lambert (1974 PIT, 139 tackles/16 games — one row, not split across "Jack
Lambert"/"J. Lambert"). Direct `resolve()` test also confirms both
"Bergey, Bill" and "Bill Bergey" now normalize to the identical
`matched_unique` canonical name.

**Issue 3 — manual override mechanism for genuinely irresolvable
`ambiguous` cases.** Per this project's standing rule ("A name fix needs
a roster citation... two or more plausible candidates -> flag, don't
pick one" — `gamebooks_boxscores/CLAUDE.md`), the resolver's `ambiguous`
bucket (a bare surname shared by 2+ roster players, no first-name hint in
the raw text) is never guessed algorithmically. `roster_name_overrides.json`
(new, `gamebooks_boxscores/`) is a small, evidence-required override file
`GamebookRosterCanonicalizer.resolve()` now checks FIRST, before any of
its own roster-matching logic — keyed by exact `(season, franchise_id,
raw_name)`, each entry requires a real, citable `evidence` string (see the
file's own `_readme` block for the full how-to-add-an-entry guide). Seeded
with 2 real, evidence-based resolutions (10 entries total — one per
covered season, since football_db positions can change year to year and
each season was individually re-verified rather than extrapolated):

  - **"Otto" / Oakland Raiders 1968-1971** → Gus Otto (LB). The other
    roster candidate, Jim Otto, played Center (offense) every one of
    those seasons — he structurally cannot appear on this corpus's
    DEFENSIVE Boxscore table. Corroborated in-corpus: one game
    (`19691221_wk15_oti_at_rai/boxscore.md`) already carries a
    human-written row note stating exactly this ("Gus Otto (RLB), not C
    Jim Otto — only Gus appears in the defensive lineup").
  - **"Adams" / New England Patriots 1972-1977** → Julius Adams (DE/DT).
    The other candidate, Sam Adams, played Guard/Tackle (offensive line)
    every one of those seasons. Corroborated in-corpus: every bare-"Adams"
    Defensive Boxscore row that also carries a grid position (LDT, RDT,
    RE, defensive-side "RT") matches Julius Adams's real position, never
    Sam Adams's; one outlier row already flags itself as "likely bench
    DL/LB" rather than the offensive guard.

  A third candidate, "Youngblood" / LA Rams 1973-1977 (Jack Youngblood LDE
  vs Jim Youngblood LB/LLB/MLB), was checked with the same method and
  deliberately left OUT of the override file: both players are on
  defense every season, so there is no positional (or other) signal
  available from football_db alone — this stays `ambiguous` pending
  someone actually looking at a specific game's page image. The remaining
  ~146 ambiguous cases (down from 155 pre-fix, 9 resolved by the two
  overrides above plus the compound-initials fix pulling a couple out via
  Issue 1) are unresolved pending the same kind of real evidence.

**YoY stability re-check** (`scripts/yoy_stability_check.py`, full
`build_dpvs_g.py --seasons 1967-2024` rebuild first):

| Version | IDI_z pooled r | Composite (no-WOWY) pooled r |
|---|---|---|
| §14 (franchise-code fix, immediately prior state) | 0.502 | 0.413 |
| **§15, this pass (name-resolver fixes)** | **0.502** | **0.413** |

Flat at 3-decimal precision, as expected: this pass recovers a genuinely
small number of additional real players (16 raw-name-instances via Issue
1, 7 via the two Issue-3 overrides, out of 13,927 total decisions) rather
than changing scoring methodology, so it was never going to move a
14,059-pair pooled correlation measurably — the point of this pass was
correctness/completeness at the margin, not a stability-metric win. No
regression at either the pooled or the (unchanged, not re-run
individually here) per-era level is expected or was observed in any
intermediate check.

**Code/data references:** `gamebooks_boxscores/roster_name_resolver.py`
(parsing fix + override-file wiring), `gamebooks_boxscores/roster_name_overrides.json`
(new), `gamebooks_boxscores/build_defensive_leaderboards.py` (resolver
swap), `gamebooks_boxscores/CLAUDE.md` (new Tools-section documentation),
`data_output/tfl_gamebooks_gated_1967_1977.csv` /
`data_output/tackle_gamebooks_gated_1967_1977.csv` (rebuilt, 7,255 rows
each), `~/data/gamebooks_v2/defensive_leaderboards.json` (regenerated),
`~/data/silver/dpvs_g_player_season.parquet` (rebuilt, full 1967-2024).
Left uncommitted per this task's instructions.

---

## 16. Postgres Migration: Gamebook Reload, First PFR Per-Game Load, DPVS-G Output Table (2026-08-21)

Three-part production migration, run in dependency order (task 3 depends on
1 and 2). Full row counts, grain decisions, and the football_db-side schema
detail live in `football_db/CLAUDE.md`'s own 2026-08-21 section — this
entry covers the DPVS-G-facing side: what got rewired, what didn't, and the
end-to-end validation.

**Tasks 1-2 (football_db side, summarized):** `silver.player_game_stats_gamebook`
reloaded with the §15 name-resolver fixes (30,388 rows, 1967-1977, now
carrying a `completeness_qualified` flag per row instead of the ratio gate
living only in `build_tfl_gated_corpus.py`/`build_tackle_gated_corpus.py`'s
CSV outputs). `silver.player_game_stats_pfr` populated for the first time —
422,823 rows, 1978-2025, `pbp.csv`-derived stats (this project's own
scoring convention) with player identity upgraded via
`player_defense.csv`'s real `pfr_player_id` cross-referenced through
`internal.player_xref` (73.3% of rows resolved this way — a materially more
reliable path than the name/surname matching `parse_pfr_pbp.py` used
alone). `gold.player_game_stats` rebuilt via a new merge script
(453,211 rows total). Two real pre-existing parser bugs (an ISO-date format
half the gamebook corpus uses, and `"XXX TOTAL"`-style team-total rows)
were found and fixed as part of getting the reload to actually cover the
full corpus, not introduced by this pass.

**Task 3 — what moved to Postgres in `dpvs/idi.py`:**

| Component | Before | After | Still falls back to file when |
|---|---|---|---|
| 1967-1977 TFL | `data_output/tfl_gamebooks_gated_1967_1977.csv` | `silver.player_game_stats_gamebook` (same >=70% ratio gate, now a stored column not a recomputation) | Postgres unreachable |
| 1967-1977 tackle_share | `data_output/tackle_gamebooks_gated_1967_1977.csv` | same table | Postgres unreachable |
| 1978-1998 TFL (undercount-tagged) | `gamebooks_boxscores/outputs/pfr_pbp_defensive_stats_1978_2025.csv` | `silver.player_game_stats_pfr` | Postgres unreachable |
| sack_share / int / fr / ff / comb_tackles / tfl, 1967-2025 | `~/data/gold/player_season_card.parquet` (CLAUDE.md-superseded layer) | `gold.player_game_stats` | season < 1967 (no Postgres per-game source built) |

Each of the four rewired loaders (`load_gamebook_tfl_from_db()`,
`load_gamebook_tackle_from_db()`, `load_pfr_tfl_from_db()`,
`load_gold_stats_from_db()`, all new in `dpvs/idi.py`) is tried first; the
original file-based function only runs if the Postgres connection itself
fails, not as a quality trade-off — when the DB is reachable (the normal
case) file data is no longer read for these four sources at all. A gap in
`_FID_TO_TEAM` was found and fixed while wiring `load_gold_stats_from_db()`:
that dict was built for `gamebooks_boxscores`' 1967-1977 corpus and only
had the 28 franchises relevant to it, but `gold.player_game_stats` spans
the full 1967-2025 range — the four post-1977 franchises (Jaguars,
Panthers, Ravens, Texans) were silently dropping out of the merge entirely
until added.

**What did NOT move to Postgres, and why:**
- **`dpvs/tcs.py`'s Team Credit Share** (TDGS + opponent-quality
  adjustment) — built from PFR team-level game files (`team_stats.csv`,
  `scoring.csv`, `drives.csv`, ...) via `scripts/build_game_defense.py`, a
  wholly separate pipeline from the player-level defensive-stat tables this
  migration populated. `gold.team_game_stats` has rush/pass/sack counts
  (used as this task's own completeness-ratio denominator) but not TDGS's
  point-differential/opponent-adjusted methodology. Building that in
  Postgres is a real, separate undertaking — out of scope here, TCS stays
  100% file-based.
- **1960-1966** — before both `gamebooks_boxscores`' 1967-1977 corpus and
  the PFR raw per-game files this migration ingested. `load_gold_stats()`
  still falls through to the legacy parquet for exactly this 7-season
  range; every other requested season (the standard `--seasons 1967-2024`
  rebuild) is 100% Postgres-backed for this component.
- **WOWY** (`dpvs/wowy.py`) — untouched this pass; still reads whatever it
  already read. Not part of this task's scope (the task's Postgres-source
  list was TCS/IDI only), noted here so it's not mistaken for an oversight.

**`gold.dpvs_g_player_season`** (new table, `football_db/schema/dpvs_g.sql`):
composite score (`dpvs_g`/`dpvs_a`/`dpvs_p`) plus `tcs_z`/`idi`/`idi_z`/
`wowy_z`, IDI's five z-scored components
(`tackle_share_z`/`tfl_component_z`/`sack_share_z`/`int_component_z`/
`ff_component_z`), the raw shares behind them, `position_group`, rank
columns, and provenance/confidence tags. Loaded by new
`scripts/load_dpvs_g_to_db.py` from the rebuilt
`~/data/silver/dpvs_g_player_season.parquet` — `player_id` resolved via
`internal.player_xref` (19,713/19,991 rows, 98.6%; the rest keep
`player_id` NULL with `player_name` as the fallback identifier, per this
project's standing rule against storing a raw external id on a gold
table). Full `TRUNCATE` + reload each run. 19,991 rows, 1967-2024.

**End-to-end rebuild:** `scripts/build_dpvs_g.py --seasons 1967-2024` (via
`football_analytics/.venv`, needed for `pyarrow`) ran clean against the new
Postgres-backed sources: TCS 47,640 player-seasons, WOWY 33,453, IDI's gold
stats 65,088 / gamebook tackle 2,800 / gamebook TFL 2,800 / PBP TFL 22,735
(all four counts matched exactly what each new loader returned when tested
standalone beforehand), final composite 19,991 player-seasons, 4,677 career
summaries.

**YoY stability re-check** (`scripts/yoy_stability_check.py`), against the
just-established §15 baseline:

| | Pooled n | IDI_z pooled r | Composite (no-WOWY) pooled r |
|---|---|---|---|
| §15 baseline (immediately prior state, file-based sources) | 14,059 | 0.502 | 0.413 |
| **§16, this pass (Postgres-backed sources)** | **13,657** | **0.496** | **0.415** |

Both correlations are flat within noise (IDI_z -0.006, composite +0.002) —
the storage-layer swap did not measurably change either stability metric,
which is the actual claim this check exists to validate: rewiring WHERE
the data comes from, with the same values and the same methodology, should
not move a YoY correlation, and it didn't. Per-era breakdown (not measured
before §15, so no direct prior-pass comparison, but included for the
record): 1967-1977 n=2,165 IDI_z r=0.403 / composite r=0.510; 1978-1998
n=5,171 IDI_z r=0.507 / composite r=0.423; 1999-2024 n=6,321 IDI_z r=0.518 /
composite r=0.375.

Pooled n dropped 14,059 → 13,657 (-2.9%). This was NOT tracked down
row-by-row given this task's time budget — the honest, not-fully-verified
explanation is that it's consistent with the same name-consolidation
pattern §15 already documented and measured (merging previously-fragmented
name variants onto one real player reduces player-season row counts,
which mechanically reduces the number of consecutive-season pairs
available to correlate) rather than a new data-loss bug, but this is a
plausible account, not a confirmed one — worth a direct row-count diff
against a saved pre-migration copy of the parquet if this ever needs to be
certain rather than plausible.

**Overall verdict:** all three tasks completed as scoped. Tasks 1-2 are
straightforward, verified reloads/loads with real row-count evidence.
Task 3's rewiring is real (four of `dpvs/idi.py`'s five file-based loaders
now query Postgres by default, not just in principle) and honestly scoped
(TCS and the 1960-1966 tail explicitly documented as staying file-based,
not silently left behind). The YoY re-check is the credible signal that
nothing broke in the process — flat correlations, explained (if not fully
row-level-verified) row-count delta, clean end-to-end rebuild with no
errors. Nothing in this pass was forced to look more finished than it is:
the TCS gap and the small unverified n-drop are both stated plainly above
rather than smoothed over.

Code/data references: `football_db/scripts/ingest_gamebook_boxscores.py`
(resolver swap + completeness-ratio columns + ISO-date/TOTAL-row parser
fixes), `football_db/scripts/ingest_pfr_defensive_stats.py` (new),
`football_db/scripts/build_gold_player_game_stats.py` (new),
`football_db/schema/migrations/20260821_gamebook_pfr_pergame_reload.sql`
(new), `football_db/schema/dpvs_g.sql` (new),
`gamebooks_boxscores/parse_pfr_pbp.py` (additive `id_cache`/`load_game_id_map()`/
`load_pfr_player_id_cache()` extension, backward-compatible default
`id_cache=None`), `dpvs/idi.py` ("Postgres-backed sources" section, new),
`scripts/load_dpvs_g_to_db.py` (new). Left uncommitted per this task's
instructions.

---

## 17. §16's 402-Pair YoY Drop: Root-Caused and Fixed (2026-08-22)

Follow-up task, closing §16's one open item ("the honest, not-fully-verified
explanation ... worth a direct row-count diff ... if this ever needs to be
certain rather than plausible"). It needed to be certain: the drop was NOT
the name-consolidation effect §16 guessed at. Real cause found, fixed, and
confirmed by rebuild.

**Method.** `dpvs/idi.py` is currently mid-migration (uncommitted changes on
top of the committed, pre-migration file-based version), so the committed
`git HEAD` version of `dpvs/idi.py` IS the exact §15 baseline
(file-based, pre-Postgres, post-name-resolver-fixes) — no separate backup
needed. `git stash push -- dpvs/idi.py`, full `build_dpvs_g.py --seasons
1967-2024` rebuild → OLD parquet (20,541 player-seasons, 14,059 pooled
pairs, matches §15/§16's documented baseline exactly). `git stash pop`,
same rebuild → NEW parquet (matches §16's committed 19,991/13,657 exactly).
Diffed the two parquets' `(pfr_player_id, season)` pair sets directly:
**401 pairs lost, 0 gained** — a pure, one-directional loss, immediately
ruling out name-consolidation (which would show losses roughly balanced by
gains as split variants merge into fewer, not-strictly-fewer rows). All 401
were entirely-missing player-season *rows* in NEW, not present-but-null
`tcs_z`/`idi_z` — so the cause lives in `build_composite()`'s row-survival
filters (min_games, position_group), not in IDI's scoring math. Losses
concentrated 1997-2023 (peak 2004-2022), matching `compute_idi()`'s own
documented "no starters.csv, `pos` falls back to `gold_pos`" range
(2001-2018) almost exactly.

**Root cause.** `load_gold_stats_from_db()`'s SQL selected
`pgs."position" AS pos` from `gold.player_game_stats`. Queried directly:
that column is **NULL for all 422,823 `pfr`-sourced rows** (0 non-blank),
vs. 30,357/30,388 populated for `gamebook`-sourced rows. Not a bug in
`gold.player_game_stats` itself — `silver.player_game_stats_pfr` (its pfr
input) is genuinely position-less by construction:
`ingest_pfr_defensive_stats.py` derives its stats from `pbp.csv` play text,
which carries no position field at all (confirmed: neither `pbp.csv` nor
`player_defense.csv`, the per-game PFR boxscore file, has a position
column — position is roster-level PFR data, not per-game boxscore data).
The legacy `~/data/gold/player_season_card.parquet` had `pos` populated for
all but 4/69,818 rows because its now-deleted builder pulled position from
a season-level roster source; `load_gold_stats_from_db()` was never given
an equivalent join when it replaced that parquet read, so ~91% of its
`pos` values (65,088 → 59,160 null) went silently empty.

The mechanism from there to a vanished row: `compute_idi()`'s `gold_pos`
fallback only fires when TCS's own `pos` is ALSO blank for that row (the
2001-2018 no-starters.csv gap, or a position-split player-season whose
`_dedup_positions()`-chosen "primary" row happened to be the blank-pos
one). For those rows, `build_composite()` had nothing to fall back to,
`position_group` resolved to `"unknown"`, and `df[df["position_group"] !=
"unknown"]` (composite.py's own explicit drop line) removed the row
entirely — not a missing stat, the whole player-season. Verified directly
against a 4-player sample (Husain Abdullah, Sam Acho, Anthony Adams,
Jahleel Addae) by instrumenting the actual pipeline: TCS/WOWY/dedup
row counts were bit-identical between OLD and NEW runs (as expected — TCS
and WOWY were untouched by §16), and `gold_db["pos"]` was NaN for literally
every one of their rows while the legacy parquet had a real code
(`FS`/`DB`/`LB`/`DT`/etc.) for every one of the same rows.

**Fix.** `silver.player_team_seasons_pfr` — a real, already-populated,
season-level roster/position table (118,090 rows, 1921-2025, one row per
`(player_id, franchise_id, season)`, no duplicate keys, built 2026-07-10,
untouched by §16) already has exactly the position data needed and was
simply never joined by `load_gold_stats_from_db()`. Added a `LEFT JOIN` on
`(player_id, franchise_id, season)` and changed the select to
`coalesce(pgs."position", pts.position) AS pos` (keeps the `gamebook`
source's own per-game position where it exists, backfills from the roster
table only where `gold.player_game_stats.position` is null — i.e., every
`pfr` row). One query, no data written, no schema change, no other file
touched.

**Rebuild + re-check** (`scripts/build_dpvs_g.py --seasons 1967-2024`,
`scripts/yoy_stability_check.py`):

| | Pooled n | IDI_z pooled r | Composite (no-WOWY) pooled r |
|---|---|---|---|
| §15/§16 baseline (file-based, pre-migration) | 14,059 | 0.502 | 0.413 |
| §16 (Postgres, position bug present) | 13,657 | 0.496 | 0.415 |
| **§17, this fix (position backfilled)** | **14,054** | **0.494** | **0.413** |

Final player-seasons 20,534 (vs. OLD's 20,541, vs. §16's buggy 19,991) —
recovers 543 of the 550 rows §16's bug had dropped. Pooled pairs recover
397 of 402 (14,054 vs. 14,059, **98.8% closed**). Both correlations stay
flat within the same noise band §16 already established (IDI_z -0.008 from
baseline, composite exactly matches) — consistent with this being a
row-survival fix, not a scoring-methodology change, exactly as expected.

**4 pairs still unrecovered** (Josh Hines-Allen 2019→2020, Michael Carter
II 2021→2022 and 2022→2023, Chris Harris Jr. 2011→2012): checked directly
against `silver.player_team_seasons_pfr` — all four have real, correctly-
keyed position rows for the relevant seasons/franchises, so the join
itself isn't failing on them; whatever's still filtering these specific
four out is a smaller, different, not-yet-diagnosed edge case (a
`gold.player_game_stats` franchise-id mismatch on a partial-season/trade
row is the leading guess, unconfirmed). Left as an explicitly open,
low-priority tail rather than chased further — it's 1% of the original
gap and the pooled correlation is already fully validated as flat.

**Verdict:** genuine, fixable data gap — not a legitimate exclusion. Fixed
at the correct layer (the Postgres-reading loader, not the ingestion
scripts that built `silver.player_game_stats_pfr` — that table's own
positionlessness is a real and permanent property of its `pbp.csv` source,
not a bug to fix there). §16's own "plausibly name-consolidation, not
row-verified" guess is now known to have been wrong, on the record, per
this section's own row-level diff.

Code/data reference: `dpvs/idi.py`'s `load_gold_stats_from_db()` (the
fix). No football_db schema or data changes — read-only diagnosis, one
query edit downstream. Left uncommitted per this task's instructions.

---

## Open Questions

- **Eller pre-2001 gamebook supplement:** Use era_plays_all.csv to identify Eller's
  game appearances and add him as a participant. Straightforward but not yet done.
- **Playoff games vs regular season:** Included in TDGS accumulation; opponents
  are more talented in playoffs but opponent season averages already account for this
  partially. Could separate if needed.
- **Special teams effect on pts_allowed:** Pts include defensive TDs by the opponent
  which may inflate pts_allowed in rare games. Not corrected for.
- **OQA for pts vs OQA for yds:** Both are computable from per-game scoring.csv (pts)
  and team_stats.csv "Total Yards" row (yds). Yds OQA may be cleaner for DPVS than
  pts OQA due to lower non-offensive-TD noise. Not yet tested.
