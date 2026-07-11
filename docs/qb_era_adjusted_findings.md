# QB Era-Adjusted Findings

Narrative summary of confirmed findings from `notebooks/qb_value_analysis.ipynb`.
All analysis covers 1,800+ NFL team-seasons, 1960–2025.

---

## The Central Question

Does having a great QB matter more than having a great defense? And how has that changed?

**Short answer:** Historically, defense has been more predictive of wins. But in the 2020s, that relationship has inverted for the first time in the dataset.

---

## 1. How Predictive Is Each? (1960–2025)

| Metric | Pearson r | r² (variance explained) |
|---|---|---|
| Defense PPG rank vs Win% | −0.70 | 49% |
| Composite QB rating vs Win% | +0.53 | 28% |

Defense explains nearly twice as much variance in wins as QB rating does across the full dataset.

---

## 2. Tier-by-Tier: Defense vs. QB Rating

QB tiers use **within-season percentile rank** (era-adjusted). A "top 10% QB" means top 10% of QBs in that specific year — controlling for the fact that a 95 rating in 1970 and 2015 mean very different things.

| Tier | Defense — P(10+W) | Defense — P(SB Win) | QB Rating — P(10+W) | QB Rating — P(SB Win) |
|---|---|---|---|---|
| Top 10% | **83%** | 14.2% | 75% | 10.7% |
| 11–25% | 62% | 6.1% | 61% | 7.5% |
| 26–50% | 36% | 1.8% | 34% | 2.0% |
| 51–75% | 16% | 0.7% | 19% | 1.1% |
| Bottom 25% | **3%** | 0.2% | 6% | 0.5% |

**The counterintuitive finding at the bottom:** A bottom-25% defense gives you only a 3% chance of 10 wins. A bottom-25% QB gives you 6%. A terrible defense is more crippling than a terrible QB — you can win with a game-manager if the defense holds; you almost never win if the defense is historically bad regardless of who's throwing.

**At the very top:** Elite defense has an 8-percentage-point edge (83% vs 75%) in producing 10-win seasons. But for Super Bowl wins in the 11–25% tier, QB teams slightly edge defense teams (7.5% vs 6.1%), suggesting playoff performance may be more QB-dependent.

---

## 3. Has Defense Always Dominated? Decade-by-Decade Breakdown

| Decade | n | \|r\| Defense | \|r\| QB Rtg | r² Defense | r² QB Rtg | Defense advantage |
|---|---|---|---|---|---|---|
| 1960s | 146 | 0.742 | 0.607 | 0.550 | 0.368 | **1.22×** |
| 1970s | 268 | 0.761 | 0.654 | 0.579 | 0.427 | 1.16× |
| 1980s | 280 | 0.635 | 0.533 | 0.403 | 0.284 | 1.19× |
| 1990s | 291 | 0.743 | 0.632 | 0.551 | 0.399 | 1.17× |
| 2000s | 318 | 0.687 | 0.646 | 0.472 | 0.417 | 1.06× |
| 2010s | 320 | 0.699 | 0.651 | 0.489 | 0.424 | 1.07× |
| **2020s** | 160 | **0.624** | **0.694** | 0.390 | 0.481 | **0.90×** |

The decline from 1.22× in the 1960s to 0.90× in the 2020s is systematic, not noise. In the current decade, **QB rating is more predictive of wins than defense PPG rank** — the first decade in the dataset where this is true.

Structural causes: 2004 receiver-protection rules, 2023 helmet-contact rules, and the general pass-heavy evolution of the league have shifted value from defensive performance toward quarterback play. The Mahomes/Allen/Jackson era is not just different in perception — it's different in the data.

---

## 4. Wins Above Expected (WAE) — Full Rankings

**Methodology:** For each team-season, the model asks: *given how good your defense was, how many wins should you have expected?* The expected win% is computed using **isotonic regression** on the full 1960–2025 dataset — a monotone model that guarantees a better defense always predicts more expected wins (unlike a rolling mean, which can have local inversions).

