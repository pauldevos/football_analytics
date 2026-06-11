# Offensive Player OQA — Opponent Quality Adjustment

## Overview

This framework computes **context-adjusted offensive stats** for individual players
by comparing each game's performance against what the opposing defense typically
allows — normalized using a leave-one-out (LOO) season average computed from the
**defense's** perspective.

It serves two purposes in the broader project:

1. **Companion to QB value analysis** — isolate how much of a QB's statistical
   output was driven by facing weak defenses vs. real per-snap efficiency.
2. **Input to DPVS** — when we credit a defense for suppressing an offense, we
   need to know how strong that offense was, and by extension how unusual a
   great individual offensive performance against them actually was.

---

## The Core Idea

For each player game, we compute:

```
delta = actual_stat − defense_LOO_average_allowed
```

Where `defense_LOO_average_allowed` is what that defense allowed in
all OTHER regular-season games that season (excluding the current game to
prevent circularity — the same leave-one-out approach used in the team-level
OQA for the defensive analysis).

**Key distinction from team-level OQA:** The team-level `oqa_game_detail` table
uses the *offense's* LOO average (what does this offense typically produce?).
This framework uses the *defense's* LOO average (what does this defense typically
allow?). Both are needed for the full picture.

**Sign convention:**

| Stat | Positive delta = | Negative delta = |
|------|-----------------|-----------------|
| Pass yards, rush yards, rec yards | Above what defense allows | Held below defense average |
| Pass TDs, rush TDs, rec TDs | Above what defense allows | Below defense average |
| Pass INTs (for QB) | More than defense forces | *Fewer* picks than defense forces — this is **good** for the QB |
| QB rating | Above what defense allows | Below defense average |

The INT sign convention surprises people: a QB who throws *fewer* picks than a
defense normally forces gets a *negative* `delta_pass_int`. Read it as "how much
better than expected did the defense do at forcing turnovers?"

---

## Position-Specific Methodology

### QB

Comparison is the most direct: one QB handles essentially all passing in a game,
so comparing their total pass yards to the defense's total pass yards allowed is
apples-to-apples.

**Metrics computed per game:**
- `delta_pass_yds` — actual passing yards minus defense's average allowed
- `delta_pass_td` — actual pass TDs minus defense's average allowed
- `delta_pass_int` — actual INTs thrown minus defense's average forced (negative = good for QB)
- `delta_qb_rate` — actual passer rating minus defense's average allowed rating

QB rating is computed from aggregated raw totals (completions, attempts, yards, TDs,
INTs), not as an average of per-game rates, so it's accurate across partial games
and multi-QB games.

**Season rollup:** Sum and per-game average of each delta. Also reports `avg_qb_rate`
(season rating recomputed from full-season totals).

---

### RB — The Carry-Adjusted Approach

**The naive approach fails.** The first attempt compared an individual RB's rush
yards to the defense's average team rush yards allowed per game. Even elite, high-volume
running backs came out deeply negative:

- Herschel Walker 1988 (1,514 yards): **−260** yards vs. defense averages
- Eric Dickerson 1988 (1,659 yards): **−320** yards
- Roger Craig 1988 (1,502 yards): **−405** yards

All negative because defenses allow ~110 rush yards per game *to the whole team*,
but even a featured back averages only ~90 yards per game. Multiple players share
team rushes; QBs scramble; fullbacks carry. Comparing one back to the team total
systematically punishes everyone.

**The Keith Byars case** made this explicit. Byars was a receiving back in the
1988 Eagles offense — primarily a blocker and check-down target. He only got
5–50 rushing yards in most games, but the Eagles faced defenses that allow 100+
rush yards per game to the entire team. The naive approach showed Byars at −1,297
yards for the season — a nonsensical result that told us nothing about his actual
effectiveness.

**The fix: carry-adjusted expected yards.** Instead of comparing to the defense's
average total rush yards, we compute:

```
expected_rush_yds = player_rush_att × defense_avg_rush_ypc_allowed
delta_rush_yds    = actual_rush_yds − expected_rush_yds
```

This answers the right question: **did this RB get more yards per carry than what
the defense typically allows?** It controls for how many carries the player had
and makes the comparison per-carry efficient rather than per-game volume.

