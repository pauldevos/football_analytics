# Deferred work: career-prior construction for empirical-Bayes shrinkage (whole-career vs. sequential, injury handling, age curves)

Paste this whole file as the prompt to a fresh session to pick up this work.
It is intentionally self-contained — do not assume the new session has any
memory of the conversation this was extracted from. This is closely related
to `docs/deferred/04_idi_weight_revisit.md` (same shrinkage mechanism in
`dpvs/idi.py`) but is a genuinely separate methodological question — that
doc is about the top-level component weights; this one is about how the
*prior* each component shrinks toward gets built in the first place.

## The problem

`dpvs/idi.py`'s `_add_rate_component()` (used for tackle/run stuff/INT/FF)
computes each player-season's empirical-Bayes prior as a **sequential,
prior-seasons-only** cumulative average:

```python
# career-to-date prior: cumulative count/n_obs over strictly earlier
# seasons in THIS loaded frame, keyed by pfr_player_id.
prior_count = grp.transform(lambda s: s.shift(1).fillna(0).cumsum())
prior_nobs  = grp_n.transform(lambda s: s.shift(1).fillna(0).cumsum())
```

For J.J. Watt's 2012 season (21 run stuff / 18 games, raw rate 1.167), this
produced a shrunk rate of 0.985 — pulled down because his ONLY prior
evidence at that point was a modest 2011 (5 run stuff / 17 games, rate 0.294).
That specific case reads fine on its own (2011 genuinely was Watt's weaker,
earlier-career season) — but the user identified that the *mechanism*
generating it has two real, symmetric biases baked in:

> "I don't want a 'prior career' to pull down a player's weight in a season
> if the seasons after that are higher, I'd want to weight against the
> entire career within a reasonable 'prime' age range, not their prior
> years as that will weight up a later year, e.g. age 34 against an amazing
> age 33 and prior career. But a 2nd season on a soon to be an amazing
> career would weight down that year from a poor rookie year. That's not
> indicative of the player's real talent, the prior year is not as telling
> as the whole career within a reasonable age curve."

Concretely, two failure modes from the same root cause (using only
*chronologically earlier* seasons as the prior):

1. **Early-career seasons get shrunk toward a thin, possibly-unrepresentative
   rookie/sophomore prior**, even when the rest of the career (available in
   the data, just not yet "in the past" relative to that season) shows the
   player's real talent was much higher. A 2nd-year breakout gets
   artificially dragged down by a mediocre rookie season.
2. **Late-career decline seasons get shrunk *upward*, toward a strong prior
   built from the player's own earlier prime.** An age-34 decline season
   sitting right after an "amazing age-33 and prior career" would get
   inflated by that history, masking a real decline rather than measuring
   it honestly.

## The injury complication

A third, related issue, also raised directly:

> "The other tough part is once injured, they're a completely different
> player and so we do want to try to avoid those weighing down a player's
> season because he got hurt."

This is harder than the chronology problem above, because **games-played
weighting (n_obs) already down-weights short, injury-shortened seasons
automatically** — but it does NOT catch a season where a player played a
full slate of games while still meaningfully diminished by injury
after-effects. The user's specific validation case, worth preserving
exactly for whoever builds and tests this:

> "JJ Watt is one actually - he got hurt in 2016, 2017, 2019, and 2021 --
> all of them greatly affected his explosion and performance. 2020 he
> played 16 games, but wasn't full strength and you can see that season
> was nowhere even close to his 'normal' full seasons: 2012-2015 and 2018."

Note 2020 specifically: a full 16-game season by the games-played metric,
but NOT representative of Watt's true talent per the user's football
knowledge — exactly the case no simple n_obs-based fix can catch, since
"played" and "played at full strength" are different things this project
has no direct signal for.

## Two proposed directions — pick one to start, don't block on the other

