# QB Composite Metric Research

Research log for building a historically grounded, context-adjusted QB ranking system. Documents every metric attempted, why it was built, what broke, what the data showed, and where the thinking landed.

---

## The Problem

Traditional QB evaluation conflates individual skill with team outcomes. Win totals and rings are the most cited measures even though team defense — not QB play — is the strongest single predictor of winning (r = −0.70 defense PPG vs win%, vs r = +0.53 QB rating vs win%, across 1,800+ team-seasons 1960–2025). The goal is a metric that isolates QB skill from defensive context, era, and opponent quality — and holds up to scrutiny across 65 years of data.

**Test case:** Reggie White aside, the main QB comparison anchoring this work is Manning vs. Brady vs. the field. The central hypothesis: Brady's GOAT reputation is partly a defense artifact.

---

## Metrics Attempted

### 1. WAE/s — Wins Above Expected per Season

**What it is:** `WAE = actual_wins − expected_wins(defense)`. Expected wins are computed via isotonic regression on `def_pts_norm` (defensive PPG rank normalized 0=best, 1=worst, accounting for league size). Career WAE/s = average WAE per season as primary starter (most pass attempts on the team).

**Why isotonic regression, not rolling mean:** Rolling mean had 573 monotonicity violations — it could predict that a worse defense expected more wins in some range. Isotonic regression (sklearn, `increasing=False`) enforces the guarantee that a better defense always predicts at least as many expected wins. This matters most at the extremes (historically elite or historically bad defenses), which is exactly where Brady vs. Montana vs. Griese debates live.

**What it measures:** QB + offensive coordinator scheme + OL quality + special teams + schedule luck + close-game variance. It does **not** isolate the QB. The defense context is removed, but everything on the offensive side of the ball rolls in together.

**YoY stability: r = 0.226.** Second-noisiest metric. Only 5% of WAE carries forward year to year. Typical swing: ±2.6 wins in a single season.

> *"WAE sounds like it should be the cleanest measure but it's actually the messiest per-season signal because it's a 16-game coin flip with the team, not the QB, as the unit of analysis."*

**Why it still belongs:** The noise is at the season level. Sustained WAE over 10+ seasons is a strong signal — the law of large numbers eventually cuts through. Manning at +2.92 over 17 seasons, Mahomes at +3.19 over 7, Brady at +1.94 over 21 are not explained by luck at those sample sizes.

**Proof via sustained positive rate:**
| QB | Positive WAE Seasons | Total Seasons | Rate | Expected (random) |
|---|---|---|---|---|
| Peyton Manning | 15 | 17 | 88% | 50% |
| Patrick Mahomes | 6 | 7 | 86% | 50% |
| Tom Brady | 18 | 21 | 86% | 50% |
| Aaron Rodgers | 10 | 15 | 67% | 50% |

15/17 positive at a 50% base rate has p < 0.0013. The career signal is real.

**Manning season-by-season:**
```
1998:  3W  ExpW 3.9  WAE −0.9   Def 96%ile   (rookie, #1 pick)
1999: 13W  ExpW 7.9  WAE +5.1   Def 53%ile
2000: 10W  ExpW 8.4  WAE +1.6   Def 46%ile
2001:  6W  ExpW 3.6  WAE +2.4   Def 100%ile  (worst defense in league)
2002: 10W  ExpW10.0  WAE −0.0   Def 19%ile
2003: 12W  ExpW 7.3  WAE +4.7   Def 61%ile
2004: 12W  ExpW 7.7  WAE +4.3   Def 58%ile
2006: 12W  ExpW 6.7  WAE +5.3   Def 70%ile
2009: 14W  ExpW 9.9  WAE +4.1   Def 22%ile
2013: 13W  ExpW 6.9  WAE +6.1   Def 67%ile   (best single-season WAE)
```

**Mahomes season-by-season:**
```
2018: 12W  ExpW 6.2  WAE +5.8   Def 74%ile
2020: 14W  ExpW 9.2  WAE +4.8   Def 29%ile
2022: 14W  ExpW 8.7  WAE +5.3   Def 48%ile
2023: 11W  ExpW12.2  WAE −1.2   Def 3%ile   (only negative: elite defense, 11 wins)
2024: 15W  ExpW10.9  WAE +4.1   Def 9%ile
```

**Full named-QB ranking (career WAE/s, qualifying ≥6 seasons):**
| QB | Seasons | WAE/s | Total WAE | Avg Def %ile |
|---|---|---|---|---|
| Patrick Mahomes | 7 | +3.19 | +22.3 | 29% |
| Peyton Manning | 17 | +2.92 | +49.6 | 45% |
| Drew Brees | 19 | +2.37 | +45.0 | 56% |
| Tom Brady | 21 | +1.94 | +40.7 | 20% |
| Aaron Rodgers | 15 | +1.69 | +25.3 | 45% |
| Dan Marino | 16 | +1.49 | +23.8 | 48% |
| Trent Dilfer | 7 | −1.97 | −13.8 | 26% |

