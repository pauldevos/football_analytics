# TCS Mechanism, Fully Explained (2026-08-22)

Pure documentation of the **current, as-built** TCS (Team Credit Share) pipeline —
no design changes, no recommendations baked in. Every number below is pulled
live from the actual parquet files (`~/data/silver/game_defense.parquet`,
`player_game_defense.parquet`, `dpvs_g_player_season.parquet`) and cross-checked
by re-running the real formulas by hand. Where a formula is quoted, it is copied
verbatim from the source file with its line reference.

---

## 1. `tdgs` — Team Defense Game Score (`scripts/build_game_defense.py`)

### 1.1 What it measures

One number per (game, defending team): how good was this team's defense in
this one game, adjusted for (a) the league-wide scoring/yardage environment
that season and (b) how good the specific opponent's offense is on average.
It is **not** player-specific — it describes the team's defensive performance
for that game, full stop. Everything downstream (credit split, WOWY) is built
on top of this single number.

### 1.2 The formula, term by term

From `_compute_tdgs()` (`scripts/build_game_defense.py:332-373`):

```python
yds_credits = []
if lg_avg_yds is not None:
    yds_credits.append(lg_avg_yds - yds_allowed)
if opp_avg_yds is not None:
    yds_credits.append(opp_avg_yds - yds_allowed)
yds_z = (sum(yds_credits) / len(yds_credits)) / lg_std_yds

pts_credits = []
if lg_avg_pts is not None:
    pts_credits.append(lg_avg_pts - pts_allowed)
if opp_avg_pts is not None:
    pts_credits.append(opp_avg_pts - pts_allowed)
pts_z = (sum(pts_credits) / len(pts_credits)) / lg_std_pts

TDGS = round(0.55 * yds_z + 0.45 * pts_z, 4)
```

In plain terms, when both benchmarks are available (the normal case):

```
yds_credit = 0.5 × (lg_avg_yds − yds_allowed) + 0.5 × (opp_avg_yds − yds_allowed)
pts_credit = 0.5 × (lg_avg_pts − pts_allowed) + 0.5 × (opp_avg_pts − pts_allowed)

yds_z = yds_credit / lg_std_yds
pts_z = pts_credit / lg_std_pts

TDGS  = 0.55 × yds_z + 0.45 × pts_z
```

**What each term is and where it comes from:**

| Term | Meaning | Source |
|---|---|---|
| `total_yds` (`yds_allowed`) | Total yards this team's defense gave up **this game** — the offense's `Total Yards` line from `team_stats.csv`, or rush+pass if that field is missing | `scripts/build_game_defense.py:_parse_team_stats()`, reading `~/data/pfref/raw/boxscores/{season}/{game}/team_stats.csv` |
| `pts_allowed` | Points the opposing offense scored this game | Final score from `scoring.csv`, falling back to `pbp.csv`'s last row (`_get_game_scores()`) |
| `opp_avg_yds` / `opp_avg_pts` | The **specific opponent's own season-average** offensive yards/points per game (not this game's number — their full-season rate) | `_load_opp_averages()`, reading `~/data/pfref/raw/season/team/offense/team_stats_{season}.csv` and `team_scoring_{season}.csv` |
| `lg_avg_yds` / `lg_avg_pts` | **League-wide** average offensive yards/points per game that season (mean across all teams) | `_load_league_averages()`, same source files, averaged over every team |
| `lg_std_yds` / `lg_std_pts` | **League-wide** standard deviation of team offensive yds/g and pts/g that season — this is what turns the credit into a z-score | Same `_load_league_averages()` call, `.std()` over all teams |

**Reading the math:** `lg_avg_yds − yds_allowed` is positive when the defense
held the opponent below what a league-average offense normally gains — i.e.
"vs. league" credit. `opp_avg_yds − yds_allowed` is positive when the defense
held *this specific* opponent below what *that opponent* normally gains — i.e.
"vs. this opponent's own baseline" credit (this is the "opponent-adjusted"
part — holding a run-heavy 400-yd/g offense to 250 yards is worth more than
holding a 260-yd/g offense to 250). The two credits are averaged 50/50, then
divided by that season's league-wide standard deviation to turn "yards saved"
into a z-score — so the units are standard deviations of team offensive output
that season, not raw yards. Same logic for points. The final blend weights
yards at 0.55 and points at 0.45 (a hand-set weighting, not derived from a
fit). If `opp_avg_yds`/`opp_avg_pts` is unavailable (e.g. an AFL team pre-1970
data gap), the credit silently falls back to the league-only term (list of
length 1 instead of 2) — see the `if lg_avg_yds is not None` / `if
opp_avg_yds is not None` branches above.

