# Deferred work: position/scheme grouping refinement — scoping, not a build

Paste this whole file as the prompt to a fresh session to pick up this work.
It is intentionally self-contained — do not assume the new session has any
memory of the conversation this was extracted from. **This is explicitly a
scoping/investigation task first** — the user asked "what's the tradeoff
[data needed]" before committing to actually building anything more granular.
Answer that question thoroughly; only propose (don't necessarily build) an
implementation once the tradeoff is actually understood.

## The problem

IDI currently z-scores every player against peers in one of three coarse
position groups (`football_analytics/dpvs/positions.py`):

```
pass_rusher  — DE, OLB
run_stopper  — DT/NT/DL, all LB/MLB/ILB
coverage     — CB/S/DB
```

This is a peer-comparison mechanism (so a nose tackle competes against
other run-stoppers, not cornerbacks), not itself a weighting scheme.

**The specific gap the user identified**: a "3-4 OLB" and a "4-3 OLB" are
currently both mapped to `pass_rusher`, but they play genuinely different
roles depending on the team's defensive scheme. The user's example: Lawrence
Taylor (3-4 OLB, essentially a pure edge pass rusher, closer in role to a
4-3 DE) vs. Derrick Brooks (4-3 OLB, a much more coverage/run-responsibility
heavy role, closer to what a 3-4 defense would ask of an ILB). Grouping them
together as "OLB" ignores that scheme context changes what the position
actually demands, and therefore what stat production should be expected
from it. The user is "all for it being more precise" but wants to know the
**tradeoff and data cost** before committing to a build.

## What to investigate (this is the actual deliverable — a scoping report)

1. **Does this project already have team-season scheme data (4-3 vs. 3-4,
   or finer)?** Check `football_db`: `silver.team_schemes_pfr` exists per
   the schema list found this session — read it directly (columns, season
   coverage, source, how "current" the data is) before assuming it does or
   doesn't have what's needed. If it exists and is well-populated, a large
   part of this problem may already be solvable with an existing, unused
   data source rather than new ingestion.

2. **If team-season scheme data exists, is that enough, or is
   player-level role data also needed?** A team's official base scheme
   (3-4 vs 4-3) is necessarily a simplification — many teams run hybrid
   packages, and a specific player's snap-by-snap role can differ from the
   team's "listed" scheme (a "3-4 OLB" on a team that mixes packages might
   spend real snaps in a 4-3-style edge role). Investigate what granularity
   is actually achievable:
   - **Team-scheme only** (cheapest): tag each player-season with their
     team's base scheme that year, and split `pass_rusher`/whatever group
     by scheme (e.g. `pass_rusher_34` vs `pass_rusher_43`) rather than
     inferring anything player-specific. Cheap, but doesn't solve the
     "hybrid player" case at all.
   - **Snap-count / personnel-package data** (if available): would let a
     player's ACTUAL role be quantified (e.g. % of snaps as an edge rusher
     vs. % in coverage) rather than assumed from a listed position/scheme
     label. Check whether this project has access to anything like this
     (PFR snap counts? Pro Football Focus-style data? Neither may be
     available for older eras) — report honestly what's realistic to get
     and for which years, don't assume it exists without checking.
   - **A "hybrid-ness" continuous score** (most ambitious): rather than a
     hard position-group bucket, compute something like "this player's
     stat profile this season looked X% like a typical pass-rusher's and
     Y% like a typical coverage player's" from the player's OWN production
     mix (sacks/TFL vs. PD/INT ratio, say) rather than from an external
     scheme label at all. This sidesteps needing new external data
     entirely, but conflates "what role were they asked to play" with
     "how well did they do in whatever role they had" — flag this
     conflation risk explicitly if this path is explored, it's a real
     methodological concern, not just an implementation detail.

3. **Report the tradeoff clearly**: for each of the three approaches above
   (or others found during investigation), state what data is needed,
   whether this project already has it, how far back it would cover, and
   the estimated effort to build vs. the precision gained. The user
   explicitly wants this framed as a cost/benefit decision they can make,
   not a foregone conclusion that more granularity is automatically worth
   building.

4. **A concrete before/after example**, even if only a mockup/estimate
   rather than a full build: show what Lawrence Taylor vs. Derrick Brooks
   would look like under the current 3-group system vs. under whichever
   refined approach seems most promising — does splitting them actually
   change their IDI_z meaningfully, or does the current system already
   handle this case reasonably well because their raw stat profiles differ
   enough that z-scoring within `pass_rusher` doesn't actually average them
   into an unfair comparison? This concrete check might reveal the problem
   is smaller (or bigger) in practice than the position-label mismatch
   alone suggests.

## Context this depends on (read before starting)

- `football_analytics/dpvs/positions.py` — current 3-group mapping.
- `football_db` schema — specifically check `silver.team_schemes_pfr` (seen
  in the schema list this session, not yet investigated for content/
  coverage) and whether any snap-count/personnel data exists anywhere in
  this project's data sources.
- `football_analytics/docs/framework_decisions.md` — for how position
  grouping interacts with IDI's z-scoring (`_resolve_position_group` in
  `dpvs/idi.py`) and DPVS-P's separate run/pass credit-fraction weighting
  (`dpvs/composite.py`, `_POS_RUN_CREDIT`/`_POS_PASS_CREDIT` — a related
  but distinct positional mechanism, currently computed but not consumed
  anywhere downstream; worth being aware of since a scheme-aware position
  refinement might eventually want to feed both mechanisms consistently).

## Explicitly NOT in scope for this doc

Actually building a new grouping scheme is NOT the deliverable here unless
the investigation makes an unusually clear, cheap case for one specific
approach. The primary deliverable is the tradeoff report — what data
exists, what it would take, and a recommendation the user can decide on
in a follow-up session.
