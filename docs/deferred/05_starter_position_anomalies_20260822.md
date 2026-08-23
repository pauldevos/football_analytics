# Starter-focused position/scheme anomaly report

Completed 2026-08-22, on top of `docs/deferred/05_position_scheme_grouping_scoping.md`
and `docs/deferred/05_RESULTS_position_scheme_classifier_20260822.md` (read
those first — this doc assumes the 8-bucket taxonomy and the classifier's
`data_output/position_scheme_classification.parquet` output as given).

This is a working review list, not a teaching piece — organized for the
user to go through flagged cases directly, per their own framing: *"You may
have players who are not starters who are playing multiple positions
because they don't start... I'm happy to look at these individually if
needed, especially for players that are starters."*

Script: `football_analytics/scripts/build_starter_position_anomalies.py`.
Full flagged list (720 rows, one per anomalous player-season): `data_output/
starter_position_anomalies.csv`. Read-only against `football_db` and the
Phase 2 parquet; writes only its own output files. No production pipeline
code touched.

## 1. Scope and method

**Starters only, 1967-2025.** A "starter" is anyone `starters.csv` lists
for that game — that's what the file records, no separate filter needed.
1950-1966 was **excluded**, not just left as a maybe: the classifier's own
8 named buckets don't exist before 1967 (`gold.team_scheme_coach_season`
starts there), so there's no season-level classification to check a pre-1967
starter's game log against in the first place. Checking raw position
consistency without a scheme label would be a materially different,
smaller task than what was asked for here (whether a player fits their
*classified* profile) — better left as explicit future scope than folded in
under the same "anomaly" umbrella.

**Data**: `~/data/pfref/raw/boxscores/{year}/{game_id}/starters.csv`
(14,013 games, 616,571 starter rows scanned). `pfr_player_id` resolved via
`internal.player_xref` (`source_system='pfr'`), same pattern
`load_dpvs_g_to_db.py`/`build_tackle_quality_by_position.py` already use.
`team_abbrev` resolved to `franchise_id` via `gold.franchise_aliases`
(season-bounded, handles franchise moves/renames correctly — 0 unresolved).
Per-game `pos` normalized to the same `pos_group` values the classifier
itself uses (`gold.position_taxonomy`, plus the classifier's own small
`LEGACY_POS_GROUP` fallback for old-notation codes).

**Coverage**: of 616,571 starter rows, 5,094 had no PFR-id xref match,
462,061 belonged to a `(player_id, season)` the classifier didn't put in
one of its 8 named buckets (offense, DB/secondary, or a gap bucket — all
correctly out of scope here), and 2,511 had no position mapping at all.
**12,175 starter player-seasons** had at least one trackable game against a
named classified bucket — that's the real denominator this report checks.

**Threshold**: an alternate `pos_group` needs **≥3 starts** in that season,
outside the family of `pos_group`s consistent with the player's classified
bucket, to count as a flagged anomaly — the user's own suggested language.
A 1-2 game blip is far more likely a data quirk or a single unusual game
plan than a real role signal, and is excluded entirely (not even shown in
the CSV). Full family mapping used:

| Classified bucket | Consistent `pos_group`(s) |
|---|---|
| 3-4 NT | NT |
| 3-4 DE | DE |
| 3-4 OLB (edge) | OLB |
| 3-4 ILB/MLB | ILB, MLB |
| 4-3 DE | DE |
| 4-3 MLB | MLB, ILB |
| 4-3 OLB | OLB |

