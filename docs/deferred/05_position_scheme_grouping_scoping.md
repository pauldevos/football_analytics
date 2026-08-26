# Deferred work: position/scheme grouping refinement — feasibility confirmed, ready to build

Paste this whole file as the prompt to a fresh session to pick up this work.
It is intentionally self-contained — do not assume the new session has any
memory of the conversation this was extracted from.

**Status update (2026-08-22): the original version of this doc asked "is
this even feasible?" That question has now been answered directly — yes,
with real data already in `football_db`. This doc is now closer to a build
spec than a scoping question. The remaining open item is closer to
"validate at scale and integrate," not "does the data exist."**

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

**The gap**: a "3-4 OLB" and a "4-3 OLB" are currently both mapped to
`pass_rusher`, but play genuinely different roles depending on team scheme
— e.g. Lawrence Taylor (3-4 OLB, essentially a pure edge rusher) vs.
Derrick Brooks (4-3 OLB, a much heavier coverage/run-responsibility role).

## The user's real position-group taxonomy (ground truth, save exactly as given)

This is real football domain knowledge, given directly, with responsibility
splits, expected stat ranges, and named examples per bucket — use this as
the target taxonomy and validation set for whatever gets built.

**Correction (2026-08-22)**: the classifier built per this doc (see the
companion `05_RESULTS_position_scheme_classifier_20260822.md`) flagged
Bobby Wagner as a mismatch against his original placement here under
"3-4 ILB/MLB" — real data shows 13 of his 14 Seattle seasons labeled
`'4-3'` (only 2022 shows `'3-4'`). The user confirmed this was their own
placement error, not a classifier bug: "Wagner could be a 4-3 MLB... I
think he's a 4-3." Moved to the "4-3 MLB" row below. This is a useful
example of the validation loop working as intended — a taxonomy generated
from memory/expertise can still have individual errors, and a data-checked
classifier is a real way to catch them.

| Scheme/Position | Responsibilities | Sample stat profile (season) | Example players |
|---|---|---|---|
| 3-4 NT | 85% run defense, 15% pass rush | 30-65 tackles, 3-5 sacks, 5-10 run stuff | Ted Washington, Vince Wilfork, Curley Culp, Casey Hampton, Fred Smerlas, Michael Carter, Bob Baumhower (early NT who also rushed the passer — rare for a 0-technique) |
| 3-4 DE | 40% run defense, 60% pass rush | 50-70 tackles, 5-10 sacks, 5-10 run stuff | J.J. Watt, Bruce Smith, Howie Long, Lee Roy Selmon, Richard Seymour, Justin Smith, Calais Campbell, Elvin Bethea, Art Still, Doug Betters |
| 3-4 OLB (edge rusher) | 80% pass rush, 15% run defense, 5% coverage | 40-55 tackles, 7-12 sacks, 5-10 run stuff | Lawrence Taylor, Terrell Suggs, Kevin Greene, Greg Lloyd, T.J. Watt, Von Miller, Derrick Thomas, Andre Tippett, DeMarcus Ware, James Harrison |
| 3-4 ILB/MLB | 70% run defense, 10% coverage, 20% pass rush (blitzing) | 80-120 tackles, 3-6 sacks, 5-10 run stuff, 2-4 INT | Levon Kirkland, Ray Lewis, Pepper Johnson, Harry Carson, Randy Gradishar, Patrick Willis, Steve Nelson, Sam Mills |
| 4-3 DE | 70% pass rush, 30% run defense | 50-75 tackles, 5-10 sacks, 5-10 run stuff | Myles Garrett, Deacon Jones, Carl Eller, Chris Doleman, Charles Haley, Charles Mann, Jack Youngblood |
| 4-3 MLB | 60% run defense, 20% coverage, 20% pass rush (blitzing) | 120-150 tackles, 1-2 sacks, 5-10 run stuff, 1-3 INT | Bill Bergey, Dick Butkus, Mike Singletary, Willie Lanier, Brian Urlacher, Luke Kuechly, Nick Buoniconti, Tommy Nobis, Bobby Wagner |
| 4-3 OLB | 50% run defense, 30% coverage, 20% pass rush | 80-120 tackles, 3-5 sacks, 5-10 run stuff, 2-5 INT | Derrick Brooks, Lavonte David, Ed McDaniel, Bobby Bell, Jack Ham, Junior Seau, Ted Hendricks, Chuck Howley, Matt Blair, Wilber Marshall |