`WAE = actual wins − expected wins`

Positive WAE = QB's team outperformed the defense's prediction; negative = underperformed.
Qualifies: 4+ seasons as primary starter (most passing attempts on the team).

### Top 20 — Outperforms expectations most (WAE per season)

| QB | Seasons | Avg W | Exp W | WAE/season | Total WAE | Avg Rating | Avg Def %ile |
|---|---|---|---|---|---|---|---|
| Patrick Mahomes | 7 | 12.9 | 9.7 | **+3.18** | +22.2 | 101.6 | 29% |
| Jalen Hurts | 4 | 12.0 | 9.0 | +3.04 | +12.2 | 95.2 | 44% |
| Peyton Manning | 17 | 11.2 | 8.3 | +2.92 | **+49.7** | 95.7 | 45% |
| Drew Brees | 19 | 9.6 | 7.3 | +2.37 | +45.0 | 97.9 | 56% |
| Jared Goff | 8 | 10.2 | 8.0 | +2.26 | +18.1 | 96.4 | 53% |
| Andrew Luck | 6 | 9.8 | 7.6 | +2.23 | +13.4 | 88.3 | 54% |
| Roger Staubach | 8 | 10.6 | 8.6 | +2.00 | +16.0 | 84.0 | 26% |
| Tom Brady | 21 | 12.0 | 10.1 | +1.94 | +40.7 | 96.7 | 20% |
| Tony Romo | 8 | 9.8 | 7.9 | +1.88 | +15.0 | 95.5 | 52% |
| Aaron Rodgers | 15 | 10.1 | 8.4 | +1.69 | +25.3 | 101.6 | 45% |

### All named QBs — WAE with defensive context

| QB | Seasons | WAE/season | Total WAE | Avg Def %ile | Context |
|---|---|---|---|---|---|
| Patrick Mahomes | 7 | +3.18 | +22.2 | 29% | Good defense, historically exceptional QB |
| Peyton Manning | 17 | +2.92 | +49.7 | 45% | Below-avg defense → strongest "pure QB" case |
| Drew Brees | 19 | +2.37 | +45.0 | 56% | Mostly below-avg defense; most underrated in total WAE |
| Roger Staubach | 8 | +2.00 | +16.0 | 26% | Good defense; small career sample limits recognition |
| Tom Brady | 21 | +1.94 | +40.7 | 20% | Elite defense (top 20%) inflates baseline expectations |
| Aaron Rodgers | 15 | +1.69 | +25.3 | 45% | Consistently below-avg defense; clean WAE signal |
| Dan Marino | 16 | +1.49 | +23.8 | 48% | Below-avg defense; no rings, strong pure-QB case |
| Steve Young | 9 | +1.46 | +13.2 | 28% | Underrated by short career + Montana's shadow |
| Johnny Unitas | 11 | +0.82 | +9.0 | 27% | Good defense; solid WAE despite short qualifying window |
| Joe Montana | 12 | +0.80 | +9.6 | 19% | Elite defense; WAE is positive but limited after baseline adjustment |
| Bob Griese | 9 | +0.79 | +7.1 | 17% | Most elite-defense QB in the table after Montana |
| Fran Tarkenton | 18 | +0.69 | +12.4 | 55% | Below-avg defense; consistent middling WAE over long career |
| Terry Bradshaw | 12 | +0.44 | +5.3 | 28% | Good Steel Curtain defense; adds modest WAE above it |
| Bart Starr | 10 | +0.16 | +1.6 | 14% | Best defense in the table; barely adds to it |
| Jim McMahon | 9 | −0.89 | −8.0 | 18% | Elite defense; actually underperformed expectations |
| Trent Dilfer | 7 | −1.97 | −13.8 | 26% | Worst WAE despite top-quartile defense — canonical clipboard QB |

