# CLAUDE.md — NFL Defensive Player Value Analytics

> **Project context:** Read `~/github/football/DEFENSIVE_STATS_PROJECT.md` first for the full picture of the multi-source defensive stats database this scoring system depends on.

## Project Purpose

Build a comprehensive, historically grounded metric — **DPVS (Defensive Player Value Score)** — that assigns a fair, context-adjusted value to individual NFL defensive players across any era. The canonical test case is Reggie White (PHI 1988, GNB 1993) but the system should work for any player from 1950 onward wherever data allows.

The core problem: traditional counting stats (sacks, tackles) fail to capture context. A great defender commands double teams and draws plays away. The approach layers individual stats on top of team performance, opponent quality adjustments, and year-over-year changes when a player joins or leaves a roster.

## Working Directory

`/Users/devos/github/football_analytics/`

## Related Repos

| Repo | Purpose |
|------|---------|
| `/Users/devos/github/football/football_analytics/ingestion/pfref/` | PFR scraper — offensive/defensive player stats, team stats, rosters, boxscores |
| `/Users/devos/github/football/gamebooks_boxscores/` | Current, canonical gamebook boxscore + PBP extraction — operates on the unified `~/data/gamebooks/` corpus (1967-2001, all teams) |
| `/Users/devos/github/football/media_guide_parser/` | Media guide PDF extraction — defensive season stats from team yearbooks (pre-1995 fills) |

## Primary Data

All under `/Users/devos/data/pfref/`:

| Directory | Contents | Notes |
|-----------|---------|-------|
| `boxscores/{year}/*.csv` | Per-game offensive player stats (pass/rush/rec) | 1950–2025. Named `YYYYMMDDTEAM.csv`. Key column: `sacked` on QB rows. No individual defensive stats. |
| `team-defense/team-defense/team-defense-{year}.csv` | Season team defense ranks + aggregate yards/pts | Rank column is position in sorted list (1 = best). 28 teams pre-2002, 32 after. |
| `player-stats/defense/defense_{year}.csv` | Individual season totals: int, sack, ff, fr, tackles, awards | Tackles reliable from **2001+** only. Pre-2001: use sacks only and gamebook tackle share. |
| `team-rosters/{team}_{year}_roster.csv` | Full roster: position, age, AV, G, GS, draft info | Team abbrevs: `phi`, `gnb`, `min`, `pit`, etc. |
| `season-gamelogs/gamelogs_{year}.csv` | List of game IDs for the season | game_id maps to boxscore filename |
| `team-offense/` | Offensive team stats | For opponent quality assessment |
| `standings/` | Team W-L records | |

Gamebook play-by-play (defender attribution) — current sources for DPVS:
- `/Users/devos/data/gamebooks_processed/ocr_cache_mistral/` — Mistral OCR'd text files (hash-keyed)
- `/Users/devos/data/gamebooks_processed/ocr_named_mistral/` — same, named `YYYYMMDDVIS@HOME.txt`
- `/Users/devos/data/gamebooks_processed/teams/{team}/seasons/{season}_defense.csv` — per-team season CSVs from the old, now-deleted `gamebooks_research/` pipeline; kept live because `dpvs/idi.py` still reads them, even though the repo that produced them is gone
- Teams available: Minnesota Vikings 1967–1981, Pittsburgh Steelers 1969–1973

Note: new gamebook boxscore extraction happens in `gamebooks_boxscores/` against `~/data/gamebooks/`
(the unified 1967-2001 corpus, all teams, consolidated 2026-09-01). Its `boxscore.md`/`pbp.csv` output
isn't wired into DPVS or gold yet — that's listed as an open gap in the root CLAUDE.md. `gamebooks_research/`
no longer exists on disk (archived) — its CSV *output* above is still read by `idi.py`, but there's no
repo to go back to for new gamebook OCR/extraction work; use `gamebooks_boxscores/` for that.

Media guide data:
- `/Users/devos/github/football/media_guide_parser/` — extraction pipeline, 982+ pages processed
- Fills gaps for pre-1995 team defensive stats not available on PFR

## Key Data Gaps & Workarounds

| Gap | Workaround |
|-----|-----------|
| No individual defensive game logs pre-2001 | Use seasonal totals + gamebook data where available |
| Tackle data unreliable on PFR pre-2001 | Use "tackle share" % from gamebooks (teams tracked inconsistently) |
| No snap count data pre-2012 (patchy) / pre-2015 (full) | Assume played full game unless known injured; flag games player missed |
| No direct matchup data (which OL blocked which DE) | Infer from position: LDE ↔ RT, RDE ↔ LT, DT ↔ OG/C |
| Individual defensive game logs require additional scraping | PFR player game log pages exist — scraper extension needed |

