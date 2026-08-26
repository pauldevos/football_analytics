# Results: real event value from PFR's own expected-points data (1978-2025)

Completed 2026-08-22, answering the "value" leg of the brief in
`docs/deferred/04_idi_weight_revisit.md` (the skill/rarity/**value**
three-part framing that doc asks for) and superseding the core assumption
of `docs/deferred/03_epa_pbp_value_model.md` — that doc assumed an
expected-points model would need to be **fit from scratch**, at real risk
(data completeness, attribution ambiguity, engineering scope). It doesn't.
PFR's own `pbp.csv` already carries `exp_pts_before`/`exp_pts_after` on
every play, 1978-2025, confirmed populated at scale below. This doc verifies
those columns' exact semantics, attributes each play's swing to a defensive
event type by reusing `gamebooks_boxscores/parse_pfr_pbp.py`'s existing
regex definitions, and reports real average event values — pooled and by
era — as the direct input the weight re-derivation in doc 04 needs next.

**This doc does not touch `dpvs/idi.py` or re-derive IDI's weights.** That
is explicitly a later step, once these numbers are reviewed.

Script: `football_analytics/scripts/build_event_value_by_era.py` (stdlib
only, no DB, ~60s over the full corpus). Raw aggregates: `data_output/
event_value_results.json` (per-season, per-category n/sum/sum-of-squares).

## 1. Scope

**1978-2025 only**, per explicit direction. Two independent reasons, both
already established elsewhere in this project: pre-1978 gamebook PBP is
lower-confidence OCR text that would need heavy filtering to trust for a
numerical value calculation (see `gamebooks_boxscores/docs/experiments/
2026-08-20_pfr_pbp_vs_gamebook_completeness/README.md`), and the 1978 Mel
Blount Rule changed what a "normal" pass defense play even looks like —
pre/post-1978 aren't measuring the same game, so mixing them would
contaminate the era comparison this doc is specifically asked to run.

## 2. Verifying `exp_pts_before`/`exp_pts_after` before trusting them

This was the highest-priority step, done with direct spot-checks against
known, obvious plays before writing any aggregation code — real examples
from `202309070kan` (2023 KC-DET) and a random corpus sample, not
assumptions.

**(a) Whose perspective.** Both columns are expressed in the reference
frame of **whichever team started that specific play with the ball** — the
offense for that play, not a fixed home/away or possessing-team-at-drive-
start convention. Confirmed three ways:
- A game-opening touchback: `0.000 → 0.610` — a small positive value for
  the receiving offense starting at their own ~25-35, exactly the shape a
  standard NFL EP curve predicts for that field position.
- A punt, KC (offense pre-play) punting on 4th-and-3 from their own 38:
  `-0.850 → 0.380`. The `-0.850` is the Chiefs' own EP entering a 4th-down
  decision at that spot (low but not disastrous). The `0.380` **is not**
  DET's own EP for taking over at their 9-yard line (that would be
  meaningfully negative on a standard curve) — it's the *negated* value,
  i.e. still in the punting team's (KC's) frame: "how good was this outcome
  for the team that just had the ball." This is the mechanism that makes a
  turnover attribute correctly to the defense (next point).
- An interception returned for a touchdown (Brian Branch pick-six off
  Mahomes, KC on offense pre-play): `1.030 → -7.000`. If `exp_pts_after`
  were in the *new* possessor's frame, a pick-six would show `+7.000`
  (seven points for the team that just scored). It shows `-7.000` —
  confirming the value stays in the **original, pre-play offense's frame**
  through a possession change, and a defensive/return score is recorded as
  the maximum possible penalty (-7) to the team that had the ball when the
  play started. **This is exactly what makes "value to the defense"
  computable as a single, uniform formula for every play, with no separate
  turnover-detection logic needed**: `defense_value = -(exp_pts_after -
  exp_pts_before)`, always, regardless of play type.

**(b) Continuity across a drive.** `exp_pts_before` on play N equals
`exp_pts_after` on play N-1 **exactly**, confirmed on four consecutive
same-drive plays in the sample game (1.000→1.140, 1.140→0.430,
0.430→-0.850, -0.850 continuing into the next play's before value). This
breaks in two situations, both expected and neither a semantics problem:
(1) when a drive ends in a score or turnover — the next row starts a brand
new EP computation for the new team/new field position, unrelated by
subtraction to the terminal value that closed out the prior drive (this is
correct model behavior, not a defect); (2) a small number of cases where
`pbp.csv` is simply missing a row — found one directly (a first-down
conversion between a punt-return spot and the next logged play, evidenced
by a 46-second game-clock jump with no intervening play recorded). This
matches a **known, already-documented gap** in this same PFR `pbp.csv`
source (`gamebooks_boxscores`'s memory: "PFR pbp.csv text completeness
gap" — confirmed undercounts elsewhere too). It is real but rare enough
not to bias large-sample averages meaningfully.

**(c) Scoring plays.** Confirmed across four separate touchdowns and two
field goals in the sample game: `exp_pts_after` is set to **exactly**
`7.000` for every touchdown and **exactly** `3.000` for every made field
goal, regardless of the pre-play value. The model treats a completed score
as a deterministic +7/+3, not a probability-weighted value.

**(d) Turnovers.** Covered under (a) — the pick-six example is the cleanest
possible case and it flips sign/perspective correctly, showing the full
-7.000 penalty to the team that lost the ball.

**Conclusion: the semantics are unambiguous and directly usable.** No
forced interpretation was needed — every one of the four checks the task
asked for came back clean and mutually consistent.

## 3. Method: attributing plays to event types

Reused `gamebooks_boxscores/parse_pfr_pbp.py`'s regex definitions directly
(`SACK_RE`, `TACKLE_RE`, `LOSS_TACKLE_RE`, `FF_RE`, `FR_RE`, `INT_RE`,
`PD_RE`, `SPECIAL_TEAMS_RE`) — copied inline into the new script rather
than importing the module, since that module's DB-backed player-resolution
machinery (`football_db.db`, `RosterResolver`) isn't needed here: this is
an aggregate value analysis, not a per-player attribution pass. The regex
patterns themselves are unchanged.

**Primary categories are mutually exclusive per play**, assigned by
priority `INT > sack > run stuff > FR > tackle`, matching this project's own
boxscore convention that a play lands in exactly one of these columns
(`gamebooks_boxscores/CLAUDE.md`'s Output Format / Scoring Rules — a sack
already carries its own Solo-tackle credit rather than also counting as a
plain tackle, etc.):
- **tackle** = matches `TACKLE_RE`, and is *not* also a sack/run stuff/INT play —
  i.e. genuinely the routine case the task asked for ("no other event on
  the play").
- **run stuff** = `LOSS_TACKLE_RE` (non-sack loss), excluding kick plays and sacks.
- **sack** = `SACK_RE`.
- **INT** = `INT_RE`.
- **FR** (fumble recovery) = `FR_RE`, **with one added filter**: the named
  recoverer must differ from the named fumbler (`"X fumbles ... recovered
  by Y"`, `X != Y`) — a proxy for "someone other than the original ball
  carrier recovered it," since `FR_RE` alone doesn't carry team identity
  and this analysis didn't do full roster resolution (see limitation
  below).

**Bonus categories (not mutually exclusive with the above)**: `PD` and
`FF`, computed independently over all matching plays regardless of primary
category — a forced fumble and a sack can legitimately co-occur on the same
play and both numbers should reflect that. Measured directly: **32% of
FF-tagged plays are also primary-sack plays** (6,434 of 20,074) — the
other 68% are forced fumbles on tackles, run stuffs, or returns.

## 4. Real event values

**Pooled, 1978-2025** (excluding the 1993 data gap — see §5):

| Event | n | Mean value (EP, to defense) | SE |
|---|---|---|---|
| INT | 23,530 | **+3.58** | 0.015 |
| FF (bonus) | 20,074 | +2.36 | 0.020 |
| Sack | 50,865 | **+1.75** | 0.005 |
| FR | 19,975 | +1.67 | 0.020 |
| run stuff | 60,792 | **+1.10** | 0.003 |
| PD (bonus, 1999+ only) | 51,629 | +0.82 | 0.003 |
| Tackle (routine) | 894,406 | **-0.36** | 0.001 |

A routine tackle carries a *negative* average value to the defense — this
is expected, not a bug: "routine tackle" plays are, by construction, every
play that wasn't a sack/run stuff/turnover, i.e. mostly ordinary 3-8 yard
gains that still favor the offense on average. This is the same
"not all defensive stats are equally valuable" point the wOBA analogy in
doc 04 makes: a stop that still concedes real yardage is worth less than a
stop that erases the play (run stuff) or wins the ball outright (INT/FR/sack),
and now that gap is a real, measured number instead of an assumption.

**By era** (n / mean):

| Event | 1978-1985 | 1986-1998 | 1999-2020 | 2021-2025 |
|---|---|---|---|---|
| Tackle | 117,944 / -0.246 | 210,672 / -0.269 | 453,156 / -0.415 | 112,634 / -0.431 |
| run stuff | 7,751 / 1.132 | 13,651 / 1.095 | 32,160 / 1.096 | 7,230 / 1.079 |
| Sack | 7,810 / 1.817 | 11,531 / 1.787 | 25,529 / 1.686 | 5,995 / 1.833 |
| INT | 4,419 / 3.323 | 5,958 / 3.440 | 10,951 / 3.781 | 2,202 / 3.469 |
| FR | 4,947 / 1.507 | 6,358 / 1.447 | 7,344 / 1.915 | 1,326 / 1.933 |
| PD | n/a (no data) | n/a (11 rows) | 42,215 / 0.786 | 9,403 / 0.978 |
| FF | 3,301 / 2.162 | 5,173 / 2.215 | 9,648 / 2.528 | 1,952 / 2.238 |

Full year-by-year values for tackle/run stuff/sack/INT/FR are in
`data_output/event_value_results.json` (`by_year` key) — every year 1978-
2025 individually, not just the four buckets above.

## 5. Era-drift findings — the two hypotheses, tested directly

**Recent kicking-rule era (2021-2025 vs. the rest): weak, partial support
— not the broad shift the hypothesis predicted.** Sack value is real but
modestly higher in 2021-2025 (1.833) than 1999-2020 (1.686), a ~9%
relative bump that is many standard errors outside noise (SE ≈0.01 on
each) but small in absolute EP terms (+0.15 pts). run stuff shows essentially no
shift (1.079 vs. 1.096 — statistically indistinguishable in practical
terms). Tackle drifts slightly more negative (-0.431 vs -0.415), a small
continuation of a trend that actually started decades earlier (see below),
not a new 2021-2025-specific effect. **Conclusion: the "60-65 yard FGs are
now real" hypothesis shows up faintly in sack value and nowhere else —
directionally consistent, but far too small and too narrow (one stat, not
the broad field-position effect predicted) to call confirmed.**

**Early post-Blount-rule "smoothing" (1978-1985 vs. 1986-1998): not
confirmed.** run stuff (1.132 vs 1.095), sack (1.817 vs 1.787), and INT (3.323
vs 3.440) are all close, with no directional pattern suggesting an
unsettled early period converging toward a stable later one — if anything
sack and INT are *slightly lower* in the immediate post-rule years, the
opposite of what a "still adjusting" story would predict for a rule that
made scoring easier. Tackle shows a small, real drift (-0.246 → -0.269),
but it's a fraction of the much larger jump found next, and it continues
in the same direction well past 1998. **Conclusion: the user's own prior —
"probably a very smooth value and very little difference" — holds for this
window.**

**An unhypothesized third finding, and the most substantial one in the
data: a real structural jump around 1999, concentrated in the "tackle"
baseline.** Tackle value steps from -0.255 (1998) to -0.393 (1999) in a
single season and stays in the -0.38 to -0.47 range for every year after —
a ~0.15-point shift, roughly 7x the standard error, not a gradual drift.
This coincides exactly with two independently-confirmed facts: (1) `PD`
annotation ("defended by X" in the detail text) is essentially **absent
from `pbp.csv` before 1999** (0 matches in 1978-1998 except 11 stray rows
in 1994; 2,031 matches in 1999) — confirmed directly by grepping the raw
text; (2) this matches a data-completeness boundary already documented
elsewhere in this project (`parse_pfr_pbp.py`'s own docstring: "blank run stuff
pre-1999" in PFR's `player_defense.csv`). **This reads as a PFR
scrape/text-vintage boundary — a change in how much detail PFR's own
source recorded starting in 1999 — not a football rule change** (there was
none in 1999). Flagging this explicitly for whoever next touches this
data: **any PD-based analysis must exclude 1978-1998 entirely** (not
"treat as zero" — treat as missing), and any full-corpus tackle-value
trend line should note the 1999 boundary rather than reading it as smooth
drift.

**A secondary, smaller unexplained dip**, noted but not chased further per
scope: sack and run stuff values both dip noticeably in 2013-2015 (sack as low as
1.456 in 2014, vs. ~1.7-1.9 in surrounding years) before recovering by
2018. The dip is real (many SEs beyond noise) but its cause wasn't
investigated — worth a look if a future pass revisits this era specifically.

## 6. A known limitation in the FR number

The FR proxy (recoverer's name ≠ fumbler's name) is a heuristic, not true
team resolution — it doesn't verify the recoverer is actually on the
defense. A sample of raw fumble text found real cases where a *teammate*
of the fumbler recovers (e.g. a punt-team player recovering their own
returner's muff), which this heuristic would misclassify as a defensive
takeaway. This likely explains why FR's measured value (1.67 pooled) comes
in well below Burke's ~4-point estimate for fumbles generally (§7) — some
genuinely low-value, non-turnover recoveries are almost certainly diluting
the average downward. **Recommendation: before this FR number is used in
the weight re-derivation, redo it with `parse_pfr_pbp.py`'s actual
`RosterResolver` (team-based, not name-heuristic) to isolate true
defensive takeaways.** INT, sack, and run stuff don't have this problem — their
regex matches are inherently defense-only.

## 7. Cross-validation against published estimates

Brian Burke's Advanced Football Analytics (via web search, not blocking on
availability per the task's own instruction):
- **Sack ≈ 2.0 EP** (Burke's own methodology: average EP after a sack vs.
  average EP in comparable non-sack situations). This project's own
  directly-measured before/after swing: **1.75**, same order of magnitude,
  modestly lower — plausibly because Burke's comparison baseline differs
  from a strict single-play before/after swing.
- **Interception ≈ 3.8-4.0 EP.** This project's own measurement: **3.58**
  — close agreement, same order of magnitude, slightly conservative.
- **Fumble (general) ≈ 4+ EP.** This project's FR proxy: **1.67** — the
  clear outlier vs. published estimates, consistent with the known
  proxy-heuristic dilution described in §6, not a semantics problem with
  the underlying `exp_pts` data itself (INT/sack agree well using the same
  data and method).

Sources: [The Value of a Sack](https://www.advancedfootballanalytics.com/2008/11/value-of-sack.html?m=1), [Expected Point Values](http://www.advancedfootballanalytics.com/2009/12/expected-point-values.html)

## 8. Data coverage note

**1993 is a complete gap**: every game that season has blank
`exp_pts_before`/`exp_pts_after` for every play (confirmed: 0 valid rows
across 233 games, vs. tens of thousands in every adjacent season). This
looks like a genuine hole in PFR's own source data for that one season,
not a parsing bug in this analysis — every other season 1978-2025 has
substantial, consistent coverage (17,000-26,000+ classified plays/year).
1993 simply contributes nothing to any pooled or era number above; no
other year required exclusion.

## 9. Bottom line for the weight re-derivation

Real, directly-measured event values, ranked: **INT > FF > sack ≈ FR >
run stuff > PD > tackle**. The values are broadly stable across 1978-2025 — the
two specific hypotheses this doc was asked to test (recent kicking-range
effect, early post-Blount-rule smoothing) both come back small-to-null,
matching the user's own "probably very smooth" expectation — but the
unhypothesized 1999 data-vintage boundary is real and should be respected
in any downstream analysis that touches PD or the raw tackle-value trend.
Note directly for whoever picks up doc 04's weight re-derivation: **pure
event value ranks sack above run stuff** (1.75 vs 1.10) here, the opposite
ordering from the user's skill-based DL-vs-LB argument in doc 04 — that's
not a contradiction to resolve in this doc. Per this session's own
wOBA/reliability framing, value and skill-attributability are separate
axes; doc 04's weight formula needs to combine this value number with the
φ-based skill measurement deliberately, not read this ranking alone as a
verdict on which stat should be weighted higher.