**Results with carry-adjusted metric (1988 season, feature backs ≥8 primary games):**

| Player | Team | Rush Yds | Δ total | Δ/game |
|--------|------|---------|---------|--------|
| Ickey Woods | CIN | 1,066 | +276 | +18.4 |
| Roger Craig | SFO | 1,502 | +241 | +15.0 |
| Gary Anderson | SDG | 1,119 | +191 | +13.7 |
| Herschel Walker | DAL | 1,514 | +124 | +7.7 |
| Eric Dickerson | IND | 1,659 | +105 | +6.6 |
| Greg Bell | RAM | 1,212 | +52 | +3.2 |
| Joe Morris | NYG | 1,083 | −156 | −9.8 |

Dickerson's raw 1,659 yards drops to only +105 adjusted — he faced softer run
defenses than Craig (1,502 yards, +241). Ickey Woods in the Bengals' Super Bowl
run comes out #1.

**Barry Sanders 1997 (MVP season):**
- 2,053 rush yards, +712 carry-adjusted yards above expected
- Best individual game: 215 yards vs Tampa Bay, 24 carries against a defense
  allowing 3.51 YPC → expected 84.2 yards → **+130.8 above expected**
- Second-best game: 216 yards vs Indianapolis, +109.4 above expected

**Receiving for RBs:** Compared against the defense's average RB receiving yards
allowed per game (the position-group total, not carry-adjusted, since we don't
have target splits).

---

### WR

**The position group problem.** Teams typically play 3+ WRs per game, and receiving
stats are spread across the group. Comparing one WR's yards to the defense's total
WR yards allowed mixes apples and oranges: the #1 WR gets the best corner and
sometimes a safety, while the slot WR exploits linebacker/safety mismatches and
accumulates shorter catches. The 2007 New England Patriots are the canonical example:

- Randy Moss: 23 TD season, massive yards, takes the best CB + double coverage —
  the clear #1 WR
- Wes Welker: leads the team in receptions on short, underneath routes — the slot
  WR exploiting linebackers

By receptions, Welker looks like the #1 WR. By impact, Moss is unambiguously #1.
Any WR identification based on seasonal totals must account for this.

**Current state:** WR individual stats are stored in `player_game_offense` and
comparisons are made against the defense's total WR yards allowed. This is a
coarse estimate — the delta tells you more than nothing, but an individual WR's
delta vs. the full WR-group defensive average is noisy, especially for slot
receivers whose role is to accumulate short yardage.

**Planned: Season YPG-based #1 WR identification.** See Open Questions section
below for the planned approach.

---

### TE

More tractable than WR because most teams have a clear #1 TE who handles the
majority of routes and targets. The comparison is individual TE stats vs. the
defense's total TE yards allowed per game.

The `is_primary` flag marks the TE with the highest receiving yards for each
team in each game — useful for filtering to meaningful comparisons and for the
"opponent's #1 TE" calculation in future DPVS opponent matchup grades.

---

## Data Sources & Implementation

**ETL script:** `scripts/etl_player_game_offense.py`

```bash
# All seasons
python scripts/etl_player_game_offense.py

# Single season
python scripts/etl_player_game_offense.py --season 1988

# QA a specific player
python scripts/etl_player_game_offense.py --season 1988 --qa-player "Randall Cunningham"
python scripts/etl_player_game_offense.py --season 1997 --qa-player "Barry Sanders"
python scripts/etl_player_game_offense.py --season 2023 --qa-player "Travis Kelce"
```

**Outputs per season (in `data_output/`):**

| File | Description |
|------|-------------|
| `player_game_offense_{year}.csv` | One row per player per regular-season game with actual stats + delta columns |
| `defense_loo_avg_{year}.csv` | Per-game LOO average of what each defense allowed (defense perspective) |
| `player_oqa_season_{year}.csv` | Season rollup: totals and per-game averages of all deltas |

**Schema tables:** `player_game_offense`, `defense_loo_avg`, `player_oqa_season`
(see `schema/schema.sql`).

