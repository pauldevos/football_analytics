# Data Pipeline Reference

Quick-start reference for the two primary data sources used in DPVS analysis.
Read this instead of re-deriving coverage every session.

---

## 1. PFR Play-by-Play (1978–2025)

**Path:** `~/data/pfref/raw/boxscores/{year}/{game_id}/`

**Coverage:** 76 seasons (1978–2025), ~230–285 games per season, complete.

**Files per game:**

| File | Key columns |
|------|-------------|
| `pbp.csv` | `quarter, down, yds_to_go, location, pbp_score_aw, pbp_score_hm, detail, exp_pts_before, exp_pts_after` |
| `player_defense.csv` | `player, pfr_player_id, team, sacks, tackles_combined, tackles_solo, tackles_assists` (tackle columns blank pre-2001) |
| `starters.csv` | Starter positions per game — used for player-id resolution |
| `expected_points.csv` | Team-level EP splits (pass/rush/TO/ST) |

**Tackle attribution in `pbp.detail`:**
```
"Ricky Bell middle for 1 yard (tackle by George Martin )"
"Gary Huff pass complete to Morris Owens for 4 yards (tackle by Terry Jackson )"
"(tackle by Ron Johnson and Nat Terry )"   ← two-man split
```
`exp_pts_before` and `exp_pts_after` are present on ~98% of plays. EPA is always from offensive team's perspective; `epa_def = ep_before - ep_after` (positive = good for defense).

**Silver outputs (already built, do not re-run unless rebuilding):**

| File | Rows | Description |
|------|------|-------------|
| `~/data/silver/tackle_events.parquet` | 1,244,690 | Play-level: one row per tackler slot, includes `epa_def`, `epa_def_share`, `is_sack`, `pos`, `pos_group` |
| `~/data/silver/tackle_epa_season.parquet` | 61,651 | Player-season aggregates: `epa_def_total`, `epa_def_per_tackle`, run/pass splits |
| `~/data/silver/player_season_rankings.parquet` | 15,190 | Rankings + z-scores + composite DPVS score |

**Scripts:**
- `scripts/build_tackle_epa.py` — rebuilds `tackle_events` and `tackle_epa_season`
- `scripts/build_player_rankings.py` — rebuilds `player_season_rankings`
- `scripts/enrich_tackle_events.py` — adds position, pos_group enrichment

**Do NOT OCR gamebooks for 1978–1981.** PFR PBP covers this era completely. The handful of 1978–1981 gamebook OCR files in `ocr_named_mistral/` are legacy Page research, not needed.

---

## 2. NFL Gamebooks / OCR Pipeline (1967–1977)

Gamebooks are the only play-by-play source for individual defender attribution before 1978.

**Raw PDFs:** `~/data/gamebooks/{year}/` (organized by year/week for 1978+, flat for earlier)

**OCR status:**

| Era | Seasons | Mistral OCR status | Named files |
|-----|---------|-------------------|-------------|
| ERA1 | 1967–1973 | **Complete** | ~730 files |
| ERA2 | 1974–1977 | **Complete** | ~968 files |
| ERA3 | 1978–1981 | Not needed (use PFR) | 8 legacy files |

Named OCR output: `~/data/gamebooks_processed/ocr_named_mistral/YYYYMMDDVIS@HOME.txt`
Hash-keyed cache: `~/data/gamebooks_processed/ocr_cache_mistral/{md5}.txt`

**Gamebook format eras and parser status (as of June 2026):**

| Era | Years | Format example | Parser status |
|-----|-------|---------------|---------------|
| ERA1 | 1967–1973 | `2SF/ 8/40SF  Willard gained 3, stopped by Page` | Adequate — 60-80% field extraction |
| ERA2 | 1974–1977 | `2-9 M31 Goodman sweep for 5 (Page)` | Solid — 97-99% field extraction when play found |
| ERA3 | 1978–1981 | `1/10/ D 20--Armstrong at left side for 3 (Page).` | N/A — use PFR |

**ERA2 format variants** (all handled as of June 2026):
```
Standard:  "2-9 M31 Goodman le sweep for 5 (Page)"         ← down-dist TEAM+ydl
Variant A: "2-2-22 Green hits the middle for 1 yd (Page)"   ← down-dist-ydl all hyphens
Variant B: "2/8/8/L Watkins tried right end (Page)"         ← down/dist/ydl/TEAM
Variant C: "2/6 D49—Baynham lt for 2. (Page)"              ← down/dist TEAM+ydl— (em-dash)
Variant D: "1/10 C16 Conjar lt for 1. Lundy tackler."      ← no-sep (multi-cell table stripped)
```
Also fixed: 2-letter team codes (GB, OK, TB, SF, etc.), markdown table pipe-stripping.

**Game-level quality from full 1,701-file sweep:**

