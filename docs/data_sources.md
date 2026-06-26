# Data Sources Inventory

## 1. Pro Football Reference — Scraped CSV Data

**Root:** `/Users/devos/data/pfref/`
**Scraper:** `/Users/devos/github/football/football_analytics/ingestion/pfref/`

---

### 1.1 Boxscores

**Path:** `boxscores/{year}/{YYYYMMDDTEAM}.csv`
**Coverage:** 1950–2025 (all regular season + playoff games)
**Key:** `game_id` = filename stem e.g. `198809110phi`

**Columns:**
```
season, game_id, player_link, player_name, team,
pass_comp, pass_att, pass_yds, pass_td, pass_int,
sacked, sack_yds_lost, pass_long, qb_rate,
rush_att, rush_yds, rush_td, rush_long,
rec, rec_yds, rec_td, rec_lng
```

**Era differences:**
- Pre-~2002: no `targets` column; `fumble`/`fumble_lost` absent
- ~2002+: `targets` added
- 2021+: `fumble`, `fumble_lost` added

**What it gives us:**
- Individual player game stats for every offensive player — the raw material for
  individual OQA (see `docs/offensive_oqa_framework.md` and `scripts/etl_player_game_offense.py`)
- `sacked` on QB rows = total sacks that QB was charged in this game → proxy for team defensive sack count per game
- Opponent pass attempts + rush attempts → denominator for sack rate, disruption rate
- Opponent scoring (derived from game_id lookup) → pts allowed per game

**Limitations:**
- Contains ONLY offensive player stats — no individual defender data
- To get total team sacks in a game: filter opponent QB rows, sum `sacked`
- To get team's defensive plays: sum `rush_att + pass_att` for the opponent's offensive players in that game

---

### 1.2 Team Defense (Season Aggregates)

**Path:** `team-defense/team-defense/team-defense-{year}.csv`
**Coverage:** 1950–2025

**Columns:**
```
rank, team, games, pts_against, pen_yards, total_plays, yards_per_play,
takeaways, fr, rush_firstdowns,
[passing block]: comp, rush_att, pen_yards, rush_td, int, net_yards_per_att, rush_firstdowns,
[rushing block]: rush_att, pen_yards, rush_td, yards_per_rush, rush_firstdowns,
penalties, pen_yards, firstdown_by_penalty,
score_pct, turnover_pct
```

**Note:** Column headers are repeated (passing/rushing blocks share names). Be careful with positional indexing.

**What it gives us:**
- Season rank per team (1 = best defense in league)
- Total pts_against, yards — for WOWY year-over-year comparison
- League-wide context for normalizing individual team performance

