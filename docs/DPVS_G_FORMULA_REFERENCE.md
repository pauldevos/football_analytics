# DPVS-G Formula Reference

A single-page reference for every formula and sub-formula behind DPVS-G
(Defensive Player Value Score, Gamebook-Enhanced), current as of
`docs/framework_decisions.md` §26/§27. This is a reference, not a decision
log — read `framework_decisions.md` for the "why" behind each choice;
this file is only the "what," kept in sync as the live code changes.

DPVS-G has two independent layers, blended at the end:

```
DPVS-G = 0.25 · TCS_z + 0.75 · IDI_z          (both z-scored within season only)
```

(`dpvs/composite.py`, `_W_NO_WOWY`). WOWY (a third, "with or without you"
layer) is fully excluded from the live formula — see framework_decisions.md
§21/23 for why (pooled YoY r=0.023, effectively no signal).

---

## Layer 1: TCS (Team Credit Share)

**What it measures:** how much of the team's real defensive performance
this specific player is responsible for, in a specific game.

### Step 1 — Team-level "points earned" per game (`dpvs/run_pass_points.py`)

For a (game, defending team), "expected" = that SPECIFIC OPPONENT
OFFENSE's own leave-one-out (LOO) season average — never blended with a
league average, never the defense's own typical level.

```
pass_points_earned = z_season( any_a_expected − any_a )
run_points_earned  = z_season( (rush_yards_expected − rush_yards) / rush_yards_expected )
```

- `any_a = (pass_yds − sack_yds_lost + 20·pass_tds − 45·pass_ints) / (pass_att + times_sacked)`
- `z_season(x)` = z-score of x within that season only, across every game
  in the league that season (not within team, not within position)
- Both formulas are single-stat — completion%, sack rate, pass-yards, and
  YPC were all tested and dropped (redundant with ANY/A, or too weak
  standalone against the validated target — see framework_decisions.md
  §24.3 for the full correlation table and the reasoning for switching the
  validation target from win/loss to points allowed)

### Step 2 — Fixed group-role credit (`dpvs/position_credit.py`) — REDESIGNED 2026-08-24

**This step was fully rewritten 2026-08-24 (framework_decisions.md §26).**
The individual-production-based share-splitting mechanism this section
used to describe (`run_share`/`pass_share`, weighted by a player's own
sacks/tackles/run stuff that game) is REMOVED — per the user's explicit
instruction, weighting TCS credit by a player's own game production
double-counted the same production IDI (Layer 2) already rewards.

```
player_run_credit  = run_tier_points(role)  × run_points_earned  × run_role_share
player_pass_credit = pass_tier_points(role) × pass_points_earned × pass_role_share
team_credit_share    = player_run_credit + player_pass_credit
```

- `run_tier_points`/`pass_tier_points` — FIXED point values per (scheme,
  phase, role), from `dpvs/position_weights.py`'s `ROLE_TABLES` (see below)
  — do not scale with anything the player did that game.
- `role_share` — a CAPACITY-based proration (not production, not real
  snap counts — this project has no per-game snap data for any era,
  confirmed directly; capacity/headcount is the finest real granularity
  available): `min(1.0, role_capacity / n_players_sharing_this_role_
  this_game)`. Normal case (role fully staffed) → 1.0 (full value,
  un-prorated). Genuine in-game substitution (2 players share one
  single-capacity role, e.g. an injured NT replaced mid-game) → the
  role's point value splits evenly among them.
- 1-technique/3-technique DT identity resolved via `dpvs/
  dt_technique_overrides.json` (`dpvs/dt_technique.py`) — evidence-cited,
  name-level citations only (16 players, from `docs/deferred/
  09_dl_technique_research_pilot_20260823.md`); every other 4-3 DT
  defaults to the "(other) DT" bucket, never a stats-based guess.

**Fallback rule (unchanged):** unknown scheme for a team-season → the
whole side falls back to the original flat `tdgs / n_participants` split
for every participant that game. Known scheme, unresolved individual
position → just that player falls back, teammates with a resolved
position still get the fixed-role computation.

