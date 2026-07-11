# Defensive Metric Layers: From Raw Stats to OQA Z-Score

**Audience target:** Blog readers / book chapters. Assumes algebra comfort, no stats background required.
**Canonical example:** 1969 Minnesota Vikings through each metric layer.
**Key question answered:** How do you measure how good a defense *really* was?

---

## Why This Matters

The NFL records points allowed and yards allowed for every team every season going back to 1960. Everyone can look at a box score. So why do we need anything beyond "they allowed 10.8 points per game"?

Because every number in sports hides noise — and the noise compounds when you try to compare across teams, divisions, and eras. Each metric layer below removes one source of noise. More importantly, it reveals a *different* question hiding inside the one you thought you were answering.

---

## The Layers

### Layer 1: Points Per Game (PPG) Allowed

The simplest measure. Add up all points allowed, divide by games played.

**What it captures:** Whether you won (roughly). Points-per-game allowed has the single strongest correlation with win percentage of any team statistic — r = −0.70 across 1,800+ team-seasons from 1960–2024.

**What it hides:** Some of those "points allowed" were not the defense's fault.

When an opposing cornerback returns an interception 60 yards for a touchdown, or a special teams return goes 90 yards to the house, or a fumble recovery is returned for a score — all of those show up in your "points allowed" column. They are called non-offensive touchdowns (or defensive/special teams TDs *by the opponent*), and they inflate a defense's points-allowed number without the defense having surrendered a yard on a sustained drive.

---

### Layer 2: Yards Per Game (YPG) Allowed

How many total yards did opponents gain per game?

**What it adds:** Yards is a drive-level stat. You have to actually move the ball to gain yards. Non-offensive TDs — pick-sixes, fumble returns, kick returns — do not add to the opposing offense's yardage total. So yards-per-game is a cleaner signal for *drive-level defensive quality*.

**What it hides:** Yards don't win games; points do. A defense that holds opponents to 250 yards but allows a blocked punt returned for a TD has a great yards number and a bad points number. Both numbers are telling you something true.

**The proof:** Look at Pittsburgh 1969:

| Team | PPG Allowed | Pts Rank | YPG Allowed | Yds Rank |
|------|-------------|----------|-------------|----------|
| PIT  | 28.9        | 17/17 (worst!) | 314   | 11/17    |

Pittsburgh was the worst scoring defense in the 1969 NFL — but a *below-average* yards defense. They were giving up non-offensive touchdowns at a high rate, not losing on sustained drives. The yards number sees through that noise. The points number does not.

**Another example from 1969:** Chicago allowed 24.2 PPG (rank 13th) but only 277 YPG (rank 6th). The Bears were a legitimate yards defense but were hurt by non-offensive touchdowns in the points column.

The same effect appears for the 1991 Philadelphia Eagles: rank 5th in points (15.2 PPG), but rank **1st in yards** with a yards z-score of **+3.04** — more than three standard deviations above the league average, the best yards-z ever recorded in this dataset. Buddy Ryan's defense was historically great at preventing drives. The points column undersold them.

---

### Layer 3: Ordinal Rank

Convert PPG allowed to a rank within the season (1 = fewest points allowed = best).

**What it adds:** Instant context. "#1 defense in the league" means something everyone understands.

**What it hides:** The magnitude of the difference between teams. Being #1 in 1985 with 10.9 PPG allowed is not the same as being #1 in 1962 with 16.7 PPG allowed. Ordinal rank makes them look identical.

Equally important: the gap *between* ranks varies wildly. In a year where the top three defenses are clustered at 10.8, 11.1, and 11.4 PPG, rank #1 and rank #3 are nearly the same defense. In a year where the top defense allows 10.9 PPG and the #2 allows 13.1, rank #1 is in a different tier entirely.

Rank also says nothing meaningful about *how much* a defense contributed to wins. Two wins above a median defense and seven wins above a median defense are both "#1 in the league" if no other team is in between.

---

### Layer 4: Z-Score (Era-Adjusted Magnitude)

The z-score answers: *by how many standard deviations did this defense beat the league average that season?*

Formula (negated so that higher = better defense):

```
def_pts_z = −1 × (team_PPG_allowed − league_avg_PPG) / league_std_PPG
```

A z-score of +1.0 means the team allowed one standard deviation fewer points than the average team that season. A z-score of +2.0 means two standard deviations — exceptionally rare. A z-score of +2.5 or above is historic.

**What it adds:**
- Magnitude: +2.59 (1985 Bears) is roughly twice as dominant as +1.53 (1969 Vikings in raw points). Rank would show both as "#1 defense."
- Era comparison: a +2.59 in 1985 and a +2.59 in 2000 represent the same level of *relative* dominance within their respective seasons, even though PPG allowed may differ.

**Predictive improvement:** Using z-score instead of rank improves R² from 0.491 to 0.511 in the wins model — about 2 percentage points of additional win variance explained, worth roughly a third of a win per season.