| Tier | Count | % | Description |
|------|-------|---|-------------|
| GOOD | 560 | 33% | ≥60% fields complete, has tackle attribution |
| LOW_PARSE | 252 | 15% | Play lines found, <30% fields complete |
| SPARSE | 196 | 12% | Fewer than 10 play lines |
| DEAD | 628 | 37% | No play-by-play (stats/scoresheet only) |

**Per-game averages (usable games):**
- Avg play lines/game: **94.8** (vs ~120 expected — 79% coverage, expected for attribution gaps)
- Avg field complete: **71%**
- Avg tackles attributed: **43.8** (among games with any attribution)
- Avg strict sacks/game: **3.14** (conservative — ERA1 sack detection requires QB context keyword)
- Avg unique tacklers: **12.5** (vs ~25-35 expected — selective attribution)

**Known limitations:**
- ERA1 sack classification unreliable: "thrown for loss" = QB sack AND run TFL; no QB name lookup
- 37% of files are genuine score-sheet-only (not recoverable OCR failures)
- Some game files appear 2-3× under different names (duplicate OCR pages — deduplicate by play text)

**Extracted play data (Alan Page only):**

| File | Rows | Notes |
|------|------|-------|
| `~/github/football/gamebooks_research/page_plays_fresh.csv` | 967 | Alan Page, 1967–1977, v5 parser (deduped — 6 duplicate game files removed) |
| `~/data/gamebooks_processed/teams/min/seasons/*_defense.csv` | — | MIN season summaries 1967–1978 (sample games only, not full seasons) |
| `~/data/gamebooks_processed/teams/pit/seasons/*_defense.csv` | — | PIT season summaries 1969–1973 |

**Alan Page validation (June 2026, deduped):**
- **100 sacks** vs. John Turney's historical count of 108.5 through 1977 → 7.8% undercounting
- Undercounting source: ERA1 strict sack filter misses some "thrown for loss" lines lacking QB context keyword; 37% DEAD game files never OCR'd
- 100 TFLs, 349 solo tackles, 224 assists across 967 play instances
- Implied Page sack share of MIN team total: **24.5%** (100 Page / 408 PFR MIN) — reasonable for a dominant DT alongside Eller and Marshall

**Roster-based name validation (June 2026):**
- 4,833 tackler name instances across all 121 deduped MIN gamebook files
- **91.2% match** a known PFR roster for the two teams in that game
- Top unmatched reasons: teams without roster files (GB, SF, LA, OAK, KC = ~200 names), OCR noise words (~20), retired players appearing in wrong year (~10)
- PFR roster files available for: MIN, DET, DAL, PIT, PHI, CLE, ATL, NYJ, MIA, WAS, BUF, CHI, DEN, NYG, SEA (1967–1977)
- Teams WITHOUT roster files: GB, SF, LA/STL, OAK, KC, SD, BAL, HOU, BOS

**Team-level sack check (June 2026):**
- PFR source: `~/data/pfref/raw/season/team/defense/passing/passing_{yr}.csv` → `pass_sacked` column
- Gamebook sack counts cannot be split between teams' offense/defense from raw text
- ERA2 (1974-1977) strict capture 19–98% of PFR single-team total; ERA1 (1967-1973) only 2–31%
- **Use individual player stats (Page share) for quality signal, not raw team sack count**

**Common commands:**
```bash
cd ~/github/football/gamebooks_research

# Re-parse Page plays with updated parser (regenerates page_plays_mistral_full.csv)
python parse_gamebook_plays.py \
    --csv page_mentions_all.csv \
    --cache-dir ~/data/gamebooks_processed/ocr_cache_mistral \
    --search Page --min-mentions 1 \
    --output page_plays_mistral_full.csv

# Run team defense pipeline for MIN or PIT
python team_defense_pipeline.py --team min --csv page_mentions_all.csv
python team_defense_pipeline.py --team pit --csv pit_gamebooks.csv
```

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| No Mistral OCR for 1978–1981 regular season | PFR PBP has complete EPA data from 1978; gamebook inconsistency adds noise not signal |
| Gamebook scope = 1967–1977 only | Pre-PFR PBP era; only source for individual play attribution |
| ERA2 parser fix (June 2026) | 420 of 663 ERA2 rows were LOW-conf due to 3 unhandled format variants — not OCR quality |
| Team sack count unusable directly from gamebooks | Both teams' plays mixed in same file; ERA1 QB-context filter too strict; use individual player share instead |
| ERA1 sack detection stays strict | "Thrown for loss" in ERA1 matches both QB sacks and RB TFLs; strict QB-context keyword prevents double-counting |
| Roster validation: 91.2% match rate is target baseline | 8.8% unmatched = teams without roster files + OCR noise; not parser failure |
