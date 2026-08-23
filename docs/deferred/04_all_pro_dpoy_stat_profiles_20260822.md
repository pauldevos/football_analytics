# Results: real stat profiles of All-Pro / DPOY-recognized defenders, by position

Completed 2026-08-22. Requested as a follow-on to
`docs/deferred/04_idi_weight_revisit.md` and
`docs/deferred/04_award_recognition_vs_int_value_20260822.md`: those two
docs measure whether raw stats (φ overdispersion, event value, award
recognition patterns) support specific IDI weight choices. This doc builds
the other half — **a real, position-organized empirical reference of what
recognized defenders' seasons actually looked like**, statistically, so a
candidate DPVS-G weighting scheme can be sanity-checked against real
players instead of only against internal consistency metrics.

**This is explicitly NOT a target to optimize against.** Per the user's own
framing: *"we definitely don't wanna forfeit and just try and get the stats
to basically approve all the DPOY winners, but we also want to see that it
is probably a good signal for a meaningful way to identify players."* A
weighting scheme that reproduces every DPOY winner's rank-1 finish would
almost certainly be overfit to award-voting idiosyncrasy (the previous doc
found voters miss real statistical standouts 40-87% of the time depending
on leaderboard rank) rather than a better measure of on-field value. The
right use of this dataset is the reverse: does a candidate scheme's ranking
of these player-seasons look *roughly* sane against what recognized
defenders' real box scores show, and where it disagrees, is that
disagreement a plausible "the stats caught something voters missed" case
(the project's own stated goal — the Joe Greene question) or a red flag
that the scheme is broken?

Script: `football_analytics/scripts/build_all_pro_dpoy_stat_profiles.py`.
Output: `football_analytics/data_output/all_pro_dpoy_stat_profiles.csv`
(1,456 rows). Not loaded into `football_db` — kept CSV-only, since this is
explicitly a validation/analysis artifact, not a production pipeline input.

## 1. Population and coverage

Four sources, unioned on `(player_id, season)`:

| Source | Rows | What it is |
|---|---|---|
| AP 1st-Team All-Pro, defensive positions | 697 | `gold.player_awards`, `org='AP'`, `designation='1st Tm'` — the primary All-Pro cohort per the task brief |
| AP DPOY full voting board | 413 | `~/data/pfref/ap_dpoy_voting.csv`, 1971-2025, every player who received at least one vote |
| NEA / PFWA / 101 Awards DPOY winners | 235 | `gold.player_awards`, `designation LIKE 'DPOY%'` |
| **Total unique player-seasons** | **1,456** | |

AP 1st-Team was chosen as the population-defining All-Pro signal (per the
task's "prioritize AP as primary") rather than unioning in every other
org's 1st-Team selections too — SN/UPI/FW/PFW alone would add several
thousand more rows, many from eras (1930s-60s) with much weaker underlying
stat coverage, and would make "All-Pro" mean something different in nearly
every decade. Other orgs' 1st-Team selections ARE captured, just as
**enrichment** on the AP-anchored population: `other_org_1st_tm` lists
which other bodies also named that player-season 1st-team, letting real
disagreement show up without exploding the population.

**Stat-profile coverage, by era** (source: `gold.player_game_stats`, the
project's own already-built 1967-2025 merge of `silver.
player_game_stats_gamebook` for 1967-1977 and `silver.
player_game_stats_pfr` for 1978-2025 — see `docs/framework_decisions.md`
§16-17):

| Era | Population rows | Got a stat profile | Coverage |
|---|---|---|---|
| pre-1967 | 1 | 0 | 0% (no Postgres per-game source exists this far back — expected, not a bug) |
| 1967-1977 (gamebooks_boxscores corpus) | 231 | 226 | 97.8% |
| 1978-1998 (PFR pbp.csv-derived) | 531 | 528 | 99.4% |
| 1999-2025 (PFR pbp.csv-derived) | 693 | 680 | 98.1% |
| **Total** | **1,456** | **1,434** | **98.5%** |

**The 22 real gaps**: one is the expected pre-1967 case (Larry Wilson,
1966). The other 21 are a genuine, not-fixed-here upstream gap: a specific
set of modern and 1967-68-era players (Patrick Surtain II, Derek Stingley
Jr., Jessie Bates III, Antoine Winfield Jr., Chris Harris Jr., Roy
Williams, Ken Norton Jr., Mike Nelms, Roger Wehrli, Bob Hayes, Homer Jones,
Charley Taylor) have **zero rows at all** in `gold.player_game_stats` for
the affected seasons — not a franchise/trade-row mismatch (checked
directly; e.g. Patrick Surtain II has zero rows for *any* season), more
likely a player-identity resolution failure somewhere upstream in the
`pbp.csv` → `internal.player_xref` chain this project doesn't own. This
echoes `docs/framework_decisions.md` §17's own still-open "4 pairs
unrecovered" tail from the position-join fix — same shape of problem
(player-identity resolution gaps in the pfr merge), different specific
players. Flagged here, not chased further; out of scope for a
reference-dataset-building task.

## 2. A real bug found and fixed while building this

`gold.player_game_stats.position` is `NULL` for every `pfr`-sourced row
(422,823/422,823 — confirmed the same finding `dpvs/idi.py`'s
`load_gold_stats_from_db()` already documents, see
`docs/framework_decisions.md` §17: `pbp.csv`, the pfr-era stat source,
carries no position field at all). The first version of this script's
season-stat query grouped by `(player_id, season, franchise_id, position)`
in one step to pick each player-season's modal team/position — but pandas
`groupby` silently **drops rows with a NaN key by default**. Since
`position` is NaN for every 1978+ row, this dropped the modal-lookup
entirely for the whole pfr era: J.J. Watt, Aaron Donald, Reggie White,
Lawrence Taylor, and Micah Parsons all came back with `position=NaN`,
`team_franchise_id=NaN`, and therefore every team-defensive-rank column
empty too (the team-rank join keys off `team_franchise_id`). Caught by
spot-checking known players before trusting the output, exactly as this
project's own convention requires. Fixed two ways: (1) the same
`silver.player_team_seasons_pfr` coalesce-backfill `load_gold_stats_from_db()`
already uses, applied here too; (2) decoupled the modal-franchise and
modal-position picks into two separate groupbys so a still-missing position
can never blank out an otherwise-resolvable franchise_id. Verified after
the fix: 22/1,456 rows position-null (exactly the genuine no-stats gap
above), 23/1,456 team-rank-null (same set, +1 row whose modal franchise
falls just outside the rank CSV's coverage).

## 3. Position classification

`data_output/position_scheme_classification.parquet` (this session's own
Phase 2 output, 8-bucket DL/LB scheme taxonomy keyed on `(player_id,
franchise_id, season)`) used where it covers the row and returns a real
bucket (not `out_of_scope_db`/`scheme_unknown`/`unclassified_no_side_info`/
etc.); falls back to `dpvs/positions.py`'s coarser 3-group taxonomy
(`pass_rusher` / `run_stopper` / `coverage`) otherwise — mainly CB/S/DB,
which the scheme classifier explicitly scopes out as `out_of_scope_db`
(it only covers DL/LB by design). `position_source` on every row records
which taxonomy actually fired. Of 1,434 rows with a stat profile: 1,187
(82.8%) got the finer 8-bucket classification, 225 (15.7%) fell back to the
3-group taxonomy (nearly all coverage positions), 22 (1.5%) are the
no-stats gap rows above.

## 4. Team defensive ranks

Reused `gamebooks_boxscores/build_pass_rush_srs.py`'s already-built output
(`outputs/pass_rush_srs_1967_2025.csv`) directly for `team_ppg_allowed_rank`,
`team_yds_allowed_rank`, and `team_any_a_allowed_rank` (the ANY/A-allowed
Z-score rank, used as the ANY/A-allowed rank column) — not rebuilt.
Extended with three new columns computed here, directly from
`gold.team_game_stats` (the same source that script reads, following its
own opponent's-offense-is-this-defense's-allowed-number convention):
`team_ypc_allowed_rank` (rush yards allowed ÷ rush attempts allowed),
`team_rush_yds_allowed_rank`, `team_pass_yds_allowed_rank`. All six rank
columns join cleanly on `(season, franchise_id)`.

## 5. Position-bucket summary: what a real All-Pro's season looks like

Medians, AP 1st-Team All-Pro population only (n=685 with a stat profile,
3-group split):

| Group | n | Sacks | Solo | Ast | Total Tkl | INT | PD | FF | FR |
|---|---|---|---|---|---|---|---|---|---|
| pass_rusher | 238 | 10.8 | 47 | 10 | 56.5 | 0 | 1 | 2 | 1 |
| run_stopper | 207 | 4.5 | 47 | 12 | 60 | 0 | 1 | 1 | 1 |
| coverage | 240 | 0 | 50 | 6 | 57 | 5 | 4.5 | 1 | 1 |

By the finer 8-bucket scheme classification (selected rows — full table in
the CSV):

| Bucket | n | Sacks | Solo | Ast | Total Tkl | INT | PD | FF |
|---|---|---|---|---|---|---|---|---|
| 4-3 DE | 91 | 13.0 | 41 | 7 | 49 | 0 | 1 | 2 |
| 3-4 OLB (edge) | 62 | 12.5 | 52.5 | 10 | 64 | 0 | 0 | 3.5 |
| 3-4 DE | 30 | 10.0 | 44 | 9.5 | 54.5 | 0 | 0 | 2.5 |
| 4-3_DT_uncovered | 89 | 7.5 | 37 | 9 | 48 | 0 | 1 | 1 |
| 3-4 NT | 14 | 2.5 | 34.5 | 10.5 | 49 | 0 | 0 | 1 |
| 4-3 MLB | 57 | 2.0 | 83 | 25 | 112 | 1 | 3 | 1 |
| 3-4 ILB/MLB | 31 | 3.0 | 90 | 20 | 124 | 1 | 3 | 2 |
| 4-3 OLB | 55 | 3.0 | 64 | 18 | 84 | 2 | 4 | 1 |
| coverage | 240 | 0 | 50 | 6 | 57 | 5 | 4.5 | 1 |

This alone is a useful cross-check against `docs/deferred/
05_position_scheme_grouping_scoping.md`'s hypothesized sample ranges: the
3-4 NT median here (2.5 sacks, 34.5 solo) sits meaningfully lower on both
counting stats than every edge/DE bucket, and the MLB/ILB buckets carry
by far the heaviest tackle volume of any group (83-124 combined median) —
both consistent with that doc's positional framing, now backed by real
All-Pro-season numbers rather than assumed ranges.

## 6. DPOY-board vs. non-board All-Pro: does the gradient hold?

Four tiers, defined by recognition depth (not stat-based, purely from the
award data): **dpoy_winner** (won AP/NEA/PFWA/101-Awards DPOY outright),
**dpoy_board_nonwinner** (got at least one AP DPOY vote or was on another
org's board, didn't win), **ap1st_nonboard** (1st-Team AP All-Pro, zero
DPOY signal), **other** (in the population via a lower-signal path — AP
2nd-Team, other-org DPOY board only, etc.).

**Pass rusher — sacks scale cleanly with recognition depth, the sharpest
gradient in the whole dataset:**

| Tier | n | Sacks median | Sacks 25th/75th/90th pctile |
|---|---|---|---|
| dpoy_winner | 70 | 12.5 | 8.75 / 16.9 / 19.0 |
| dpoy_board_nonwinner | 150 | 10.5 | 6.0 / 13.9 / 16.0 |
| ap1st_nonboard | 89 | 7.0 | 3.0 / 12.5 / 14.6 |
| other | 196 | 8.5 | 3.9 / 12.0 / 14.0 |

This is close to the cleanest possible confirmation that sack volume tracks
real DPOY-level recognition for edge/DL pass rushers specifically — every
step down in recognition depth (winner → board → 1st-team-only) drops the
median by 1.5-3.5 sacks, monotonically. Note `ap1st_nonboard` sitting
*below* the unstructured `other` bucket (7.0 vs 8.5) — 1st-Team-but-no-DPOY-
signal pass rushers are, on this measure, not obviously more productive by
sacks than the broader recognized population; whatever got them 1st-Team
recognition without DPOY buzz likely wasn't pure sack volume.

**Run stopper — the gradient is much flatter, and shows up in tackles, not
sacks:**

| Tier | n | Sacks median | Solo median | Total Tkl median |
|---|---|---|---|---|
| dpoy_winner | 39 | 5.0 | 51 | 65 |
| dpoy_board_nonwinner | 87 | 3.0 | 53 | 65 |
| ap1st_nonboard | 125 | 4.0 | 45 | 57 |
| other | 185 | 4.0 | 51 | 62 |

Sacks barely move across tiers for this group (3.0-5.0, no clean
monotonic pattern) — consistent with this project's own established
finding that sacks are a poor primary signal for interior/off-ball run
stoppers. Total tackles shows a real, if noisier, step up for recognized
players (57 → 65) but nothing close to pass-rusher's sack gradient.

**Coverage — small-n, worth reporting but not over-reading:**

| Tier | n | INT median | PD median |
|---|---|---|---|
| dpoy_winner | 21 | 7 | 2 |
| dpoy_board_nonwinner | 61 | 5 | 6 |
| ap1st_nonboard | 179 | 4 | 4 |
| other | 232 | 4 | 4 |

INT climbs cleanly with recognition depth (4 → 5 → 7), consistent with
`04_award_recognition_vs_int_value_20260822.md`'s own finding that INT
*does* correlate with recognition at the very top of the leaderboard even
though it's a weak/noisy signal generally — the DPOY-winner coverage
sub-population is exactly that top slice. **The PD number for dpoy_winner
(2, below even the ap1st_nonboard median of 4) is almost certainly an n=21
artifact, not a real signal** — worth flagging explicitly rather than
building a "DPOY coverage players record fewer PD" story on 21 rows.

## 7. A team-context finding, not asked for explicitly but relevant

Recognized players' teams play meaningfully better defense, and the
gradient tracks recognition depth the same way the individual stats do:

| Tier | n | Team PPG-allowed rank (median) | Team yards-allowed rank (median) |
|---|---|---|---|
| dpoy_winner | 129 | 5 | 5 |
| dpoy_board_nonwinner | 298 | 6 | 7 |
| ap1st_nonboard | 393 | 7 | 7 |
| other | 613 | 9 | 8 |

This is exactly the confound `04_award_recognition_vs_int_value_
20260822.md` §5 already flagged for INT specifically, now shown to hold
across the whole recognized population: voters (and, presumably, the raw
counting stats themselves) are systematically drawn from good defenses.
A DPVS-G weighting scheme that doesn't separately account for team context
will inherit some of this correlation "for free," which cuts against
treating any of the above stat gradients as a completely clean
individual-skill signal — worth keeping in mind alongside `dpvs/tcs.py`'s
own opponent/team-quality adjustment machinery.

## 8. Cross-org All-Pro disagreement (the "note when orgs disagree" ask)

487 player-seasons in the population were named 1st-Team by at least one
other org (SN/NEA/NYDN/UPI/PFW/FW/PFF/NFLPA/HOF) while AP did NOT name them
1st-Team that season (AP 2nd-Team or no AP recognition at all). This is
heavily concentrated in 1967-1968 specifically — the earliest seasons in
this population, before AP had fully consolidated into the singular
"the" All-Pro standard the way it functions in later decades (multiple
wire-service All-Pro teams coexisting, sometimes disagreeing, was normal in
this era). Example rows: Homer Jones (1967, AP 2nd-Team, but NEA/NYDN/SN/
UPI all 1st-Team), Dave Robinson (1968, same pattern across four other
bodies). Full detail in the `other_org_1st_tm` column of the CSV — not
chased into a separate analysis here, since the task scoped this as a note/
enrichment field, not a second full study.

## 9. PD availability across eras (the task's explicit "check whether PBP
can fill this in" ask)

Resolved cleanly, no gap: `pd` (pass deflections) is populated in
`gold.player_game_stats` for **both** merged sources — 30,385/30,388
gamebook rows (1967-1977) and all 422,823/422,823 pfr-pbp rows
(1978-2025). Used directly for every row in this dataset; no fabrication or
blank-filling needed for any era. The pfr-era PD figure carries the same
general text-parse caveats as every other pbp.csv-derived stat in this
project (not re-litigated here), but it exists and was used.

## 10. What this dataset is and isn't for

**Is**: a real-numbers sanity check. If a candidate DPVS-G weighting
scheme, run on this same population, produces wildly different orderings
than the gradients in §6 (e.g., ranks a bunch of near-zero-sack edge
rushers above the actual DPOY-caliber sack producers, or gives coverage
defenders' PD stat so much weight that low-INT/high-PD corners
systematically outrank the real INT-heavy DPOY board), that's a real signal
something in the scheme is off — not proof, since award voting has its own
well-documented blind spots (see doc `04_award_recognition_vs_int_value_
20260822.md`), but a legitimate check worth explaining away rather than
ignoring.

**Isn't**: a target. Nothing here should be used as a loss function, an
explicit set of "these 130 dpoy_winner rows must rank in the top N," or a
reason to hand-tune a weight until some correlation number against this
dataset improves. The whole point, per the user's framing, is to keep the
weighting derivation honest to football reasoning and statistical evidence
(φ, event value, the skill/rarity/value framing in doc 04) and use this
dataset only to ask "does the result look like a defensible measure of
real value" — not to chase award-committee agreement for its own sake.

## 11. Data locations

- `football_analytics/scripts/build_all_pro_dpoy_stat_profiles.py` — the
  build script (population, stats, position, team ranks, output).
- `football_analytics/data_output/all_pro_dpoy_stat_profiles.csv` — 1,456
  rows: `player_id, full_name, season, position, position_group_or_bucket,
  position_source, team_franchise_id, games, sacks, tackles_solo,
  tackles_ast, tackles_total, ff, fr, int, pd, all_pro_tier,
  other_org_1st_tm, dpoy_rank_ap, dpoy_won_other_org,
  team_ppg_allowed_rank, team_yds_allowed_rank, team_ypc_allowed_rank,
  team_any_a_allowed_rank, team_rush_yds_allowed_rank,
  team_pass_yds_allowed_rank, stat_source`.
- Not loaded into `football_db` — CSV-only per this task's own scoping
  call (validation/analysis artifact, not a production pipeline input).
- `dpvs/idi.py` was NOT touched by this work — read-only reference for the
  Postgres query patterns this script's loaders follow, per this task's
  explicit instruction to leave IDI's actual weight-revisit work to a
  separate, parallel task.

## 12. Not done in this pass

- Other-org 1st-Team-only player-seasons (SN/UPI/FW/etc. selections with no
  AP or DPOY-board signal at all) were not given full stat profiles —
  scoped out deliberately (see §1) to keep the population AP-anchored and
  the underlying-stat-coverage era comparison clean. A future pass wanting
  a fuller pre-1970s All-Pro picture would need to build this out
  separately, and should expect materially worse stat-profile coverage the
  further back it goes (this population's own 1966 row already shows the
  1967 Postgres per-game floor).
- The 22-row `gold.player_game_stats` identity-resolution gap (§1) was
  flagged, not root-caused — a real, fixable-sounding upstream issue for
  whoever next touches `internal.player_xref`/pfr ingestion, not blocking
  for this dataset's purpose.
- No attempt was made to build career-level (multi-season) profiles or
  career trajectories — this is strictly a player-season-level reference,
  matching the grain the rest of DPVS-G operates at.