### 1.3 Worked example — Pittsburgh Steelers defense, 1976-10-04 @ MIN

Real numbers, re-derived by hand from `~/data/pfref/raw/season/team/offense/team_stats_1976.csv`
and `team_scoring_1976.csv`, and confirmed to match the stored parquet value exactly:

```
1976 league:  avg_yds = 302.70/g   std_yds = 44.28
              avg_pts = 19.15/g    std_pts = 4.99

MIN offense season averages: 347.0 yds/g,  21.8 pts/g

This game (PIT defense vs MIN):  178 total yards allowed,  17 points allowed

yds_credit = 0.5×(302.70 − 178) + 0.5×(347.0 − 178) = 62.35 + 84.50 = 146.85
yds_z      = 146.85 / 44.28 = 3.3161

pts_credit = 0.5×(19.15 − 17) + 0.5×(21.8 − 17) = 1.075 + 2.400 = 3.475
pts_z      = 3.475 / 4.99 = 0.6967

TDGS = 0.55×3.3161 + 0.45×0.6967 = 1.8239 + 0.3135 = 2.1374
```

This matches `game_defense.parquet`'s stored `tdgs = 2.1374` for
`game_id=197610040min, team=pit` exactly.

### 1.4 `_get_defense_participants()` — who "participated"

From `scripts/build_game_defense.py:278-327`. Builds a `{pfr_player_id: attrs}`
dict per (game, defending team) via two additive rules — a player qualifies if
**either** is true:

1. **Named starter.** Every row in that game's `starters.csv` for the
   defending team, excluding offensive position codes (the `_OFF_POS`
   frozenset — QB/RB/WR/TE/OL/K/P/etc.). These are added with
   `stat_events = 0` initially and `is_starter = True`.
2. **≥ `MIN_STAT_EVENTS` (= 4) stat events** in that game's
   `player_defense.csv`, if not already added as a starter. `_count_stat_events()`
   (line 246) sums: `sacks≥0.5 → 1` + interceptions + fumble recoveries +
   forced fumbles + combined tackles (solo+ast). A player already counted as a
   starter has their `stat_events` field updated to this count (for reporting
   only — it does not affect whether they're included; starters are in
   regardless of their stat count).

So a starter who recorded zero defensive stats that game (e.g. a corner who
covered but was never targeted) still counts as a participant. A bench player
who came in and racked up real production (≥4 stat events) also counts, even
without a starters.csv row. `player_defense.csv` is filtered to the defending
team's rows via `_filter_pdef_team()`, which handles a team-code mismatch
between `player_defense.csv` (NFL/media codes like `RAI`, `BAL`) and
`team_stats.csv` (PFR internal codes like `rai`, `rav`) by direct lowercase
match first, then falls back to excluding the known offensive team's code.

**Important limitation for pre-2001 seasons:** `player_defense.csv` tackle
columns are blank before 2001, so `_count_stat_events()` effectively can't
find non-starter participants from tackles pre-2001 — participation for those
years defaults almost entirely to the starters list. Confirmed empirically:
across the whole corpus, starters average only 2.2 stat events recorded per
game (median 0 — most starters' games show `stat_events=0` even though they
obviously played), while the smaller set of non-starters added via the
stat-events rule average 5.1 (min 4, since that's the qualifying threshold).
`stat_events` is bookkeeping/reporting metadata; it plays no role in sizing
the credit each participant receives (see §2).

`n_participants` (`n_parts` in the build loop) across the whole corpus:
median 11, mean 11.6, std 1.08, range 1–21 — i.e. it's usually close to (but
not fixed at) an 11-man defensive lineup, varying with how many starters were
listed and how many bench players cleared the stat-event bar that game.

---

## 2. The credit split — `credit = tdgs / n_parts`

From `scripts/build_game_defense.py:487-503`:

```python
n_parts = len(parts)
credit  = round(tdgs / n_parts, 5) if (tdgs is not None and n_parts > 0) else None
```

This is written **identically to every participant** in `parts` — there is no
position term, no stat_events weighting, no starter/bench distinction in the
divisor or the credit value itself. It is a flat equal split of the team's
single game score across everyone who qualified as a participant.

### 2.1 Confirmed with real data — PIT defense, 1976-10-04 @ MIN, all 11 participants

`game_id = 197610040min`, `team = pit`, `tdgs = 2.1374`, `n_participants = 11`:

| Player | Pos | is_starter | stat_events | team_credit_share |
|---|---|---|---|---|
| L.C. Greenwood | LDE | True | 0 | 0.19431 |
| Joe Greene | LDT | True | 0 | 0.19431 |
| Ernie Holmes | RDT | True | 0 | 0.19431 |
| Dwight White | RDE | True | 0 | 0.19431 |
| Jack Ham | LLB | True | 0 | 0.19431 |
| **Jack Lambert** | MLB | True | **1** | 0.19431 |
| Andy Russell | RLB | True | 0 | 0.19431 |
| J.T. Thomas | LCB | True | 0 | 0.19431 |
| Mel Blount | RCB | True | 0 | 0.19431 |
| Mike Wagner | SS | True | 0 | 0.19431 |
| **Glen Edwards** | FS | True | **1** | 0.19431 |

`2.1374 / 11 = 0.194327...`, rounded to `0.19431` — every row. Lambert (MLB,
run-stopper) and Edwards (FS, coverage) each recorded 1 stat event that game;
the other nine recorded 0; every one of the eleven receives the exact same
credit. This confirms the split is genuinely position-blind and
production-blind within a game — the *only* thing that determines a player's
share of a given game's credit is whether they cleared the participation bar
at all (§1.4), not how much they individually did once they cleared it.

---

## 3. `dpvs/tcs.py` — season aggregation and `tcs_z`

### 3.1 Season aggregation (`aggregate_tcs()`, `dpvs/tcs.py:130-155`)

```python
grp = player_game_df.groupby(
    ["season", "team", "pfr_player_id", "player_name", "pos"], as_index=False
).agg(
    games_played=("game_id", "count"),
    total_credit=("team_credit_share", "sum"),
)
grp["per_game_credit"] = (grp["total_credit"] / grp["games_played"]).round(5)
```

`total_credit` = the **sum** of `team_credit_share` across every regular-season
game the player participated in that season (games not participated in
contribute nothing — not a penalty, not a zero-fill row, simply absent from
the sum). `per_game_credit` is the mean of that same set. `games_played` is a
plain count of rows, i.e. games the player qualified as a participant in.

Real example — Jack Lambert, 1976, Pittsburgh: 14 regular-season games in
`player_game_defense.parquet`, `total_credit = 2.12972`,
`per_game_credit = 0.15212` (`2.12972 / 14 = 0.152123`, confirmed).

### 3.2 `tcs_z` — exact grouping (`dpvs/composite.py:107-137`, `z_score_components()`)

```python
for season, grp in df.groupby("season"):
    for pg in df["position_group"].unique():
        mask = (df["season"] == season) & (df["position_group"] == pg)
        sub = df.loc[mask]
        df.loc[mask, "tcs_z"] = _zscore_within(sub["total_credit"]).clip(-4, 4).values
```

**Confirmed: `tcs_z` is a standard z-score `(x − mean) / std` computed within
(season × position_group) — season alone is NOT the grouping.** Position group
is one of exactly three buckets (`dpvs/positions.py`):

- `run_stopper` — DT/NT/DL, and all interior/middle LBs (MLB, ILB, LLB, RLB, etc.)
- `pass_rusher` — DE, and OLB (outside linebacker defaults here, not run_stopper)
- `coverage` — CB, S, DB

So a DT's `total_credit` is z-scored only against other DTs/NTs/interior-LBs
league-wide *that season*, not against the whole league or against DBs.
`total_credit` is the input to `tcs_z` — not `per_game_credit`, and the raw
score is winsorized (clipped) at ±4σ before being used further, to keep a
single outlier season from distorting the group's whole distribution.

**Verified by hand for Lambert 1976** (position_group = `run_stopper`, n=142
qualifying run-stoppers that season): group mean `total_credit = 0.00750`,
group std = `1.01302`. `(2.12972 − 0.00750) / 1.01302 = 2.094941` — matches the
stored `tcs_z = 2.094941` exactly (well under the ±4σ clip, so it's unaffected
by winsorization here).

Note the min-games filter runs *before* z-scoring (`build_composite()`,
`dpvs/composite.py:286-287`): players with `games_played < 6` (default) are
dropped from the pool entirely, so they neither get scored nor affect anyone
else's mean/std that season.

---

## 4. WOWY — current role and honest assessment

### 4.1 Methodology (`dpvs/wowy.py`)

```python
avg_tdgs_in  = mean(tdgs for games this player participated in, that season)
avg_tdgs_out = mean(tdgs for the team's other regular-season games that season)
wowy_delta   = avg_tdgs_in − avg_tdgs_out     # None if games_out == 0
```

