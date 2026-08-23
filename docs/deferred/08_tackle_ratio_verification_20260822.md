# Verified solo:assist tackle ratio, from PFR's real official box scores (2026-08-22)

## Why this exists

Earlier this session, `scripts/build_tackle_opportunity_ratio.py` was built to fix a
known problem in DPVS-G's pre-2001 tackle normalization: some 1967-2000 team-season
tackle *totals* are inflated by their era's own scoring practice (the flagship
example: Randy Gradishar's 1978 media guide reportedly credits him 286 solo tackles
in 16 games — not plausible at any era). The fix pattern was: keep a player's real
observed *share* of his team's tackles, but replace the raw team total with an
"opportunity-anchored" expected total (real defensive plays faced that season × a
stable solo/assist ratio measured from a trusted modern reference era).

That script's reference era was `gold.player_game_stats` (`current_source='pfr'`,
2001-2025) — which this session discovered, via a direct HOU 2025 spot check, is
actually PFR's `pbp.csv` **play-by-play text** parsed into a table, not official
box-score data. The pbp.csv parenthetical-name notation reliably captures the ONE
primary tackler on a play but is far less complete at capturing a SECOND (assist)
name on the same play. Old computed HOU 2025: solo=624 (close, +5.6% vs a rough
independent estimate of ~591), assist=183 (**~2.6x under** a ~475 estimate). This
document replaces that flawed reference with a real, direct sum of PFR's own
official per-game box scores, and reports what changes.

## The real data sources (both already cached locally)

- `~/data/pfref/raw/boxscores/{year}/{game_id}/player_defense.csv` — one row per
  player per game, official per-game defensive box-score line (Solo/Ast/Comb
  tackles, sacks, INT, etc.), not text-parsed play-by-play.
- `~/data/pfref/raw/season/team/defense/team_stats/team_stats_{year}.csv` — one
  row per team per season. Despite the generic path, this is PFR's Team Defense
  page's **opponent-stats** section — `plays_offense` here is the *opponent's*
  offensive plays run against that team's defense, confirmed by an exact match to
  the pasted reference (see below). It also carries `g`, the team's real
  regular-season game count for that season.
- `~/data/pfref/franchise_year_abbrev.csv` — (year, team_name, abbrev) back to
  1920, giving the stable lowercase franchise code (`den`, `crd`, `oti`, `htx`, …)
  used throughout `football_db`/this project, for translating both files' team
  identifiers onto the same key.

New build script: `scripts/build_verified_tackle_ratio.py`. Pure pandas/CSV, no
Postgres dependency. Output: `data_output/tackle_ratio_by_team_season.csv`
(1,009 rows, one per team-season, 1994-2025).

## Denver 2001 validation — exact match

The user's own pasted PFR numbers for the 2001 Denver Broncos: `plays_offense=960`,
`Comb=951 Solo=803 Ast=148`.

Computed directly from summing `player_defense.csv` across Denver's 16 games (2001
had no playoff appearance for Denver, so this is a clean regular-season-only
check):

```
comb=951  solo=803  ast=148  plays_offense=960  n_games=16
```

**Every single number matches exactly.** This is strong direct confirmation that
`player_defense.csv` really does hold official box-score tackle totals, and that
`team_stats.csv`'s `plays_offense` really is the opponent-plays-faced figure PFR's
own site shows.

## How far back is this data trustworthy?

**1994**, not 1994-ish-maybe or 2001. Checked directly (not assumed): every season
from 1950 through 1993 was spot-checked, and in every one, `tackles_combined`,
`tackles_solo`, and `tackles_assists` are **entirely blank** in every row of
`player_defense.csv` — PFR's box scores literally did not carry the solo/assist
split before 1994. This is a hard data-format boundary, not a completeness
gradient.

From 1994 on, the columns are populated at 95.6%-100% of rows per season, rising
to 100% by 2015. The ~4-5% "blank" rows in 1994-1998 were checked directly and are
**not missing data** — they're real rows for players who had a fumble recovery/INT
but zero tackle involvement that game (e.g. a QB recovering his own fumble),
correctly blank on tackles the same way a modern box score would leave that cell
empty. Treated as 0 in every sum here, which is correct.

**Two real bugs were found and fixed while building this**, both would have
silently distorted the table if left in:

1. **Team-code translation isn't case-insensitive.** `player_defense.csv`'s `team`
   column uses era-specific short codes that often don't match the stable
   franchise abbrev by string comparison (`"ARI"` vs stable `"crd"`, `"IND"` vs
   `"clt"`, etc.). One code, `HOU`, is genuinely year-conditional: it means the
   Houston Oilers (stable code `oti`) in 1994-1996, and the unrelated Houston
   Texans expansion franchise (stable code `htx`) from 2002 on — confirmed by
   checking that `HOU` and `TEN` never overlap in the data and `TEN` picks up
   exactly where `HOU`/Oilers left off in 1997 (the real Oilers→Titans rename).