## Analytical Layers (summary — full detail in `docs/analytical_framework.md`)

1. **Team Defense Context** — rank, pts/yd allowed, games started count per player
2. **Opponent Quality Adjustment (OQA)** — each game: opponent season avg vs. what they did vs. this team
3. **Individual Stat Shares** — sack share, tackle share (% of team totals)
4. **Opponent Matchup Grade (OMG)** — quality of specific opposing players at matched position
5. **WOWY (With Or Without You)** — team defense rank change when player added/removed
6. **DPVS Composite Score** — weighted sum, normalized across all defenders that season

## Database Target

PostgreSQL. Schema in `schema/`. Seeded from CSV files above via ETL scripts in `scripts/`.

## Companion Analysis: QB Value & Defensive Context

`notebooks/qb_value_analysis.ipynb` — tests the hypothesis that Tom Brady's GOAT status
is inflated by consistently elite defensive support. Full findings in `docs/qb_value_analysis.md`.

**Confirmed headline numbers** (1,800+ NFL team-seasons 1960–2025):
- Defense PPG rank vs Win%: **r = −0.70** vs. QB rating vs Win%: r = 0.53
- Top-10% defense → 83% P(10+W); Top-10% QB rating (era-adj) → 75% P(10+W)
- Bottom-25% defense → 3% P(10+W); Bottom-25% QB rating → 6% P(10+W)
- Manning: +2.92 WAE/season at 45th-percentile defense (below avg) — strongest "pure QB" case
- Brady: +1.94 WAE/season at 20th-percentile defense (top 20%) — great QB, great defense
- Dilfer: −1.97 WAE/season despite 26th-percentile defense — the canonical clipboard QB
- (WAE uses isotonic regression model; rolling mean gave Manning +2.99, Brady +2.09 — isotonic corrects for elite-defense expected-win inflation)

**Era-adjusted z-scores** (career QB rating z-score within season, full table in `docs/qb_value_analysis.md`):
- Steve Young: **1.63 z** (9 seasons; 1994 season z=3.43 is the highest in the dataset)
- Joe Montana: 1.51 z — also highest INT-z (1.32) among all named QBs (fewest turnovers vs era)
- Roger Staubach: 1.41 z (only 8 seasons; arguably higher peak than Brady)
- Brady: 0.99 z — solidly elite but compressed by playing in a QB-rich modern era
- Mahomes: 0.81 z — modern era compression makes his z lower despite arguably best raw play

**Decade trend** — defense predictive advantage vs QB rating (`|r|` ratio):
- 1960s: 1.22× | 1970s: 1.16× | 1980s: 1.19× | 1990s: 1.17× | 2000s: 1.06× | 2010s: 1.07×
- **2020s: 0.90×** — QB rating is now MORE predictive than defense; trend is systematic, not noise

**Planned case studies** (player debates arguing context):
- Defense-carried SB wins: McMahon/Bears, Dilfer/Ravens, Montana framing
- Penalized by bad defense: Marino, Rodgers, Drew Brees (+45.0 total WAE over 19 seasons, most underrated by total)
- Overlooked: Staubach (+2.00 WAE/season), Steve Young (#1 era-adjusted QB-z), Mahomes

## Document Index

| File | Purpose |
|------|---------|
| `docs/analytical_framework.md` | Full DPVS methodology, formulas, component weights |
| `docs/metrics.md` | TDGS formula, OQA, Team Credit Share, WOWY, era adjustment — metric reference |
| `docs/framework_decisions.md` | Running log of analytical decisions with evidence (e.g. why equal credit split) |
| `docs/offensive_oqa_framework.md` | Offensive player OQA: per-player context-adjusted stats (QB/RB/WR/TE), carry-adjusted RB metric, WR #1 identification |
| `docs/data_sources.md` | Inventory of every data source, columns, coverage, quality notes |
| `docs/data_pipeline_reference.md` | Quick-start guide for PFR PBP and team history data paths |
| `docs/schema.md` | PostgreSQL table definitions and relationships |
| `docs/roadmap.md` | Phased implementation plan |
| `docs/open_questions.md` | Decisions still to be made, edge cases, research TODOs |
| `docs/qb_value_analysis.md` | QB value hypothesis, WAE table, era-adjusted z-scores, decade trend, planned case studies |
| `docs/qb_era_adjusted_findings.md` | Findings narrative: WAE (isotonic), tier comparison, decade trend, z-score table with key reads |

## Conventions

- All player IDs use PFR link path as canonical key (e.g. `/players/W/WhitRe00.htm`)
- Team abbreviations follow PFR (phi, gnb, min, pit, dal, etc.)
- Seasons are identified by year of the regular season (1988, 1993, etc.)
- "Rank" is always ordinal 1 = best (least pts/yds allowed) within that season's league
