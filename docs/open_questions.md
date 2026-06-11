# Open Questions & Design Decisions

## Statistical / Methodological

### Q1: Component Weight Calibration
**Issue:** The initial DPVS weights (sack share 20%, tackle share 15%, etc.) are educated guesses.
**Approach:** Once ~20 seasons of data are loaded, run a correlation analysis between component scores and known ground truth (All-Pro / DPOY). Use that to tune weights. Could also use a simple OLS regression with DPOY vote shares as the target if those data are available.
**Status:** Open — needs data first.

### Q2: Double-Team / Shadow Effect Credit
**Issue:** Reggie White was so dominant that OCs called plays away from him and OLs double-teamed him. Both effects reduce his raw stat counts (sacks, tackles) while actually reflecting his value. How do we capture this?
**Potential signals:**
- When team sack total is high but Reggie's personal sack share is moderate, check if sacks are concentrated in players adjacent to him (beneficiary of the double team)
- Post-2009 nflfastR data: track run direction tendencies away from known dominant DE
- WOWY is the bluntest instrument but captures this indirectly
**Status:** No clean solution pre-2009. Flag as known undercount for pass rushers with high WOWY and moderate ISS.

### Q3: Tackle Share Pre-2001 Without Gamebook Data
**Issue:** PFR tackles are unreliable pre-2001, and gamebook data only covers MIN/PIT (and some other teams partially). For players on teams with no gamebook data (e.g., Reggie White on PHI 1985–1992), we have no reliable tackle share.
**Options:**
a) Use PFR tackles with a large uncertainty flag — still informative as directional signal
b) Leave tackle_share NULL and weight sack share + WOWY higher for those seasons
c) Try to source tackle data from the media guide pipeline (team yearbooks often listed tackle totals)
**Status:** Option (b) is the safe default. Option (c) is the better long-term path. Pursue media guide pipeline integration.