**A critical data-quality fix made mid-analysis, worth stating plainly**:
the first pass flagged 1,483 anomalies, but direct inspection of raw
`starters.csv` rows across eras showed PFR's own starters template changed
materially over time. Pre-2010s rows are consistently side/role-specific
(`LDE`, `RILB`, `LOLB`, `MLB`, `RLB`...). From roughly 2016 on, many teams'
rows collapse to bare `LB` x2-3 and bare `DL`/`DT` slots with **no side or
role information at all** — e.g. a 2024 Chiefs row literally reads `DE, DE,
DT, DT, LB, LB, LB`. A bare `LB` carries zero positional signal; treating it
as "inconsistent with ILB/MLB" was PFR's own template losing granularity,
not a real anomaly. This class alone accounted for 781 of the original
1,483 flags (53%) — almost entirely bare `LB`/`DL` values. Fixed by
excluding `LB`/`DL` from ever triggering or being selected as the "top
inconsistent position" (still counted toward total games started, just
never counted as evidence of anything). **720 real flags remain** after
this fix — the number everything below is built from.

## 2. Volume summary

- **12,175** starter player-seasons checked against a named classified bucket
- **720** flagged as real anomalies (≥3 starts at a genuinely informative
  alternate position), across **536 unique players**
- Full detail (all 720 rows: player, season, classified bucket, every
  position they actually started at that season and how many times, the
  franchise(s), and a `category` column — see below) is in
  `data_output/starter_position_anomalies.csv`

## 3. The 720 flags split into four real categories — read this before the individual list

Sorting strictly by volume without categorizing would bury the genuinely
interesting cases under three large, systematic patterns that are mostly
**not** individually meaningful. Breaking them out first:

| Category | n | What it is |
|---|---:|---|
| `systematic_DL_interior_edge` | 375 | Classified 3-4 NT/3-4 DE/4-3 DE, game-level shows DE/DT/NT cross-labeling |
| `systematic_LB_role_overlap` | 240 | Classified 3-4 ILB-MLB/4-3 MLB/4-3 OLB/3-4 OLB, game-level shows ILB/MLB/OLB cross-labeling |
| `DE_OLB_edge_tweener` | 79 | Classified DE-family, game-level shows OLB (or vice versa) — real "stand-up edge" usage |
| `front7_to_secondary` | 26 | Classified front-seven, game-level shows CB/S/DB — the strongest, most novel individual signal |

**`systematic_DL_interior_edge` (375) and `systematic_LB_role_overlap`
(240) are, for the large majority of rows, near-100%-one-label patterns**
(median games at the "inconsistent" position: 6, but the top of each list
is 16-19 out of 16-19 total starts — i.e. every single start that season).
Seeing a classified `3-4 DE` (Justin Smith, Haloti Ngata, Ray McDonald,
Darnell Dockett, Cameron Heyward, Christian Wilkins, dozens more) come back
as `DT` in **every** game, across 40+ years and dozens of different real
3-4 defensive ends, is not plausibly 40 years of individual role changes —
it reads as a genuine notational difference between the two PFR source
tables: `silver.player_team_seasons_pfr.position` (the classifier's season
input) reflects a player's roster-listed primary position, while
`starters.csv`'s own slot grid appears to label the same 3-4 5-technique
end as an interior "DT" slot far more consistently than the season-position
field does. Same logic for `ILB/MLB` vs `OLB` in the LB group. **These 615
rows are shown in the CSV for completeness and are individually
inspectable, but are not prioritized below** — treating each one as a
personal anomaly to review would mean reviewing what looks like a
structural labeling difference between two PFR tables, not 615 real
football stories. This is worth fixing in the classifier or starters-join
logic itself as a follow-on (see §5), separately from user review of
individuals.

**`DE_OLB_edge_tweener` (79) is a real, well-documented football
phenomenon**, not noise: modern "stand-up edge" pass rushers who play with
a hand in the dirt (DE) in some looks and stand up (OLB) in others,
depending on package. The very top of this list is a who's-who of exactly
that role: Von Miller, Khalil Mack, Terrell Suggs, Ryan Kerrigan, Elvis
Dumervil, Jason Babin — all real edge rushers whose listed slot genuinely
does move with formation. This category is closer to "the 8-bucket
taxonomy's binary split can't fully capture this player" than "the
classifier is wrong," but a handful are worth a second look (§4).

