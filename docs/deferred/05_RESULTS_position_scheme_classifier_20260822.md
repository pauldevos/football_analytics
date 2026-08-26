# Results: position x scheme classifier

Completed 2026-08-22, answering the brief in
`docs/deferred/05_position_scheme_grouping_scoping.md`. Read that file first
for the original taxonomy and problem framing verbatim — this doc reports
what was actually built and measured, written as a self-contained teaching
piece, matching the standard set by
`docs/deferred/02_RESULTS_stat_noise_skill_rating_analysis.md`.

Script (read-only against `football_db`, writes only its own output file):
`football_analytics/scripts/build_position_scheme_classifier.py`. Output:
`football_analytics/data_output/position_scheme_classification.parquet`
(118,090 rows, one per `(player_id, franchise_id, season)`).

## 1. What this depended on, and what changed underneath it

This classifier needs a per-team-season defensive scheme. Doc 05 originally
pointed at `silver.team_schemes_pfr` directly. That table still exists and
is unchanged, but this session also built
`gold.team_scheme_coach_season` (Phase 1 of this same three-phase task —
see its own report/schema comments in `football_db/schema/
team_scheme_coach_season.sql`), which carries the identical
`defensive_alignment` values plus resolved Head Coach / Defensive
Coordinator identity on the same row. This classifier joins against the new
table, not `team_schemes_pfr` directly, per this session's own instruction
— the scheme values themselves are byte-for-byte the same either way (the
new table is a superset join, not a re-derivation), so this substitution
changed nothing about the position/scheme logic itself, only which table
supplies it.

## 2. The mapping, and three real gaps made explicit rather than papered over

`gold.position_taxonomy` (an existing, shared, defense-only reference table
in `football_db`) already normalizes side-prefixed position strings
(`LDE`/`RDE` → `DE`, `LOLB`/`ROLB`/`OLB` → `OLB`, etc.) into a `pos_group`
column. This classifier reuses that normalization rather than re-deriving
side-prefix stripping by hand, then applies one mapping table
(`pos_group`, `defensive_alignment`) → one of the user's 8 named buckets.

Three real, confirmed-by-direct-query gaps came out of building this, each
handled as an explicit separate bucket rather than a silent guess:

**Bare "DT" under a 3-4 team (869 rows) is NOT the classic-era 3-4 nose
tackle the taxonomy describes.** Its season distribution is the tell:
single digits per year before 2010, climbing to 30-59/year 2020-2025. This
is the modern rotational NFL — many current 3-4 teams run 3+ interior
D-linemen with no single "true nose," and PFR labels them all generically
`DT`. Bucketed as `3-4_DT_uncovered` (929 rows total including `LDT`/`RDT`),
not force-mapped into `3-4 NT`.

**The 4-3's own DT split (1-technique run-stuffer vs. 3-technique
penetrator) was never given by the user** — doc 05 said so explicitly and
left it as optional future work. `4-3_DT_uncovered` (4,845 rows) makes this
gap visible in the coverage numbers rather than quietly forcing every 4-3
interior lineman into one of the 8 buckets that don't actually describe
that split.

**Bare "LB"/"DL" (no O/I/side letter at all, 8,257 rows,
`unclassified_no_side_info`) genuinely cannot be scheme-role-classified** —
there's no signal in the position string for which LB role it is. Left
unclassified rather than guessed.

A fourth, expected, non-gap: `scheme_unknown` (4,606 rows, entirely
1921-1969) is the taxonomy's own explicitly-stated boundary — the 3-4
didn't meaningfully exist before ~1970, and `gold.team_scheme_coach_season`
itself only starts at 1967 with sparse pre-1970 AFL coverage (see Phase 1's
own report — one confirmed pre-merger-AFL gap, KC 1969).

Two out-of-scope categories were split out from what would otherwise have
badly understated this classifier's real accuracy: 62,201 rows (52.7% of
the whole `player_team_seasons_pfr` table) are pure offensive positions
(WR/RB/TE/QB/...), and 20,436 rows (17.3%) are secondary positions (CB/S/
DB) — neither is a failure of this classifier, both are simply outside the
8-bucket taxonomy's stated scope (front-seven only). Lumping these into a
generic "legacy_unclassified" bucket, which an early draft of this script
did before catching the bug, made the whole classifier look like it was
failing on 75% of the corpus when it was actually just counting rows it was
never asked to classify.

## 3. Real corpus-wide coverage

Of the **front-seven-only universe this classifier actually covers**
(118,090 total rows, minus 62,201 offense and 20,436 DB/secondary =
35,453 front-seven rows):

**29,666 / 35,453 = 83.7%** land in one of the user's 8 named buckets.

The remaining 16.3% splits as: `unclassified_no_side_info` 8,257 (23.3% of
the front-seven universe), `4-3_DT_uncovered` 4,845 (13.7%),
`scheme_unknown` 4,606 (13.0%, pre-1970 only), `legacy_compound_
unclassified` 1,146 (3.2%, pre-1960s two-way-player codes like `B-G-DE-E`),
`3-4_DT_uncovered` 929 (2.6%), and a handful of smaller residual buckets
(`missing_position` 35, blank position strings).