> *"Manning at 45th-percentile defense is the strongest 'pure QB' case — he's adding 3 wins per season with a below-average defense. Brady at 20th-percentile means his baseline is already ~10 expected wins; he adds ~2 more. The isotonic model correctly makes Brady's peak look harder to beat."*

---

### 2. ANYAZ — Adjusted Net Yards per Attempt (z-score, within season)

**Formula:** `ANY/A = (yards + 20×TD − 45×INT − sack_yards) / (attempts + sacks)`

Penalizes sacks and INTs more harshly than standard passer rating. Era-adjusted via within-season z-score against all QBs that year.

**ANY/A decomposition** — how much is each component?

| Predictor | r² alone | r² with others | Marginal add |
|---|---|---|---|
| Yds/Att | ~68% | — | — |
| TD% | ~15% | +10% beyond Yds/Att | |
| INT% | ~8% | +5% beyond above | |
| **Total (3-way)** | **~93%** | | |
| Comp% added | | +1% | Almost nothing |

> *"It's interesting that ANY/A didn't do so well in the career spread and YoY stability tests. It's baked out of 3 underlying stats — if any one of those is noisy, it inherits that noise."*

**YoY stability: r = 0.353.** Middle of the pack.

---

### 3. OQA-Z v3 — Opponent Quality Adjustment (z-score)

**What it measures:** Per-game z-score vs. the opposing defense's leave-one-out (LOO) rates. For each game: `z = (QB_metric − defense_LOO_metric) / season_SD_of_that_defense_metric`. Career average of season averages (min 5 games/season).

