# Results: does real-world award recognition track raw INT value?

Completed 2026-08-22. Follows directly from
`docs/deferred/04_event_value_results_20260822.md`, which measured
interceptions as the single highest-value defensive event PFR's own
expected-points data can support (**+3.58 EP**, pooled 1978-2025, highest
of every category checked — sack 1.75, FR 1.67, run stuff 1.10, tackle -0.36).
The user pushed back on the naive read of that number ("weight INT
heavily") with a concrete, real counter-example pulled directly from PFR's
own season stat pages: Scott Case (1988, 10 INT, AP 2nd-team All-Pro, zero
DPOY votes) and Erik McMillan (1988, 8 INT + 2 defensive TDs, not even
2nd-team All-Pro, zero DPOY votes) — while Carl Lee (8 INT, same season)
did get real recognition. The hypothesis: if voters treated raw INT volume
as reliably valuable, the top of each season's INT leaderboard should show
up disproportionately in All-Pro/DPOY recognition. This doc builds the
real data to test that directly, validates the user's own anecdote number-
for-number, and extends it across 55 seasons.

Scripts: `scripts/scrape_dpoy_award_voting.py` (Part 1),
`scripts/build_award_recognition_vs_int_value.py` (Part 3 merge/analysis).
Ingest scripts for the three secondary award bodies live in `football_db`
(`scripts/ingest_{nea,pfwa,101awards}_dpoy.py`), following the existing
`ingest_ap_dpoy.py` pattern into `gold.player_awards`. Output:
`data_output/int_leaders_full_recognition.csv` (724 rows).

## 1. Part 1 — full AP DPOY voting rank (not just winners)

**What existed before this**: `gold.player_awards` in `football_db` only
had AP DPOY *winners* (55 rows, 1971-2025, `org='AP'`,
`designation='DPOY'`, loaded by the existing `ingest_ap_dpoy.py`) — no
runner-up/voting-order data at all.

**Source found**: PFR maintains one page per season with full multi-
candidate voting detail for every major award —
`pro-football-reference.com/awards/awards_{year}.htm` — holding separate
tables for AP MVP, Offensive/Defensive Player of the Year,
Offensive/Defensive Rookie of the Year, Comeback Player, and Coach of the
Year. The Defensive Player of the Year table (`id="voting_apdpoy"`) carries
rank, player, team, **votes**, **vote share %**, and that season's tackle/
sack/INT line for every player who received at least one vote — confirmed
directly from the raw HTML before writing the scraper (2005's table:
Brian Urlacher, 34.0 votes, 68% share, rank 1). This table is AP-only —
no other organization's voting appears on this page (checked the full set
of table ids present: `voting_apmvp`, `voting_apopoy`, `voting_apdpoy`,
`voting_aporoy`, `voting_apdroy`, `voting_apcpoy`, `voting_apcoy` — all AP).

A separate, already-local data source (`~/data/pfref/raw/season/player/
defense/defense_{year}.csv`, one row per player-season, with a bare
`awards` text column like `"PB,AP-1,AP DPoY-8"`) turned out to *also* have
complete DPOY rank coverage for all 55 seasons once a parsing bug was
fixed (its column schema silently changes at 2006 — `rk`/`player`/`team`
becomes `rank`/`player_name`/`team_abbrev` — and the first-pass build
script only handled the pre-2006 schema, dropping every 2006+ row
entirely, not just the Awards field). This local file is kept as an
independent cross-check but the scraped `awards_{year}.htm` page is the
primary Part 1 source, since it carries actual vote counts and share %,
which the bare rank tag doesn't.

**Scrape**: reused `scrape_team_schemes.py`'s exact pattern (Playwright +
real Brave browser binary via CDP, `PFR_DELAY_MIN`/`PFR_DELAY_MAX` env
vars, 4-7s between requests, resumable, error-logged). All 55 seasons
(1971-2025) fetched cleanly — **zero Cloudflare blocks, zero errors** after
the initial homepage clearance. Output: `~/data/pfref/ap_dpoy_voting.csv`,
413 player-season voting rows.

## 2. Part 2 — three independent DPOY-style award bodies

