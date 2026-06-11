# QB Value Analysis — Problem Statement & Findings

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
Data: `/Users/devos/data/pfref/` — passing stats 1960–2024, team-history

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
Rolling mean of actual win% across all team-seasons, sorted by `def_pts_norm`
(window ≈ 8% of all seasons, minimum 20). Interpolated with `scipy.interpolate.interp1d`.
Expected wins = `expected_win_pct × season_games`.

### Wins Above Expected (WAE)
`WAE = actual_wins − expected_wins`

Positive WAE = team won more than the defense alone would predict (QB + coaching +
offense + special teams all roll in). Negative WAE = underperformed the defensive
advantage. 188 QBs qualify (4+ seasons as primary starter, 1960–2024).

---

## Confirmed Findings

### Correlations (all ~1,700 NFL team-seasons 1960–2024)

| Metric | Pearson r | r² |
|---|---|---|
| QB composite rating vs Win% | +0.532 | 0.283 |
| Defense PPG rank vs Win% | −0.700 | 0.490 |

Defense is **1.3× more predictive** of winning than QB rating.
A great offense cannot reliably overcome a poor defense.

### Tier analysis — defense PPG rank

| Tier | n | Avg Win% | P(10+ win pace) | P(Playoffs) | P(Won SB) |
|---|---|---|---|---|---|
| Top 10% defense | 211 | 71% | **83%** | 86% | 14.2% |
| Top 25% defense | 458 | 67% | 72% | 74% | 9.8% |
| Top 50% defense | 895 | 61% | 54% | 59% | 5.9% |
| Bottom 50% defense | 888 | 38% | 9% | 14% | 0.5% |
| Bottom 25% defense | 453 | 31% | **3%** | 5% | 0.2% |

### Wins Above Expected — named QBs

Sorted by avg WAE per season. `Avg Def %ile` = 0% is best defense, 100% is worst.

| QB | Seasons | Avg Wins | Avg Exp | Avg WAE | Total WAE | Avg Rating | Avg Def %ile |
|---|---|---|---|---|---|---|---|
| Peyton Manning | 17 | 11.2 | 8.3 | **+2.99** | +50.8 | 95.7 | 45% |
| Roger Staubach | 8 | 10.6 | 8.5 | +2.11 | +16.9 | 84.0 | 26% |
| Tom Brady | 21 | 12.1 | 10.0 | +2.09 | **+44.0** | 96.7 | 20% |
| Aaron Rodgers | 15 | 10.1 | 8.3 | +1.75 | +26.2 | 101.6 | 45% |
| Dan Marino | 16 | 9.6 | 8.0 | +1.59 | +25.4 | 85.2 | 48% |
| Terry Bradshaw | 13 | 10.1 | 8.5 | +1.58 | +20.5 | 68.0 | 28% |
| Joe Montana | 12 | 11.0 | 9.5 | +1.47 | +17.6 | 91.9 | 19% |
| Fran Tarkenton | 18 | 7.3 | 6.9 | +0.39 | +7.0 | 78.6 | 55% |
| Bart Starr | 10 | 10.9 | 10.1 | +0.78 | +7.8 | 78.6 | 14% |
| Johnny Unitas | 11 | 10.5 | 9.5 | +1.04 | +11.5 | 75.8 | 27% |
| Jim McMahon | — | — | — | — | — | — | — |
| Doug Williams | 6 | 6.8 | 8.5 | −1.62 | −9.7 | — | 42% |
| Trent Dilfer | 7 | 7.6 | 9.5 | **−1.93** | −13.5 | — | 26% |

**Key takeaways:**
- Manning beats expectations by nearly 3 wins/season playing with below-average defenses → strongest case for "best pure QB."
- Brady's +2.09/season looks good but his 20th-percentile defenses already produce ~10 expected wins; he adds ~2 more. Montana is the same archetype: great QB, always great defense.
- Rodgers: +1.75/season is impressive given consistently 45th-percentile defense (worse than league average). If he'd had Brady's defense, the model would project him averaging ~11.8 wins/season.
- Dilfer and Doug Williams in the negative — they *underperformed* even with top-quartile defenses. Brady's 2000 BAL defense is the actual GOAT; Dilfer just held the clipboard without fumbling.

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
