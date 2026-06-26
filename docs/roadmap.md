# Implementation Roadmap

## Guiding Principle

Build incrementally from a working Reggie White 1988 case study to a full league-wide system. At each phase, the system should produce a meaningful (if incomplete) result so validation can happen before continuing.

---

## Phase 0: Environment & Database Setup ✓ DONE

**Goal:** Working database with schema loaded.

- [x] `scripts/db.py` — SQLAlchemy connection factory reading `DATABASE_URL` from `.env`
  - Default: `sqlite:///football_analytics.db` (zero setup)
  - Postgres: set `DATABASE_URL=postgresql://user:pass@localhost/football_analytics`
  - Migration from SQLite → Postgres = re-run seed scripts or use `pgloader`
- [x] `schema/schema.sql` applied; 16 tables + 3 views confirmed in SQLite
- [ ] Create `.env.example` in project root
- [ ] Decide: stay on SQLite through prototyping, or set up Postgres now

**To switch to Postgres:** `brew install postgresql@16 && brew services start postgresql@16 && createdb football_analytics` then set `DATABASE_URL` in `.env`.

---

## Phase 1: Seed Core Reference Tables

**Goal:** `players`, `teams`, `seasons`, `games` tables populated for all available years.

### 1a. Seasons table
- ETL from `season-gamelogs/gamelogs_{year}.csv` file list
- Populate `num_teams` (28 pre-2002, 32 after 2002), `num_weeks`

### 1b. Games table
- Parse each `season-gamelogs/gamelogs_{year}.csv` to extract game URLs
- Derive `home_team`, `away_team`, `game_date`, `season` from game_id format `YYYYMMDDTEAM`
- Flag playoff games (post-week-16/17 dates)

### 1c. Teams table
- From `team-history/` CSVs + manual mapping for relocations (Houston Oilers → Tennessee Titans, etc.)

### 1d. Players table
- Initial load from `player_link` column in `player-stats/defense/defense_{year}.csv` files
- `player_link` = canonical `pfr_player_id`
- Supplement with roster data for birth_date, college, draft info

### 1e. Rosters
- Load all `team-rosters/{team}_{year}_roster.csv` files
- Resolve `pfr_player_id` where possible (by name match to players table)

---

## Phase 2: Team Defense Season Stats

**Goal:** `team_defense_season` populated; can compute WOWY for any player who joined a team.

- Load all `team-defense/team-defense/team-defense-{year}.csv`
- Extract: rank, pts_against, yds_against, rush/pass splits
- Derive `oqa_pts_rank`, `oqa_yds_rank` = NULL at this stage (filled in Phase 4)

**Validation checkpoint:**
```sql
SELECT * FROM team_defense_season WHERE team_abbrev = 'gnb' AND season IN (1992, 1993);
-- Should show: 1992: pts_rank=15, yds_rank=23 | 1993: pts_rank=9, yds_rank=2
SELECT * FROM team_defense_season WHERE team_abbrev = 'phi' AND season = 1988;
-- Should show: pts_rank=14, yds_rank=27
```

---

## Phase 3: Individual Defensive Player Season Stats

**Goal:** `player_defense_season` populated; can compute sack share, look up awards.

- Load all `player-stats/defense/defense_{year}.csv`
- Parse `awards` string into boolean flags: `is_pro_bowl`, `is_all_pro_1`, `is_all_pro_2`, `is_dpoy`
- Set `tackles_source = 'pfr_2001+'` for years >= 2001; NULL for prior years
- Flag `approx_value` from roster file join

**Validation checkpoint:**
```sql
SELECT * FROM player_defense_season
WHERE pfr_player_id = '/players/W/WhitRe00.htm';
-- Should show career across PHI (1985-1992), GNB (1993-1998), CAR (2000)
-- 1988: 18.0 sacks, is_all_pro_1=true, is_pro_bowl=true
```

---

## Phase 4: Per-Game Team Defense (from Boxscores)

**Goal:** `team_game_defense` populated; can compute per-game sack totals and opponent quality.

**Script approach:**
```python
# For each game in games table:
# 1. Load boxscore CSV: boxscores/{year}/{game_id}.csv
# 2. Sum sacked column for opponent QB rows → team_sacks
# 3. Sum pass_att + rush_att for opponent → total plays faced
# 4. Compute pts_allowed from away_score/home_score in games table
# Load into team_game_defense
```

**Then: opponent quality adjustment**
- For each game, compute opponent's season average (pass_yds_pg, rush_yds_pg, pts_pg)
  - Average excludes the game in question (to avoid circularity)
  - Use `team_defense_season` + per-game data
- Compute `delta_*` columns
- Compute `oqa_game_score`: normalize delta across all games that season

**Update `team_defense_season`** with season-mean OQA scores.

---

## Phase 5: WOWY Computation

**Goal:** `wowy_pairs` populated for all player seasons where a year-over-year comparison exists.