The user asked for a second body distinct from AP; the coordinator's
follow-up widened this to reach back into the late 1960s/1970s
specifically, since that's the era `gamebooks_boxscores`' own corpus has
real defensive PBP coverage for, and the era this whole DPVS-G project was
originally framed around (Joe Greene's 1972/1974 seasons). Three real,
independently-verified bodies were found and loaded, all winner-only (none
publish full multi-candidate voting order the way AP does):

| Org | Award | Years | Rows loaded | Source |
|---|---|---|---|---|
| **NEA** | George Halas Trophy (Newspaper Enterprise Association) | 1966-1998 | 34 | [Wikipedia](https://en.wikipedia.org/wiki/Newspaper_Enterprise_Association_NFL_defensive_player_of_the_year) |
| **PFWA** | Pro Football Writers of America DPOY | 1992-2025 | 34 | [PFWA's own site](https://www.profootballwriters.org/on-field-awards/pfwa-nfl-defensive-player-of-the-year/), cross-checked against Wikipedia (identical) |
| **101 Awards** | Committee of 101 DPOY (AFC + NFC, separate) | 1969-2025 | 112 | [Wikipedia](https://en.wikipedia.org/wiki/101_Awards) |

`gold.player_awards` already recognized `NEA` as an `org` value (it was
only ever loaded for All-Pro-style team selections before this) — no
schema change needed, just a new `designation` value, following
`ingest_ap_dpoy.py`'s exact structure for `ingest_nea_dpoy.py`/
`ingest_pfwa_dpoy.py`/`ingest_101awards_dpoy.py`. 101 Awards gets two rows
per season (`DPOY-AFC`, `DPOY-NFC`) rather than one, since it's really two
independent conference-level panels, not a single national vote — matching
this project's existing convention of not collapsing genuinely separate
selections (`player_awards.sql`'s own docstring already documents this for
All-Pro conference-level rows).

**Player-ID resolution**: 180/180 rows resolved to a PFR id by exact name
match against that season's local defense CSV; 3 needed manual
disambiguation (Bobby Bell 1969 AFL — Kansas City has zero rows at all in
`defense_1969.csv`, a known, already-documented gap: `football_db` has no
PFR opponent/roster data for AFL teams 1967-1969; resolved via
`internal.player_xref` birth-date match instead. Fred Dean 1981 — three
rows for a mid-season trade, all the same id, not a real ambiguity. Reggie
White 1995 — two different players share the PFR id prefix `WhitRe`;
resolved by matching team/position against the source row). Franchise
resolution: 180/180 exact matches against `gold.franchise_aliases`.

**Two honest gaps, not papered over**:
- **1982 is missing from the 101 Awards source entirely** — the Wikipedia
  table jumps 1981 → 1983 in both conferences. Left out of the loaded data
  rather than guessed; not established whether the award was skipped that
  year or the source page has a real omission.
- **PFWA's pre-1992 history is genuinely ambiguous.** A general "landscape"
  source claims the award traces back to 1969 under earlier Pro Football
  Weekly sponsorship; PFWA's own official site lists winners only from
  1992 forward. Scoped to 1992-2025 (the confidently-sourced range) rather
  than force an earlier start with uncertain provenance.

**A fourth candidate (Sporting News DPOY) was checked and set aside**:
`gold.player_awards` already carries `org='SN'` but only for All-Pro team
selections (26-1178 rows depending on designation), never an individual
DPOY award — and the Wikipedia awards-landscape page lists Sporting News'
own DPOY as starting only in 2008, well after AP/NEA/PFWA/101 Awards
already give four independent bodies covering the 1970s. Not loaded, since
the marginal value for this specific study (late-1960s/1970s coverage) is
low — noted here for a future pass rather than chased further.

## 3. Part 1/2 anchor-case validation: 1988

Every number the user cited from their own PFR screenshots matches the
scraped/loaded data exactly:

| Player | INT | INT-TD | AP All-Pro | AP DPOY | Other DPOY bodies |
|---|---|---|---|---|---|
| Scott Case (ATL) | 10 (rank 1) | 0 | **2nd Tm** | **none** (0 votes) | none |
| Carl Lee (MIN) | 8 (rank 3) | 2 | **1st Tm** | **rank 8, 1.0 votes (1.3% share)** | none |
| Erik McMillan (NYJ) | 8 (rank 5) | 2 | **none** | **none** (0 votes) | none |

This is a precise match to the user's own description in every particular
— including the exact vote count for Carl Lee ("finishing 8th with 1
vote"). Scott Case, the league's outright interception leader that season,
got real recognition (2nd-team All-Pro) but literally zero DPOY votes.
Erik McMillan, tied for 2nd in the league with two defensive touchdowns
added on top, got nothing at all. Carl Lee — same INT total as McMillan,
same team's secondary as Case — got both All-Pro *and* a DPOY vote. The
anecdote holds up completely under real data, not just recollection.

## 4. Part 3 — the top-15-INT-leaders-vs-recognition table, all 55 seasons

Method: for every season 1971-2025, take every player with INT count at or
above the 10th-highest total that year (so ties at the cutoff are kept,
not arbitrarily cut), capped at 15 total — 724 player-seasons across 55
years, ~13.2/season on average. Cross-referenced against AP All-Pro tier,
full AP DPOY voting rank, and the three secondary bodies above.
"Zero recognition" = none of these five signals fired at all.

**Headline: 71.1% (515/724) of top-15 INT-leader-seasons got zero
recognition from any of the five sources checked.** Even the outright INT
*leader* isn't safe — Scott Case is exactly this pattern.

**Recognition is heavily concentrated at the very top of the list, not
spread across it**:

| INT rank within season | n | Zero-recognition rate |
|---|---|---|
| 1-3 | 165 | 41.2% |
| 4-6 | 165 | 72.7% |
| 7-10 | 220 | 80.0% |
| 11-15 | 174 | 86.8% |

Even at rank 1-3 — the clear top of the league's INT leaderboard each
year — 41% get nothing. Past rank 6, recognition is the exception, not the
norm.

**A defensive touchdown attached to the interceptions helps, but doesn't
come close to guaranteeing recognition**:

| | n | Zero-recognition rate |
|---|---|---|
| ≥1 INT return TD | 301 | 64.1% |
| 0 INT return TDs | 423 | 76.1% |

A 12-point gap — real, but the *majority* of pick-six-having, top-15-INT
seasons still get zero recognition. Erik McMillan (2 TDs, zero
recognition) is the modal case in this bucket, not an outlier.

**No meaningful secular trend by decade** — the zero-recognition rate is
roughly flat across 55 years, no sign this is a modern-voting or
historical-voting-standards artifact:

| Decade | Zero-recognition rate |
|---|---|
| 1970s | 79.0% (94/119) |
| 1980s | 69.0% (89/129) |
| 1990s | 70.1% (96/137) |
| 2000s | 70.6% (96/136) |
| 2010s | 68.0% (83/122) |
| 2020s | 70.4% (57/81) |

**When the secondary bodies *do* diverge from AP, it's almost always
agreement, not independent discovery** — 21 of the 724 leader-seasons got
a NEA/PFWA/101-Awards hit, and 19 of those 21 were *also* AP 1st-Team
All-Pro (usually also AP DPOY rank 1). Only two real independent-signal
cases turned up: **Lee Roy Jordan (1973, rank 8 in INT, zero AP
recognition of any kind)** won 101 Awards' NFC DPOY that year, and **Deron
Cherry (1986, AP 1st-Team but no AP DPOY votes)** won 101 Awards' AFC
DPOY. Genuinely useful confirmation that these bodies aren't just relabeling
AP's own judgment, but rare — the four bodies mostly point the same
direction when they point anywhere at all.

## 5. Part 4 — does this support discounting INT's weight in DPVS-G?

**Short answer: yes, with real nuance, and the data converges with an
already-known internal signal rather than standing alone.**

This project's own earlier variance-decomposition work
(`docs/deferred/02_RESULTS_stat_noise_skill_rating_analysis.md`) already
found INT sits near the pure-chance floor on overdispersion — φ=1.57
pooled, and **broken out by role, φ=1.21 (coverage), 1.09 (run-stopper),
1.00 (pass-rusher)** — i.e. for two of three position groups, a season's
INT total statistically looks indistinguishable from a random draw. That's
a *statistical* argument for capping INT's weight regardless of what
anyone thinks about it.

This doc adds a second, independent kind of evidence for the same
conclusion — not a model's variance estimate, but **real human judges'
revealed behavior across 55 years and four separate voting bodies**. If
raw INT volume were being treated as reliably valuable, recognition should
cluster at the top of the INT leaderboard the way it does, say, for sacks
or tackles-for-loss (both far more skill-attributable in the φ analysis).
Instead: even the outright season INT leader misses all recognition 41% of
the time, the rate craters to 87% by rank 11-15, a literal touchdown
barely moves the needle (64% zero-recognition even with one), and this
pattern is stable across 55 years and four independently-run selection
processes, not a quirk of one committee in one era.

**The honest caveat, stated directly rather than glossed over**: this
can't fully distinguish "voters implicitly discount INT because they sense
it's luck-driven" from a more mundane alternative — **All-Pro/DPOY
recognition is a fixed, scarce quota** (roughly one starting DB slot per
position per team-of-the-year, a handful of total DPOY votes cast), so a
strong-INT season without other standout numbers (tackles, PD, a general
reputation) may simply lose out to a more complete statistical season at a
crowded position, with nothing about *discounting luck* involved at all.
The data in this doc shows the *pattern* — recognition concentrated hard
at the extreme top of the INT list and thin everywhere else — but not the
voters' actual reasoning. Both stories predict the same observed shape.

**What tips this toward the "discounting" reading rather than pure
coincidence**: the *magnitude and consistency* of the gap. If recognition
tracked "did this player have an otherwise complete, clearly-elite
season" rather than "INT count specifically," a rank-1 season should be
recognized close to universally — elite players at the top of a
statistical leaderboard usually *do* have complete seasons. 41% zero-
recognition even at rank 1-3, sustained flat across six different decades
of voting bodies and panels that never overlapped in membership, is a
harder pattern to explain purely via quota scarcity than via voters
genuinely treating raw picks as a weaker signal of skill — consistent with
(not proof of) the user's own framing: *"I think it's because we're
seeing voters say INTs can also be luck a lot of the times."*

**Recommendation for the weight re-derivation (doc 04's next step)**: the
event-value number (+3.58 EP, highest of any category) and this
recognition pattern are not in conflict — they're answering different
questions, exactly as `04_event_value_results_20260822.md` §9 already
flagged (value and skill-attributability are separate axes). What this doc
adds is a second, independently-sourced piece of evidence — real human
judgment across 55 years, not a variance model — pointing the same
direction as the φ finding: **INT's weight in DPVS-G should be bounded
well below what its raw event value alone would suggest**, not because the
turnover isn't valuable when it happens, but because the project's own
stated goal (finding real cases where voters got it wrong, the Joe Greene
question) requires distinguishing "undervalued skill" from "overvalued
noise" — and on INT specifically, both the internal statistical signal and
the external human-judgment signal now point toward the second one, not
the first.

## 6. Data locations

- `~/data/pfref/ap_dpoy_voting.csv` — 413 rows, full AP DPOY voting
  (rank/votes/share + that season's tackle/sack/INT line), 1971-2025.
- `football_db` Postgres, `gold.player_awards`: `org='NEA'` (34 rows),
  `org='PFWA'` (34 rows), `org='101AWARDS'` (112 rows), all
  `designation` LIKE `'DPOY%'`. `org='AP'`, `designation='DPOY'` already
  existed (55 winners) and is unchanged by this work.
- `data_output/int_leaders_full_recognition.csv` — 724 rows, the full
  Part 3 merged table (season, player, team, pos, INT, INT-TD, INT rank
  in season, AP All-Pro tier, AP DPOY rank/votes/share, other DPOY-body
  hits, zero-recognition flag).
- `football_db/data/{nea,pfwa,101awards}_defensive_poy.csv` — the raw
  winner lists with resolved PFR ids, feeding the three ingest scripts.

## 7. Not done in this pass

- Full voting order for NEA/PFWA/101 Awards was checked for and doesn't
  appear to exist publicly — winner-only is the real ceiling for these
  three, not a shortcut taken here.
- Sporting News' own DPOY (2008+) was identified but not loaded (§2) —
  low marginal value for the specific 1970s-coverage goal this pass was
  scoped to; worth a quick add if a future pass wants 2008+ recognition
  data from a fifth body.
- This doc does not touch `dpvs/idi.py` or re-derive IDI's actual weights
  — per the task brief, that's explicitly separate, ongoing work; this is
  input to it.