### Q4: Strike Years — 1982 and 1987
- **1982:** 9-game season (players' strike). Sack totals need to be rate-normalized vs. a 16-game season. Use per-game rates, not season totals.
- **1987:** 15-game season, but 3 of those were replacement player games (weeks 4–6). Real NFL players played 12 games. Replacement games should be excluded entirely from individual stats, but team defensive rankings for the season are muddied.
**Status:** Flag these years in all ETL with a `season_type = 'strike'` note. Use per-game rates, not totals, for those seasons.

### Q5: Mid-Season Trades
**Issue:** A player traded mid-season (e.g., from Team A at game 7 to Team B at game 8) appears on two teams in `player_defense_season`. Both the individual stats and WOWY calculations become complex.
**Decision needed:** 
- Assign DPVS score to the team where they played the most games?
- Split proportionally?
- Only compute DPVS for team where >= 8 games played?
**Status:** Open. For initial implementation, follow PFR's convention (two separate season rows, one per team).

### Q6: Franchise Relocations in WOWY
**Issue:** The Houston Oilers became the Tennessee Titans. The Cleveland Browns became the Baltimore Ravens (sort of). When computing WOWY, should a player who left the Oilers before they moved be compared to the relocated franchise's defense?
**Decision:** Generally yes — use franchise continuity, not geographic. But flag the relocation year. The move itself may have reset the roster enough that the WOWY comparison is low confidence anyway.

### Q7: Defense Scheme Changes
**Issue:** A new defensive coordinator changing from a 4-3 to a 3-4 could dramatically change team defensive ranks, independent of player additions/removals. This is a confounder for WOWY.
**Proxy:** `coaching_change` boolean in `wowy_pairs` flags this case. But scheme change under the same coordinator is harder to detect.
**Status:** Flag coaching changes. Longer term, could scrape coordinator data.

### Q8: Minimum Games Threshold for DPVS
**Issue:** A player who plays 3 games shouldn't get a DPVS score that's directly comparable to a full 16-game contributor.
**Proposed rule:** Require >= 8 games played (50% of season) for a DPVS score to be computed. Partial seasons get a `data_completeness` flag < 1.0 and a note.

### Q9: How to Weight Run Defense vs. Pass Rush
**Issue:** Some dominant defenders are primarily pass rushers (Reggie White, Deacon Jones), others are elite run stoppers (Mean Joe Greene, who was also a great pass rusher). Should DPVS weight pass rush more heavily, or be position-neutral?
**Consideration:** Pass plays are roughly 60% of modern NFL plays. In the 1960s–70s it was closer to 40%. Era should affect weighting.
**Status:** Open. Start with balanced weights; revisit after seeing variance in the data.

---

## Offensive Player OQA

### Q15: RB Comparison Baseline — Resolved

**Issue:** Should an individual RB's rush yards be compared against the defense's
total team rush yards allowed per game, or something else?

**Discovery (the Keith Byars problem):** The naive comparison (individual yards vs.
team defensive average) systematically produces negative deltas for *all* running
backs, including elite ones. Herschel Walker (1,514 rush yards, 1988) came out at
−260 for the season; Eric Dickerson (1,659 yards) at −320. The root cause: defenses
allow ~110 rush yards per game *to the whole team*, but even a featured back averages
only 90 yards per game — multiple players share carries.

Keith Byars (PHI 1988) made this explicit. As a receiving/blocking back, he got
5–50 rushing yards per game while facing defenses that allow 100+ team rush yards.
The naive metric read him as −1,297 yards for the season — worse than any starter —
with no useful signal.

**Resolution:** Use carry-adjusted expected yards:
```
expected_rush_yds = player_rush_att × defense_avg_rush_ypc_allowed
delta_rush_yds    = actual_rush_yds − expected_rush_yds
```

This measures per-carry efficiency vs. the defense, controlling for the number of
carries the player received. Barry Sanders 1997 goes from +264 (naive, still wrong
direction) to +712 carry-adjusted, with individual game breakdowns showing his
greatest performances in proper context.

**Status:** Resolved. Implemented in `scripts/etl_player_game_offense.py`.

---

### Q16: WR #1 Identification for Individual OQA — Planned

**Issue:** Teams play 3+ WRs per game. Comparing one WR's yards to the defense's
total WR yards allowed mixes role types. The 2007 Patriots problem:

- Randy Moss: massive yards, double coverage, unambiguous #1 WR by impact
- Wes Welker: leads the team in receptions on short routes as the slot receiver

By reception count, Welker appears to be the #1 WR. By per-game yards and
contextual role, Moss is clearly #1.

**Proposed approach:** Rank WRs by **season yards per game** (total rec_yds /
games_played — not total yards, to avoid penalizing players for missed games due
to injury). The #1 WR for the season is the highest YPG receiver.

For any specific game: check if the #1 WR played. If yes, mark them `is_primary`.
If they missed the game (injury, etc.), fall back to the next-highest YPG WR who
has a row in `player_game_offense` for that game.

For the defense-side average: instead of "total WR yards allowed per game,"
compute "yards allowed specifically to the opponent's #1 WR per game" — requiring
a second-pass calculation after #1 WR identification.

**Validation:** 2007 New England Patriots — Moss should be identified as #1 WR
by this method. Any season with a clear top receiver (Randy Moss, Jerry Rice,
Calvin Johnson in peak years) should pass a similar sanity check.

**Status:** Planned. Current implementation stores individual WR game stats and
uses WR group totals as a floor comparison. `is_primary` flag marks the top
rec_yds WR per team per game as a placeholder.

---

## Data / Infrastructure

### Q10: PostgreSQL vs. SQLite
**Issue:** PostgreSQL is the target but adds operational overhead (server, connection management). For a solo research project, SQLite might be simpler to start.
**Decision:** Start with SQLite for rapid prototyping (single file, zero setup), with the schema designed to be PostgreSQL-compatible for migration later. Use SQLAlchemy or similar so the switch is one-line.

### Q11: ETL Script Language
**Proposed:** Python, using pandas for CSV loading and psycopg2 / SQLAlchemy for DB writes.
**Alternative:** DuckDB for exploratory heavy lifting (reads CSVs directly, very fast, SQL native).
**Recommendation:** Use DuckDB for initial exploration and prototype calculations, then write a proper Python ETL for production loading. DuckDB can read the CSV files directly without loading them first.

### Q12: What Data Still Needs Scraping?
See `data_sources.md` section 5. Priority order:
1. Individual defensive player game logs (PFR) — needed for per-game sack share pre-2001
2. Opponent OL individual player identities per game — needed for OMG
3. Team defensive sub-tables (passing/rushing splits) — may already be available in pfref

---

## Presentation / Website

### Q13: Static Site vs. Dynamic App
**Goal:** Per-player pages, season leaderboards, career comparisons.
**Current thinking:** Statically generated from the database (PostgreSQL → JSON/CSV → static HTML/JS). No server-side rendering needed if data is pre-computed.
**Tools:** Astro, Next.js static export, or even just a Python Jinja template renderer.
**Status:** Future scope — not blocking the analytics work.

### Q14: Cross-Era Comparison
**Issue:** How do you compare Reggie White 1988 to Myles Garrett 2023? The league has changed dramatically (more passing, different rules, different number of teams).
**Approach:** Normalize DPVS within season × position group, not across eras. The "best pass rusher of 1988" is comparable to the "best pass rusher of 2023" in relative terms. Absolute sack counts are not.
**Add-on:** Era adjustment factor if we want cross-era ranking — but this is inherently subjective.

---

## Player-Specific Research Questions

### Reggie White
- What was his sack share in each of his PHI seasons? (Need per-game or season sack totals for PHI)
- How did opponent sack rates change in games vs. PHI 1985–1992 vs. their season average?
- In 1988, PHI was 27th in yards allowed despite Reggie being arguably the best DE in the NFL. Who were the weak links? Can the OQA + WOWY framework isolate that he was doing his job while the rest underperformed?
- Media guide tackles for PHI 1985–1992: can we source these to build tackle share?

### Alan Page (MIN 1967–1978)
- Gamebook pipeline is the primary data source — most of the 1967–1981 Viking games are processed
- 1971: won NFL MVP as a DT — DPVS should confirm this as an exceptional season
- Career arc: Page was asked to drop weight (~245 lb by late career) and became more of a speed rusher — how does DPVS track that transition?

### Mean Joe Greene (PIT 1969–1981)
- Some gamebooks processed for Steelers
- The Steel Curtain era (1974–1979) should show strong WOWY — but the whole defense was elite together, which makes individual attribution hard

### Deacon Jones (LA Rams 1961–1971)
- Pre-1982 sacks are reconstructed estimates
- No gamebooks expected for Rams
- WOWY is the primary signal here
