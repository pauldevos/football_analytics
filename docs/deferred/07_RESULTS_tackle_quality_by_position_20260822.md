# Results: tackle quality by position — yards gained per tackle

Completed 2026-08-22, answering the brief in
`docs/deferred/07_tackle_quality_by_position.md`. Read that file first for
the original problem framing and the user's hypothesized ranges verbatim —
this doc reports what was actually measured, with real numbers, written as
a self-contained teaching piece, matching the standard set by
`docs/deferred/02_RESULTS_stat_noise_skill_rating_analysis.md`.

Script: `football_analytics/scripts/build_tackle_quality_by_position.py`.
Raw per-tackle events: `data_output/tackle_quality_events.parquet` (762,220
rows). Summary: `data_output/tackle_quality_by_position_results.json`.

## 1. The question, restated

Is a defensive tackle a fixed-value unit regardless of who made it and
where? The user's hypothesis, in three parts: a Safety's tackles happen
much further downfield (8-30yd, ~13yd average) than a Linebacker's (-3 to
12yd, ~6yd) which happen further downfield than a Defensive Lineman's (-3
to 5yd, ~3yd) — because each position's distance from the line of
scrimmage at the snap directly shapes how much yardage has typically
already been given up by the time they make the stop.

## 2. Data and method

**Source**: PFR's own `pbp.csv` play-by-play text,
`~/data/pfref/raw/boxscores/{year}/{game}/pbp.csv`, **1978-2025 only**.
1967-1977 was excluded — that era has no PFR pbp.csv at all (confirmed in
doc 03's own data-feasibility notes), only gamebooks_boxscores' OCR-derived
prose, which lacks both a structured yards-gained field and the documented
completeness this analysis needs
(`gamebooks_boxscores/docs/experiments/2026-08-20_pfr_pbp_vs_gamebook_
completeness/README.md`). Scoping to 1978-2025 is the more defensible of
the two choices doc 07 offered, stated explicitly rather than silently
dropping the earlier era.

**Per-play extraction**: for every play, yards-gained and tackler name(s)
are read directly off one anchored pattern —
`for (-?\d+) yards? \(tackle by NAME(?: and NAME2)? ?\)` — rather than
taking the first number anywhere in the line, so a penalty yardage or
unrelated number elsewhere in the text can't be mistaken for the play's own
result. **Sack plays are excluded entirely** (a different kind of event,
already scored elsewhere in this project's own convention) and so are
**special-teams plays** (kickoffs/punts/FG/XP — tackles there belong to
gamebooks_boxscores' own separate "Special Teams" bucket by this project's
established convention, not the main tackle table).

**Multi-tackler plays**: both a solo and an assisting tackler are credited
with the SAME play's yards-gained value, not a split. Yards-gained is a
fact about the play (where it ended relative to where it started), not
something to divide between two people — documented explicitly per doc
07's own request rather than defaulting silently.

**Tackler identity**: resolved via `gamebooks_boxscores/parse_pfr_pbp.py`'s
own `RosterResolver` + PFR-`player_id` cross-reference machinery, reused
directly (not re-derived) — the same reasoning
`ingest_pfr_defensive_stats.py` already applied to this exact resolution
problem. Always resolved to `player_id`, never bare name text, per doc 05's
explicit warning about name-collision risk (Ted Washington etc.).

**Position group**: from Phase 2's classifier output
(`data_output/position_scheme_classification.parquet`), joined by
`(player_id, season)`. Two levels: a **coarse S/LB/DL group** (the
grouping the hypothesis itself is stated in) for the primary test, and the
**fine scheme-aware buckets** (3-4 NT, 4-3 DE, etc.) as a secondary
breakdown, per doc 07 item 2's "ideally scheme-aware" request. Where the
fine bucket lands in one of Phase 2's explicit gap categories (e.g.
`4-3_DT_uncovered`), a fallback to the coarse `dpvs/positions.py`-style
DL/LB/S grouping is used instead of dropping the row — this fallback is
why the coarse-group `n` (762,220 total) is larger than the sum of the
"n≥200" fine-bucket table in §4 (fine buckets below that threshold, plus
rows that only resolved at the coarse level, aren't shown there but ARE in
the coarse totals).

**Coverage**: 846,424 non-sack, non-special-teams tackle plays found across
12,127 games; 762,220 (90.1%) resolved to a known player_id AND a
position group in scope. The 9.9% drop is unresolved names (rare surnames/
OCR-adjacent PFR text issues) plus players whose position falls outside
this analysis's scope entirely (CB, since only S/LB/DL were given
hypotheses to test).