**`front7_to_secondary` (26) is the strongest, most actionable category.**
A player classified into a front-seven bucket showing up repeatedly at
CB/S/DB is unusual enough (26 out of 12,175 checked seasons) that it isn't
a systematic artifact — every name on this list is either a real,
documented hybrid "nickel/moneybacker" defender, or a genuine data
question worth the user's own eyes. This is where review time should go
first.

## 4. Top individual cases — prioritized for review

### Tier 1 — `front7_to_secondary` (26 total, full list in the CSV)

Sorted by volume (games started at the alternate position). All of these
are STARTERS with real games-started volume, not marginal 2-3-game blips.

| Player | Season | Classified | Actual starts | Games | Note |
|---|---|---|---|---|---|
| Taron Johnson | 2021 | 4-3 OLB | CB | 17/17 | Bills' long-time starting **slot corner** — never an LB in real usage. Season-level position field likely wrong, not a real hybrid case. |
| Taron Johnson | 2022 | 4-3 OLB | CB | 14/14 | Same player, same pattern, second season — strengthens the case this is a real season-position data issue, not a one-off. |
| Deommodore Lenoir | 2024 | 4-3 OLB | DB | 15/15 | 49ers CB by trade; worth checking why season position says OLB. |
| Mark Barron | 2016 | 4-3 OLB | S | 14/15 | Real, well-documented "moneybacker" hybrid safety-LB (Rams/Bucs) — Barron was drafted a safety and moved into a de facto LB role; also flagged 2014 (S:7/9) and 2015 (S:6/12, mixed with OLB) — a genuine three-year hybrid arc, not a data error. |
| David Little | 1988 | 3-4 ILB/MLB | DB | 15/15 | Steelers LB — worth a name-collision sanity check (era predates most starters.csv template consistency); see caveat below. |
| Jeremy Chinn | 2020 | 4-3 OLB | S | 11/15 | Well-documented "big nickel"/hybrid safety-LB for Carolina — genuinely real positionless usage, not an error. |
| Harry Carson | 1988 | 3-4 ILB/MLB | DB | 11/11 | HOF Giants MLB — a `DB` label for Harry Carson doesn't match any known part of his real career; flag as a likely **data/name-collision issue**, not a real role, and worth checking directly against `gold.players` before trusting (same class of bug doc 05 flagged for "Ted Washington"). |
| C.J. Gardner-Johnson | 2021 | 4-3 OLB | S | 11/11 | Real, documented "star"/hybrid safety — drafted and plays safety, PFR sometimes lists hybrid slot defenders under a generic LB-family season position. |
| Mackensie Alexander | 2020 & 2021 | 4-3 OLB | CB | 10/10, 5/5 | Real starting CB (Vikings/Bengals/Chiefs) — season position label looks wrong both years. |
| Adrian Phillips | 2022 | 4-3 OLB | S | 8/8 | Patriots hybrid safety/LB "money" defender — real modern trend. |
| Lamarcus Joyner | 2020 | 4-3 OLB | S | 5/6 | Real safety (Rams/Raiders), well documented. |

**Read across this tier**: a clear pattern emerges — most of these are
modern (2014+) "positionless" hybrid slot/nickel defenders whose *season*
position field lands in a generic OLB/LB bucket even though their *actual*
per-game starting role is clearly DB. This is close to exactly the "6-10
players per year genuinely moonlighting" case doc 05 anticipated for
hybrids — except several of these (Taron Johnson, Lenoir, Mackensie
Alexander) read less like genuine hybrids and more like the underlying
season-position source data being wrong for players whose true position is
unambiguously DB. **Recommend the user start here** — this list is short
(26 rows total, in the CSV), high-signal, and each case is easy to verify
against known player history.

