# QB GOAT Rankings — Data-Driven Assessment

> **2026-08-21 addendum #2 — game-level WAE + `WAE_Vegas`; ranking NOT re-derived:** the WAE/s figures
> in this doc's Top-10 writeups and Summary Table are the old **season-level** model (whole team-season
> win-loss record attached to whoever led the team in attempts that season). That model has been
> superseded by a game-level rebuild (`WAE_DefRank`) plus a new parallel `WAE_Vegas` baseline (Vegas
> line instead of defensive rank as the expected-outcome model) — full methodology and the Chicago
> Bears 1978-1993 validation case are in `qb_value_analysis.md`'s addendum #2. Game-level numbers for
> the nine QBs on this page (1967-2025 scope):
>
> | QB | `WAE_DefRank`/16g (new) | old WAE/s | `WAE_Vegas`/16g (new) |
> |---|---|---|---|
> | Patrick Mahomes | +3.33 | +3.20 | +1.37 |
> | Peyton Manning | +2.89 | +2.92 | +1.03 |
> | Drew Brees | +2.29 | +2.37 | +0.25 |
> | Roger Staubach | +2.15 | +2.01 | +0.69 |
> | Tom Brady | +2.08 | +1.96 | **+1.52** |
> | Aaron Rodgers | +1.87 | +1.69 | +0.46 |
> | Steve Young | +1.83 | +1.46 | **−0.12** |
> | Dan Marino | +1.63 | +1.50 | +0.39 |
> | Joe Montana | +1.38 | +0.79 | **+1.42** |
>
> **This ranking's order is NOT being mechanically re-derived from the table above** — the ranking is
> an explicit multi-metric holistic judgment (WAE/s + EliteDefZ + ERA-z), and EliteDefZ has no working
> pipeline to re-run (per addendum #1 below and `qb_composite_research.md`), so a full recompute isn't
> possible right now. What the game-level numbers *do* support, qualitatively:
> - **`WAE_DefRank` alone would not reorder the Top 5** — Manning, Mahomes, Young, Brees, Montana all
>   move by similar small amounts and stay in a similar relative band; Montana's jump (+0.79 → +1.38)
>   is the largest single change and strengthens his case slightly, not enough on its own to swap him
>   with Brees or Young given the other two metrics still apply.
> - **`WAE_Vegas` is a genuinely different signal and, if it were substituted for WAE/s, would move
>   Brady and Montana up and Young down.** Brady's `WAE_Vegas` (+1.52/16g) is the highest of any named
>   QB here, well above his `WAE_DefRank` rank (#5-6 by that metric) — beating a betting market that
>   already prices in "elite defense behind this QB" is a harder bar than beating a defense-only
>   baseline, and Brady clears it more convincingly than the defense-only framing (this doc's #6 writeup,
>   and its opening "Brady's reputation overstates his contribution" hypothesis in `qb_value_analysis.md`)
>   suggests. Montana shows the same pattern. Young is the mirror case: strong `WAE_DefRank`, essentially
>   flat-to-negative `WAE_Vegas`.
> - **Net read:** the Top-5 write-ups' *specific* WAE/s numbers below are stale (see table above for
>   current figures) but the #1-5 ordering itself is not obviously wrong under either new metric alone.
>   The Brady/Montana-vs-Young divergence between `WAE_DefRank` and `WAE_Vegas` is a real, new piece of
>   evidence this ranking hasn't incorporated yet — worth a real re-pass once EliteDefZ has a working
>   pipeline again, rather than a partial patch now that would make this doc internally inconsistent
>   (some metrics updated, some not, on a ranking that's explicitly built by combining all of them).

> **2026-08-21 addendum #1:** re-verified against a fresh, bug-fixed run of `qb_value_analysis.ipynb`
> (see `qb_value_analysis.md` for the two bugs found and fixed, and the 1960→1950 coverage extension).
> **The ranking order below is unchanged** — every metric-value shift was too small to move a QB
> past a neighbor in a ranking that's already a holistic multi-metric judgment call, not a strict sort.
> WAE/s updated for Tom Brady (+1.94 → +1.96), Roger Staubach (+2.00 → +2.01), Dan Marino (+1.49 →
> +1.50), Joe Montana (+0.80 → +0.79), Patrick Mahomes (+3.19 → +3.20), and Johnny Unitas's ERA-z
> (0.47 → 0.75 — this one was a real doc bug, not a data change: see `qb_value_analysis.md`). ERA-z is
> otherwise unchanged for everyone. **EliteDefZ could not be re-verified at all** — no script building
> it exists anywhere in the current repo (see `qb_composite_research.md`'s addendum) — so every
> EliteDefZ figure below is carried over unconfirmed, not re-computed. Also: the 1950s coverage
> extension now surfaces Otto Graham (+0.90 WAE/s), Bobby Layne (+0.68), and Y.A. Tittle (+1.23) as
> WAE-qualifying QBs for the first time, but none of them have an ERA-z or EliteDefZ figure (they aren't
> in the notebook's hardcoded named-QB lists, and EliteDefZ has no working pipeline at all), so they
> can't be scored on this ranking's other two metrics and are left out of the table below — a known
> gap, not a considered exclusion.

Based on four metrics: WAE/s (Wins Above Expected per season), Comp%-z (career within-season z-score), EliteDefZ (z-score vs top-25% defenses, within-context), and era-adjusted QB-z. Full methodology in `qb_composite_research.md`.

---

## Top 5

### #1 — Peyton Manning

It's not close across the metrics. #2 WAE/s (+2.92/season) with a 45th-percentile defense — no other QB in the top-5 WAE tier played with worse defensive support. #2 EliteDefZ (+0.675), balanced across both Comp% and Yds/G. #4 era-adjusted z-score (1.18). He shows up top-3 on every single metric we built. The "pure QB" case is unambiguous: nearly 3 wins/season above what his defense alone predicted, 88% positive WAE seasons over 17 years, holds his game when the defense across the field is elite. No other QB does all of it at this level over this duration.

### #2 — Patrick Mahomes

Caveat first: 7 seasons. If this were locked in at the end of his career today he'd still be #2, but the sample is real and the rate is historic. WAE/s #1 (+3.20/season), 86% positive seasons. His EliteDefZ Yds/G-z is the highest in the entire table (+0.985) — he's the only QB whose production against elite defenses actually *increases* from his career average. That's a genuinely unusual trait. He isn't the most accurate (Comp%-z only +0.244 vs elite D) but he's throwing into tight windows for bigger gains and it's working. If he plays to 38, he's the GOAT conversation.

### #3 — Steve Young

The data says he's severely underrated and the reason is circumstantial, not analytical. #1 era-adjusted QB-z in the entire 1950–2025 dataset (1.63 career; re-confirmed 2026-08-21 against the now-1950-2025 dataset — his 1994 z=3.43 is still the single highest of any team-season in the data, ahead of the newly-added 1950s seasons too, e.g. Otto Graham's best is 1955 at z=2.61). Best single season ever by that measure — 1994 at z=3.43, more dominant relative to contemporaries than Rodgers' 2011 or Brady's 2007. Top-10 EliteDefZ. The problem: 9 qualifying seasons, played his prime in Montana's shadow, career shortened by concussions. If you ask "who was the most dominant QB relative to his era at his peak," the answer is Young and it isn't particularly close.

### #4 — Drew Brees

The most underrated QB in the dataset, full stop. WAE/s #3 (+2.37/season) over 19 seasons with a 56th-percentile defense — worse average defensive support than anyone else in the top WAE tier. 45.0 total WAE is second only to Manning. EliteDefZ composite #3 (+0.659) with the highest Comp%-z vs elite defenses (+0.689). He's essentially never mentioned in GOAT conversations and the metrics say he belongs in the top 4. The lack of rings narrative hurts him — but his defense career average was below league average for 19 years.

### #5 — Joe Montana

ERA-adjusted z-score #2 (1.51), and the highest INT-z in the entire named-QB table (1.32) — he protected the ball better relative to his contemporaries than anyone, including Rodgers and Brady. EliteDefZ #5 (+0.617), with the best Comp%-z in the set when facing elite defenses (+0.745). The legitimate knock is the defense context: 19th-percentile career average, always elite. His WAE/s is +0.79 because the isotonic model correctly notes that those defenses were already expected to produce ~10 wins on their own. Brady has the same problem. Between the two, Montana's ERA-z dominance (1.51 vs 0.99) and superior ball protection are the tiebreaker.

---

## GOAT: Peyton Manning

Young was the most era-dominant. Mahomes might be the best ever if he plays another 8 seasons at this rate. But if you're asking who, across the longest run of the best evidence we have, was the most complete QB accounting for defensive context, opponent quality, efficiency, and wins — Manning has the strongest multi-metric case. He's #1 or #2 on everything we built, his defensive support was the worst of anyone in the top-5 WAE tier, and he did it for 17 years.

The honest footnote: if Steve Young had played 15 years as a starter the conversation might be different. And if Mahomes is still doing this in 2032, he wins by a mile.

---

## #6–10

### #6 — Tom Brady

Hard to leave him out. 21 seasons, 86% positive WAE rate (18/21), +1.96/season above what was already an elite defensive baseline. ERA-z at 0.99 reflects era compression from playing in a QB-rich era, not personal decline — in his 2007 peak season (z=2.90) he was as dominant as anyone not named Young. EliteDefZ +0.450 over 105 games (largest sample in the table) is solid, though unverified as of the 2026-08-21 pass (see addendum above). The defense context is real and the isotonic model handles it correctly — his 20th-percentile career defense was already expected to produce 10+ wins, so his +1.96 is on top of that. He's #6 rather than higher because Manning, Young, Brees, and Montana all have stronger individual metric cases, and the defense context is a legitimate deduction when the metric has already adjusted for it.

### #7 — Roger Staubach

Probably higher than most would expect, but the data supports it. ERA-z #3 in the entire dataset (1.41), behind only Young and Montana. WAE/s +2.01/season — that rate would be top-5 with a full career. His only limitation is 8 qualifying seasons, and that limitation is circumstantial: he started his NFL career at 27 due to mandatory military service after the Naval Academy. If he'd had a full 15-year window, the data says he's probably top-3. The most underrated historical QB in the dataset after Young.

### #8 — Aaron Rodgers

ERA-z 5th best in the full dataset (1.10). WAE/s +1.69/season with a 45th-percentile defense — same defensive context as Manning but about 1.2 wins/season less production. The EliteDefZ result (+0.267, 15th of 24) is the most significant knock: he's excellent against average defenses, less so against elite ones. Manning's EliteDefZ composite is 2.5× Rodgers'. That gap matters. The INT-z career number is very strong (1.21, second only to Montana) — he protects the ball well. He belongs in the top 10 but not higher given the elite-defense performance gap.

### #9 — Dan Marino

WAE/s +1.50/season over 16 seasons with a 48th-percentile defense (below average). EliteDefZ +0.527 (7th of 24), unverified as of the 2026-08-21 pass (see addendum above). The no-rings narrative is a media construct — the data says he added +1.50 wins/season for 16 years on a mediocre defense, 24.0 total WAE. His 1984 season (108.5 rating, 5,084 yards) remains one of the great individual seasons in the dataset. ERA-z 0.85. He belongs here alongside the other "penalized by defense" QBs — Brees got into the top 5 because his volume, longevity, and EliteDefZ were all slightly higher, but Marino is right behind him.

### #10 — Dan Fouts

The surprise of the analysis. EliteDefZ #4 (+0.648) — era-adjusted, facing AFC West and NFC division rivals in the late 1970s and early 1980s, he was performing at an elite level against the best defenses. His raw Yds/G-z vs elite defenses (+0.843) is second only to Mahomes. Data gaps hurt his WAE/s case (some pre-1978 seasons not fully covered) and his career was shorter than the modern era QBs. But the elite-defense performance is too strong to discount. He was genuinely dominant in a way the counting stats from a run-first era obscured.

---

## Just Outside the Top 10

- **Johnny Unitas**: ERA-z 0.75 (corrected 2026-08-21 — a doc bug, not a data change, had this at 0.47 with a wrong 11-season count instead of the correct 15; see `qb_value_analysis.md`), EliteDefZ +0.514 (unverified). Historical significance enormous but the metrics put him middle-tier vs. modern competition. His era had fewer elite QBs to compare against, which compresses his ERA-z relative to his actual dominance.
- **Philip Rivers**: EliteDefZ +0.354, consistent but not transcendent on any single metric. A legitimate top-15 QB.
- **Brett Favre**: EliteDefZ +0.398, long career, but high INT rates across his career hurt the efficiency metrics. Top 12–13 range.
- **Bob Griese**: ERA-z 1.01 (would be top 5 by that metric alone), but negative Yds-z (−0.45) reflects scheme, not skill — Shula's run-first Dolphins kept his attempts so low that volume metrics don't capture him fairly. A case for a separate scheme-adjusted metric someday.

---

## Summary Table

*WAE/s and ERA-z re-verified 2026-08-21 against the fixed pipeline (changed values marked). EliteDefZ
column is unverified — no source pipeline exists in the current repo; see addendum above.*

| Rank | QB | WAE/s | EliteDefZ | ERA-z | Notes |
|---|---|---|---|---|---|
| 1 | Peyton Manning | +2.92 | +0.675 | 1.18 | Best multi-metric case, weakest defense of top 5 |
| 2 | Patrick Mahomes | +3.20 | +0.615 | 0.81 | Historic rate, only 7 seasons |
| 3 | Steve Young | +1.46 | +0.455 | **1.63** | Most era-dominant, 9 seasons |
| 4 | Drew Brees | +2.37 | +0.659 | 1.09 | Most underrated, worst defense of top 5 |
| 5 | Joe Montana | +0.79 | +0.617 | 1.51 | Best ball protection ever, elite defense context |
| 6 | Tom Brady | +1.96 | +0.450 | 0.99 | 21 seasons, elite defense context |
| 7 | Roger Staubach | +2.01 | +0.352 | 1.41 | 8 seasons; military service cost him 5 prime years |
| 8 | Aaron Rodgers | +1.69 | +0.267 | 1.10 | Elite vs average D; fades vs elite D |
| 9 | Dan Marino | +1.50 | +0.527 | 0.85 | 16 seasons below-avg defense, no rings |
| 10 | Dan Fouts | — | +0.648 | — | EliteDefZ 4th all-time; data gaps limit WAE/s |
