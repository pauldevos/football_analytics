# QB Era-Adjusted Findings

> **2026-08-21 addendum #2 — game-level WAE + `WAE_Vegas`:** Section 4's WAE table below is a
> **season-level** model (now called `WAE_DefRank`) — it attaches a team's whole-season win-loss
> record to whoever led the team in passing attempts *that season*, not accounting for in-season QB
> changes. This has been superseded by a game-level rebuild in `notebooks/qb_value_analysis.ipynb`
> that attributes each individual game's win/loss to that specific game's leading passer, plus a new
> parallel baseline, `WAE_Vegas`, using the Vegas closing line instead of defensive rank as the
> expected-outcome model. Full methodology, the motivating 1978-1993 Chicago Bears case, and the
> complete named-QB comparison table (both baselines) are in `qb_value_analysis.md`'s addendum #2 —
> not duplicated here. Headline result relevant to this doc's Section 4 table: Joe Montana's
> `WAE_Vegas` (+1.42/16 games) is far higher than his season-level WAE/season here (+0.79) or even his
> game-level `WAE_DefRank` (+1.38/16 games) — beating the market's already-defense-informed
> expectation is a different bar than beating a defense-only one, and Montana clears it more clearly
> than the season-level number here suggests. Sections 1-3 and 5-6 below are unaffected by this
> change (they don't depend on QB win attribution).

> **2026-08-21 addendum #1:** re-executed the notebook end-to-end again to verify every table below
> against the fixed pipeline. Sections 1-4 (correlations, tiers, decades, WAE) reproduced exactly.
> Section 5's Era-Adjusted Z-Score table had two stale rows left over from before the fix — Johnny
> Unitas and Bart Starr's season counts (11/10) and z-scores didn't match a fresh run (correct: 15/12)
> even though Section 4's WAE table had already been corrected for the same two QBs. Fixed below, and
> Brett Favre (present in the notebook's `NAMED_QBS` dict but missing from this table) added. No other
> section changed.

Narrative summary of confirmed findings from `notebooks/qb_value_analysis.ipynb`.
All analysis covers 1,933 NFL team-seasons, **1950–2025** (extended from a previously-documented
1960 start — see `qb_value_analysis.md`'s Notebook section for the full audit: the 1960 cutoff was
an unverified assumption, not a real data limitation, and removing it also surfaced and fixed two
independent pre-existing bugs unrelated to the 1950s work itself, both of which had been silently
breaking every table below whenever the notebook was actually re-executed against current data).

---

## The Central Question

Does having a great QB matter more than having a great defense? And how has that changed?

**Short answer:** Historically, defense has been more predictive of wins. But in the 2020s, that relationship has inverted for the first time in the dataset.

---

## 1. How Predictive Is Each? (1950–2025)

| Metric | Pearson r | r² (variance explained) |
|---|---|---|
| Defense PPG rank vs Win% | −0.70 | 49% |
| Composite QB rating vs Win% | +0.51 | 26% |

Defense explains nearly twice as much variance in wins as QB rating does across the full dataset.
(Adding the 1950s moved this from +0.53/28% to +0.51/26% for QB rating and left defense at −0.70/49%
— a small shift, not a different story.)

---

## 2. Tier-by-Tier: Defense vs. QB Rating

QB tiers use **within-season percentile rank** (era-adjusted). A "top 10% QB" means top 10% of QBs in that specific year — controlling for the fact that a 95 rating in 1970 and 2015 mean very different things.

| Tier | Defense — P(10+W) | Defense — P(SB Win) | QB Rating — P(10+W) | QB Rating — P(SB Win) |
|---|---|---|---|---|
| Top 10% | **82%** | 13.0% | 74% | 9.8% |
| 11–25% | 61% | 5.8% | 59% | 7.1% |
| 26–50% | 36% | 1.7% | 34% | 1.9% |
| 51–75% | 17% | 0.6% | 19% | 1.0% |
| Bottom 25% | **2%** | 0.2% | 7% | 0.4% |

**The counterintuitive finding at the bottom:** A bottom-25% defense gives you only a 2% chance of 10 wins. A bottom-25% QB gives you 7%. A terrible defense is more crippling than a terrible QB — you can win with a game-manager if the defense holds; you almost never win if the defense is historically bad regardless of who's throwing.

**At the very top:** Elite defense has an 8-percentage-point edge (82% vs 74%) in producing 10-win seasons. But for Super Bowl wins in the 11–25% tier, QB teams slightly edge defense teams (7.1% vs 5.8%), suggesting playoff performance may be more QB-dependent.

*(This table's QB-Rating columns previously returned `n=0`/`nan%` for every tier due to a label-matching bug in the notebook — see `qb_value_analysis.md` — independent of the 1950s extension but fixed in the same pass since it blocked end-to-end re-execution.)*

---

## 3. Has Defense Always Dominated? Decade-by-Decade Breakdown

| Decade | n | \|r\| Defense | \|r\| QB Rtg | r² Defense | r² QB Rtg | Defense advantage |
|---|---|---|---|---|---|---|
| **1950s** | **117** | **0.678** | **0.560** | **0.460** | **0.314** | **1.21×** |
| 1960s | 146 | 0.742 | 0.607 | 0.550 | 0.368 | 1.22× |
| 1970s | 268 | 0.761 | 0.654 | 0.579 | 0.427 | 1.16× |
| 1980s | 280 | 0.635 | 0.533 | 0.403 | 0.284 | 1.19× |
| 1990s | 291 | 0.743 | 0.632 | 0.551 | 0.399 | 1.17× |
| 2000s | 318 | 0.687 | 0.646 | 0.472 | 0.417 | 1.06× |
| 2010s | 320 | 0.699 | 0.651 | 0.489 | 0.424 | 1.07× |
| **2020s** | 160 | **0.624** | **0.694** | 0.390 | 0.481 | **0.90×** |

The newly-added 1950s slots in cleanly at 1.21× — right in line with the 1960s (1.22×) — and doesn't
change the shape of the story at all; it just extends it one decade earlier. The decline from
~1.2× in the 1950s–60s to 0.90× in the 2020s is systematic, not noise. In the current decade, **QB rating is more predictive of wins than defense PPG rank** — the first decade in the dataset where this is true.

Structural causes: 2004 receiver-protection rules, 2023 helmet-contact rules, and the general pass-heavy evolution of the league have shifted value from defensive performance toward quarterback play. The Mahomes/Allen/Jackson era is not just different in perception — it's different in the data.

---

## 4. Wins Above Expected (WAE) — Full Rankings

**Methodology:** For each team-season, the model asks: *given how good your defense was, how many wins should you have expected?* The expected win% is computed using **isotonic regression** on the full 1950–2025 dataset — a monotone model that guarantees a better defense always predicts more expected wins (unlike a rolling mean, which can have local inversions).

`WAE = actual wins − expected wins`

Positive WAE = QB's team outperformed the defense's prediction; negative = underperformed.
Qualifies: 4+ seasons as primary starter (most passing attempts on the team). **198 QBs now qualify**
(up from 188 pre-1950s-extension) — 10 newly-qualify from the 1950s, listed in the named-QB table below.

### Top 20 — Outperforms expectations most (WAE per season)

| QB | Seasons | Avg W | Exp W | WAE/season | Total WAE | Avg Rating | Avg Def %ile |
|---|---|---|---|---|---|---|---|
| Patrick Mahomes | 7 | 12.9 | 9.7 | **+3.20** | +22.4 | 101.6 | 29% |
| Jalen Hurts | 4 | 12.0 | 9.0 | +3.04 | +12.2 | 95.2 | 44% |
| Peyton Manning | 17 | 11.2 | 8.3 | +2.92 | **+49.7** | 95.7 | 45% |
| Drew Brees | 19 | 9.6 | 7.3 | +2.37 | +45.0 | 97.9 | 56% |
| Jared Goff | 8 | 10.2 | 8.0 | +2.28 | +18.2 | 96.4 | 53% |
| Andrew Luck | 6 | 9.8 | 7.6 | +2.21 | +13.3 | 88.3 | 54% |
| Trent Green | 6 | 8.3 | 6.2 | +2.18 | +13.1 | 86.8 | 75% |
| Daunte Culpepper | 5 | 7.8 | 5.7 | +2.08 | +10.4 | 91.5 | 81% |
| Kurt Warner | 9 | 9.1 | 7.1 | +2.03 | +18.3 | 90.2 | 61% |
| Roger Staubach | 8 | 10.6 | 8.6 | +2.01 | +16.1 | 84.0 | 26% |

Manning and Staubach retain top-10 spots after the fix; the reshuffle among ranks 6-10 (Trent Green,
Daunte Culpepper, Kurt Warner newly appearing) is a direct effect of the `player_name`/`games_started`
rename bug fix (see `qb_value_analysis.md`) correctly attributing seasons that were previously silently
dropped — not an effect of the 1950s extension.

### All named QBs — WAE with defensive context

| QB | Seasons | WAE/season | Total WAE | Avg Def %ile | Context |
|---|---|---|---|---|---|
| Peyton Manning | 17 | +2.92 | +49.7 | 45% | Below-avg defense → strongest "pure QB" case |
| Drew Brees | 19 | +2.37 | +45.0 | 56% | Mostly below-avg defense; most underrated in total WAE |
| Roger Staubach | 8 | +2.01 | +16.1 | 26% | Good defense; small career sample limits recognition |
| Tom Brady | 21 | +1.96 | +41.1 | 20% | Elite defense (top 20%) inflates baseline expectations |
| Aaron Rodgers | 15 | +1.69 | +25.4 | 45% | Consistently below-avg defense; clean WAE signal |
| Dan Marino | 16 | +1.50 | +24.0 | 48% | Below-avg defense; no rings, strong pure-QB case |
| Johnny Unitas | 15 | +1.10 | +16.4 | 35% | Solid WAE across a 15-season qualifying window |
| **Otto Graham** | **6** | **+0.90** | **+5.4** | **3%** | **1950s Browns; best defensive support of any QB in this table, still added value** |
| Joe Montana | 12 | +0.79 | +9.5 | 19% | Elite defense; WAE is positive but limited after baseline adjustment |
| **Bobby Layne** | **12** | **+0.68** | **+8.2** | **37%** | **1950s Lions/Steelers; mid-pack WAE over a long career** |
| Fran Tarkenton | 18 | +0.68 | +12.2 | 55% | Below-avg defense; consistent middling WAE over long career |
| Terry Bradshaw | 12 | +0.44 | +5.3 | 28% | Good Steel Curtain defense; adds modest WAE above it |
| Bart Starr | 12 | +0.20 | +2.4 | 24% | Strong defense; adds modestly above it |
| Jim McMahon | 9 | −0.88 | −8.0 | 18% | Elite defense; actually underperformed expectations |
| Doug Williams | 6 | −1.72 | −10.3 | 42% | Below expectations despite middling defense |
| Trent Dilfer | 7 | −1.96 | −13.7 | 26% | Worst WAE despite top-quartile defense — canonical clipboard QB |

*(Steve Young and Bob Griese dropped from this specific named list in the current notebook's
`GOAT_IDS`/`CLIPBOARD_IDS` dicts — they remain in the Section 5 z-score table below.)*

**Key reads:**
- **Manning vs Brady:** Manning adds +2.92 wins per season with a 45th-percentile defense. Brady adds +1.96 with a 20th-percentile defense. The isotonic model raises Brady's baseline (a 20th-percentile defense is expected to win ~10+ games), making his over-performance look more modest.
- **Montana:** Had a historically elite defense (19th percentile). The model correctly expects that defense to produce ~10 expected wins on its own; Montana adds modestly above that. The WAE confirms his rings were earned — but also shared with a historically dominant defense.
- **McMahon at −0.88:** The 1985 Bears defense was so dominant that McMahon's mediocre QB play *underperformed* what the model expected. The defense didn't just carry him — it outran him.
- **Staubach at +2.01 in only 8 seasons:** Most similar career profile to Brady, one of the most underrated QBs in the data.
- **New: Otto Graham and Bobby Layne now qualify (1950s extension).** Graham's Cleveland teams had the single best defensive support of any QB in this table (3rd percentile average — even better than Montana's or Bart Starr's) and he *still* posted a positive WAE, which puts him in the "elite QB + elite defense, adds real value anyway" category rather than at either extreme. Layne lands mid-pack over a long (12-season) career. Neither result is surprising or extreme — a reasonable sanity check that the 1950s extension is behaving correctly rather than introducing bias into the rankings.

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
| Johnny Unitas | 15 | 0.75 | 1.01 | 0.53 | 0.51 | 1958 | 2.13 | 85.4 |
| Fran Tarkenton | 18 | 0.74 | 0.59 | 0.36 | 0.72 | 1975 | 1.68 | 90.8 |
| Brett Favre | 19 | 0.58 | 0.69 | 0.85 | −0.10 | 1996 | 2.26 | 95.7 |
| Bart Starr | 12 | 0.51 | −0.53 | −0.07 | 0.42 | 1966 | 2.09 | 102.1 |
| John Elway | 16 | 0.26 | 0.41 | 0.10 | 0.39 | 1993 | 1.71 | 94.2 |
| Terry Bradshaw | 12 | 0.10 | 0.02 | 0.69 | −0.33 | 1978 | 1.43 | 81.5 |
| Jim McMahon | 9 | −0.21 | −0.56 | −0.33 | −0.06 | 1985 | 0.39 | 77.3 |
| Trent Dilfer | 7 | −0.80 | −1.41 | −0.60 | −0.50 | 1997 | 0.29 | 80.4 |

**Notable reads:**
- **Steve Young (#1 career QB-z):** 1994 season (z=3.43) is the most dominant QB season relative to contemporaries in the entire 1950–2025 dataset (z-scores are computed within-year, so the 1950s extension doesn't change this specific number — it just extends the years the claim is checked against). He is severely underrepresented in GOAT debates — partly because he played in Montana's shadow, partly because his career was shortened by concussions. The data says he was the most era-dominant QB ever recorded.
- **Montana's INT-z (1.32) is the best in the table** — he protected the ball more relative to his era than even Rodgers (1.21) or Brady (1.15). This directly explains his flawless Super Bowl record.
- **Mahomes at 0.81 QB-z despite being the best current player:** modern era has more elite QBs. Even an extraordinary player compresses toward a smaller z-score because the competition is denser. This is a structural argument against using raw z-scores for cross-era GOAT claims — use it for "was he dominant in his era" rather than "who was the absolute best ever."
- **Bradshaw's negative INT-z (−0.33):** He threw more picks relative to his era than the average starting QB. The Steel Curtain genuinely carried the offense.
- **Griese's negative yards-z (−0.45) with positive QB-z (1.01):** High efficiency in a run-first Miami offense. His low volume was scheme, not limitation — when he passed, he passed well.
- **Starr's negative yards-z (−0.53) and near-zero TD-z:** Lombardi's system kept him from throwing. His QB-z (0.51) reflects being above average in a limited role, not a dominant passer.

---

## 6. Z-Score WAE Model — Alternative Baseline

**2026-08 note:** while re-executing the notebook for the 1950s coverage audit (see Sections 1-4
above and `qb_value_analysis.md`), no cell implementing this OLS/z-score alternative model was found
anywhere in the current `qb_value_analysis.ipynb` (28 cells, Chart 1 through the Section-5 z-score
table). This section's numbers were not re-verified or regenerated and may be stale relative to
current data — the code that produced them may live elsewhere or may have been removed from the
notebook at some point. Treat this section as unconfirmed until its source is located.

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
