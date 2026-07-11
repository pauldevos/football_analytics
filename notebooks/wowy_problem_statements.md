# WOWY positional research — problem statements

Relocated from `gamebooks_research` on 2026-07-09. **The code will likely need
to be redone** — both scripts currently read
`~/data/gold/player_season_card.parquet`, which is superseded (see
`DEFENSIVE_STATS_PROJECT.md`'s Architecture section — the canonical store is
now `football_db`/Postgres). What matters and shouldn't be lost is the
research question and methodology below; re-implement against `football_db`
once player/season stats are loaded there, don't just repoint the old script
at a new table name without reconsidering the approach.

## `sack_wowy_analysis.py` — do elite pass rushers elevate teammates?

**Question**: does having an elite pass rusher on the roster measurably
increase teammates' sack production — a "gravity" effect where opposing
protection schemes shift attention and open things up for everyone else?

**Player tiers**:
- Tier 1 (Elite): career avg ≥ 7 sacks/season (seasons with ≥8 games played),
  OR 5+ seasons with 10+ sacks
- Tier 2 (Truly Elite): 3+ seasons with sacks/game ≥ 0.8

**Analyses**:
1. Age curve (quadratic polynomial across elite rushers' career arcs)
2. Targeted team-change WOWY — detailed year-by-year view for 15 named
   players who changed teams
3. Aggregate team-change WOWY — all Tier 1+ players who changed teams
4. Injury WOWY (season-level) — injury years vs. healthy years, same team
5. Injury WOWY (game-level) — games started vs. games missed, within a season
6. Sack-share descriptive stats + "paradox" test (does a teammate's sack
   share go up or down when the elite rusher is out?)

## `mlb_wowy_analysis.py` — do elite middle linebackers elevate team defense?

**Question**: the positional analogue to the sack-gravity hypothesis, but for
interior run-defense — does an elite MLB improve team rush defense and total
defense when they join a new team?

**Why this is harder than the pass-rush version** (explicitly noted in the
original script): tackles don't cleanly isolate an "additive" effect the way
sacks do, and many elite MLBs spent their whole career on one team, so this
leans more heavily on injury-based WOWY (in/out within a season or across
healthy vs. injured seasons) than team-change WOWY.

**Player tiers** (era-normalized, since raw tackle counts vary wildly by
decade — see `football_db/docs/source_priority_and_normalization.md` for why):
- Tier 1 (Elite MLB): career avg z-score ≥ 1.0 AND ≥ 4 qualifying seasons
- Tier 2 (Truly Elite MLB): career avg z-score ≥ 1.5 AND 3+ seasons with
  z ≥ 1.5

**Primary outcome**: rush defense rank + total defense rank (not sack rank).