**Logic:**
1. For each player, for each team-season, find adjacent seasons (year before + year after) where player was NOT on same team (or was added/removed)
2. Compute rank percentile in both years
3. Assess roster overlap: count defenders in rosters table who appear in both years
4. Flag coaching changes (from `coaches/` data in pfref)
5. Compute OQA-adjusted versions using `oqa_pts_rank`, `oqa_yds_rank` from team_defense_season

**Special case — Reggie White WOWY:**
- PHI 1985 → 1986 (first full season): compare to 1984 PHI defense
- GNB 1992 → 1993: this is the marquee WOWY validation case
- PHI 1992 → 1993 (left Eagles): what happened to PHI defense when he left?

---

## Phase 6: Individual Defensive Game Logs (PBP Scraper Ready)

**Goal:** `player_defense_game` populated, enabling per-game sack share.

**Two sources:**

**6a. Gamebook pipeline (pre-2001, MIN/PIT only)**
- Load `page_plays_final.csv` from gamebooks_research repo
- Resolve player names to `pfr_player_id` via name matching against players table
- Aggregate per-player per-game: count sacks, tackles, ints, etc.
- Insert with `data_source = 'gamebook_mistral'` or `'gamebook_tesseract'`

**6b. PFR boxscore play-by-play (scraper built, not yet run)**
- `play_by_play.py` module added to `/Users/devos/github/football/football_analytics/ingestion/pfref/`
- Reuses existing boxscore page fetch; parses `id="pbp"` table (buried in HTML comments, handled via `strip_comments=True`)
- Each play's `detail` column names individual defenders
- Run: `pfref.play_by_play.scrape_pbp(years=range(1982, 2002), teams=["phi"])` for PHI priority
- Name resolution (initials+last to pfr_player_id) happens in ETL

**6c. PFR player game logs (future)**
- PFR also has per-player seasonal game logs at `/players/{X}/{id}/gamelog/{year}/`
- These would give clean per-game stat rows without needing to parse play descriptions
- Lower priority since PBP approach above gives richer data

---

## Phase 7: Matchup Grades

**Goal:** `matchup_grades` populated; OMG scores available per game.

**7a. Position mapping**
- Use `rosters` table to map defender position → expected blocker position
- Default mapping (see analytical_framework.md): LDE → opp RT, etc.

**7b. OL player identification**
- Find opposing team's RT/LT/etc. from their roster for that game
- Resolve to `pfr_player_id` via name match

**7c. Grade calculation**
- `ol_grade`: (opp pass_yds season rank pct × 0.5) + (opp rush_yds season rank pct × 0.3) + (OL recognition score × 0.2)
- `qb_grade`: from `player_defense_season` or QB passing stats (passer rating, sack rate)
- `combined_omg`: position-weighted blend

---

## Phase 8: DPVS Score Assembly

**Goal:** `dpvs_components` and `dpvs_career` fully populated.

- Compute per-player per-season weighted score from all components
- Normalize within position group × season to 0–100 scale
- Rank within position groups
- Aggregate to `dpvs_career`

**Validation:**
- Run `v_dpvs_leaderboard` for 1988 season — Reggie White should rank top 3 among pass rushers
- Run for 1971 — Alan Page should rank very high despite sparse data
- Run for 1986 — Lawrence Taylor should be #1 overall LB
- Compare DPVS rankings against contemporaneous All-Pro selections — should be strongly correlated

---

## Phase 9: Output & Reporting

**Goal:** Per-player season reports and comparative leaderboards.

- Script to generate per-player season summary (component breakdown + final score)
- Script to generate season leaderboard by position group
- Script to generate career summary page
- Export to CSV / JSON for future website consumption

**Eventually:** Static site generator pulling from the DB to produce per-player pages (separate project).

---

## Phase 10: Data Gaps & Quality Improvements

- Expand gamebook OCR coverage to additional teams (requires gamebook PDFs)
- Integrate media guide parsed data for pre-1995 gaps
- Scrape PFR player game logs for full game-by-game coverage 1982+
- Add nflfastR play-by-play data for 2009+ (snap direction, coverage assignment)
- Snap count data (2015+) for precise playing-time adjustment

---

## Prioritized Quick Wins (do early for momentum)

1. Load `team_defense_season` + run the GNB 1992/1993 WOWY sanity check (1–2 hours)
2. Load `player_defense_season` + query Reggie White's career sack total (1 hour)
3. Load rosters + compute basic team sack share from season totals (2 hours)
4. Load boxscores + compute per-game opponent pass/rush/pts (4 hours)
5. First DPVS run using only sack share + WOWY (no OMG, no per-game tackle share) as a skeleton

These five steps give you a partial score for any player with sack data (1982+) and WOWY-eligible seasons.

---

## Open Questions (see `docs/open_questions.md`)

- Weight calibration: how do we tune the 5 component weights empirically?
- How to handle mid-season trades (player appears on two teams in one season)?
- Should we track franchise relocations as the same team in WOWY, or a different team?
- What minimum games played threshold to include a season in DPVS calculations?
- How to handle strike-shortened 1982 season (9 games) and 1987 (15 games, 3 games played by replacements)?