**Four components:** yds/game (volume), comp%, TD%, INT% (inverted — fewer picks vs. opponent's allowed rate = good).

**Why LOO:** Removes circularity — the opponent's season average is computed excluding this specific game, so the QB isn't measured against his own contribution to the defense's stats.

**Why we rebuilt v1→v3:**
- v1: used per-game volume totals (pass_yds, TD count, INT count). Brady's 2007 season with Randy Moss and Mahomes' Chiefs offense dominated because high-volume schemes produce more raw stats.
- v2: switched to per-attempt rates. Better, but Comp% was still missing from the build.
- v3: four rate metrics (yds/game, comp%, TD%, INT%). INT% component has r = 0.146 YoY stability — essentially noise.

> *"I've watched a lot of INTs and I'd say at least 40–66% of them are not the QB's fault. WR didn't finish the route, end-of-half heaves, balls bounce off WR hands. The play caller forcing a hail mary that isn't really there but the team needs 7 pts. So while it's a penalty to the team win, it's not a penalty the QB should have to bear."*

**INT% noise analysis:** YoY r = 0.146 → skill% ≈ 15%, noise ≈ 85%. This is consistent with ~62% of INT variance being non-QB-controlled — squarely in the user's 40–66% range. A reliability-weighted OQA-Z would give comp% ~50% weight, yds/game ~29%, TD% ~16%, INT% only ~4%.

---

### 4. QBRtgZ — Passer Rating (z-score, within season)

Standard passer rating (1973 formula), era-adjusted via within-season z-score. The formula has known issues: doesn't penalize sacks, capped at 158.3, doesn't include rushing. Used as a sanity check alongside ANYAZ more than as a primary metric.

**YoY stability: r = 0.371.** Slightly better than ANY/A.

---

## Metric Quality Summary

Three tests applied to each stat:

| Metric | YoY Stability (r) | Skill% | Notes |
|---|---|---|---|
| **Comp%** | **0.508** | 51% | Most stable individual passing stat |
| Yds/Season | 0.389 | 39% | Volume, era-adjusted z needed |
| QB Rating-z | 0.371 | 37% | Legacy formula issues |
| Yds/Att | 0.370 | 37% | Cleaner than rating |
| ANY/A | 0.353 | 35% | Composite of noisy inputs |
| TD% | 0.289 | 29% | Volatile; scheme-dependent |
| **WAE/s** | **0.226** | 23% | Team outcome; season-level noise high |
| **INT%** | **0.146** | 15% | ~62% non-QB variance; weakest signal |

> *"Comp% is interesting in that while you could say someone is hunting short accurate passes, that still likely wins a lot of games vs. longer passes with less accuracy."*

**Comp% and ANY/A:** Comp% adds only ~1% additional information to ANY/A once Yds/Att + TD% + INT% are already in the model. This means Comp% and ANY/A are not independent signals — they share almost everything. But Comp% alone is more YoY-stable than ANY/A (0.508 vs 0.353), making it a better building block for a composite than ANY/A is.

---

## EliteDefZ — Performance vs. Top-25% Defenses

**Motivation:** All the metrics above measure average performance. The question of whether a QB is truly elite is better answered by what they do against the best defenses. Manning vs. Marino: both have strong career numbers, but how do they hold up when the defense is legitimately good?

**Construction:**
1. Filter to games where the opposing defense had `def_pts_norm ≤ 0.25` (top 25% best defenses in that season, normalized for league size).
2. For each game, compute z-score of Comp% and Yds/Game **against all other QB games vs. top-25% defenses in that same season** — not against all games.
3. Career average of those z-scores (min 15 games vs elite defense).

**Why z-score within the elite-defense context (not vs all games):**

First version z-scored against the full season distribution. Lamar Jackson's Comp% is structurally lower from scheme (run-heavy, short-to-intermediate passing). He was already below average across all games; filtering to elite defenses pushed him further negative. He was getting penalized twice for the same structural fact.

> *"Lamar Jackson gets murdered — he's already low but then using league avg of top-25% defenses to normalize it in a given year... will be stupid low."*

Fix: baseline is the distribution of all QB games vs top-25% defenses that season. This asks "compared to every other QB who also faced an elite defense this year, how did you do?" Lamar's 64.9% Comp% vs elite defenses is actually above the era mean for those games (~61-63%), so his Comp%-z flips to +0.178. His Yds/G is below average (−0.218) but that reflects scheme, not failure.

**Results (career composite = avg of Comp%-z and Yds/G-z, min 15 games):**

| QB | G vs Elite D | Comp%-z | Yds/G-z | Composite | Raw Comp% | Raw Yds/G |
|---|---|---|---|---|---|---|
| Kurt Warner | 19 | +0.587 | +0.812 | **+0.699** | 64.6% | 259.6 |
| Peyton Manning | 89 | +0.574 | +0.776 | **+0.675** | 65.2% | 264.5 |
| Drew Brees | 61 | +0.689 | +0.628 | **+0.659** | 67.1% | 265.3 |
| Dan Fouts | 41 | +0.452 | +0.843 | +0.648 | 56.8% | 235.0 |
| Joe Montana | 47 | +0.745 | +0.488 | +0.617 | 62.1% | 222.1 |
| Patrick Mahomes | 30 | +0.244 | +0.985 | +0.615 | 65.3% | 299.6 |
| Dan Marino | 72 | +0.300 | +0.754 | +0.527 | 57.4% | 244.3 |
| Johnny Unitas | 28 | +0.355 | +0.674 | +0.514 | 53.3% | 186.7 |
| Steve Young | 40 | +0.520 | +0.391 | +0.455 | 61.0% | 214.7 |
| Tom Brady | 105 | +0.236 | +0.664 | +0.450 | 62.1% | 265.2 |
| Brett Favre | 84 | +0.291 | +0.505 | +0.398 | 60.2% | 231.2 |
| Philip Rivers | 57 | +0.217 | +0.491 | +0.354 | 62.5% | 254.4 |
| Roger Staubach | 38 | +0.367 | +0.338 | +0.352 | 55.1% | 159.6 |
| Fran Tarkenton | 69 | +0.165 | +0.456 | +0.311 | 51.6% | 171.4 |
| Aaron Rodgers | 65 | +0.169 | +0.365 | +0.267 | 63.0% | 249.6 |
| Jared Goff | 35 | +0.208 | +0.339 | +0.273 | 65.2% | 242.6 |
| Terry Bradshaw | 32 | +0.182 | +0.294 | +0.238 | 53.2% | 169.5 |
| Bart Starr | 41 | +0.360 | +0.186 | +0.273 | 53.2% | 147.0 |
| John Elway | 57 | −0.053 | +0.382 | +0.165 | 53.0% | 212.8 |
| Lamar Jackson | 46 | +0.178 | −0.218 | −0.020 | 64.9% | 193.9 |
| Trent Dilfer | 34 | −0.403 | −0.298 | **−0.350** | 50.2% | 153.9 |

**YoY stability: r = 0.398.** Better than WAE/s, TD%, any part of ANY/A. Comparable to Yds/Season.

**Profiles within the top tier:**

- **Manning**: balanced. Holds both Comp%-z (+0.574) and Yds/G-z (+0.776). Nothing breaks under pressure.
- **Mahomes**: skewed toward volume. Comp%-z is modest (+0.244) but Yds/G-z is the highest in the table (+0.985). His Yds/G against elite defenses is actually *above* his career average — the only QB in the set where this is true. He takes shots against elite defenses and they connect.
- **Montana**: mirror image of Mahomes. Best Comp%-z (+0.745), modest Yds/G. High efficiency in a scheme that limited his volume by design.
- **Brees**: most balanced. Highest raw Comp%-z (+0.689), virtually no drop from career average.
- **Rodgers**: 15th overall at +0.267. Above average but not elite against elite defenses. Manning's composite is 2.5× Rodgers'. This partially answers why Rodgers' OQA-Z wasn't top-5 even though his raw career numbers are arguably best-ever.
- **Fouts**: surprisingly strong (+0.648) — era-adjusted his 1979–1983 seasons against top AFC West/NFC defenses were genuinely dominant. Worth noting he played in arguably the most pass-unfriendly era for volume.

---

## The 4 Stats That Stood Up

After all the testing, these four have distinct, non-overlapping signal and YoY stability that justifies inclusion:

| Metric | What It Captures | YoY r | Note |
|---|---|---|---|
| **Comp%-z** (career, within-season) | Accuracy vs era | 0.508 | Most stable; hunting short passes is still winning |
| **Yds/G-z** (career, within-season) | Volume/aggression vs era | 0.389 | Era-normalizes for pass/run balance shifts |
| **EliteDefZ** (vs top-25% D) | Does the game elevate vs best? | 0.398 | Catches the Rodgers/Manning split |
| **WAE/s** | Actual team wins beyond defense | 0.226 | Noisiest per-season; meaningful over long careers |

These four are not a composite yet — they're four lenses. The weights question is open.

> *"Not sure on a composite yet. Each for their own."*

---

## Metrics Considered But Not Primary

**WOWY (With or Without You) for QB WAE:** Would measure defense delta when QB joins or leaves. Clean conceptually; hard to isolate from coaching/roster changes in the same offseason.

**Snap-weighted OQA-Z:** Weight z-scores by snap count to reward durability. Data gap: snap counts are only reliable 2015+, patchy 2012-2014, unavailable pre-2012.

**QB Rating z-score (QBRtgZ):** Still in the 4-metric table from earlier work. The formula has known flaws but as an era-adjusted measure it correlates well with the other metrics and provides a check.

**ANY/A-z:** Slightly less stable than Comp%-z alone, and mostly redundant with it once you have Yds/G separately.

---

## Metric Ideas Still to Evaluate

### 4th Quarter / Within-1-Score Clutch Stats

**Concept:** Comp% and Yds/Game when within 1 score (≤8 pts) in the 4th quarter. The process metric version of 4QC records.

**Data availability:** PBP with score columns goes back to 1978 in local data (`pbp.csv` has `quarter`, `pbp_score_aw`, `pbp_score_hm`). Pre-1978 QBs (Unitas, Staubach, Starr, Griese, early Fouts) would have no coverage. Gamebook data (MIN 1967–1981, PIT 1969–1973) is too narrow to generalize.

**The build:** Passing stats are in the `detail` text column as prose. Extracting Comp%/Yds from Q4 within-1-score plays needs regex attribution by player. Not impossible, real work.

**Sample size:** Maybe 4–8 qualifying games per QB per season where the team is within 1 score in Q4. Career minimum of ~30 games would require 4–7 qualifying seasons, which covers all modern QBs and most of the historical ones with 1978+ data.

> *"4QC and come-from-behind wins are probably pretty noisy [as outcomes]. But Comp% and yards/game in those situations is the process version."*

**Assessment:** Worth building. Would be the most direct measure of "do you elevate when it matters." YoY stability unknown — could be 0.3–0.45 if the sample is large enough. The Comp%/Yds version removes the binary win/loss luck that makes 4QC records unreliable.

---

## Open Weighting Questions

When a composite is built, what should the weights be? Some candidate frameworks:

**Stability-proportional weighting** (more stable = more weight):
- Comp%-z: 35% (r = 0.508)
- Yds/G-z: 28% (r = 0.389)
- EliteDefZ: 28% (r = 0.398)
- WAE/s: 16% (r = 0.226)
- *Note: WAE/s is the only metric that directly measures wins — dropping it entirely loses the team-outcome signal.*

**Equal weighting:** Simpler; avoids over-fitting to stability estimates from a limited sample.

**Diminishing-returns weighting on Comp%:** Comp% and Yds/G are correlated. If a QB has a very high Comp% from dinking and dunking, Yds/G catches the volume side. The two together probably don't need to be weighted as heavily as their individual stability numbers suggest.

---

## Data Notes

- Passing files pre-2003 use column names `cmp/yds/team`; post-2003 use `comp/yards/team_abbrev`. Load code renames both.
- Steve Young's player ID is `YounSt00` (not `YoungSt00`).
- Team franchise relocations require year-aware mapping. `STL` was Cardinals (≤1987) then Rams (≥1995). `BAL` was Colts (≤1983) then Ravens (≥1996). `HOU` was Oilers (≤1996) then Texans (≥2002).
- OQA-Z v3 built from 15,438 player_offense.csv files (1950–2025); 10,013 games matched to top-25% opponent defense.
- PBP data: present in all local boxscores from 1978+. Quarter and score columns available. Passing stats embedded in `detail` text.