## 3. Results: the primary hypothesis test

| Group | n | Mean | Median | p10 | p25 | p75 | p90 | Hypothesized range | Hyp. mean | % in hypothesized range | Hyp: >80% in range |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DL | 211,207 | **+2.99** | +3.0 | -1 | +1 | +4 | +7 | -3 to 5 | ~3 | **81.7%** | met |
| LB | 354,904 | **+5.36** | +4.0 | +1 | +2 | +7 | +12 | -3 to 12 | ~6 | **90.2%** | met |
| S | 196,109 | **+10.30** | +8.0 | +2 | +4 | +14 | +21 | 8 to 30 | ~13 | **50.7%** | **not met** |

## 4. Verdict, honestly: two hypotheses hold up well, one only partially

**The core ordering claim is strongly confirmed**: DL tackles happen
closest to the line (mean +2.99yd), LB tackles happen further downfield
(mean +5.36yd), Safety tackles happen furthest downfield of all (mean
+10.30yd). This ordering holds cleanly across the full 762,220-event,
48-season corpus, not just a handful of games.

**DL matches the specific hypothesis almost exactly**: real mean 2.99yd
vs. hypothesized ~3yd, and 81.7% of DL tackles fall in the hypothesized -3
to 5yd range (hypothesis: >80%) — this one number came back essentially
exactly as estimated.

**LB matches well, on the strong side**: real mean 5.36yd vs. hypothesized
~6yd (close, slightly lower), and 90.2% of LB tackles fall in the
hypothesized -3 to 12yd range — comfortably clearing the user's own >80%
bar.

**Safety does NOT match as specifically stated.** The real mean (10.30yd)
is meaningfully lower than the hypothesized ~13yd, and only 50.7% of
Safety tackles fall in the hypothesized 8-30yd range — far short of the
>80% bar the user set. The reason is visible directly in the distribution:
**42.1% of all Safety tackles happen in the 0-7yd range**, well below the
hypothesized floor of 8yd (only 3.8% are behind the line, and just 3.3% go
beyond 30yd — the hypothesized range isn't missing the tail, it's missing
a huge chunk of the middle-short end). This makes real football sense once
you consider the full range of what a "Safety tackle" actually is in this
era's game: not just a last-line-of-defense stop on a broken long play, but
also routine run-support tackles in the box, tackles on short/quick
completions (screens, hitches) where a safety rotates down, and blitz
tackles — all of which land much closer to the LOS than the "safety
cleaning up a big play" mental model the hypothesis was built on. The
directional intuition (safeties tackle furthest downfield of the three
groups) is real and clearly confirmed by the data; the specific numeric
claim about WHERE most of those tackles cluster was too narrow.

## 5. A candidate tackle-quality weighting, from the real numbers

Doc 07 item 4 asked for a concrete weighting proposal from the real data,
connecting to `docs/deferred/04_idi_weight_revisit.md` (which currently
treats every tackle as equal within `tackle_share_z`/`tackle_component_z`).

A simple, position-agnostic-by-formula weight was tested directly against
this corpus:

```
quality_weight(yards_gained) = clip(1 - yards_gained / 15, -0.5, 1.5)
```