**Data coverage:** 1950–2025 wherever boxscore CSVs exist. Roster position lookup
(used to assign position_group) covers years with available PFR roster files.
Without roster data, `position_group` is unassigned and rows are excluded.

**Minimum thresholds:**
- QB: `pass_att >= 5` to count as a QB game (excludes scrambler stats, trick plays)
- RB: `rush_att >= 1 OR rec >= 1`
- WR/TE: `targets >= 1 OR rec >= 1`

**`is_primary` flag:** For each (game, team, position_group), marks the player
with the highest stat by position: pass_att (QB), rush_yds (RB), rec_yds (WR/TE).
Used to filter for meaningful individual comparisons, especially for TEs.

---

## Validated Test Cases

### Randall Cunningham, PHI 1988

| Metric | Actual | Avg Allowed | Δ total | Δ/game |
|--------|--------|------------|---------|--------|
| Pass yards | 3,808 | — | +207 | +12.9 |
| Pass TDs | 24 | — | +1.8 | +0.1 |
| INTs | 16 | — | −2.7 | −0.2 |
| QB rating | 77.6 | — | — | +3.1 |

Best game: vs NYG (week 5) — 369 yards, 3 TDs, 0 INTs, +143.3 yards above
NYG's defense average. NYG allowed 225.7 passing yards per game that season.

---

### Barry Sanders, DET 1997

| Metric | Actual | Δ total (carry-adj) | Δ/game |
|--------|--------|---------------------|--------|
| Rush yards | 2,053 | +712 | +44.5 |
| Rush TDs | 11 | −2.5 | −0.2 |

Peak game: 215 yards vs Tampa Bay (24 carries), defense allows 3.51 YPC →
expected 84.2 yards → **+130.8 above expected**. 

The −2.5 TD delta despite 11 rushing TDs indicates the defenses he faced were
above-average at preventing red-zone touchdowns — his raw rushing dominance was
even more remarkable in context.

---

### Herschel Walker, DAL 1988

| Metric | Actual | Δ total (carry-adj) | Δ/game |
|--------|--------|---------------------|--------|
| Rush yards | 1,514 | +124 | +7.7 |

Context: faced better run defenses than Dickerson (1,659 yards, +105). Walker's
raw total is lower but his carry-adjusted performance is meaningfully better.

---

### Travis Kelce, KAN 2023

| Metric | Actual | Δ total (vs TE group avg) | Δ/game |
|--------|--------|--------------------------|--------|
| Rec yards | 984 | +329.8 | +22.0 |
| Receptions | 93 | +27.6 | +1.8 |

Peak game: 179 yards vs LAC, defense allows 38.3 TE yards per game → **+140.7**.
15 games played; missed week 1 vs Detroit (27-yard output, the season low).

---

## Open Questions

### WR #1 Identification (planned)

The agreed approach: rank each team's WRs by **season yards per game** (total
rec_yds / games_played, not total yards — to handle injuries and missed games
correctly). The #1 WR is the player with the highest yards-per-game for the
season. For any specific game, check whether that WR played; if not, fall back
to the next-highest yards-per-game WR.

This works for the 2007 Patriots case: Moss accumulated far more yards per game
than Welker despite fewer receptions, correctly identifying him as the #1 WR.
It handles injuries: if Moss misses a game, Welker (or whoever is the highest
remaining YPG WR who played) becomes the game's #1 WR.

**Implementation steps:**
1. Compute `season_rec_yds_pg` = `total_rec_yds / games_played` for each WR season
   from `player_game_offense` grouped by `(season, team_abbrev, pfr_player_id)`
2. Rank within `(season, team_abbrev)` by `season_rec_yds_pg` descending →
   assign `wr_rank_season`
3. For each game: mark the lowest `wr_rank_season` WR who also has a row in
   `player_game_offense` for that game as `is_primary = TRUE`
4. For WR OQA, use only `is_primary = TRUE` rows on both sides (the team's #1 WR
   stats, compared against the defense's average for its opponents' #1 WR)

The last point requires computing a new defense average: instead of "total WR yards
allowed per game," it becomes "yards allowed to the opponent's #1 WR per game."
This needs a second-pass computation after #1 WR identification.

**Status:** Planned. Current implementation uses WR group totals as a floor.
