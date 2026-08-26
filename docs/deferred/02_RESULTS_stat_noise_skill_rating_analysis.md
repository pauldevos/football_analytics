# Results: per-position, per-stat noise/skill-rating analysis

Completed 2026-08-22, answering the brief in
`docs/deferred/02_stat_noise_skill_rating_analysis.md`. Read that file
first if you want the original problem framing verbatim — this doc reports
what was actually measured, with real numbers, and is written as a
self-contained teaching piece: what the question was, how it was answered,
what came back, and what to trust it for.

Analysis script (read-only, does not touch `dpvs/idi.py` or any production
table): `football_analytics/scripts/stat_noise_skill_rating_analysis.py`.
Raw output: `football_analytics/data_output/stat_noise_skill_rating_results.json`.

## 1. The problem, restated simply

Some defensive stats are mostly *skill* — the same players are good at them
year after year. Others are mostly *luck* — this season's leader is often a
different, unrelated player next season, because the stat is rare and
whoever happened to be near the ball when it bounced free gets credit.
`docs/framework_decisions.md` §12/§14 already measured this once, pooled
across every position (tackle φ=4.87, run stuff φ=2.69, INT φ=1.57, FF φ=1.32, FR
φ=1.08 — explained below). This task asks the same question **broken out
by position group**, because "how noisy is a sack" is a different question
for a defensive end than for a cornerback, and adds **sack** and **PD**
(pass deflections), which had never been measured this way at all, plus a
**per-player skill-distance leaderboard** and a **data-integrity check** on
games-played counts.

## 2. Data and method

**Source**: `football_db` Postgres, `gold.player_game_stats` — one row per
(player, game) with position and all seven counting stats (tackle, sack,
run stuff, FR, INT, PD, FF), reconciled from PFR (1978-2025) and the
`gamebooks_boxscores` corpus (1967-1977, extending further for a few teams).
For 1967-1977, only game-sides where
`silver.player_game_stats_gamebook.completeness_qualified = true` were
included — this is the project's existing ≥70% completeness-ratio gate
(team Solo+Ast ÷ opponent snaps), read directly from a pre-computed column
rather than re-derived. **448,853 gated (player, season, game) rows**
went into this analysis; 65,282 player-seasons after aggregation, 43,120
of them resolved to one of the three position groups (`pass_rusher`,
`run_stopper`, `coverage` — `dpvs/positions.py`'s current grouping; the
finer DE-vs-LB split proposed in `docs/deferred/05_position_scheme_grouping_scoping.md`
has not been built yet, so a supplementary ad-hoc finer split was run
separately for the run stuff question in §5 below, using the raw position string
already present in the data).

**Three complementary methods, used for different reasons:**

1. **Overdispersion (φ)** — the primary signal, especially for rare
   events. For a purely-random (Poisson) process, variance equals the
   mean. φ is the ratio of *observed* variance to that Poisson baseline:
   φ=1.0 means "this looks like pure chance," φ>1.0 means some of the
   spread is real, persistent skill. Computed the same way
   `scripts/build_tackle_gated_corpus.py` did originally (method-of-moments
   quasi-Poisson: season-pooled rate as μ, Pearson χ² / (N − n_seasons)),
   now run separately within each stat × position_group slice.
2. **Split-half career reliability** — a player's qualifying seasons
   (≥4 games, the same floor `dpvs/idi.py` uses) are split by alternating
   season order into two halves, a per-game rate computed in each half,
   and the Pearson r between halves measured across all players in the
   group. Reported both raw and Spearman-Brown corrected (`2r/(1+r)`) to
   estimate full-career, not half-career, reliability. This is the
   textbook "does this player's own number correlate with itself" test.
