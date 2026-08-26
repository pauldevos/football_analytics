# Deferred work: IDI weight revisit (skill/rarity/value) + sack_share fix + parameter optimization

Paste this whole file as the prompt to a fresh session to pick up this work.
It is intentionally self-contained — do not assume the new session has any
memory of the conversation this was extracted from. **The user flagged this
as the highest-priority item among several deferred DPVS-G follow-ons** —
"yes, we're on same page, these are probably most important to revisit."

## The problem

IDI's current formula (`football_analytics/dpvs/idi.py`):

```
IDI = 0.23·tackle_share_z + 0.26·run_stuff_component_z + 0.16·sack_share_z
    + 0.20·int_component_z + 0.16·ff_component_z
```

These five weights were a **negotiated judgment call** reached in
conversation earlier this session (proposed, then approved) — they were
NOT derived algorithmically from the variance-decomposition (φ) evidence
the same session collected, unlike the shrinkage constants (`k =
8.0/(φ-1)`), which ARE directly formula-derived from φ. This is a real
methodological inconsistency: the piece of the formula measuring "how much
to trust one season's number" is rigorously derived; the piece measuring
"how much this stat should count at all" is not. The user wants this fixed.

**Two specific, football-grounded critiques the user raised, both worth
taking seriously and testing directly:**

1. **`sack_share_z` is too low, and structurally under-treated.** Unlike
   run stuff/INT/FF, `sack_share_z` is still computed as a raw team-season share
   (`sk / team_sk`), z-scored directly — it never got the rate+shrinkage+
   count treatment (`_add_rate_component`) the other three rare-event
   stats received in the §12 rebuild. Nobody has ever measured sack's own
   φ (overdispersion) this session. The user's own read: "I've come to not
   be a fan of sack_share in general as we found they're more additive" —
   meaning sacks (and possibly other stats) behave more like a simple sum
   that should be compared as a rate/count the way run stuff is, not treated
   as a fixed proportion of a team total. This needs its own φ measurement
   before its treatment can be fixed properly — likely reuses/depends on
   `docs/deferred/02_stat_noise_skill_rating_analysis.md`'s work.

2. **Run stuff is probably undervalued relative to sacks, for a specific football
   reason.** The user's reasoning, given in detail and worth preserving
   for whoever picks this up:

   > "I think run stuff should probably be higher than Sacks in value as Sacks
   > often mean the defensive backfield covered the receivers well (your
   > research by the coaches also noted this to be the case, they even
   > call them 'coverage sacks' although not officially tallied that way).
   > A run stuff almost always is a DL or linebacker blowing up the play,
   > especially so for the DL/DT as they can't move before the play as
   > they have a hand down on the LOS, so they're winning that battle
   > decidedly in most cases they get a run stuff. Meanwhile a LB is almost
   > always on a blitz as the OLB are almost always going downfield to get
   > a sack (so in the backfield) and the MLB really would only go into
   > the backfield to get behind the LOS to get the ball carrier. As they
   > often have a lot of responsibility to cover the middle of the field,
   > pass, run, etc. So the run stuff, especially for a DL (DE, DT, NT and
   > secondarily a 3-4 OLB) is often a high skill value play by them."

   In short: a sack's value is often shared with (or even mostly earned
   by) the coverage unit, while a run stuff — especially one recorded by an
   interior lineman who has a literal physical head start (hand down,
   already at the LOS, no coverage responsibility) — is much more purely
   attributable to that individual defender's own skill. This should be
   testable, not just asserted: see the "value" framing below.

## The three-part framing the user wants: skill, rarity, value

This is the conceptual structure requested for how weights should actually
be derived, distinct from the raw φ number alone:

- **Skill**: how much of this stat's variance is real individual ability
  vs. chance (the existing φ measurement — `docs/deferred/
  02_stat_noise_skill_rating_analysis.md` extends this per-position).
- **Rarity**: how uncommon the event is (bears on how much shrinkage it
  needs, and possibly on how much a single instance should be "worth" —
  a rarer, harder-to-manufacture event might deserve more credit per
  occurrence even independent of its skill/chance ratio).
- **Value**: how much the event actually mattered to the outcome — this is
  where `docs/deferred/03_epa_pbp_value_model.md` connects, if/when that
  work exists. The user explicitly flagged this overlap: "may bleed into
  #3 EPA, let me know your thoughts." **Recommendation for whoever picks
  this up**: don't block this weight-revisit work on EPA being finished —
  EPA is a large, separate, uncertain project (see that doc). Do the
  skill+rarity-based weight revisit first using what's already
  measurable (φ, shrinkage behavior, the position-specific run stuff/sack
  reasoning above), and treat EPA-informed value weighting as a SECOND,
  later refinement pass once/if that project lands, not a prerequisite.

## What to build

1. **Measure sack's own φ** (and any other stat not yet measured — this
   likely overlaps directly with `docs/deferred/
   02_stat_noise_skill_rating_analysis.md`; if that doc's work is done,
   pull its results rather than re-deriving). If sack's φ is genuinely low
   (consistent with the user's "more additive"/coverage-dependent
   intuition), that's real evidence for reducing its independent weight
   and/or giving it the same rate+shrinkage+count treatment as run stuff/INT/FF
   rather than a raw team-share.