i.e. a tackle for a loss earns up to +50% credit, a tackle right at the
line earns roughly neutral credit, and a tackle after a 15+ yard gain
trails off toward a -0.5 floor (so one enormous broken play doesn't swing
a season total wildly). **The formula itself never mentions position** —
it's purely a function of the play's own yards-gained — and yet, applied
to the real 762,220-event corpus, it naturally separates the three groups
in exactly the direction the raw yards-gained numbers above would predict:

| Group | Mean quality_weight | Median | Std |
|---|---|---|---|
| DL | **0.80** | 0.80 | 0.24 |
| LB | **0.65** | 0.73 | 0.33 |
| S | **0.36** | 0.47 | 0.45 |

This is the useful property doc 07 asked for: the weighting doesn't
hard-code "give DL more credit than Safeties" as a blunt per-position
multiplier — it re-derives that ordering from the real, measured
distribution of what each position's tackles actually look like, and it
would automatically adapt if a future era or team's data shifted those
distributions (e.g. a scheme that used safeties much more aggressively in
the box). The specific constants here (`15`, `-0.5`/`1.5` clip bounds) are
a first-pass, round-number choice, not fit/optimized — a natural next step
for whoever picks up doc 04 is deciding whether `15` (roughly the p90ish
region across all three groups) is the right scale, or whether it should
be tuned against the same skill/noise (φ) methodology
`docs/deferred/02_RESULTS_stat_noise_skill_rating_analysis.md` already
built, to check whether this weighted version of tackle volume is a
*more* skill-driven signal than raw tackle count, not just a
face-plausible reweighting.

## 6. Secondary breakdown: fine scheme-aware buckets

Using Phase 2's classifier (buckets with n≥200 shown):

| Bucket | n | Mean | Median |
|---|---|---|---|
| 3-4 NT | 20,394 | +2.86 | +3.0 |
| 3-4_DT_uncovered | 9,602 | +2.98 | +3.0 |
| 4-3_DT_uncovered | 66,863 | +2.80 | +2.0 |
| 4-3 DE | 65,478 | +3.19 | +3.0 |
| 3-4 DE | 44,864 | +3.05 | +3.0 |
| 3-4 OLB (edge) | 50,128 | +4.62 | +4.0 |
| 4-3 MLB | 67,626 | +5.38 | +4.0 |
| 3-4 ILB/MLB | 81,251 | +5.39 | +4.0 |
| 4-3 OLB | 99,052 | +5.52 | +4.0 |

Worth noting: all four interior-line buckets (3-4 NT, both DT-uncovered
buckets, and both DE buckets) cluster tightly together (2.80-3.19yd mean)
— scheme doesn't meaningfully change where a defensive lineman's tackles
happen, which makes sense given they're all still playing at or near the
LOS regardless of front. The LB-family buckets show more spread (4.62 for
3-4 edge OLBs — the group with the most pass-rush-oriented sub-role tag
from Phase 2 — up to 5.52 for 4-3 OLB), consistent with 4-3 OLBs' heavier
coverage/run-support responsibilities per doc 05's own taxonomy (50%
run defense + 30% coverage vs. 3-4 OLB's 80% pass rush) putting them
further from the LOS on the plays where they do make a tackle.

## 7. Known caveats

- This is 1978-2025 only (see §2) — the 1967-1977 gamebooks-era games are
  not part of this analysis at all, a scoping decision, not an oversight.
- pbp.csv's own known text-completeness gaps (undercounted sacks/tackles,
  documented in `gamebooks_boxscores/docs/experiments/2026-08-20_
  pfr_pbp_vs_gamebook_completeness/README.md`) apply here too — this
  analysis inherits whatever undercount exists in that source, though
  there's no reason to expect it to bias the yards-gained-per-tackle
  *distribution* the same way it might bias raw tackle *counts* (a missed
  tackle mention just means one fewer data point, not a systematically
  wrong yardage value for the ones that WERE captured).
- The quality_weight formula in §5 is a first-pass proposal with
  round-number constants, explicitly flagged as needing further tuning
  before being treated as production-ready for doc 04.