**The landmark z-scores (full dataset, 1960–2024):**

| Team | Year | Pts/G | PPG Rank | Pts-z | Yds/G | Yds Rank | Yds-z |
|------|------|-------|----------|-------|-------|----------|-------|
| CHI  | 1985 | 10.9  | 1/28     | **+2.59** | 240 | 1/28 | +2.40 |
| RAV  | 2000 |  9.4  | 1/31     | +2.40 | 240 | 2/31 | +2.12 |
| MIN  | 1970 | 10.7  | 1/26     | +2.26 | 206 | 1/26 | +2.75 |
| CHI  | 1986 | 12.6  | 1/28     | +2.12 | 261 | 1/28 | +2.26 |
| MIN  | 1971 | 10.6  | 2/26     | +1.96 | 239 | 2/26 | +1.56 |
| MIN  | 1969 | 10.8  | 2/17     | +1.53 | 207 | 1/17 | +1.94 |
| PIT  | 1976 | 11.0  | 1/28     | +1.63 | 232 | 1/28 | +1.80 |
| PHI  | 1991 | 15.2  | 5/28     | +1.16 | 222 | 1/28 | **+3.04** |

Notice: the 1985 Bears have the highest *pts-z* ever recorded (+2.59). The 1970 Vikings have the highest *yds-z* (+2.75). The 1991 Eagles have a yds-z of +3.04 — the highest yards z-score in 65 years of data — but rank only 5th in *points* that season, a perfect illustration of the non-offensive TD noise problem from Layer 1.

---

### Layer 5: Opponent Quality Adjustment (OQA)

Not all opponents are created equal. A defense that faces the 1984 Miami Dolphins passing offense, the 1994 San Francisco 49ers, and the 2007 New England Patriots all in one hypothetical season is playing a much harder schedule than one that faces three average teams.

**What OQA does:** For each game, we calculate how good the opposing offense was *in every other game that season* (leave-one-out, to avoid counting the current game against itself). We express that as a ratio to the league average:

```
OQA ratio = opponent_avg_PPG_scored_(excluding_this_game) / league_avg_PPG
```

- Ratio > 1.0: you faced a stronger-than-average offense that game
- Ratio < 1.0: you faced a weaker-than-average offense that game

Then we adjust the points allowed for that game:

```
OQA-adjusted points = actual_points_allowed / OQA_ratio
```

If you allowed 14 points to a team that averaged 28 PPG elsewhere (ratio = 28/21 ≈ 1.33), your adjusted points for that game = 14 / 1.33 = 10.5. You get credit for suppressing a hot offense.

If you allowed 14 points to a team that averaged 14 PPG elsewhere (ratio = 14/21 ≈ 0.67), your adjusted points = 14 / 0.67 = 20.9. You don't get as much credit — your opponent wasn't very threatening to begin with.

Average these across all 14–17 games in the season and you have an OQA-adjusted PPG allowed per season.

**LOO validation:** Across all 29,000+ team-game rows from 1960–2024, the mean OQA ratio = 0.9999. This confirms the leave-one-out is mathematically correct with no systematic bias in the calculation itself.

**How much does OQA change things?**

- In **48.6%** of team-seasons, OQA shifts the team's rank by 2 or more spots.
- In **19.6%** of team-seasons, OQA shifts the rank by 4 or more spots.
- The largest single shift: Cincinnati 2011 jumped 12 spots (from rank 12 → rank 24 out of 32) once OQA revealed they'd faced some of the weakest offenses in the league that year (schedule factor 0.871 — opponents scored 12.9% below average against everyone else).
- The largest beneficial shift: New York Giants 1983 jumped from rank 15 to rank 5 after OQA credited them for playing against some of the league's stronger passing offenses (schedule factor 1.134).

**Scheduling bias by era:**

This is where the NFL's scheduling rules become analytically important. In the modern NFL (post-2002), teams finishing first in their division play other first-place finishers in cross-conference games. Good teams are intentionally matched against other good teams.

| Era | Correlation: schedule difficulty vs win% |
|-----|----------------------------------------|
| 1960–2001 | **+0.25** (meaningful bias) |
| 2002–2024 | −0.05 (essentially zero) |

Pre-2002, good teams systematically faced *stronger* offensive opponents (r = +0.25). A top-5 defense in 1975 was more likely facing tough opponents than a bottom-5 defense was. OQA is more important for pre-2002 historical analysis as a result.

Post-2002, the formalized scheduling formula distributes opponents much more evenly. The correlation is near zero — good teams and bad teams face essentially the same average offensive quality. OQA matters less for modern-era comparisons.

---

### Layer 6: OQA + Z-Score (The Full Picture)

After computing OQA-adjusted PPG allowed for each team-season, apply the same z-score formula within the season:

```
def_pts_z_oqa = −1 × (team_OQA-adj-PPG − season_avg_OQA-adj-PPG) / season_std_OQA-adj-PPG
```

This is the most refined single number for team defensive quality: magnitude-preserving, era-normalized, and opponent-adjusted.