2. **Test the DL-vs-LB run stuff distinction directly.** The user's reasoning
   implies run stuff's skill signal should differ by *which position* records it
   — a DT/DE run stuff should show a stronger, cleaner skill signal than an
   OLB/MLB run stuff (which is more often a scheme/blitz-design outcome). Split
   the φ/skill-distance measurement for run stuff by position group (or finer,
   if `docs/deferred/05_position_scheme_grouping_scoping.md`'s work has
   landed) and report whether the data actually supports this — this is a
   real, falsifiable hypothesis, not something to assume true just because
   the reasoning sounds right.

3. **Fix `sack_share_z`'s treatment** in `dpvs/idi.py` to match run stuff/INT/FF
   (`_add_rate_component`, empirical-Bayes shrinkage with a sack-specific
   `k` derived the same way: `k = 8.0/(φ_sack - 1)`) once its φ is known.
   This is a direct, mechanical fix once the measurement above exists.

4. **Re-derive the five top-level weights from φ directly**, rather than
   from negotiation. A natural, defensible approach (not the only one —
   use judgment, but justify whatever's chosen): weight each component
   proportional to `(φ_stat − 1)` (the "signal over the pure-chance floor"
   quantity already used for the k-derivation), normalized to sum to 1,
   then sanity-check the result against football intuition (including the
   DL-run stuff-vs-sack finding above) rather than accepting a purely mechanical
   number blindly. Report both the mechanically-derived weights AND the
   final chosen weights if they differ, with reasoning for any deviation.

5. **Parameter optimization sweep** (this was originally its own item —
   "K0=8.0, the 4-game/8-game floors, and the 50/50 rate/count blend...
   let's do it, [it's] cheap to actually optimize" — folded in here since
   it's the same rebuild-and-YoY-test loop as the weight revisit above,
   not worth a separate session). Sweep, independently or jointly:
   - `_K0` (currently 8.0, the shrinkage reference scale)
   - `MIN_GAMES_QUALIFIED_FLOOR` (currently 4) and `MIN_CAREER_OBS_FLOOR`
     (currently 8.0)
   - the rate/count blend ratio in `_add_rate_component` (currently a
     fixed 50/50 — `component_z = 0.5·z(shrunk_rate) + 0.5·z(raw_count)`)
   against the existing YoY stability metric (`scripts/
   yoy_stability_check.py`) as the objective — pick whichever combination
   maximizes pooled + per-era stability, report the full grid (don't just
   report the winner — show the sensitivity, since a flat landscape near
   the optimum is itself useful information about how much this matters).

6. Rebuild DPVS-G end to end with whatever final weights/parameters this
   work lands on, rerun YoY stability, reload `gold.dpvs_g_player_season`
   in football_db (`scripts/load_dpvs_g_to_db.py`), and — since this
   session already found a real team-clustering problem in the OUTER
   TCS/IDI blend (see `docs/deferred/01_tcs_idi_blend_tuning.md`) — note
   whether changing IDI's internal composition changes that outer-blend
   clustering finding at all, even though fully resolving it is that
   other doc's job.

## Deliverable

Per the user's explicit request: **a separate written doc, teaching-style**
— problem statement, the stats actually measured, the conclusion, the
tests run — same standard as `docs/deferred/
02_stat_noise_skill_rating_analysis.md`. This should read as a real,
citable piece of statistical reasoning, not just a changelog entry.

## Context this depends on (read before starting)

- `football_analytics/dpvs/idi.py` — full current IDI implementation,
  read in full (it's ~1,100 lines but well-commented; the module docstring
  alone covers most of the existing design reasoning).
- `football_analytics/docs/framework_decisions.md` §11-§17 — full history:
  the original run stuff/FR reweight, the failed first attempt, the shrinkage
  fix, the name-resolution and Postgres migration work.
- `docs/deferred/02_stat_noise_skill_rating_analysis.md` — likely a direct
  input to this doc's work; check if it's been completed first.
- `docs/deferred/03_epa_pbp_value_model.md` — the "value" leg of the
  skill/rarity/value framing; don't block on it, but read it for context
  on where this work could eventually connect.

## Known pitfalls

- Don't derive new weights from φ and declare victory without the DL-vs-LB
  run stuff check (#2 above) — the user's reasoning is specific and falsifiable,
  test it rather than assuming it.
- The existing shrinkage `k` values (run stuff≈4.73, INT≈14.04, FF≈25.00,
  tackle≈2.07) already encode φ-based trust; don't double-count by also
  cranking the top-level weight for a stat that's already getting light
  shrinkage because it's reliable — the weight is about how much the
  stat's *content* matters, the shrinkage is about how much a *given
  season's number* should be trusted. Keep these conceptually separate,
  as the code already does.
- Reuse `scripts/yoy_stability_check.py` and `_add_rate_component`
  directly — don't reimplement either from scratch.