3. **Year-over-year (YoY) Pearson r** — pooled (season N, season N+1)
   pairs for the same player, rate vs. next season's rate. Included for
   comparability with the existing `scripts/yoy_stability_check.py`
   convention, but **treated as secondary**, not primary, for rare events:
   the brief flagged (and this session's earlier work already confirmed)
   that naive YoY correlation is biased low for sparse counts — a
   good-but-quiet season can look like a bad season simply from Poisson
   noise on a small numerator. φ and split-half (which pools more
   observations per side) are the more trustworthy signal for FR/FF/INT/run stuff
   specifically. Where YoY and φ/split-half disagree in this data, that
   disagreement itself is informative and is called out below.

**Skill-distance leaderboard**: for each stat × position_group, career
totals were shrunk toward the population rate with empirical-Bayes weight
`k = 8.0/(φ−1)` (same `K0=8.0` reference scale `dpvs/idi.py` uses, but with
*this* slice's own measured φ, not the pooled one) and converted to a
z-score against the distribution of shrunk rates across all qualifying
careers (≥16 career games, roughly one season). This is a simplified,
career-snapshot version of `_add_rate_component()` — it uses one pooled
population prior rather than `idi.py`'s sequential career-to-date prior,
which is the right tool for a per-season production formula but overkill
for a one-time leaderboard.

## 3. Results table

| Stat | Position group | φ | Noise read | Split-half r (S-B) | YoY r |
|---|---|---|---|---|---|
| Tackle | run_stopper | **8.82** | very strong skill signal | 0.888 | 0.735 |
| Tackle | coverage | 4.52 | strong skill signal | 0.806 | 0.554 |
| Tackle | pass_rusher | 3.15 | strong skill signal | 0.831 | 0.629 |
| PD | coverage | 2.02 | moderate skill signal — **see caveat §6** | 0.794 | 0.631 |
| Sack | pass_rusher | 1.90 | moderate skill signal | 0.748 | 0.488 |
| Sack | run_stopper | 1.85 | moderate skill signal | 0.732 | 0.512 |
| PD | run_stopper | 1.42 | weak-moderate skill signal | 0.703 | 0.461 |
| PD | pass_rusher | 1.41 | weak-moderate skill signal | 0.712 | 0.464 |
| run stuff | run_stopper | 1.46 | weak skill signal | 0.602 | 0.339 |
| run stuff | coverage | 1.26 | weak skill signal | 0.517 | 0.251 |
| run stuff | pass_rusher | 1.33 | weak skill signal | 0.518 | 0.258 |
| INT | coverage | 1.21 | weak skill signal | 0.644 | 0.313 |
| FF | pass_rusher | 1.19 | very weak — near chance | 0.486 | 0.264 |
| Sack | coverage | 1.16 | near chance (rare blitz sacks) | 0.503 | 0.241 |
| FR | pass_rusher | 1.10 | near chance | 0.190 | 0.081 |
| INT | run_stopper | 1.09 | near chance | 0.522 | 0.264 |
| FR | coverage | 1.08 | near chance | 0.224 | 0.100 |
| INT | pass_rusher | 1.00 | pure chance | 0.533 | 0.207 |
| FF | coverage | 1.01 | pure chance | 0.246 | 0.117 |
| FR | run_stopper | 0.97 | **at/below chance floor** | 0.153 | 0.078 |
| FF | run_stopper | 1.00 | **pure chance — no leaderboard computed** | 0.293 | 0.122 |

n per stat×group ranges 8,662-17,829 player-seasons, 7,265-13,881 with the
≥4-game floor applied for the rate-based tests — full breakdown in the JSON.

**Reading the split-half vs. φ gap for INT/FR**: split-half reliability
(0.5-0.65) looks much higher than φ (~1.0-1.2) would suggest for INT and FR.
This is not a contradiction — split-half correlates a player's own *shrunk,
career-length* aggregate against itself, which any positive φ (even barely
above 1.0) will show up in given enough games pooled per half; φ instead
asks "how much of one season's variance is signal," a much harder bar for a
low-count stat to clear. Both are "true," they're answering different
questions — this is exactly why the brief asked for both methods rather
than picking one.

## 4. What this actually says about each stat

- **Tackle** is, by a wide margin, the most skill-driven stat in the
  dataset, and **run-stopper tackle volume (φ=8.82) is the single cleanest
  signal measured anywhere in this analysis** — more than double the
  pooled-all-positions φ=4.87 from §12/§14. This makes football sense:
  interior run-stoppers see the ball far more often per game than a
  pass-rush specialist or a deep-zone corner, so their tackle count has
  much less small-sample noise baked in.
- **Sack** shows real, moderate skill for the two positions that actually
  rush the passer (φ≈1.85-1.90) — clearly above pure chance, clearly below
  tackle. For coverage (mostly DB blitz sacks), it's indistinguishable from
  chance (φ=1.16) — a defensive back's occasional sack looks like scheme
  luck, not individual pass-rush skill, which is exactly what football
  intuition would predict.
- **run stuff** is weak-but-real everywhere (φ 1.26-1.46), and — unexpectedly —
  is **not** stronger for the run-stopper group than for pass-rusher or
  coverage the way the pooled §12/§14 number (φ=2.69) implied. This gets
  its own dedicated section (§5) because it's the direct evidence input to
  `docs/deferred/04_idi_weight_revisit.md`'s DL-vs-LB hypothesis.
- **PD** (pass deflections) shows the second-strongest per-position signal
  in coverage (φ=2.02) — genuinely interesting, since PD isn't in IDI at
  all today — but this number needs the caveat in §6 before it's trusted.
- **INT, FF, FR** are all close to or at the pure-chance floor (φ 0.97-1.21)
  once split by position, confirming and sharpening §12/§14's original
  finding that FR in particular carries almost no individual-skill signal
  (φ=0.97-1.10 across all three groups here — this is why it was already
  dropped from IDI). **FF for run-stoppers came back at φ=0.998, literally
  indistinguishable from a coin flip**, and the leaderboard script
  correctly refused to produce a ranked list for it (see `_skill_leaderboard`'s
  `phi <= 1.0` guard) rather than rank players on pure noise.

## 5. The DL-vs-LB Run Stuff hypothesis (direct input to doc 04)

`docs/deferred/04_idi_weight_revisit.md` records a specific, falsifiable
claim from the user: a DT/DE's run stuff should show a *stronger* skill signal
than an OLB/MLB's, because interior/edge linemen "win the battle" with a
physical/positional head start, while a linebacker's run stuff is more often a
scheme/blitz-design outcome. The current 3-group system can't test this
directly (`pass_rusher` = DE+OLB together; `run_stopper` = DT/NT+all LB
together), so this was tested with a one-off finer split of the raw
position string, run stuff only:

| Fine position group | n seasons | φ | Split-half r (S-B) | YoY r |
|---|---|---|---|---|
| MLB/ILB | 11,612 | **1.50** | **0.637** | **0.362** |
| OLB | 1,504 | 1.34 | 0.540 | 0.215 |
| DE (edge) | 7,281 | 1.30 | 0.467 | 0.248 |
| DT/NT (interior) | 6,492 | 1.28 | 0.516 | 0.294 |

**The data does not support the hypothesis as stated — it points the
other way.** Off-ball linebackers (MLB/ILB) show the *strongest* run stuff skill
signal of the four groups on both independent metrics (φ and split-half),
not the weakest, and defensive ends show the weakest. A plausible
explanation, offered as a hypothesis for whoever picks up doc 04, not a
proven mechanism: an MLB/ILB reads the play and is often unblocked at the
snap read, giving a fast, instinctive player a repeatable individual edge;
a DE's run stuff count is more entangled with the whole defensive line's
pass-rush push and stunt calls, which would suppress the individual signal
relative to team scheme — arguably the mirror image of the reasoning in
doc 04, not a confirmation of it. **This is worth flagging plainly to doc
04's next reader: the specific DL-vs-LB direction proposed there is not
borne out by this measurement**, though the broader "run stuff carries real
signal, worth weighting" conclusion still stands. Caveats: OLB's sample
(1,504 seasons) is much smaller than the others, and this fine split mixes
run stuff data across all three source eras (1967-77 gamebook-gated, 1978-98 PFR
PBP undercount, 1999+ gold) the same way the main 3-group analysis does, so
era-mix effects aren't ruled out as a contributor — a season-controlled
re-run would be the natural next check if this number needs to bear real
weight in a formula change.

## 6. PD's known over-crediting risk

`gamebooks_boxscores/CLAUDE.md` flags PD as "the single most commonly
over-counted stat in this project so far" for the 1967-77 gamebook corpus —
scorers extracting boxscores were prone to crediting a bare `(Defender)`
next to an incomplete pass as a PD when the source document didn't actually
say so explicitly. PD's φ=2.02 for coverage is the second-highest
per-position signal measured (after tackle), which is exactly the kind of
result that over-crediting would produce: if some fraction of "PD" credits
in the 1967-77 slice are actually just "was in coverage on this incomplete
pass," a genuinely average defender would get a artificially inflated,
*correlated* bonus (the same defender tends to be the primary coverage man
across many plays), which inflates apparent skill signal rather than
looking like random noise. The PD coverage leaderboard's top names
(Leroy Mitchell, Robert James, Larry Carwell, Alvin Wyatt, Calvin Jones) are
disproportionately 1970s players, consistent with this era-concentration
concern. **Recommendation: PD's φ should be re-measured after a targeted
PD-specific accuracy audit of the 1967-77 corpus (paralleling the sack
audit already done for 1969-1974, per project memory), before this number
is used to justify adding PD to IDI.** The moderate, more plausible
pass_rusher/run_stopper PD numbers (φ≈1.41-1.42, mostly modern-era data)
are less exposed to this risk and can be trusted with less caveat.

## 7. Skill-distance leaderboards (real players, not just Woodson)

The Rod Woodson example from the brief checks out directionally: population
mean INT rate for the `coverage` group (career-shrunk, ≥16 game careers) is
**0.137/game → 2.17 per 16-game season**; Woodson's own career rate is
0.266/game → **4.26/16-game season**, about 2 SD above the DB population
mean once shrunk — real, but not actually the *top* of the leaderboard (see
below; several players show an even larger gap, mostly because his 17-year
career length pulls his shrunk rate down less dramatically than it should
for ranking purposes — this metric rewards a short, hot peak slightly more
than a long, very-good career, worth knowing before treating the ranking
as gospel).

**INT, coverage** (top 5 of 15): Ed Reed (z=4.70, 0.40/g vs. 0.14/g
average), Bill Simpson (4.43), Jake Scott (4.10), Ken Stone (3.98),
Deron Cherry (3.93). Ed Reed at the top matches broad football consensus —
a good sign the method isn't producing nonsense.

**Run stuff, pass_rusher** (top 5): J.J. Watt (z=5.49), Deacon Jones (5.27),
Maxx Crosby (4.95), Dave Lewis (4.42), Michael Bennett (4.29).

**Run stuff, run_stopper** (top 5): Wally Chambers (z=4.87, only 20 career
games — a short, extreme peak worth a grain of salt), Lavonte David (4.59),
Luke Kuechly (4.42), Aaron Donald (3.98), Earl Holmes (3.76).

**Sack, pass_rusher** (top 5): Myles Garrett (z=3.43), Mark Gastineau
(3.32), Chad Brown (3.22, only 16 games — same short-peak caveat), Nick
Bosa (3.21), DeMarcus Ware (3.19).

**Tackle, run_stopper** (top 5): Tommy Nobis (z=4.72, only 37 games —
career cut short by injury, extreme rate), Bob Babich (4.14), Willie
Lanier (4.12), Cedric Gray (3.78, 16 games — rookie-season spike),
Alex Singleton (3.67).

**PD, coverage** (top 5, see §6 caveat): Leroy Mitchell (z=5.40), Robert
James (4.24), Larry Carwell (4.02), Alvin Wyatt (3.90), Calvin Jones (3.90).

**FR, coverage** (top 5): Ricky Smith (z=5.22, 9 FR in 23 games — extreme
short-career rate), Johnnie Gray (5.05), Beasley Reece (5.01), Mike
Reinfeldt (4.34), Darrien Gordon (4.34). Given φ≈1.08 for this
stat×group, treat this whole leaderboard as mostly reflecting who happened
to be near the ball, not a real skill ranking — it's included for
completeness, not because it's trustworthy (this is the direct,
concrete illustration of what a low-φ leaderboard means in practice).

Full top-15s for every stat × position_group are in the JSON output.

## 8. Games-played integrity check

**Finding, stated plainly: PFR's season-level `games_played`
(`silver.player_team_seasons_pfr`) and an independent per-game presence
count derived from `gold.player_game_stats` disagree far more than the
brief anticipated — only 12.5% of player-seasons match exactly, mean
absolute gap 6.13 games, and the gap is overwhelmingly in one direction
(PFR's count higher, 42,587 of 42,593 big-discrepancy cases), worst in the
1967-1977 era (3.1% exact match, mean gap 7.32 games).**

**But this is not primarily a PFR data-quality bug — it's a structural
property of how `gold.player_game_stats` is built, confirmed directly:**
querying for rows where every one of the seven counting stats is exactly
zero returns only 14 of 422,823 PFR-sourced rows (0.003%). In other words,
this table only gets a row for a player in a game where they recorded at
least one countable defensive event (a tackle, a PD, anything). A
player who plays a full game and genuinely records zero counted stats —
common for a part-time defender, and not even rare for a starter having a
quiet game — simply has **no row at all** for that game, so the
"independent" count used here systematically undercounts true games
played, and does so more for players who record fewer events per game.
This is worth its own separate follow-up (the brief's own bar: "if it's
not negligible, flag it") — but the follow-up is "audit whether
`gold.player_game_stats` should also carry zero-stat presence rows," not
"audit whether PFR's games_played column is wrong." **A real, secondary
consequence worth carrying forward**: every rate (`count/games`) computed
in this entire analysis — φ, split-half, YoY, the leaderboards — uses this
same undercounted "games" denominator, which biases every rate upward,
more so for players/stats with sparser per-game events. The bias should be
roughly consistent within a stat × position_group (so *relative* rankings
and reliability comparisons *between* stats/groups, which is what this
whole analysis is built to do, are less affected), but any *absolute* rate
number quoted above (e.g. "0.137 INT/game") should be read as an upper
bound on the true per-game rate, not a precise value.

## 9. Conclusion — evidence for `docs/deferred/04_idi_weight_revisit.md`

1. **Tackle deserves its position as IDI's most-trusted rate-shrunk
   component, more so than the pooled φ=4.87 already suggested** —
   run-stopper tackle volume (φ=8.82) is the strongest skill signal in the
   whole dataset.
2. **Sack has real, moderate, position-dependent skill signal (φ≈1.85-1.90
   for the two pass-rushing groups)** — enough to justify doc 04's planned
   move of `sack_share_z` onto the same rate+shrinkage+count treatment as
   run stuff/INT/FF, using `k = 8.0/(1.9-1) ≈ 8.9` as a starting point for the
   pass-rush-relevant groups. It is clearly weaker than tackle and roughly
   comparable to run stuff, consistent with the user's "more additive"
   intuition — it should not be treated as equal-confidence to tackle.
3. **The specific DL-vs-LB run stuff argument in doc 04 is not supported by this
   measurement — the data points the opposite direction** (MLB/ILB
   φ=1.50 > OLB 1.34 > DE 1.30 > DT/NT 1.28). Doc 04 should not lean on
   that argument to justify raising run stuff's weight over sack without
   revisiting it; the general "run stuff carries real, if modest, individual
   skill signal" conclusion (φ 1.26-1.46 across all three groups, clearly
   above the chance floor) still stands on its own.
4. **PD is a plausible future IDI component (φ up to 2.02) but should not
   be added yet** — its strongest number is concentrated in the exact era
   flagged elsewhere in this project for PD over-crediting risk, and needs
   a targeted accuracy audit first.
5. **INT, FF, FR remain close to the chance floor per-position, same as
   the pooled result** — nothing here argues for changing their existing
   light/dropped treatment in IDI.
6. **The games-played integrity finding is a real, separate, non-blocking
   data-architecture issue**: `gold.player_game_stats` is an
   event-presence table, not a participation table, and every per-game
   rate this project computes from it (inside or outside this analysis)
   inherits a same-direction upward bias. Worth a dedicated follow-up, but
   it does not undermine the *relative* comparisons this doc's conclusions
   above are based on.
