# Deferred work: EPA (Expected Points Added) model from play-by-play

Paste this whole file as the prompt to a fresh session to pick up this work.
It is intentionally self-contained — do not assume the new session has any
memory of the conversation this was extracted from. This is the largest,
most uncertain, and most independent of the several DPVS-G follow-on items
identified this session — treat it as its own standalone project, not a
quick add-on.

## The problem

Every defensive-value metric built so far in this project (TCS, IDI, DPVS-G)
measures *credit for events* (a tackle, a run stuff, a sack) without measuring
*how much those events actually mattered* to the game's outcome. A run stuff for
-3 yards on 1st-and-10 at your own 35 is a very different play than the same
run stuff on 1st-and-10 at the opponent's 20 — the second one costs the offense
much more expected value, because it happened much closer to a score. The
project doesn't currently distinguish these.

**EPA (Expected Points Added)** is the standard way the analytics world
solves this: build an expected-points model — for any (down, distance,
yard line) state, what's the expected point value of that drive continuing
from here (accounting for it ending in a TD, FG, punt, turnover, etc.)?
Then a play's EPA = expected_points(state after the play) −
expected_points(state before the play). A defensive player's contribution
to a play can be credited with (some share of) that EPA swing.

**Concrete example the user gave**: 1st-and-10 at your own 35 (65 yards to
the end zone). A defender records a run stuff for -3, making it 2nd-and-13 at the
32. If the pre-play expected value of that drive was 2.33 points and the
post-play value is 2.25, that run stuff is worth roughly −0.08 EPA (from the
offense's perspective; +0.08 defensively). The same run stuff near the goal line
— 1st-and-10 at the opponent's 20, pre-play expected value maybe 5.82,
post-play maybe 5.22 after the same -3 yard run stuff — would be worth roughly
0.60 EPA, a much bigger defensive contribution for an outwardly identical
play (same down/distance/yards-lost). This is the whole point: raw stat
counting can't distinguish these two plays, EPA can.

## What's uncertain / why this wasn't started this session

The user was explicit about the real risks here, stated verbatim:
- **PBP quality/completeness is the foundation and it's shaky.** For
  1967-1977 this project only has Mistral-OCR-derived play-by-play text
  (not independently verified at the level PFR's own play text is), and
  this session's own investigations found PFR's `pbp.csv` text itself has
  real completeness gaps for later eras too (see
  `gamebooks_boxscores/docs/experiments/2026-08-20_pfr_pbp_vs_gamebook_
  completeness/README.md` — confirmed undercounts on sacks and tackles,
  scrambled tackler name order). An EPA model built on incomplete/uncertain
  PBP inherits all of that uncertainty, possibly amplified (EPA is a
  derived, compounding calculation, not a direct count).
- **Attribution ambiguity is worse for EPA than for simple stat credit.**
  A sack's EPA swing is real, but crediting 100% of it to the pass rusher
  who recorded the sack ignores that teammates (coverage holding up long
  enough for the sack, an interior lineman drawing a double-team) may have
  meaningfully contributed. This project's own coach-values research
  (referenced elsewhere in `docs/framework_decisions.md`) found NFL
  coordinators themselves use the term "coverage sacks" informally for
  exactly this reason — a sack often reflects the secondary's work more
  than the pass rusher's. A naive full-credit EPA attribution would
  mis-state defensive value in a very specific, well-understood way.
- **It's a lot of new engineering**, and this session deliberately did NOT
  attempt it with a reasoning-model-driven boxscore pass, out of concern
  that mixing "read the OCR / resolve names" work with "do EPA-style
  numerical reasoning" in the same pass would degrade the boxscore
  aggregation work that's this whole project's core deliverable. Keep
  these separated in whatever approach a future session takes — EPA should
  be built as its own numerical pipeline against clean, already-extracted
  PBP data, not folded into the boxscore-extraction reasoning pass itself.

## What to build (if a future session takes this on)

1. **An expected-points model itself**, fit from historical PBP data:
   `E[points on this drive | down, distance, yard_line]` (and possibly
   `| score_differential, quarter, time_remaining` if game-script control
   is wanted — see `gamebooks_boxscores/docs/research/deferred/
   run_defense_srs_prompt.md`, a separate deferred item in a different
   repo about game-script confounds in raw rush-defense stats, for
   related methodology on score/quarter bucketing that might be reusable
   here). This needs enough clean PBP volume to fit reliably — scope
   started years by what data quality actually supports (1999+ almost
   certainly first, since that's this project's highest-confidence PBP
   era; extend backward only as far as PBP completeness genuinely allows,
   likely NOT into the 1967-77 gamebooks-OCR era without a lot more
   validation work first).
2. **Per-play EPA computation**: for every play in the fitted range, EPA =
   E[post-play state] − E[pre-play state], handling scoring plays,
   turnovers, and drive-ending events (punt, missed FG) as absorbing
   states with known point values.
3. **A defensive-credit attribution scheme** that explicitly accounts for
   the "coverage sack" problem above rather than ignoring it — e.g. a
   partial-credit split between the recorded event-maker and context
   (down/distance trend over the drive, or explicit teammate involvement
   where PBP text supports it) rather than 100%-to-one-player. This is
   the single hardest design decision in this whole doc — don't rush it,
   and validate against known cases (e.g. a QB coverage sack where PBP
   text or other sources make the "the secondary actually won this play"
   read obvious) before trusting it at scale.
4. **Validation**: compare EPA-based player rankings against IDI/DPVS-G's
   existing event-count-based rankings for the same players/seasons — do
   they agree directionally? Where they disagree sharply, is it explainable
   (e.g. a player who racks up garbage-time stats scores well on IDI but
   poorly on EPA)? This cross-check is itself a valuable finding regardless
   of whether EPA becomes a permanent addition to the project.

## Context this depends on (read before starting)

- `gamebooks_boxscores/docs/pbp_verb_reference.md` — verb/stat-type mapping
  for PBP text, useful for any new PBP parsing this needs.
- `gamebooks_boxscores/docs/experiments/2026-08-20_pfr_pbp_vs_gamebook_
  completeness/README.md` — the known PBP quality gaps to design around,
  not ignore.
- `football_analytics/docs/framework_decisions.md` — search for "coverage
  sack" / coach-values research for the full context on why sack
  attribution specifically needs care.
- Whatever raw PBP source(s) are richest/cleanest for the target era — check
  `~/data/pfref/raw/boxscores/{year}/{game}/pbp.csv` (has running score,
  down/distance/yard-line per play, confirmed present 1978-2025) before
  assuming any particular season range is feasible; the score-column
  semantics (before vs. after the play) need verification before trusting
  any down/distance bucketing built on them — this exact caveat is already
  flagged in the separate run-defense deferred-work doc referenced above.

## Suggested scope for a first pass

Given the size and risk here, a first pass should probably NOT try to solve
attribution and go straight to a full defensive value metric. A more
tractable first deliverable: build the expected-points model and per-play
EPA computation only, for a single well-covered era (1999+ most likely),
and report team-defense-level EPA-allowed as a validation step (much lower
attribution risk than player-level credit) before attempting any
individual-player crediting at all.