**Hybrid players**: real, but the exception, not the rule — the user's
estimate is roughly 6-10 players per year genuinely moonlighting across two
positions in a way that's a real schematic advantage for their team. Don't
build the classification system around hybrids as the common case; build
it for the clean 90%+ case first, then handle hybrids as a flagged
minority (see the hybrid-identification section below).

**Note**: this taxonomy doesn't cover a 4-3's two DT roles (1-technique
run-stuffer vs. 3-technique penetrator) — the user didn't give that split
explicitly. Worth asking for it, or inferring it from stat profile
(run stuff/sack-heavy = 3-technique, pure-volume/lower-sack = 1-technique) if a
future session needs that level of granularity.

## Feasibility validation already done — direct database evidence

**1. Team-season scheme data exists and is well-populated.**
`silver.team_schemes_pfr` (`franchise_id, season, defensive_alignment`):
1,718 rows, 1967-2025, all 32 franchises, 627 seasons labeled `'3-4'`,
1,091 labeled `'4-3'`.

**2. Position strings in `silver.player_team_seasons_pfr` already carry
real scheme-relevant detail, and validate cleanly against real players when
correctly resolved.** Direct query results, joining `position` +
`silver.team_schemes_pfr.defensive_alignment` by `(franchise_id, season)`:

| Player | Real history | Position label | Team scheme | Matches taxonomy? |
|---|---|---|---|---|
| Lawrence Taylor | 1981-93 NYG | `ROLB` | `3-4` every season | Yes — 3-4 OLB edge rusher |
| Dick Butkus | 1965-73 CHI | `MLB` | `4-3` | Yes — 4-3 MLB |
| Derrick Brooks | 1995-2008 TB | `RLB` | `4-3` every season | Yes — 4-3 OLB |
| Myles Garrett | 2017-present CLE | `LDE` | `4-3` every season | Yes — 4-3 DE |
| J.J. Watt | 2014 HOU | `LDE` | `3-4` | Yes — 3-4 DE (Wade Phillips scheme, exactly as expected) |
| Ted Washington (real one — see below) | 1991-2007, multiple teams | `NT` in 3-4 seasons, `LDT`/`RDT`/`DT` in 4-3 seasons | flips team to team | **Position label itself flips in sync with team scheme** — strong, clean signal |
| Ray Lewis | 1996-2012 BAL | `LILB`/`MLB` | 10 seasons `'3-4'`, 7 seasons `'4-3'` (Ravens genuinely changed fronts over his career) | Real, correct nuance — not a data error |

**Important caveat surfaced during validation, not a data bug but a real
trap for whoever builds this**: `gold.players` has two entirely different
real people both named "Ted Washington" — a 1970s Oilers linebacker (b.
1948, Miss. Valley St., `player_id` 3031) and the famous NT (b. 1968,
Louisville, `player_id` 4862). They are ALREADY correctly split with
distinct `player_id`s in the data. The only failure was an unfiltered ad
hoc query grabbing the wrong one first. **Any implementation must always
resolve by `player_id`, never by bare name string** — this project has
hit this exact class of bug repeatedly this session (Mike McCoy, Robert
Jackson, Mike Jones — see `football_db/docs/roster_name_collision_audit_
20260821.md`) and it will happen again here if name-based joins are used
carelessly.

**Conclusion: the position + team-scheme join is a real, validated,
cheap-to-build signal for most of the taxonomy above (NT vs. DE vs. MLB vs.
OLB, times 3-4 vs. 4-3).** The main remaining gap: `OLB`/`LOLB`/`ROLB`
alone doesn't distinguish which of a 3-4's two OLBs is the primary edge
rusher vs. the more coverage-oriented one (L/R indicates formation side,
not role) — see the hybrid/refinement section below for how to close that
specific gap.

## Coach/scheme tracking — also already available, no new data needed

The user separately wants Head Coach and Defensive Coordinator tracked
per player-season, reasoning that a DC's scheme preferences directly shape
which players get put in position to make plays. **This already exists**:
`silver.coach_seasons_pfr` (`coach_id, franchise_id, season, coach_role,
coach_level, ..., def_scheme, ...`) has clean `coach_role` values including
exactly `'Head Coach'` and `'Defensive Coordinator'` (plus many
hybrid-role variants like `'Defensive Coordinator/Assistant Head Coach'` —
handle with a `LIKE`/`ILIKE` match or an explicit list, not exact-match
only, to avoid silently dropping those). It ALSO carries its own
`def_scheme` field directly on the coach row (`'3-4'`/`'4-3'`), which
should be cross-checked against `silver.team_schemes_pfr.defensive_
alignment` for the same team-season as a free data-quality sanity check
when this gets built — if they ever disagree, that's worth investigating
before trusting either blindly.

