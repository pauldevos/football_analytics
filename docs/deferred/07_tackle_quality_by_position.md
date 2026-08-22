# Deferred work: tackle quality by position — yards gained per tackle

Paste this whole file as the prompt to a fresh session to pick up this work.
It is intentionally self-contained — do not assume the new session has any
memory of the conversation this was extracted from. This is a lighter,
much more tractable precursor to `docs/deferred/03_epa_pbp_value_model.md`
— it tests a real, sharp hypothesis with existing data, without needing a
full expected-points model first.

## The problem

Every defensive-value metric in this project (TCS, IDI) currently treats
"a tackle" as a fixed-value unit regardless of who made it or where on the
field. The user's direct challenge to that assumption, given with real
football reasoning:

> "Not all tackles are equal. For instance, a SS or FS who gets 80 tackles
> vs a MLB who gets 80 tackles and a DL who gets 80 tackles will have a
> very different quality of defense in terms of yards per play allowed.
> And that is a virtue of the position they play on the field relative to
> the line of scrimmage."

The reasoning, position by position (the user's own estimates, framed as
hypotheses to test, not established facts):
- **Safeties (SS/FS)** typically play 15-25 yards off the ball. When a
  safety makes a tackle, it's usually because the play has already gained
  significant yardage and they're converging from depth — the user's
  estimate: >80% of a safety's tackles come on plays that gained roughly
  8-30 yards, averaging perhaps ~13 yards.
- **Linebackers** play closer to the box. Estimate: >80% of a linebacker's
  tackles occur in the -3 to +12 yard range, averaging perhaps ~6 yards.
- **Defensive tackles/linemen** are already at the line of scrimmage.
  Estimate: >80% of a DL's tackles occur in the -3 to +5 yard range,
  averaging perhaps ~3 yards.

The implication: a defensive tackle racking up 80 tackles is a much
stronger signal of individual run-stopping dominance (winning at the point
of attack, consistent with what the coach-values research earlier this
session found — "pressure/disruption causes bad plays for the offense" was
the dominant theme, not raw volume) than a safety racking up 80 tackles,
which more often reflects "the defense as a whole allowed a big play and
this player cleaned it up," a very different kind of contribution.

## Why this is more tractable than full EPA (Doc 03)

Doc 03 (the full EPA/expected-points model) requires fitting an entire
expected-points-by-game-state model and handling all the attribution
complexity of crediting a value swing to specific players. **This
hypothesis needs much less**: just the yards gained on the play a tackle
occurred on, and the position of the tackler. That's a direct aggregation
over existing per-play data, not a new statistical model. This is a good,
fast way to get real evidence on "does tackle location/depth matter"
before committing to the bigger EPA project — and its output (yards-
gained-per-tackle by position) is itself useful as a tackle-quality
weighting input to IDI, independent of whether the fuller EPA project ever
happens.

## What to build

1. **Per-tackle yards-gained**, joined to the tackler's position, for
   every game/era where this is derivable from existing PBP data:
   `~/data/pfref/raw/boxscores/{year}/{game}/pbp.csv` has play-level detail
   including yards gained — confirmed present for 1978-2025 (see
   `docs/deferred/03_epa_pbp_value_model.md`'s data-feasibility notes,
   which this task should reuse rather than re-derive). For 1967-1977,
   `gamebooks_boxscores`' own PBP-derived data could be used but carries
   the documented completeness caveats (`gamebooks_boxscores/docs/
   experiments/2026-08-20_pfr_pbp_vs_gamebook_completeness/README.md`) —
   decide whether to include this era at reduced confidence or scope this
   analysis to 1978+ only where the PBP source is more reliable; either
   choice is defensible, just state which was made and why.
2. **Aggregate to a real distribution per position** (not just a mean —
   the user's own framing is a full distribution: ">80% of tackles fall in
   this range, averaging about this many yards"). Report:
   - Mean and median yards-gained-per-tackle
   - The actual percentage falling in the ranges the user hypothesized
     (safety: 8-30yd, LB: -3 to 12yd, DL: -3 to 5yd) — test the specific
     numbers given, don't just eyeball a rough distribution
   - Break out by the SAME position groups `docs/deferred/
     05_position_scheme_grouping_scoping.md` establishes if that work has
     landed by the time this runs (ideally scheme-aware — a 3-4 NT
     tackling at the LOS should look different from a coverage safety
     regardless of grouping scheme); fall back to the current coarse
     3-group `dpvs/positions.py` taxonomy otherwise.
3. **Test the hypothesis directly, honestly** — does the data actually
   support "DL tackles happen closer to the LOS, on average, than LB
   tackles, which happen closer to the LOS than safety tackles"? Report
   the real numbers whether or not they match the user's estimates exactly
   — the goal is calibrating real numbers to replace the estimates, not
   confirming them.
4. **Propose a concrete tackle-quality weighting** based on the real
   numbers found — e.g. a yards-gained-adjusted tackle credit (a tackle
   for a 2-yard gain counts differently than a tackle for a 20-yard gain),
   possibly normalized/scaled per position group so it doesn't just
   re-derive "give DL more credit" as a blunt instrument but actually
   reflects the real distribution of play outcomes each position's tackles
   represent. This connects directly to `docs/deferred/
   04_idi_weight_revisit.md` (which currently treats all tackles as equal
   within `tackle_share_z`/`tackle_component_z`) — flag this as a
   candidate refinement for that work once real numbers exist here.
5. Document as a teaching-style write-up (problem, method, real numbers,
   conclusion) in this same `docs/deferred/` folder, matching the standard
   set by `docs/deferred/02_stat_noise_skill_rating_analysis.md`.

## Context this depends on (read before starting)

- `docs/deferred/03_epa_pbp_value_model.md` — the fuller, related EPA
  project; read its data-feasibility section (PBP source, score-column
  semantics caveats) since this task uses the same raw data at a much
  simpler level of aggregation.
- `docs/deferred/04_idi_weight_revisit.md` and `docs/deferred/
  05_position_scheme_grouping_scoping.md` — both directly relevant: this
  task's output is meant to feed weighting decisions in the former, and
  should ideally use the latter's position/scheme classification once
  built, not just the coarse 3-group taxonomy.
- `gamebooks_boxscores/docs/pbp_verb_reference.md` — useful if any new PBP
  text parsing is needed for tackler identification.

## Known pitfalls

- Don't conflate "distance from the tackle point to the yard line where
  the play started" with "yards gained on the play" — these can differ
  if a tackle occurs after a lateral/broken-play scramble; use actual
  yards-gained-on-the-play (offense's perspective) as the primary metric,
  consistent with how the rest of this project frames yardage.
- A tackler's position/scheme should be resolved per-season via `player_id`
  (see `docs/deferred/05_position_scheme_grouping_scoping.md`'s explicit
  warning about name-collision risk) — don't join on raw name text.
- Multi-tackler plays (Solo + Assist) need a clear rule for whether both
  credited tacklers get the same yards-gained value, or whether it should
  be split/weighted — decide explicitly and document the choice rather
  than defaulting silently to one behavior.