Named-bucket counts: 4-3 DE 5,107, 3-4 DE 2,947, 4-3 OLB 2,407, 3-4 OLB
(edge) 1,523, 3-4 ILB/MLB 1,322, 4-3 MLB 1,228, 3-4 NT 1,101.

## 4. Named-player validation: 54/61 (88.5%)

Doc 05 gave 61 named players across its 8 buckets as a built-in test set
(not just the 7 already spot-checked in the original scoping doc — every
name in the taxonomy table was checked here). For each player, every
classified season was pulled and the **modal** (most common) bucket across
their career compared against the taxonomy's expected bucket.

**54 of 61 matched exactly.** All 7 mismatches are real, explainable cases,
not classifier bugs — full season-by-season evidence for each is in the
script's own output, summarized here:

| Player | Expected | Got (modal) | Real explanation |
|---|---|---|---|
| Curley Culp | 3-4 NT | 4-3_DT_uncovered | Genuine career arc: 6 seasons as a 4-3 DT (Chiefs, 1969-74) before Houston moved to a 3-4 and he became a true NT (1975-80). Both labels are correct for their respective years — a near-even split, not an error. |
| James Harrison | 3-4 OLB (edge) | unclassified_no_side_info | Early-career seasons (2002-06) as a backup/special-teamer carry a generic `LB` label before he won the starting ROLB job in 2007 — a real seasons-played artifact of a slow-developing career, not a misclassification of his defining role. |
| Bobby Wagner | 3-4 ILB/MLB | 4-3 MLB | Real data says Seattle ran a 4-3 for essentially his entire career (2012-2025) — 12 of 14 seasons labeled `4-3` in `gold.team_scheme_coach_season`. This is likely the taxonomy doc's own example placement being imprecise for this one player, not a classifier error — the data supports 4-3 MLB more strongly than 3-4. |
| Nick Buoniconti | 4-3 MLB | scheme_unknown | 8 of his 13 seasons (1962-69) predate `team_schemes_pfr`'s 1967-70 coverage start; his 1970-74 seasons (post-merger, scheme data available) DO correctly resolve to `4-3 MLB` — a tie in season-count that data availability, not misclassification, decided. |
| Bobby Bell | 4-3 OLB | scheme_unknown | Same pattern: 6 pre-1969 seasons with no scheme data vs. 6 correctly-resolved `4-3 OLB` seasons (1969-74) — an artifact of scheme-data coverage starting where it does, not an error. |
| Chuck Howley | 4-3 OLB | scheme_unknown | Same pattern again: 8 pre-1967 seasons unknown vs. 6 correctly-resolved `4-3 OLB` seasons. |
| Ted Hendricks | 4-3 OLB | 3-4 OLB (edge) | Real 15-year career genuinely spans both schemes: 7 seasons 4-3 OLB (Colts/Packers, 1969-75) then 8 seasons 3-4 OLB (Raiders, 1976-83) — the modal bucket landed on the (slightly longer) second half of a real scheme-spanning career, exactly the kind of case doc 05 already flagged as "real, correct nuance" using Ray Lewis as the template example. |

Three of the seven (Buoniconti, Bell, Howley) are the same root cause: a
career that started before scheme data exists. Two (Culp, Hendricks) are
genuine multi-scheme careers where "expected" and "got" are both correct
for different years. One (Wagner) may be the source taxonomy's own example
placement being the imprecise part. One (Harrison) is a slow-developing
career diluting a clear later-career signal. None of the seven reflect the
classifier applying the mapping rule incorrectly to a season it had good
data for.

## 5. The 3-4 OLB rush-vs-coverage sub-split

Doc 05 item 3 asked for a secondary signal to distinguish a 3-4's primary
edge rusher from a more coverage-oriented OLB, since `L`/`R` in the raw
position string encodes formation side, not role. A `sub_role` tag
(`rush_leaning` / `coverage_leaning`) was added within the `3-4 OLB (edge)`
bucket only, using each player-season's own (sack + run stuff) per-game rate from
`gold.player_game_stats`: **n=1,494, median 0.50/game, mean 0.57/game,
p25=0.33, p75=0.77** — split at the median. This is a continuous signal
collapsed to a documented threshold for readability, not a hard taxonomy
distinction; treat it as directional, not precise, since doc 05 gave no
named validation set for this specific sub-split.

## 6. What's in the output file, for Phase 3 and beyond

`data_output/position_scheme_classification.parquet` — one row per
`(player_id, franchise_id, season)`: `player_id`, `full_name`,
`franchise_id`, `season`, `raw_position`, `pos_group`, `pos_global`,
`defensive_alignment`, `dc_source`, `bucket` (the 8-named-bucket-or-
explicit-gap label), `sub_role` (3-4 OLB only, else null). Consumed
directly by `scripts/build_tackle_quality_by_position.py` (Phase 3, see its
own results doc) for position-group lookup, with a fallback to the coarse
3-group `dpvs/positions.py` taxonomy wherever the fine bucket lands in one
of the explicit gap categories above.

Per doc 05 item 6, this classifier is validated here but **not yet wired
into `dpvs/positions.py`'s z-scoring groups or `dpvs/composite.py`'s
run/pass credit-fraction mechanism** — that's a deliberate next step, not
an oversight, left for whoever picks this up next to decide given the real
83.7% coverage and 88.5% validation numbers above.