**Option A — trimmed/robust career prior (simpler, tractable now).**
Instead of "cumulative prior seasons," build the prior from a player's
**best N% of career seasons** (the user's suggestion: "sample their top 60%
seasons (so 3 of 5, or 6 of 10)"), selected by output/rate, not
chronology. This is a standard robust-statistics idea (a trimmed mean) and
has real advantages here:
- It's symmetric — a 2nd-year season can be evaluated against the WHOLE
  career's best seasons (including future ones), not just a thin, possibly
  unrepresentative early sample.
- It naturally down-weights genuine outlier-bad seasons (which
  disproportionately correlate with injury, per the user's Watt example)
  without needing to explicitly detect "was this player injured" at all —
  a season that's bad enough to fall outside the top 60% simply doesn't
  contribute to defining the player's "true talent" baseline.
- It's NOT a full solution to the late-career-decline problem on its own —
  think through and test explicitly whether a genuinely age-declined season
  still gets shrunk sensibly (its own OBSERVED rate, weighted by its own
  n_obs against the trimmed prior, should still pull the final shrunk value
  down for a real decline — shrinkage isn't supposed to erase real signal,
  just dampen small-sample noise — but this needs to be verified against
  real cases, not assumed).

**Option B — full age-curve model by position (bigger, more rigorous, a
valuable deliverable in its own right).** The user flagged this explicitly:
"we could do an age curve across all players by position to get an
expected number here. Probably would be a good analysis and table value.
But that could be a lot more complexity." This means: fit an expected
production curve by age (and position_group, or finer per
`docs/deferred/05_position_scheme_grouping_scoping.md` if that's landed) —
the sabermetrics-style aging-curve approach — then evaluate each
player-season against age-adjusted expectation rather than against the
player's own career average at all. This is more work but produces a
genuinely useful standalone artifact (an age-curve table by
position/stat) independent of whatever it's eventually used for in IDI's
shrinkage.

**Recommendation for whoever picks this up**: build and validate Option A
first (cheap, testable, directly fixes the two chronology biases
identified). Treat Option B as a larger, separately-valuable follow-on —
if it's built, its output (an expected-rate-by-age curve) could REPLACE or
supplement Option A's trimmed-career prior as an even better baseline, but
don't block Option A on Option B being finished.

## What to build and test

1. Implement whichever prior-construction approach is chosen as a
   modification to `_add_rate_component()` in `dpvs/idi.py` (the
   `career_prior_rate` computation specifically — the rest of the shrinkage
   machinery, including the `k` values, doesn't need to change).
2. **Validate directly against the J.J. Watt case** — this is the concrete
   test the user already gave: does the new prior construction correctly
   treat 2012-2015 and 2018 as his real full-strength seasons, and
   2016/2017/2019/2020/2021 as clearly reduced (2020 especially, since it's
   the hardest case — full games played, real talent reduction)? Report
   the actual before/after shrunk rates for every one of Watt's seasons
   under both the old (sequential) and new (trimmed/whole-career) prior.
3. Ask the user for a few more validation examples if useful before
   finalizing — the message that spawned this doc offered "I can also give
   you some examples of players here" beyond Watt; a fresh session could
   ask for 3-5 more before committing to a final approach, since more
   real cases will surface edge behavior a single player can't.
4. Rerun the existing YoY stability check (`scripts/yoy_stability_check.py`)
   after the change — a better prior construction should, if anything,
   IMPROVE stability (a fairer baseline should make true skill more
   visible, not less), but confirm rather than assume.
5. Document as a genuine teaching-style writeup (problem, method, real
   before/after numbers, conclusion) in this same `docs/deferred/` folder
   or wherever this project's convention has settled by the time this
   runs — matching the standard already set by
   `docs/deferred/02_stat_noise_skill_rating_analysis.md`.

## Context this depends on (read before starting)

- `football_analytics/dpvs/idi.py` — `_add_rate_component()`, specifically
  the `career_prior_rate`/`prior_count`/`prior_nobs` block, is the exact
  code this doc is about.
- `docs/deferred/04_idi_weight_revisit.md` — related but distinct: that
  doc is about the five TOP-LEVEL weights; this doc is about the PRIOR
  each shrinkage-treated component uses. Both touch the same function,
  so whoever does one should check whether the other has landed first to
  avoid rebuilding on top of stale assumptions.
- `docs/deferred/02_stat_noise_skill_rating_analysis.md` — if that
  per-position skill-rating work has landed, its per-player skill-distance
  output might be directly reusable as a way to identify "top N%" seasons
  for the trimmed-prior approach.

## Known pitfalls

- Don't just swap "prior seasons" for "all seasons including future ones"
  naively without addressing the late-career-decline case — read the user's
  reasoning above carefully; the fix needs to handle BOTH directions of the
  bias, not just the early-career one (which is the easier, more obvious
  half).
- The 2020 Watt case (full games, reduced output) is the single hardest
  test case here — don't consider this work done until that specific
  season is examined explicitly, not just the more obvious short-season
  injury years (2016/2017/2019/2021, where low games-played already gives
  a partial signal even under the OLD mechanism).