---

## The 1969 Vikings Through Every Lens

The 1969 Minnesota Vikings are the ideal teaching example because their numbers *change meaningfully* at each layer, and the changes are explainable.

| Metric | Value | Context |
|--------|-------|---------|
| PPG allowed | 10.8 | #2 in NFL (behind only Kansas City in limited AFL data) |
| YPG allowed | 207 | **#1 in NFL** |
| Pts-z | +1.53 | Clearly elite; about 1.5 SD above league average |
| Yds-z | +1.94 | Even more impressive on yards — better at drive-stopping |
| Schedule factor | 0.943 | Opponents averaged 5.7% *below* league average in PPG scored |
| OQA-adj PPG | 14.4 | Adjusted up (penalized for easier opponents) |
| OQA rank | 3/17 | Drops from #2 to #3 in pts after OQA |
| OQA pts-z | +0.98 | Drops from +1.53 — still elite, but the gap narrows considerably |
| OQA-adj YPG | 249 | Also adjusts upward from raw 207 |
| OQA yds rank | 3/17 | Drops from #1 to #3 |

**What the layers reveal:**

The 1969 Vikings were a legitimately elite defense — #1 in yards prevention in the whole NFL. But they were playing in what was then still largely an NFL-only season (pre-AFL-NFL full merger), and their opponents happened to be weaker-than-average offenses. After adjusting, the 10.8 PPG raw figure is better understood as equivalent to about 14.4 PPG against a normal schedule. They were #3, not #2, after OQA.

More importantly: compare 1969 to 1970. Same core roster, full merger year:

| | 1969 | 1970 |
|--|------|------|
| PPG allowed | 10.8 | 10.7 |
| Pts rank | 2/17 | 1/26 |
| Pts-z | +1.53 | **+2.26** |
| Schedule factor | 0.943 | 0.989 |
| OQA pts-z | +0.98 | **+2.26** |

Nearly identical raw numbers. But 1970 was a 26-team merged league with the AFC's strongest offenses now on the schedule. The Vikings' score didn't change; the quality of what they were doing relative to their competition did. Z-score captures that. And OQA confirms it — in 1970, their schedule was balanced (0.989), so the +2.26 stands up fully.

The 1969 Vikings were good. The 1970 and 1971 Vikings were historically great.

---

## Side-by-Side: What Each Layer Adds (and Removes)

| Layer | What it removes | What it adds | Limitation remaining |
|-------|----------------|--------------|---------------------|
| Raw PPG | — | Intuition, win correlation | Non-off TD noise; era incomparability |
| Raw YPG | Non-off TD noise | Drive-level quality | Era incomparability; yards ≠ wins |
| Ordinal rank | Era-level average differences | Immediate context | Loses magnitude |
| Z-score | Era incomparability | Magnitude; cross-era comparison | Schedule bias |
| OQA | Schedule strength bias | Opponent-normalized value | Minor mutual-influence effect |
| OQA + Z-score | All of the above | Cleanest single defensive quality number | — |

---

## Glossary Entries (For Later Reference)

**Points per game allowed (PPG):** Total points allowed divided by games played. Includes points scored by opponents' defense and special teams. Strongest raw predictor of win percentage.

**Yards per game allowed (YPG):** Total offensive yards gained by opponent divided by games played. Cleaner drive-level signal than PPG; immune to non-offensive TD noise.

**Non-offensive touchdown:** A touchdown scored by the *opposing* defense or special teams — pick-six, fumble return TD, blocked kick return, etc. These inflate the defending team's PPG-allowed number without any drive-level defensive failure.

**Z-score (within-season):** Number of standard deviations above or below the season mean. Negated for defense so higher = better. Formula: `z = −(x − μ) / σ`. Enables cross-era comparison while preserving magnitude.

**OQA (Opponent Quality Adjustment):** Per-game normalization of defensive performance by strength of opposing offense. Uses leave-one-out averaging of opponent's season PPG scored (excluding the current game) divided by league average. OQA ratio > 1 = faced stronger-than-average offense; < 1 = weaker-than-average.

**Schedule factor:** Average OQA ratio across all games in a season. Values near 1.0 indicate a balanced schedule. Below 0.95 indicates the team systematically faced below-average offenses; above 1.05 indicates systematically tougher opponents.

**Leave-one-out (LOO):** A technique to avoid circularity: when measuring how good an opponent's offense was, exclude the game against *this* defense from the calculation. Prevents a great defense from making opponents look artificially weak when rating those same opponents.

---

## Pending Additions

- Non-offensive TD count per game by team-season (to quantify the pts/yds gap directly)
- OQA for individual players (game-level; more critical pre-2002 due to scheduling bias)
- Table: largest pts-z vs yds-z divergences (Buddy Ryan defenses, 1969 PIT, 1979 Steelers, etc.)
- Era-by-era trend in defensive dominance (is the modern NFL harder or easier to be an elite defense?)