**Confirmed data points:**
- 1988 PHI: rank 14 pts, rank 27 yards (confirmed matches user's cited stats)
- 1992 GNB: rank 15 pts, rank 23 yards (without Reggie White)
- 1993 GNB: rank 9 pts, rank 2 yards (with Reggie White → WOWY delta is massive)

---

### 1.3 Team Defense Sub-tables

**Paths:**
- `team-defense/team-defense-passing/`
- `team-defense/team-defense-rushing/`
- `team-defense/team-defense-scoring/`
- `team-defense/team-defense-kicking/`

Use these for more granular pass/run split defensive ranks and for building opponent quality metrics.

---

### 1.4 Individual Defensive Player Season Stats

**Path:** `player-stats/defense/defense_{year}.csv`
**Coverage:** 1950–2025

**Columns:**
```
rank, player_link, player_name, age, team_abbrev, position, games, games_started,
int, yards, td, long,
ff, fumbles, fr, yards, fr_td,
sack,
comb_tackles, solo_tackles, ast_tackles,
safety, awards
```

**Critical notes:**
- **Sacks** are reliable from 1982 onward (NFL began officially tracking sacks in 1982). Pre-1982 sacks on PFR are reconstructed estimates.
- **Tackles** (`comb_tackles`, `solo_tackles`, `ast_tackles`): PFR notes these are **reliable only from 2001+**. Teams tracked their own tackles inconsistently before 2001. Do NOT use raw tackle totals pre-2001 for cross-team comparison. Use only as relative context within one team-season, or prefer gamebook-derived tackle share instead.
- `awards` field: comma-separated, e.g. `"PB,AP-1,AP DPoY-2"` — parse carefully
- `player_link` is canonical player ID (PFR URL path)

**Example — Reggie White 1988:**
```
191, /players/W/WhitRe00.htm, Reggie White, 27, PHI, LDE, 16, 16,
0, 0, 0, 0,   ← int
1, 0, 2, 0, 0, ← ff, fumbles, fr, fr_yds, fr_td
18.0,           ← sacks
133, 133, 0,    ← comb_tackles, solo, ast (2001+ reliable — 1988 value is team-tracked estimate)
0,              ← safety
"PB,AP-1,AP DPoY-2"
```

---

### 1.5 Team Rosters

**Path:** `team-rosters/{team}_{year}_roster.csv`
**Coverage:** Varies by team; roughly 1966–2024 for most franchises

**Columns:**
```
No., Player, Age, Pos, G, GS, Wt, Ht, College/Univ, BirthDate, Yrs, AV, Drafted (tm/rnd/yr)
```

**What it gives us:**
- **AV (Approximate Value):** PFR's single-number player quality estimate per season. Useful for quantifying teammate strength, OL grade proxy, overall roster context.
- `G, GS` — games played/started. Essential for computing per-game rates and flagging injury-shortened seasons.
- `Pos` — position code for matchup mapping

**Team abbrevs (PFR):** `phi`, `gnb`, `min`, `pit`, `dal`, `chi`, `nyg`, `clt` (pre-move Baltimore Colts), `sfo`, `was`, etc.

---

### 1.6 Season Gamelogs

**Path:** `season-gamelogs/gamelogs_{year}.csv`
**Coverage:** 1950–2025

**Columns:** `game_url` (PFR URL path for each game)

Used to enumerate all game IDs for a given season, which map to boxscore filenames.

---

### 1.7 Team Offense (Season)

**Path:** `team-offense/team-offense/`

Mirror of team defense but for offense. Use for opponent quality: a team ranked #1 in offense is a harder matchup for any defense.

---

### 1.8 Standings

**Path:** `standings/`

W-L records. Use to assess schedule quality and as a general team quality context variable.

---

### 1.9 Draft Data

**Path:** `draft-data/`

Draft position is a reasonable proxy for expected player talent level, useful in teammate quality grading.

---

## 2. NFL Gamebooks (Play-by-Play with Defender Attribution)

**Processed cache:** `/Users/devos/data/gamebooks_processed/ocr_cache_mistral/` (hash-keyed)
**Named copies:** `/Users/devos/data/gamebooks_processed/ocr_named_mistral/` (game ID named)
**Research repo:** `/Users/devos/github/football/gamebooks_research/`

**What it gives us:**
- Individual defender named on each play (tackle, sack, fumble forced, etc.)
- Solo vs. assisted distinction
- Play type (run, pass, sack, TFL, INT, fumble)
- Down, distance, yardline (when parseable)

**Coverage:**
- Minnesota Vikings: 1967–1981, ~45 games with high-quality Mistral OCR
- Pittsburgh Steelers: 1969–1973, some games processed
- Total: ~45 games with Mistral quality, additional Tesseract-quality games

**Output CSV schema** (from `page_plays_final.csv`):
```
year, filename, visitor, home, era, period, down, distance,
yardline, yardline_side, clock, play_type, player_role,
is_solo, co_tacklers, ocr_conf, description, play_text
```

**Play types:** `RUN | PASS | SACK | TFL | INTERCEPTION | FUMBLE | BLOCKED_KICK | SPECIAL | UNKNOWN`

**Player roles:** `SOLO_TACKLE | ASSISTED_TACKLE | SACK | TFL | PASS_DEF | QB_PRESSURE | FUMBLE_REC | TACKLE_UNKNOWN`

**Era-specific format notes:**
- ERA1 (1967–1973): Sparse attribution, often only notable plays named defenders
- ERA2 (1974–1977): More consistent, parenthetical notation `(Page, Hilgenberg)`
- ERA3 (1978–1981): Best structure, consistent format per play

**Tackle share file:** `/Users/devos/github/football/gamebooks_research/tackle_share.csv`
```
year, filename, page_credits, total_credits, tackle_share, players_credited
```

**To extend coverage:** Run `team_defense_pipeline.py` for other teams (requires gamebook PDFs to exist in `~/data/gamebooks/`).

---

## 3. NFL Media Guides

**Parser repo:** `/Users/devos/github/football/media_guide_parser/`
**Processed output:** Within that repo's `output/` and `output_targeted/` dirs
**982 pages processed** (as of May 2026)

**What it gives us:**
- Per-player defensive season stats directly from team yearbooks (pre-1995 fills)
- Some depth chart / position information
- Awards and recognition not always captured by PFR

**Status:** WIP — data extracted as JSON/Markdown but not yet fully normalized to CSV. Parsing pipeline is functional.

**Use case for this project:**
- Fill gaps in team defensive stats pre-1995
- Cross-reference PFR data for accuracy
- Extract OL/position quality data from roster sections

---

## 4. Data Availability Matrix

| Data Type | 1950–1981 | 1982–2000 | 2001–2011 | 2012+ |
|-----------|-----------|-----------|-----------|-------|
| Boxscores (off. stats) | ✓ | ✓ | ✓ | ✓ |
| Team defense season ranks | ✓ | ✓ | ✓ | ✓ |
| Individual sacks | ~ (reconstructed) | ✓ | ✓ | ✓ |
| Individual tackles | ✗ (PFR unreliable) | ✗ (PFR unreliable) | ✓ | ✓ |
| Gamebook tackle share | MIN/PIT only | — | — | — |
| Snap counts | ✗ | ✗ | ✗ | ✓ (full 2015+) |
| Play-by-play w/ defenders | ✗ (mostly) | ✗ | ✗ | ✓ (2009+ nflscrapr) |
| Rosters w/ AV | ✓ | ✓ | ✓ | ✓ |
| Draft data | ✓ | ✓ | ✓ | ✓ |
| Awards (PB/AP) | ✓ | ✓ | ✓ | ✓ |

Legend: ✓ = reliable, ~ = partial/reconstructed, ✗ = not available from current sources

---

## 5. Play-by-Play from Boxscores (Scraper Built, Not Yet Run)

**Module:** `/Users/devos/github/football/football_analytics/ingestion/pfref/play_by_play.py`
**Output:** `~/data/pfref/boxscores_pbp/{year}/{game_id}.csv`

Each PFR boxscore page contains a full play-by-play table (`id="pbp"`) buried in an HTML comment block. The existing scraper's `strip_comments=True` flag unlocks it with no extra HTTP requests — the page is already fetched for the offense table.

**Columns saved per play:**
```
season, game_id, quarter, time, down, togo, location, epb, epa, detail
```

The `detail` column names individual defenders: *"J.Brooks left end for 5 yards, tackled by R.White."*

**Usage:**
```python
from pfref import play_by_play

# All PHI 1988 games only (won't re-fetch already-scraped offense data)
play_by_play.scrape_pbp(years=[1988], teams=["phi"])

# Full 1982–2001 era (the gap before per-game defensive stats on PFR)
play_by_play.scrape_pbp(years=range(1982, 2002))
```

**Important:** The PBP table on PFR uses initials + last names (`R.White`, `J.Brooks`). Name resolution to `pfr_player_id` is done in the ETL layer, not in the scraper.

**Coverage:** PBP data on PFR appears to be available back to at least the mid-1990s with full play-by-play; earlier years may have partial or no PBP. Test with a few 1988 games before running a full scrape.

---

## 6. Media Guide Defensive Stats (Parsed, Pre-1995 Gap Filler)

**Root:** `/Users/devos/data/media_guides_processed_v2/teams/`
**Format:** `{team}/{year}/extracted/defensive_stats.csv`

Extracted from team media guide PDFs via the media guide parser pipeline. Columns vary by team/year but typically include:
```
Player, Solo, Assist, Totals (or Total Tackles), Sacks-Yds
```

**Teams currently processed:**

| Team | Years Available |
|------|----------------|
| Baltimore Colts | 1953, 1975–1995 |
| New England Patriots | 1970–1991 (most years) |
| Houston Oilers | 1978, 1979, 1981, 1982 |
| Miami Dolphins | 1984 |

**Data quality note:** The CSVs are parsed but not QA'd. The extraction from scanned PDFs produces a sparse, wide CSV where column alignment can be unreliable. Always cross-reference against PFR season totals for sacks/ints. Tackle totals are the primary reason to use this source — they're not available elsewhere pre-2001.

**Eagles and Packers not yet processed** — needed for Reggie White PHI years. This is a gap to fill via the media_guide_parser pipeline.

---

## 7. Computed ETL Outputs (`data_output/`)

These are derived from the raw PFR CSVs by ETL scripts. They are the primary inputs
for analysis scripts and notebooks.

### 7.1 Team Game Offense + OQA (offense perspective)

**Script:** `scripts/etl_oqa_boxscores.py`

| File | Description |
|------|-------------|
| `team_game_offense_{year}.csv` | Per-game team offense totals (passing, rushing, receiving by position group) |
| `oqa_game_detail_{year}.csv` | Leave-one-out OQA from the **offense's** perspective: for each game, the offense's season average (excluding that game) and the actual vs. average delta |

Sign convention: negative delta = defense held offense below their norm (good for defense).
INT/sacks: positive delta = more than offense's typical rate.

### 7.2 Individual Player Game Offense + OQA (defense perspective)

**Script:** `scripts/etl_player_game_offense.py`

| File | Description |
|------|-------------|
| `player_game_offense_{year}.csv` | One row per player per regular-season game; actual stats + per-game OQA delta vs. defense's LOO average |
| `defense_loo_avg_{year}.csv` | Leave-one-out averages from the **defense's** perspective: for each (game, defending_team), average of stats that defense allowed in all other games that season |
| `player_oqa_season_{year}.csv` | Season rollup: for each player, totals and per-game averages of all deltas |

**Position-specific delta computation:**

| Position | Comparison |
|----------|-----------|
| QB | Actual passing stats vs defense's average passing stats allowed |
| RB | Carry-adjusted: `actual_rush_yds − (rush_att × defense_avg_YPC_allowed)` — see Q15 in open_questions.md for why |
| WR | Individual rec_yds vs defense's total WR rec_yds allowed (group-level; see Q16) |
| TE | Individual rec_yds vs defense's total TE rec_yds allowed; `is_primary` flags top TE per game |

**`is_primary` flag:** Marks the top statistical producer per position group per
team per game (most pass_att for QB, most rush_yds for RB, most rec_yds for WR/TE).
Useful for filtering to feature-back/top-TE comparisons.

---

## 8. Data Not Yet In Hand (Future Acquisition)

| Data | Source | Use |
|------|--------|-----|
| Individual defensive player game logs | PFR player pages (scraping needed) | Per-game sack/tackle/int by player |
| Opponent OL individual stats/awards | PFR roster pages | OMG calculation |
| nflscrapr / nflfastR play-by-play | R package / GitHub | Post-2009 snap direction, coverage tracking |
| Sports Reference play-by-play pre-2009 | PFR | Additional game-level context |
| Gamebooks for non-MIN/PIT teams | Physical archives / NFLPA | Extended gamebook tackle share coverage |