**Key reads:**
- **Manning vs Brady:** Manning adds +2.92 wins per season with a 45th-percentile defense. Brady adds +1.94 with a 20th-percentile defense. The isotonic model raises Brady's baseline (a 20th-percentile defense is expected to win ~10+ games), making his over-performance look more modest. Manning on Brady's defense would be projected at ~12.5 wins/season.
- **Montana and Griese:** Both had historically elite defenses (19th and 17th percentile). The model correctly expects those defenses to produce ~10 expected wins on their own. Both QBs add modestly above that. The WAE confirms their rings were earned — but also shared with historically dominant defenses.
- **McMahon at −0.89:** The 1985 Bears defense was so dominant that McMahon's mediocre QB play *underperformed* what the model expected. The defense didn't just carry him — it outran him.
- **Staubach at +2.00 in only 8 seasons:** Most similar career profile to Brady, but with +0.06 more WAE per season. One of the most underrated QBs in the data.

---

## 5. Era-Adjusted Z-Scores — Dominance Relative to Contemporaries

Within-season z-score: how many standard deviations above the league mean that year. Accounts for era-inflation in all passing statistics.

**INT-z: positive = good** (fewer INTs per attempt than the league average that year).

| QB | Seasons | QB-z | Yds-z | TD-z | INT-z | Best Yr | Best QB-z | Best Raw Rtg |
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
| Fran Tarkenton | 18 | 0.74 | 0.59 | 0.36 | 0.72 | 1975 | 1.68 | 90.8 |
| Bart Starr | 10 | 0.69 | −0.60 | −0.04 | 0.52 | 1966 | 2.09 | 102.1 |
| Johnny Unitas | 11 | 0.47 | 0.98 | 0.15 | 0.30 | 1964 | 1.44 | 91.8 |
| John Elway | 16 | 0.26 | 0.41 | 0.10 | 0.39 | 1993 | 1.71 | 94.2 |
| Terry Bradshaw | 12 | 0.10 | 0.02 | 0.69 | −0.33 | 1978 | 1.43 | 81.5 |
| Jim McMahon | 9 | −0.21 | −0.56 | −0.33 | −0.06 | 1985 | 0.39 | 77.3 |
| Trent Dilfer | 7 | −0.80 | −1.41 | −0.60 | −0.50 | 1997 | 0.29 | 80.4 |