Grouped by `(season, pfr_player_id, player_name, team)`. `games_in` is
whatever `player_game_defense.parquet` already has for that player (built by
the same `_get_defense_participants()` participation rule from §1.4).
`games_out` = team's regular-season games that season minus `games_in`. If a
player played every one of their team's games that season, `games_out = 0`
and `wowy_delta` is `None` — there is no "without" sample to compare against.

`wowy_z` (`dpvs/composite.py:129-135`) z-scores `wowy_delta` the same way as
`tcs_z`/`idi_z` — within (season × position_group), winsorized ±4σ — but only
computed for a group if it has ≥3 non-null `wowy_delta` values; otherwise the
whole group's `wowy_z` stays `NaN`.

**Real-data note:** across the full parquet, `wowy_z` is non-null for 61.8%
of player-seasons (12,694 / 20,534) — the rest, including Lambert's 1976
season (`games_out = 0`, he started all 14), have no WOWY signal at all and
fall back to the no-WOWY composite weights.

### 4.2 How it feeds the composite (`dpvs/composite.py:41-46, 142-161`)

```python
_W_FULL    = {"tcs_z": 0.50, "idi_z": 0.30, "wowy_z": 0.20}   # used when wowy_z is not NaN
_W_NO_WOWY = {"tcs_z": 0.60, "idi_z": 0.40}                    # used when wowy_z is NaN
```

`_compute_dpvs_g_row()` checks `pd.notna(wowy_z)` per row: if present, WOWY
gets a flat 20% weight and TCS/IDI are rescaled down (0.50/0.30); if absent,
the formula silently rebalances to TCS/IDI only (0.60/0.40), with no gap or
penalty for missing it. This is a row-level (player-season-level) branch, not
a global toggle — two players in the same season/position group can be scored
under different formulas depending on whether either one has a `games_out=0`
season. `DPVS-A` and `DPVS-P` apply the same present/absent branch with their
own weight sets (`_WA_FULL`/`_WA_NO_WOWY`, `_WP_FULL`/`_WP_NO_WOWY`).

### 4.3 YoY stability — restated with a source pointer

`scripts/yoy_stability_check.py` (committed) computes pooled year-over-year
Pearson r for `idi_z` and the no-WOWY composite, but as shipped it does
**not** include `wowy_z` — no committed script or doc currently states a WOWY
stability number. To answer this section honestly, the same pooled-pairs
methodology (every same-player season N → season N+1 pair, pooled across the
whole corpus, one Pearson r) was applied directly to `wowy_z` from
`~/data/silver/dpvs_g_player_season.parquet` for this document:

```
Pooled (season N, season N+1) wowy_z pairs: n = 4,900
wowy_z pooled YoY Pearson r = 0.0227
```

This reproduces the "r=0.023" figure referenced in this session's prior
discussion. For comparison, `idi_z`'s pooled YoY r (from the committed script,
full corpus) is materially higher — see `docs/framework_decisions.md` §17-19
for the exact current value, which has moved across several IDI revisions
this session; the qualitative point that matters here is that WOWY's 0.023 is
close to zero — a player's `wowy_delta` this season predicts almost nothing
about their `wowy_delta` next season.

### 4.4 Assessment (evidence only — no recommendation made here)

**In favor of keeping it:**
- It is cheap to compute — reuses the same `tdgs` numbers already built for TCS, no new data source.
- Conceptually it targets something TCS's flat split structurally cannot see: whether the *team* defense is measurably worse in the games this specific player misses (an availability/impact signal, not a per-play stat).
- It only ever adds 20% weight and never actively penalizes a player for lacking it — the no-WOWY fallback is a clean no-op, not a missing-data penalty.

**Against / grounds for skepticism:**
- r=0.023 YoY is close to what pure noise would produce — a metric with essentially no persistence season to season is a weak candidate for describing a stable, real player quality ("skill"), as opposed to schedule/injury noise (who else was hurt those specific weeks, which specific opponents were faced with/without this player, etc.).
- It's `NaN` for 38.2% of player-seasons outright (anyone who played every game), and structurally biased toward rewarding players who missed games over players who did not — a durable, always-active player who never has a "without" sample gets no WOWY credit at all, while a similar player who missed 3 games due to injury gets a shot at a positive `wowy_delta`.
- Small `games_out` samples (many players are missing only 1-3 games — 25th percentile of `games_out` among non-null rows is 2) mean `avg_tdgs_out` is often estimated from very few team-games, which is a plausible mechanical explanation for why the year-over-year signal doesn't hold up — a small sample of "the games he missed" is inherently noisy and not obviously about the player at all (it reflects whatever else happened to the team, e.g. the tdgs of an entirely different set of opposing offenses).
- Both the TDGS "with" and "without" sides being pure team defense numbers means WOWY, like TCS, is not actually isolating this player's individual contribution — it's asking "was the team defense better when he happened to be on the field," which is confounded by every other lineup change (injuries, opponent strength, weather) that also varies between the "in" and "out" game sets.