---

## Layer 2: IDI (Individual Disruption Index)

**What it measures:** a player's individual defensive production,
compared to the WHOLE LEAGUE that season (never position-relative, per
the user's explicit rule — "There shouldn't be ANY z-score by position at
all for these stats").

### Step 1 — Empirical-Bayes shrinkage per rare-event stat (run stuff, INT, FF, FR, sack)

```
shrunk_rate = (n_obs · observed_rate + k · prior_rate) / (n_obs + k)
k = 8.0 / (φ − 1.0)
```

- `φ` (phi) = the stat's measured overdispersion (real skill-signal
  strength vs. pure chance; φ=1 means no signal at all)
- `prior_rate` = the player's own career rate as of the prior season (if
  ≥8 games of career history exist), else the season-wide population rate,
  else a dataset-wide fallback

| Stat | φ (measured) | k (derived) |
|---|---|---|
| tackle | 4.872 | 2.07 |
| sack | 2.126 | 7.10 |
| run_stuff | 2.69 | 4.73 |
| int | 1.57 | 14.04 |
| ff | 1.32 | 25.00 |
| fr | 1.08 | 100.00 (extreme shrinkage — almost no repeatable skill signal, per-player FR is pulled hard toward the population/career prior) |

### Step 2 — Blend rate with volume

```
component_z = 0.5 · z_season(shrunk_rate) + 0.5 · z_season(raw_count)
```

Both halves z-scored WITHIN SEASON ONLY (not season × position_group —
the §20 fix; z-scoring within a narrow same-position peer group let a
rare event in a low-variance group produce an extreme, misleading z-score
— the Donnie Shell 1978 sack_component_z=4.0 bug).

### Step 3 — Weighted sum

```
IDI = 0.269·sack_component_z + 0.224·run_stuff_component_z + 0.179·tackle_share_z
    + 0.112·ff_component_z + 0.108·int_component_z + 0.108·fr_component_z
```