**Notable reads:**
- **Steve Young (#1 career QB-z):** 1994 season (z=3.43) is the most dominant QB season relative to contemporaries in the entire 1960–2025 dataset. He is severely underrepresented in GOAT debates — partly because he played in Montana's shadow, partly because his career was shortened by concussions. The data says he was the most era-dominant QB ever recorded.
- **Montana's INT-z (1.32) is the best in the table** — he protected the ball more relative to his era than even Rodgers (1.21) or Brady (1.15). This directly explains his flawless Super Bowl record.
- **Mahomes at 0.81 QB-z despite being the best current player:** modern era has more elite QBs. Even an extraordinary player compresses toward a smaller z-score because the competition is denser. This is a structural argument against using raw z-scores for cross-era GOAT claims — use it for "was he dominant in his era" rather than "who was the absolute best ever."
- **Bradshaw's negative INT-z (−0.33):** He threw more picks relative to his era than the average starting QB. The Steel Curtain genuinely carried the offense.
- **Griese's negative yards-z (−0.45) with positive QB-z (1.01):** High efficiency in a run-first Miami offense. His low volume was scheme, not limitation — when he passed, he passed well.
- **Starr's negative yards-z (−0.60) and near-zero TD-z:** Lombardi's system kept him from throwing. His QB-z (0.69) reflects being above average in a limited role, not a dominant passer.

---

## 6. Z-Score WAE Model — Alternative Baseline

The isotonic regression WAE (Section 4) is the more precise model. A simpler linear z-score baseline produces a complementary table that is easier to explain and reproduce.

**Method:** Fit OLS: `win_pct = α + β × def_pts_z`. Use predicted win% as expected wins. WAE = (actual win% − predicted win%) × season_games. Defense baseline model R² = 0.496.

**Model:** `win_pct = 0.496 + 0.141 × def_pts_z`  (1,762 team-seasons, 1960–2024)

**Combined model with QB-z:** R² = 0.706, coefficients: `+0.113 × def_pts_z + 0.093 × qb_z`

### WAE Table (z-score baseline, per season avg / career total)

| QB | Seasons | Avg def-z | Avg QB-z | WAE/yr | Total WAE |
|---|---|---|---|---|---|
| Mahomes | 8 | +0.43 | +1.05 | **+3.31** | +26.5 |
| P. Manning | 18 | +0.03 | +1.06 | +2.72 | **+49.0** |
| Drew Brees | 20 | −0.27 | +1.01 | +2.08 | +41.6 |
| R. Staubach | 11 | +0.79 | +1.17 | +1.83 | +20.1 |
| Steve Young | 13 | +0.84 | +1.82 | +1.77 | +23.0 |
| Dan Marino | 17 | −0.03 | +0.85 | +1.75 | +29.8 |
| Tom Brady | 23 | +0.90 | +0.93 | +1.69 | +38.9 |
| A. Rodgers | 20 | +0.10 | +0.72 | +1.24 | +24.8 |
| Joe Montana | 16 | +0.64 | +1.45 | +1.06 | +17.0 |
| T. Bradshaw | 14 | +0.87 | −0.07 | +0.54 | +7.6 |
| L. Jackson | 7 | +1.21 | +0.52 | +0.12 | +0.8 |
| Bart Starr | 12 | +1.05 | +0.56 | −0.08 | −1.0 |

**How this table differs from the isotonic WAE (Section 4):**
- Simpler baseline (OLS linear vs isotonic regression) → slightly different per-season numbers
- Does not include the full QB roster (only named QBs with ≥4 qualifying seasons defined explicitly)
- Uses composite team QB rating (all QBs combined) rather than identifying a single primary starter
- Both tables agree on the directional story: Manning leads per-season among the historical greats; Brady's high def support limits his WAE; Bradshaw and Starr are defense-carried

**Notable reads unique to this table:**
- **Marino at +1.75 WAE/season with essentially average defense (−0.03 def-z):** The cleanest pre-2000 "pure QB" case — no defensive floor inflating his win baseline.
- **Lamar Jackson at +0.12 WAE/yr with +1.21 def-z:** The Ravens' defense is earning most of those wins by expectation. His QB contribution is modest in this model — may improve with ANY/A vs passer rating.
- **Starr at −0.08 WAE/yr:** A valid finding. The Packers under Lombardi had a +1.05 def-z — the best average defensive support of any named QB in the table. The model expected ~11 wins/year from that defense alone; Starr just met the bar.

---

## 7. Open Improvements Planned

- **Upgrade WAE model:** Rolling mean → isotonic regression (implemented in notebook). Next step: isotonic regression within era (pre-1978, 1978–2003, 2004+) to account for structural rule-change breaks.
- **Replace composite QB rating with ANY/A:** Adjusted Net Yards per Attempt = `(yards + 20×TD - 45×INT - sack_yards) / (att + sacks)`. Penalizes sacks and INT more correctly than passer rating. Available directly from data for 2003+ (`any_per_a` column), computable from boxscores for earlier years.
- **QB rating formula is arbitrary (1973):** Does not penalize sacks, excludes rushing, caps at 158.3. ANY/A or a data-driven composite z-score is superior. See `docs/open_questions.md`.
- **Playoff WAE:** Current model is regular-season only. Brady's playoff exceptionalism is unmeasured.
- **Isolate QB from WAE:** WAE captures QB + OC scheme + special teams + OL. Controlling for OL quality (team sack rate as proxy) and receiver quality (skill position AV as rough estimate) would be more precise.
- **WR #1 identification:** Current OQA uses WR group totals. Plan: rank by season yards-per-game → identify true #1 WR per game for more meaningful individual comparison.