This is direct input to "is WOWY pulling its weight" — the low YoY stability
number is real and reproducible, and the mechanical reasons for it (thin
"out" samples, confounding with every other lineup/schedule variable) are
visible in the data. Whether that's disqualifying is a design call for the
user to make, not this document.

---

## 5. Full worked example — Jack Lambert, MLB, Pittsburgh Steelers, 1976

End-to-end trace, every number pulled from the actual pipeline output.

### Step 1 — one game's TDGS (§1.3 above, PIT defense @ MIN, 1976-10-04)

```
178 total yards allowed, 17 points allowed
vs. league avg (302.70 yds, 19.15 pts) and MIN's own offense avg (347.0 yds, 21.8 pts)
→ TDGS = 2.1374
```

### Step 2 — that game's credit split (§2.1 above)

```
11 defensive participants that game (the full Steel Curtain starting defense)
credit = 2.1374 / 11 = 0.19431 for every one of the 11, including Lambert
```

### Step 3 — season aggregation (`dpvs/tcs.py`)

Lambert's 1976 `player_game_defense.parquet` rows (14 regular-season games;
2 more rows exist in the full table but are playoff games filtered out by
`is_regular_season`):

```
game_id        tdgs      team_credit_share
197609120rai  -2.0877   -0.18979
197609190pit   0.2581    0.02346
197609260pit  -1.6224   -0.14749
197610040min   2.1374    0.19431   ← Step 1/2 above
197610100cle  -0.0530   -0.00482
197610170pit   3.0633    0.27848
197610240nyg   3.0530    0.27755
197610310pit   3.8539    0.35035
197611070kan   2.6149    0.23772
197611140pit   2.4841    0.22583
197611210pit   0.8065    0.07332
197611280cin   2.6632    0.24211
197612050pit   3.1739    0.28854
197612110oti   3.0816    0.28015
```
(2 further games in the raw table, `197612190clt` and `197612260rai`, are
playoff games and excluded from the regular-season sum below.)

```
total_credit    = sum of the 14 rows above = 2.12972
games_played    = 14
per_game_credit = 2.12972 / 14 = 0.15212
```

### Step 4 — `tcs_z` (§3.2 above)

```
position_group = run_stopper (MLB)
1976 run_stopper pool: n=142, mean total_credit=0.00750, std=1.01302
tcs_z = (2.12972 − 0.00750) / 1.01302 = 2.094941
```

### Step 5 — `idi_z` (IDI layer — not modified or re-derived here, quoted as stored)

```
idi (season aggregate individual-defense index) = 1.510816
1976 run_stopper pool: mean idi=0.10605, std=0.49321
idi_z = (1.510816 − 0.10605) / 0.49321 = 2.848192
```

### Step 6 — WOWY

```
games_out = 0 (Lambert started all 14 regular-season games)
→ wowy_delta = None, wowy_z = NaN  (no "without Lambert" sample exists)
```

### Step 7 — final composite (`dpvs/composite.py`, no-WOWY branch, since wowy_z is NaN)

```
DPVS-G = 0.60 × tcs_z + 0.40 × idi_z
       = 0.60 × 2.094941 + 0.40 × 2.848192
       = 1.256965 + 1.139277
       = 2.396242  →  stored dpvs_g = 2.3962
```

Confirmed against the stored row: `season_pos_rank = 1`,
`season_overall_rank = 1` — Lambert 1976 is the #1 run-stopper and #1
defender overall in the dataset that season under the current formula, driven
almost equally by TCS (team-context, position-blind flat-split credit) and
IDI (individual gamebook-tackle-derived index), with zero WOWY contribution
because he played every game.

---

## Source files referenced

- `scripts/build_game_defense.py` — `_compute_tdgs()`, `_get_defense_participants()`, credit-split loop
- `dpvs/tcs.py` — `aggregate_tcs()`, `load_or_build_player_game()`
- `dpvs/wowy.py` — `compute_wowy()`
- `dpvs/composite.py` — `z_score_components()`, `_compute_dpvs_g_row()`, weight constants
- `dpvs/positions.py` — `POSITION_GROUP` mapping
- `~/data/silver/game_defense.parquet`, `player_game_defense.parquet`, `dpvs_g_player_season.parquet` — all real numbers above pulled live from these