2. **Raw boxscore folders include playoff games; `team_stats.csv`'s `plays_offense`
   and `g` do not.** Found via a second HOU 2025 check: 19 raw game folders vs
   `team_stats.csv`'s own `g=17`. Left unfixed, playoff tackles would inflate the
   numerator against a denominator that never counted them. Fix: per team-season,
   sort games chronologically by the `YYYYMMDD` game_id prefix and keep exactly
   the first `g` games (`trim_to_regular_season()` in the build script) — playoff
   games always fall after every regular-season game on the calendar, so this is
   exact, not a heuristic.

**One genuine, small data gap, documented rather than patched**: 6 real 2022 games
have an empty `player_defense.csv` locally (the Jan 2, 2023 Bills-Bengals game
suspended after Damar Hamlin's cardiac arrest and never replayed — correctly
reflected in both teams' reduced `g` — plus 5 unrelated missing files: BUF-MIA
12/18, CLE-BAL 12/18, MIN-CLT 12/18, JAX-OTI 1/8, RAI-KAN 1/8). This leaves 10 of
1,009 team-season rows (~1%) one game short of their real season. Not fixed here
(no scraping in scope); flagged per-row via `n_games` vs `g` disagreement — anyone
using this table can filter on that if it matters for their purpose.

**Verdict: 1994-2025 is the real, trustworthy window.** 2001-2025 is fully within
it — the "known good" range holds.

## The real solo:ast ratio — not stable, drifts hard over time

The user's own recollection was roughly "5:4." The real Denver 2001 example alone
(803:148 ≈ 5.4:1) already contradicted that as a fixed ratio, so the full
distribution was computed directly rather than assumed.

**2001-2025, 799 team-seasons:**

| | solo_ratio (solo/comb) | ast_ratio (ast/comb) | solo:ast |
|---|---|---|---|
| mean | 0.719 | 0.281 | 2.84 |
| std | 0.075 | 0.075 | 1.09 |
| min | 0.508 | 0.101 | 1.03 |
| max | 0.898 | 0.492 | 8.85 |

That spread (solo:ast ranging 1.03 to 8.85 across team-seasons) already says this
isn't one constant. The **league-pooled ratio by season** shows why — a real,
monotonic, large decline, not season-to-season noise:

| Season | solo:ast | Season | solo:ast | Season | solo:ast |
|---|---|---|---|---|---|
| 2001 | 3.52 | 2009 | 3.53 | 2017 | 2.58 |
| 2002 | 3.47 | 2010 | 3.30 | 2018 | 2.49 |
| 2003 | 3.55 | 2011 | 2.80 | 2019 | 2.16 |
| 2004 | 3.29 | 2012 | 2.68 | 2020 | 2.02 |
| 2005 | 3.35 | 2013 | 2.65 | 2021 | 1.77 |
| 2006 | 3.19 | 2014 | 2.62 | 2022 | 1.80 |
| 2007 | 3.62 | 2015 | 2.64 | 2023 | 1.80 |
| 2008 | 3.45 | 2016 | 2.52 | 2024 | 1.52 |
| | | | | 2025 | **1.23** |

Going back further (1994-2000, same computation, same 1994 data-availability
floor): 1994=3.36, 1995=3.66, 1996=3.48, 1997=3.21, 1998=3.42, 1999=3.62,
2000=3.65 — i.e. the ratio was **flat around 3.2-3.7:1 through 2010**, then
declined steadily and substantially to 1.23:1 by 2025. Real-world read: assist
tackles have become dramatically more common relative to solo tackles over the
league's last 15 years (more zone/gang-tackling schemes, and/or more permissive
official assist-crediting) — a genuine scoring-convention shift, not measurement
noise. The `ast_ratio` share of team tackles nearly triples from ~0.10-0.15 in the
early 2000s to ~0.45-0.49 by 2024-2025.

**Practical implication for anyone reusing a single "reference ratio" (as
`build_tackle_opportunity_ratio.py` does to project onto 1967-2000): which
sub-window you pool matters a lot**, and the early-2000s window (closer in era to
1967-2000) gives a meaningfully different ratio than pooling the full modern range.
This script still uses the same early-window (2001-2010) choice as before — now
just fed by the corrected numerator.

## `data_output/tackle_ratio_by_team_season.csv`

Full inspectable table, 1,009 rows (32 franchises × 1994-2025, minus a handful of
expansion-team-not-yet-existing gaps). Columns: `season, team, team_name, g,
n_games, comb_tackles, solo_tackles, ast_tackles, plays_offense,
tackle_share_denominator, solo_ratio, ast_ratio, solo_to_ast_ratio`.
`tackle_share_denominator` is just `plays_offense` under its task-specified name —
kept as two columns so nothing is silently renamed away from its source meaning.

## Applying the fix: `build_tackle_opportunity_ratio.py` before/after

