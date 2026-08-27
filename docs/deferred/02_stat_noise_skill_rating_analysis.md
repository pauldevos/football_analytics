# Deferred work: per-stat, per-position skill-rating analysis (how noisy is each stat, how good is each player)

Paste this whole file as the prompt to a fresh session to pick up this work.
It is intentionally self-contained — do not assume the new session has any
memory of the conversation this was extracted from.

## The problem

This session already ran a variance-decomposition (overdispersion, φ) test
on five defensive stats — tackle, run stuff, INT, FF, FR — to answer "how much of
this stat's variance across players is real skill vs. pure chance?" (See
`docs/framework_decisions.md` §12/§14 for the original work, and
`docs/deferred/04_idi_weight_revisit.md` for how those φ values currently
feed IDI's shrinkage constants.) That was a single aggregate number per
stat, not broken out by position or by individual player.

The user wants this extended into something richer: **a proper per-position,
per-stat "how noisy is this stat" analysis, AND a per-player "how much
better than replacement is this player at this stat" skill rating**, using
a Z-score-like distance metric. Concrete example given: defensive backs
average around 3 INT/year, but Rod Woodson averaged 4.8/year — that gap,
expressed as a standardized distance from the position-group mean, IS the
skill rating. Do this for every stat this project has: **tackles, sacks,
run stuff, FF, FR, INT, PD** (pass deflections — not currently in IDI at all,
worth including here as a candidate future component).

**Why this matters beyond just satisfying curiosity**: this is meant to be
the evidence base that `docs/deferred/04_idi_weight_revisit.md` uses to set
IDI's weights more rigorously — right now those weights are a negotiated
judgment call (see that doc), not derived from real per-stat skill
distributions. This analysis is upstream of that one.

## What to build

1. **YoY (year-over-year) stability AND split-half career reliability**, per
   stat, per position group — not just pooled across all positions the way
   the original φ test was. Use both methodologies already established this
   session (see `docs/framework_decisions.md` for the exact YoY Pearson-r
   approach and the split-half/variance-decomposition approach — the user
   specifically flagged earlier this session that naive YoY correlation is
   biased against rare events, so the φ/dispersion approach should still be
   the primary methodology for rare stats; combine both where they're
   informative, and say clearly which one is driving which conclusion).
   Break results out per `position_group` (`dpvs/positions.py`'s three
   groups: `pass_rusher`, `run_stopper`, `coverage` — or finer if
   `docs/deferred/05_position_scheme_grouping_scoping.md` has landed and
   changed the grouping by the time this runs) for every stat: tackle,
   sack, run stuff, FF, FR, INT, PD.

2. **A per-player skill-distance rating**: for each player-season (or
   career, aggregated with the same shrinkage logic already used in
   `dpvs/idi.py`'s `_add_rate_component` — reuse it directly rather than
   reinventing), compute how many standard deviations above/below their
   position-group's mean rate they sit for each stat. The Rod Woodson
   example is the target output shape: "average DB gets ~3.0 INT/yr,
   Woodson got 4.8/yr" → express that gap as a z-score distance, then find
   and report the actual top players by this metric for each stat (not
   just Woodson — a real leaderboard per stat per position group).

3. **Historical range**: go back as far as the data allows. For any season
   1978 or later, use existing sources (gold parquet / `football_db`
   `gold.player_game_stats`, both already populated per this session's
   Postgres migration — see `docs/framework_decisions.md` §16-§17). For
   1977 and earlier (the `gamebooks_boxscores` corpus era), **only include
   games/team-sides that clear the established ≥70% completeness-ratio gate**
   — this project's existing convention (see `gamebooks_boxscores`'
   `build_defensive_leaderboards.py` and this repo's own
   `build_run_stuff_gated_corpus.py`/`build_tackle_gated_corpus.py` for exactly
   how that gate is computed; reuse it directly, don't re-derive). Do not
   include ungated 1967-77 data in this analysis — it would bias the
   "how noisy is this stat" measurement with artificially sparse/incomplete
   team-sides.

4. **A data-integrity side-check, explicitly requested**: cross-reference
   PFR's own reported `games_played` (season level, from whatever source
   `dpvs/tcs.py`/`dpvs/idi.py` currently use for `g`) against an independent
   games-played count derived from actual per-game data (starters/box
   score presence — `gold.game_starters_pfr` in football_db, or the
   per-game rows in `gold.player_game_stats` itself, whichever is the more
   reliable independent count). The user's own framing: "might be 14 gp in
   PFR, but we see only 12 in starters by game stuff... I don't expect much
   difference here, but could be a thing." Report the actual discrepancy
   rate (how many player-seasons disagree, by how much, concentrated in
   which eras) — if it's negligible, say so plainly and move on; if it's
   not, flag it as a real data-quality finding worth its own follow-up
   before trusting any rate-based (per-game) stat computed against a wrong
   denominator.

## Deliverable

A written doc (in this same `docs/deferred/` folder, or `docs/research/` if
that convention exists by the time this runs — check first) with:
- The problem statement (this section, adapted)
- The exact stats/tests run, with real numbers
- A results table: stat × position_group → φ (or split-half r) → noise
  interpretation
- Real player leaderboards per stat per position group (skill-distance
  ranked)
- The games-played cross-check findings
- A clear conclusion section usable directly as input evidence for
  `docs/deferred/04_idi_weight_revisit.md`

Per the user's explicit request this session: **write this up as a genuine
teaching document** — problem, data, method, conclusion, in a form useful
for someone learning statistical analysis, not just an internal engineering
note.

## Context this depends on (read before starting)

- `football_analytics/docs/framework_decisions.md` §12/§14 — the original
  φ/dispersion methodology and results (tackle 4.87, run stuff 2.69, INT 1.57,
  FF 1.32, FR 1.08) — this task extends that, doesn't replace it.
- `football_analytics/dpvs/idi.py` — `_add_rate_component()`'s shrinkage
  machinery, directly reusable for the per-player skill-rating computation.
- `football_analytics/dpvs/positions.py` — current position grouping.
- `gamebooks_boxscores/build_defensive_leaderboards.py` — the ≥70%
  completeness-ratio gate, for 1967-77 data.
- `football_db` schema: `gold.player_game_stats`, `silver.
  player_game_stats_pfr`, `silver.player_game_stats_gamebook`,
  `gold.game_starters_pfr` — all populated per this session's migration
  work (§16-§17).

## Known pitfalls

- Don't repeat the naive-YoY-correlation mistake already caught once this
  session for rare events (FF/FR/INT/run stuff) — use the variance-decomposition/
  φ approach as the primary signal for anything low-count, per position
  group. This is explicitly why the original φ test exists.
- PD (pass deflections) has a documented over-crediting risk elsewhere in
  this project (`gamebooks_boxscores/CLAUDE.md`'s Scoring Rules: "PD is a
  deflection, not a coverage note... has been the single most commonly
  over-counted stat in this project so far") — if PD's noise/skill numbers
  look unusually extreme, consider whether that's a real signal or an
  artifact of this known scoring-quality issue before trusting it.