## What to build

1. **A position×scheme classifier**: for each `(player_id, season)`, join
   `silver.player_team_seasons_pfr.position` with `silver.team_schemes_pfr.
   defensive_alignment` (by `franchise_id, season`) and map the combination
   onto the 8-bucket taxonomy above (extend/adjust bucket boundaries as
   needed once real coverage is checked — e.g. decide what a bare `DT`
   label under a `'3-4'` team means, since the taxonomy expects `NT` there;
   is it a genuine hybrid/rotational lineman, a data-entry inconsistency,
   or something else? Check real cases before assuming either way).
2. **Handle the pre-1970s/multi-position legacy data explicitly.**
   `silver.player_team_seasons_pfr.position` has a lot of noisy compound
   strings from the leather-helmet era (`"B-G-DE-E"`, `"C-LB-E-DE"`, etc.)
   — largely irrelevant here anyway since the 3-4 scheme didn't really
   exist before the 1970s, but decide and document an explicit cutoff/
   fallback (e.g. `'unknown'` bucket) rather than silently mis-mapping
   these.
3. **Close the 3-4-OLB rush-vs-coverage gap** using the player's own stat
   profile as a secondary signal once the position×scheme join is in
   place: within `3-4 OLB`, a player with a sack/run stuff-heavy profile close to
   the "80% pass rush" taxonomy row is the rush OLB; one with a heavier
   tackle/coverage profile is closer to what the 3-4 ILB/MLB row describes
   for coverage responsibility. This is the "hybrid-ness continuous score"
   idea from the original version of this doc — now scoped narrowly to
   just this one specific, real disambiguation need rather than as a
   general-purpose mechanism.
4. **Validate at real scale** — not just the 7 hand-picked cases above.
   Run the classifier across the full historical dataset, spot-check a
   larger random and stratified sample against the taxonomy's named
   examples (every player explicitly named in the table above is a
   built-in test case — check all of them, not just the ones already
   spot-checked), and report the real coverage/accuracy rate honestly,
   including the "unknown"/unmapped rate for whatever falls outside the 8
   buckets.
5. **Wire in coach data** (`coach_role IN`/`ILIKE` `'Head Coach'` and
   `'Defensive Coordinator'` variants from `silver.coach_seasons_pfr`,
   joined by `franchise_id, season`) alongside the position/scheme
   classification, so a future player-season table (or `dpvs/idi.py`'s
   position-group resolution) can carry both.
6. **Only after the classifier is validated**: decide whether/how to feed
   it into `dpvs/positions.py`'s z-scoring groups (finer buckets than the
   current 3), and whether `dpvs/composite.py`'s currently-unused DPVS-P
   run/pass credit-fraction mechanism (`_POS_RUN_CREDIT`/`_POS_PASS_
   CREDIT`) should be revisited with the new, more precise groups —
   that mechanism was originally built on the coarse 3-group taxonomy and
   might change meaningfully with 7-8 real groups instead.

## Context this depends on (read before starting)

- `football_analytics/dpvs/positions.py` — current 3-group mapping.
- `football_db`: `silver.team_schemes_pfr`, `silver.coach_seasons_pfr`,
  `silver.player_team_seasons_pfr`, `gold.players` — all confirmed
  populated and usable, per the validation above.
- `football_analytics/docs/framework_decisions.md` — for how position
  grouping interacts with IDI's z-scoring (`_resolve_position_group` in
  `dpvs/idi.py`) and DPVS-P's separate run/pass credit-fraction weighting.
- `football_db/docs/roster_name_collision_audit_20260821.md` — read this
  before writing ANY name-based join for this task; use `player_id`
  throughout, never a bare name string.

## Known pitfalls

- Never resolve a player by name string alone — see the Ted Washington
  case above. Always join on `player_id`.
- Don't assume `OLB`/`LOLB`/`ROLB` alone tells you rush-vs-coverage role
  within a 3-4 — it doesn't; L/R is formation side, not role. Use the
  stat-profile secondary signal described above.
- Cross-check `coach_seasons_pfr.def_scheme` against `team_schemes_pfr.
  defensive_alignment` for the same team-season — don't assume they always
  agree without checking.
