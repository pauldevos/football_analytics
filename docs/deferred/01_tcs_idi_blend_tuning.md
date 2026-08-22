# Deferred work: TCS/IDI outer blend ratio tuning

Paste this whole file as the prompt to a fresh session to pick up this work.
It is intentionally self-contained — do not assume the new session has any
memory of the conversation this was extracted from.

## The problem

DPVS-G's final composite score is currently:

```
DPVS-G (no WOWY) = 0.60·TCS_z + 0.40·IDI_z
DPVS-G (with WOWY, when available) = 0.50·TCS_z + 0.30·IDI_z + 0.20·WOWY_z
```

(`dpvs/composite.py`, `_W_NO_WOWY` / `_W_FULL`.)

TCS = Team Credit Share (how much of the *team's* defensive success this
player's games were part of — built from TDGS, a per-game team defensive
score with opponent-quality adjustment). IDI = Individual Disruption Index
(the player's own individual stat production — tackles, TFL, sacks, INT, FF
— relative to season × position-group peers; see
`docs/deferred/04_idi_weight_revisit.md` for that formula's own separate
revisit).

**The observed problem, from a real sniff test**: pulling top-10 DPVS-G
rankings for a season currently shows a noticeable cluster of players from
the *same team* — e.g. several players from one historically great defense
all landing in the top 10 for that season. The user's read, from real
football knowledge: "of the top 10 defensive players in the NFL, it would be
exceedingly rare for more than 2-3 of the top 10 to be from one team." Great
defenses do produce multiple good players, but not usually 4+ genuinely
top-10-caliber ones in the same season — that pattern is a sign the *team*
context (TCS, 60% of the score) is dominating the *individual* signal (IDI,
40%) more than it should.

**Hypothesis**: the 60/40 split overweights team context. A better balance
is probably closer to 30/70 (TCS/IDI) — i.e. individual disruption should
matter more, team success less, in the final ranking. This is a hypothesis
to test, not a conclusion to assume.

## What to build

1. **A sweep script** that rebuilds the composite (not the whole DPVS-G
   pipeline — TCS_z and IDI_z are already computed and stable; just the
   final blend step) across a grid: TCS weight ∈ {0.20, 0.25, 0.30, 0.35,
   0.40}, IDI weight = 1 − TCS weight (so this covers the requested
   0.20-0.40 TCS / 0.60-0.80 IDI range at 0.05 resolution — adjust the step
   size if a finer sweep is cheap enough). Read `~/data/silver/
   dpvs_g_player_season.parquet` (has `tcs_z` and `idi_z` already computed)
   rather than re-running the whole pipeline for every grid point — this
   should be fast.

2. **For each candidate blend, compute two things**:
   - **The team-clustering sniff test**: for a sample of seasons (pick a
     mix of eras — at minimum a few from 1967-77, 1978-98, 1999-2024 — and
     ideally the specific seasons/teams the user already has strong
     priors about from this project's other work this session, e.g. the
     1971 Vikings, the 2006-2009 Vikings run defense, 1970s Steelers) count
     how many of the top-10 DPVS-G players that season come from the same
     team. Report the distribution (how often is it 4+, how often 2-3, how
     often ≤1) across all seasons tested, not just the anecdotal cases —
     a single season proving the point isn't enough evidence, this needs
     to hold up in aggregate.
   - **The existing YoY stability metric** (`scripts/yoy_stability_check.py`
     — read it to understand exactly how it's computed, then adapt it to
     score the *composite* under each candidate blend, not just the
     currently-hardcoded 60/40 one). A blend that fixes clustering but
     tanks predictive stability would be a bad trade — report both metrics
     side by side for every grid point.

3. **Report a table**: blend ratio → team-clustering distribution → YoY
   stability (both `dpvs_g` pooled r and by era). Recommend a specific
   ratio with reasoning, but leave the final call to the user — this is a
   real tradeoff, not a pure optimization (the "right" answer partly
   depends on which failure mode the user is more willing to tolerate).

4. If a clearly-better ratio emerges, update `_W_NO_WOWY` (and proportionally
   `_W_FULL`, keeping WOWY's own relative weight sensible — or ask the user
   whether WOWY's slice should also move, since it currently isn't part of
   this specific tuning question) in `dpvs/composite.py`, rebuild DPVS-G
   end to end, rerun YoY stability one final time to confirm, and reload
   `gold.dpvs_g_player_season` in football_db
   (`scripts/load_dpvs_g_to_db.py`).

## Context this depends on (read before starting)

- `football_analytics/dpvs/composite.py` — the actual blend logic
  (`_compute_dpvs_g_row`, `_W_FULL`, `_W_NO_WOWY`).
- `football_analytics/docs/framework_decisions.md` §11-§17 — full history of
  how IDI itself was built/validated this session; useful context for why
  IDI_z means what it means, even though this specific task doesn't touch
  IDI's internals.
- `football_analytics/scripts/yoy_stability_check.py` — the validation
  methodology to reuse/extend.
- `~/data/silver/dpvs_g_player_season.parquet` — has `tcs_z`, `idi_z`,
  `wowy_z` (where available), `dpvs_g` (current 60/40 result) already
  computed; also now loaded into football_db's `gold.dpvs_g_player_season`.

## Known pitfalls / things to get right

- Don't re-run the full `build_dpvs_g.py` pipeline for every grid point —
  TCS_z/IDI_z are already computed and don't change with this tuning; only
  the final weighted-sum step does. Re-deriving those from scratch 5+ times
  would be needlessly expensive.
- The team-clustering sniff test needs a real, honest sample of seasons —
  don't cherry-pick seasons that happen to confirm the hypothesis. Pull a
  representative spread across eras and check whether the pattern holds
  everywhere or is concentrated in specific years/team situations (e.g.
  maybe it's worse in the 1967-77 era where TCS/IDI data sourcing differs
  from 1999+ — that itself would be a useful finding).
- This is explicitly a candidate follow-on to `docs/deferred/04_idi_weight_
  revisit.md` — if IDI's own internal weights change first (that doc's
  work), IDI_z's distribution could shift and this blend tuning might need
  a second pass. Either order is fine to start with, but note in your
  final report which order you used and flag if a re-check after the other
  doc's work seems warranted.