**Caveat on the two 1980s cases** (David Little 1988, Harry Carson 1988,
also Thomas Benson 1987 further down the list): checked directly against
`gold.players` — there is only one `Harry Carson` (player_id 2795, b.
1953-11-26) and one `David Little` (player_id 15732, b. 1959-01-03) in the
table, so this is **not** a name-collision bug (the class of error doc 05's
"Ted Washington" case warned about) — the `player_id` resolution is
correct. The raw `starters.csv` rows themselves genuinely say `DB` for
Harry Carson in 1988 (verified directly: `grep "Harry Carson"
~/data/pfref/raw/boxscores/1988/*/starters.csv` → `DB` in every row that
season, his final NFL season). Harry Carson was an unambiguous Hall of Fame
MLB, never a defensive back, so this reads as a genuine PFR source-data
quirk specific to that season/team's box-score template — not a real
football finding about Carson, and not a resolution bug on this project's
side either. Still worth the user's eyes as a "the source data itself says
something implausible" case, distinct from the modern hybrid-defender
cases above.

### Tier 2 — `DE_OLB_edge_tweener`, mixed (non-100%) seasons only

The 100%-one-label rows in this category (Von Miller 2021: OLB 19/19 vs.
classified `3-4 DE`; Khalil Mack 2022: OLB 17/17 vs. classified `3-4 DE`)
are almost certainly the classifier's season-position source disagreeing
with real per-game usage for a specific season — both players are
career-long, unambiguous edge/OLB types, so a "DE" season label for either
looks like a data quirk worth a direct follow-up, not really a "hybrid"
question. The genuinely interesting subset is the **mixed-within-season**
rows — real week-to-week flexibility, not a single wrong label:

| Player | Season | Classified | Breakdown | Read |
|---|---|---|---|---|
| Adalius Thomas | 2007 | 3-4 ILB/MLB | ILB:9, OLB:9 | Exactly even split — Thomas was famously used all over the Patriots defense ("space player") — a real, well-documented hybrid. |
| Roman Phifer | 2001 | 4-3 OLB | OLB:12, DE:6, LB:1 | Veteran LB known for positional flexibility late career (Patriots). |
| Mike Vrabel | 2005, 2006 | 3-4 ILB/MLB, 3-4 OLB (edge) | ILB:13/OLB:5, OLB:11/ILB:8 | Vrabel is a famous "Swiss army knife" LB for Belichick's Patriots defenses — genuinely moved inside/outside by game plan. Real, not a data issue. |
| Clay Matthews | 2014 | 3-4 OLB (edge) | OLB:12, MLB:6 | Packers moved Matthews inside to ILB for stretches in 2014-2015 — a real, reported in-season scheme change. |
| Deone Bucannon | 2015 | 3-4 ILB/MLB | LB:7, OLB:5, S:4, ILB:2 | Cardinals' original "moneybacker" — drafted safety, converted to a hybrid LB role; the S:4 games are a real signature of that documented conversion. |
| Dre'Mont Jones | 2025 | 3-4 OLB (edge) | OLB:9, DE:8 | Near-even in-season split — worth checking for a scheme change (Seahawks) mid-2025. |

These are genuinely worth the user's individual review — real,
football-explainable hybrid usage in most cases, exactly the kind of
"happy to look at individually" case the user described.

## 5. Recommended follow-on (not done here — flagged, not fixed)

- **`Taron Johnson`/`Mackensie Alexander`/`Deommodore Lenoir`-type cases**
  look like real data issues in the classifier's season-position source
  (`silver.player_team_seasons_pfr.position`) for players whose true
  position is unambiguous — worth a direct spot-check against PFR's own
  player pages before assuming the classifier's season label is right.
- **The systematic DE/DT and ILB-MLB/OLB overlap (§3)** suggests
  `starters.csv`'s slot-grid labels and `player_team_seasons_pfr`'s
  roster-position field encode position differently for 3-4 fronts
  specifically. Worth reconciling directly (which source is more accurate
  for scheme-role purposes) before either is trusted as ground truth for a
  future per-game position feature — out of scope for this pass, which was
  a review/flagging task, not a source-of-truth adjudication.
- Full CSV (`data_output/starter_position_anomalies.csv`) has a `category`
  column pre-applied, `all_pos_breakdown` per player-season, and is sorted
  by games-at-inconsistent-position descending so the user can keep working
  down the list past what's summarized here.