(`dpvs/idi.py`'s `_W_BASE`, sums to 1.000). These weights come from
real event value derived from PFR's own EPA data
(`exp_pts_before`/`exp_pts_after` in `pbp.csv`) — NOT from φ/skill-
consistency, which was explicitly rejected as a weighting input (see
framework_decisions.md §22 — "that analysis and those metrics have no
business being at all involved in this... I don't care if he has 20
interceptions one year and none for the rest of his career, he's gonna
get credit for those interceptions").

### Step 4 — Season-only z-score, applied to the finished IDI value

`idi_z` (used in the outer DPVS-G blend) is `z_season(IDI)` — again,
within season only, full league, not position-grouped. This is the
`composite.py` fix from §24.1 (the identical bug to Step 2 above, found
one layer up).

---

## Layer 3: DPVS-G composite (`dpvs/composite.py`)

```
tcs_z  = z_season(team_credit_share)
idi_z  = z_season(IDI)
DPVS-G = 0.25 · tcs_z + 0.75 · idi_z
```

Two other variants exist in the same module but are not the primary
metric:
- **DPVS-A** (individual-weighted): `(0.25·tcs_z + 0.50·idi_z) / 0.75`
- **DPVS-P** (positional run/pass split): replaces `tcs_z` with `ptcs_z`
  (a position-weighted blend of team run/pass defensive quality, distinct
  from TCS's own game-level mechanism above)

---

## A separate, EMPIRICALLY-FIT additive formula (NOT yet live in `idi.py`)

Superseded by real data-derived weights, 2026-08-23, same day — see
framework_decisions.md §25 for the full derivation, validation, and honest
caveats. This section previously described a HAND-PICKED test variant
(FF=0.133/INT=0.150, weights summing to 1.0) tried against the Jack Ham/
Dwight White 1972 discussion; the user explicitly rejected that approach
("I don't want it hand-picked... I want it fit properly") in favor of a
genuinely additive formula — RAW season counts, no "sum to 1.0" constraint
(the user's own analogy: "a 3-point shot is worth 3 points, full stop") —
with weights derived via `sklearn.LogisticRegression` against real AP
All-Pro recognition, 1999-2024 (PFR's own OFFICIAL season-defense tables,
not football_db's Postgres per-game path — see §25.1 for a real,
previously-undocumented data-sourcing bug found while confirming this):

```
score = 0.0225·tackle_total + 0.2358·sacks + 0.1338·pfr_tfl + 0.1671·ff
      + 0.1227·fr + 0.6808·int          (intercept -7.4315, logistic-only)
```

INT's weight (0.68) is roughly 3x any other stat's — the single strongest
real predictor of AP All-Pro selection in the fitting data, not an
artifact. Validation (§25.3): 50.5% of real AP All-Pro defensive
player-seasons land in the model's own top-30 that season (aggregate,
1999-2024); model's own #1 defender matches the real DPOY winner in 8/26
seasons (30.8%). Out-of-sample on the three team-seasons this whole line of
work started from (§25.4): CONFIRMS Ham above White in 1972 (wider margin
than the hand-picked version, in fact); COMPLICATES the 1974 finding —
Ernie Holmes actually ranks above Joe Greene under the real fitted weights,
the opposite of every hand-picked version tried; and puts Charlie West
(7 INT) above Alan Page in 1971 despite Page's real 1971 NFL MVP award —
a plain, reported-not-smoothed-over disagreement with historical
recognition, directly traceable to the INT weight above.

Not yet adopted into the live `_W_BASE` — under discussion. Full derivation,
per-season tables, and file list: framework_decisions.md §25.

---

## Fixed group-role point tables (`dpvs/position_weights.py`'s `ROLE_TABLES`) — 2026-08-24 REDESIGN

Replaces the "Position-group weight tables" this section used to describe
(proportions summing to 1.0, split by individual production). These are
POINT UNITS, not proportions — they do not sum to 1.0. `pts` = the fixed
value a player in that role gets; `cap` = how many players normally share
that exact role label in one team's one game (used for `role_share`'s
capacity-based proration — see Layer 1 Step 2 above).

**3-4 RUN** (verbatim from the user)

| Role | pts | cap |
|---|---|---|
| NT | 4.00 | 1 |
| MLB (each) | 2.00 | 2 |
| DE (each) | 1.50 | 2 |
| SS | 0.75 | 1 |
| OLB (each) | 0.75 | 2 |
| FS, CB (each, pooled) | 0.25 | 3 |

**3-4 PASS** (verbatim from the user)

| Role | pts | cap |
|---|---|---|
| OLB (each) | 3.00 | 2 |
| DE (each; pools 2×DE + 1×NT*) | 3.00 | 3 |
| CB, FS (each; pooled "DB"*) | 2.00 | 3 |
| SS | 1.00 | 1 |
| MLB (each) | 0.25 | 2 |

\* pre-existing judgment calls from the §21 fine-position mapping (3-4 NT
has no dedicated PASS row in the given table, pooled under DE as the
closest interior-lineman analog; 3-4's CB/FS can't always be told apart
from raw position data, pooled as "DB" — both get the same 2.0 value so no
real distinction is lost here).

**4-3 RUN** (DERIVED — NOT given as explicitly; r=0.65 tier-decay anchored
to point total=14.0, matching 3-4 RUN's own value×capacity sum; DE
inserted as a judgment call — the user's given tier list omitted it
entirely, treated as a spec gap not an intentional zero-credit omission,
see framework_decisions.md §26.3)

| Role | pts | cap |
|---|---|---|
| 1-technique DT/NT | 4.036 | 1 |
| (other) DT | 2.623 | 2 |
| DE (each) | 1.705 | 1 (2 if side unknown) |
| MLB | 1.108 | 1 |
| OLB (each) | 0.720 | 1 (2 if side unknown) |
| SS | 0.468 | 1 |
| FS, CB (each, pooled) | 0.304 | 3 |

**4-3 PASS** (DERIVED — same r=0.65 method, point total=19.5 matching 3-4
PASS's sum; "(other) DT" given the LOWER of the two DT values since the
user's tiers named no explicit "(other)" bucket for PASS — a judgment
call, not an assumption of pass-rush credit without a citation)

| Role | pts | cap |
|---|---|---|
| DE (each) | 2.946 | 2 |
| 3-technique DT (confirmed only) | 2.946 | 1 |
| CB | 1.915 | 2 |
| FS | 1.915 | 1 |
| SS | 1.245 | 1 |
| ROLB | 1.245 | 1 |
| LOLB | 0.809 | 1 |
| 1-technique DT/NT (confirmed) | 0.809 | 1 |
| (other) DT (uncited default) | 0.809 | 2 |
| MLB | 0.809 | 1 |

**1-technique/3-technique DT resolution**: `dpvs/dt_technique.py` +
`dpvs/dt_technique_overrides.json` — 16 players, each individually
confirmed by name in `docs/deferred/
09_dl_technique_research_pilot_20260823.md`, evidence-cited. Every other
4-3 DT defaults to "(other) DT," never a stats-based guess. Full player
list and the two explicitly-excluded names (Merlin Olsen, Randy White):
framework_decisions.md §26.4.

**Derivation method**: 3-4 tables are literal, user-given numbers, not
derived. 4-3 tables use the SAME r=0.65 geometric tier-decay formula this
project already established for the old proportional tables
(`build_weight_table()`/`TIER_STRUCTURE` in `position_weights.py`),
anchored to a fixed point-unit total instead of a 1.0 proportion — full
worked derivation and both judgment calls (DE's insertion into 4-3 RUN,
the "(other) DT" PASS default): framework_decisions.md §26.3.

The OLD proportional tables (`PRODUCTION_TABLES`, summing to 1.0, split by
individual production share) are retained in `position_weights.py`,
UNUSED by production code, as historical reference only.

---

## INT trailing-window smoothing (`dpvs/int_smoothing.py`) — standalone, not live

2026-08-24 (framework_decisions.md §27), independent of the TCS redesign
above. Replaces a season's raw INT count with the average of that season
plus the prior N−1 seasons (strictly trailing, no look-ahead), tested by
substituting it into §25's fitted additive formula in place of raw `int`.
**N=5 validated better than N=7** (same DPOY-#1-agreement rate, higher
top-30-vs-AP-All-Pro hit rate) — both real, both correctly drop Charlie
West's outlier 1971 season from #1 to #10/28 on his own team while
IMPROVING Paul Krause's rank (a genuinely sustained producer, same
team-season). NOT wired into `dpvs/idi.py` or any live formula — same
standing as §25's additive formula, a validated alternative for a future
adoption decision. Full validation table and the Charlie West/Paul Krause
before-after: framework_decisions.md §27.

---

## Files

- `dpvs/idi.py` — IDI (Layer 2)
- `dpvs/run_pass_points.py` — per-game team run/pass points-earned
- `dpvs/position_credit.py` — fixed group-role credit split (TCS Step 2, redesigned 2026-08-24)
- `dpvs/position_weights.py` — `ROLE_TABLES` (live) + old `PRODUCTION_TABLES` (unused, historical)
- `dpvs/dt_technique.py` / `dpvs/dt_technique_overrides.json` — 1-tech/3-tech DT resolution
- `dpvs/int_smoothing.py` — INT trailing-window smoothing (standalone, not live)
- `dpvs/composite.py` — the outer z-scoring + DPVS-G/A/P blend
- `scripts/build_dpvs_g.py` — full pipeline entry point
- `scripts/load_dpvs_g_to_db.py` — Postgres loader (`gold.dpvs_g_player_season`)
- `scripts/build_int_smoothing_validation.py` — INT smoothing validation (N=5/N=7 vs. raw)