`_team_season_tackles_2001plus()` now reads
`data_output/tackle_ratio_by_team_season.csv` (this document's table) instead of
querying `gold.player_game_stats`. Nothing else in that script changed — the
"opportunities" denominator (opponent rush attempts + pass completions + times
sacked, from `gold.team_game_stats`) is untouched, since that side was never found
to be wrong, only the tackle numerator was.

**Re-run outputs, corrected reference ratio (2001-2010 pooled, applied to
1967-2000):**

| | solo_ratio | ast_ratio |
|---|---|---|
| Old (flawed pbp.csv-derived source) | 0.8897 | 0.1763 |
| **New (verified player_defense.csv source)** | **1.0134** | **0.2961** |

(Note: this script's own `solo_ratio`/`ast_ratio` are tackles-per-*opportunity*,
not tackles-per-comb-tackle like this document's table above — a different,
narrower denominator that only counts opponent scrimmage plays. `solo_ratio`
exceeding 1.0 in the corrected numbers is real and expected: official Solo/Ast
box-score totals include special-teams-return tackles, which `player_defense.csv`
does not separate out, while "opportunities" only counts opponent offensive
scrimmage plays. This is a genuine scope mismatch between numerator and
denominator in this specific script, inherited unchanged from before this fix —
flagged here, not fixed, since fixing it is outside this task's scope of
"swap the flawed reference source.")

**HOU 2025 re-check** (same sanity check the script already printed before this
fix, now against the corrected source): **solo=591, assist=475** — matches this
project's own independent ~591/~475 estimate almost exactly (vs. the old flawed
624/183).

### Randy Gradishar, 1978, before vs. after

Gradishar's raw regular-season 1978 line, as currently loaded in
`gold.player_game_stats` (`current_source='pfr'`, i.e. pbp.csv-text-derived —
**not** the 286-solo media-guide figure the original motivating example cited;
that figure isn't in `football_db` today, so this check works with what
production's Layer 2 actually sees): **comb=137, solo=129, ast=8** over 16 games.
Denver's 1978 team totals from that same source: `team_solo=695, team_ast=74`.

Applying `dpvs/idi.py`'s Layer 2b formula externally (not modifying that file —
just replaying its math with each ratio) for DEN 1978, `opportunities=825`:

| | adj_expected_solos | adj_expected_ast | Gradishar's solo_share / ast_share | opportunity-normalized implied solo | implied ast | normalized tackle_share |
|---|---|---|---|---|---|---|
| **Before** (old ratio) | 734.0 | 145.5 | 0.1856 / 0.1081 | 136.2 | 15.7 | 0.1728 |
| **After** (new ratio) | 836.1 | 244.3 | 0.1856 / 0.1081 | 155.2 | 26.4 | **0.1681** |

Both `adj_expected_solos` and `adj_expected_ast` go up substantially under the
corrected ratio (assists +68%, since the old ast_ratio was itself undercounted)
— but Gradishar's *normalized tackle_share* actually moves slightly **down**
(0.1728 → 0.1681), because his own assist involvement is proportionally smaller
than his solo involvement, and assists now make up a much larger share of the
opportunity-anchored total. Net effect: correcting the reference source doesn't
mechanically inflate every pre-2001 player's normalized share — it can go either
direction depending on how that player's own solo/assist mix compares to the era
he's being projected against. In both cases the result sits nowhere near the
286-solo raw media-guide figure, which is the whole point of the opportunity-
anchoring approach in the first place.

**Caveat carried over unchanged from before this fix**: per `docs/framework_decisions.md`
§13, Layer 2b currently doesn't actually fire for most 1967-1977 (and some later)
player-seasons including, per that doc, Gradishar's — `tackle_share_z` comes back
NaN for him in the full pipeline for reasons unrelated to this fix (a separate,
already-documented gap in how `load_all_gamebook_idi()` sources 1967-1977 tackle
data). The before/after above is a direct replay of the Layer 2b formula against
real inputs, not a claim that the full IDI pipeline's Gradishar row changes today —
that would require the separate fix §13/§14 already describe, out of scope here.

## Bottom line

- Denver 2001 validated exactly against the user's pasted numbers.
- `player_defense.csv` is trustworthy back to 1994 (hard format cutoff, confirmed
  directly), not just 2001 — but 2001-2025 remains the fully-clean window free of
  the minor 2022 gap.
- The solo:ast ratio is **not** stable — real ~3.2-3.7:1 through 2010, declining
  steadily to ~1.2:1 by 2025. Any downstream use of a single ratio should say
  explicitly which era it's drawn from and why.
- `data_output/tackle_ratio_by_team_season.csv` is the full inspectable table.
- `build_tackle_opportunity_ratio.py` now consumes this verified data; the HOU
  2025 and Gradishar 1978 checks both moved in the expected direction once the
  numerator stopped undercounting assists.

Nothing in `dpvs/idi.py`, `dpvs/tcs.py`, or any other production pipeline file was
touched. Nothing here was committed to git.
