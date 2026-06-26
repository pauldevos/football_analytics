# DPVS Framework — Analytical Decisions Log

A running record of analytical decisions made during framework development:
what we tried, what we found, and why we settled on the approaches we did.
Each entry captures the finding, the evidence, and the conclusion.

---

## 1. Team Credit Split: Equal vs Stat-Events-Weighted

**Decision:** Split team game credit (TDGS) equally among all qualifying defensive
participants.

**Finding:** Correlation between per-game participant stat events and per-game TDGS = **r = 0.054** (2000 NFL season, 259 games, all teams). Effectively zero.

**Why this matters:** The question was whether a defender who recorded more tackles/sacks
in a game should receive proportionally more of the team's defensive credit for that
game. The intuition: "more active = more responsible for the result." The data says no.

**Explanation:** Stat events are largely a function of *volume of plays the team faced*
and *how the game unfolded*, not the quality of defense. A team giving up 500 yards
tends to generate more tackle events (opponent keeps sustaining drives) than a team
allowing 150 yards (fewer plays, fewer tacklers needed). Weighting by stat events
would therefore *penalize* the better defense.

**Conclusion:** Equal split. Keep team credit strictly independent of individual
counting stats. TDGS / n_participants is the correct formula.

**Code reference:** `scripts/build_game_defense.py` → `team_credit_share`

---

## 2. Team Credit vs Individual Counting Stats: Kept Separate

**Decision:** TDGS team credit and individual play-level EPA (from gamebook or PFR
play-by-play) are computed independently and combined at the DPVS composite stage.
They are never merged or double-counted at the game level.

**Rationale:** A sack or a tackle already carries its own EPA value (from the EP model).
That EPA belongs to the individual play. The team credit is a separate accounting of
"this team held a tough offense in check" — value that accrues to all defenders on
the field whether or not they personally were credited with a play. 

The cleanest analogy: team credit = floor credit for being on the field for a
great defensive performance. Individual EPA = credit for specific plays.

**Example that motivated this:** Alan Page in a game where the Vikings held Cleveland
to 151 yards and 3 points. Page had 2 tackles credited in the gamebook. But the
defense as a whole outplayed a strong offense by ~165 yards. Page deserves credit
for that team performance even on plays where he didn't get a stat. The team credit
captures exactly this contribution.

---

## 3. TDGS Formula — Dual Benchmark (League Average + Opponent Expectation)

**Decision:** The game-level team defense score uses a 50/50 blend of two benchmarks:
1. vs. league average offense (absolute quality)
2. vs. opponent's season offensive average (opponent-adjusted quality)

```
yds_credit = 0.5*(league_avg_yds − yds_allowed) + 0.5*(opp_avg_yds − yds_allowed)
pts_credit = 0.5*(league_avg_pts − pts_allowed) + 0.5*(opp_avg_pts − pts_allowed)
TDGS = 0.55*yds_credit/season_std_yds + 0.45*pts_credit/season_std_pts
```

**Why both benchmarks:** Using only vs. league average ignores that holding a 420-yd
offense to 300 yards is more impressive than holding a 260-yd offense to 300 yards.
Using only vs. opponent expectation would miss the absolute quality dimension — some
defenses are great week after week regardless of opponent.

The 50/50 blend rewards both.

**Weights 0.55/0.45 (yards/pts):** Yards is a better leading indicator of defensive
process; points includes variance from turnovers, special teams, and scoring position
that isn't purely the defense's doing. Yards gets slightly more weight.

**Normalization by season std (z-score):** Makes scores comparable across eras. A defense
that is 90 yards/game below average is more dominant in a tight-std era (1969, std=33)
than in a high-variance era (2000, std=49).

---

## 4. Z-Score Era Adjustment — What It Means and Doesn't Mean

**Finding:** The 1969 Minnesota Vikings score higher (TDGS +2.70/game avg) than the
2000 Baltimore Ravens (+1.73/game avg) despite the Ravens being widely regarded as
the best modern defense.

**Why:** The 1969 league had very low variance (std_yds = 33) vs 2000 (std_yds = 49).
The Vikings were 2.8σ below average in yards; the Ravens were 1.6σ below.

**The philosophical question this raises:**
- **Z-score = era-relative dominance.** The Vikings were more unusual for their time.
- **Raw performance** would favor the Ravens (165 yds/game allowed vs. Vikings' 194).

| Measure | 1969 Vikings | 2000 Ravens |
|---------|-------------|-------------|
| Yds/game allowed | 194 | 165 |
| League avg yds/game | 299 | 319 |
| League std yds/game | 33 | 49 |
| Yds below average | −105 | −154 |
| Yds z-score | **−3.2σ** | **−3.2σ** |

Interestingly, both defenses are almost identical in yds z-score. The TDGS difference
mainly comes from the **points** component: the 1969 Vikings allowed 10.8 ppg in an
era where league avg was 20.9 ppg, std=3.4 → **−3.0σ below average** in scoring.
The 2000 Ravens allowed 9.4 ppg vs. avg 20.7, std=5.2 → **−2.2σ** below average.

The Vikings' points defense is more extreme relative to their era than the Ravens'.
This is a valid finding: the 1969 NFL had far less offensive variance, so maintaining
9-10 ppg allowed was even harder by the field distribution.

**Practical implication for DPVS:** The z-score approach is correct for comparing
players across eras on a common scale. If you want to say "which defense was literally
better in terms of yards allowed," use raw numbers. If you want to say "which defense
was more dominant relative to what their opponents could do against typical defenses
in that era," use z-scores. DPVS uses z-scores by design.

---

## 5. Participation Framework — Starters + Player_Defense Supplement

**Decision:** Defensive participant = named starter in `starters.csv` OR player with
≥4 stat events in `player_defense.csv` for that game.

**Stat events defined (pre-2001):** sacks (≥0.5 = 1 event) + INTs + FRs + FFs.
Tackles blank pre-2001; starters.csv is the primary source.

**Stat events defined (post-2001):** tackles_combined + sacks (≥0.5=1) + INTs + FRs + FFs.

**Why the threshold matters:** Non-starters with 4+ events are meaningfully "in the game"
defensively. The min_events=4 threshold captures players like Rob Burnett (Ravens 2000 LDE,
6 games, avg 6.0 events) who are excluded from PFR's starters.csv due to the systematic
10-starter issue described below.

---

## 6. The Missing LDE Bug — Scraper, Not PFR Data

**Finding:** `starters.csv` consistently lists **10 defensive starters** (not 11)
for 4-3 defenses. The LDE position is always missing.

- **1969 Vikings:** Carl Eller (LDE) missing in all 17 games. LDE appears 1×/232 expected.
- **1971 Vikings:** Same — Eller missing in all 15 games.
- **1983–86 Raiders:** Howie Long (LDE) missing from all games.
- **2000 Ravens:** Rob Burnett (LDE) missing from starters.csv.

**Initial (wrong) diagnosis:** PFR data limitation — thought PFR only provided 10 starters.

**Correct root cause (confirmed by user screenshots):** PFR has ALL 11 starters correct
back to the 1930s. The bug is in our scraper.

PFR's starters HTML table uses `class="divider"` on the **first defensive player's
row** (always LDE in a 4-3) to draw the thick visual border separating offense and
defense sections. `parse_standard_table` in `base.py` had:

```python
if "thead" in cls or "divider" in cls:
    continue  # ← unconditionally skipped Eller's entire row
```

**Fix applied (June 2026):** Changed to check for empty content before skipping:
```python
if "divider" in cls:
    if not any(td.get_text(strip=True) for td in tr.find_all(["th", "td"])):
        continue  # only skip truly empty divider rows
```

**Required follow-up:** All existing `starters.csv` files were scraped with the broken
parser and need to be re-scraped. Run `scrape_all_tables.py` with `--force` for
seasons 1950–2024.

**Impact until re-scraped:** LDE gets zero team credit from starters.csv source.
Post-2001: mitigated by player_defense.csv supplement (4+ stat events).
Pre-2001: only captured when Eller/Long has 4+ non-tackle events (sacks/INTs/FFs/FRs).

**Alternative scraper:** `scrape_game_starters.py`'s `parse_starters_table` uses
positional cell access and never had this bug — its output (in Postgres `game_starters`
table) includes Eller correctly.

---

## 7. Validation Results (Four Test Cases)

**Target:** Four historically elite defenses that should score in the top tier.

| Team | Season | TDGS avg/game | Yds/g | Pts/g | League avg yds | League avg pts |
|------|--------|---------------|-------|-------|---------------|---------------|
| MIN  | 1969   | **+2.702**    | 206.8 | 10.8  | 299.4         | 20.9          |
| MIN  | 1971   | **+1.854**    | 239.3 | 10.6  | 285.8         | 19.4          |
| ATL  | 1977   | **+1.422**    | 231.6 | 9.2   | 285.8         | 17.2          |
| RAV  | 2000   | **+1.733**    | 240.2 | 9.4   | 319.4         | 20.7          |

**Reference anchor:** Kansas City Chiefs 2000 = −0.040 (near-perfect zero = average defense).
Cleveland Browns 2000 = −0.855 (bad expansion team).

**Narrative consistency:**
- Vikings arc: 1969–1971 peak → gradual decline through 1970s → poor in 1978–1981 → resurgence 1988–1989. Matches historical record.
- Falcons: 1977 is their only elite year. All other seasons average or below.
- Ravens: Built from −1.8 in 1996 (expansion year) to +1.1 in 1999 to +1.7 in 2000.

---

## 8. Best Individual Games (Historical)

Top individual game TDGS scores observed in validation runs:

| Game | Defending team | Opp | Yds allowed | Pts | TDGS |
|------|---------------|-----|-------------|-----|------|
| 196911090min | MIN 1969 | CLE | 151 | 3 | **+5.249** |
| 196910120chi | MIN 1969 | CHI | 119 | 0 | **+5.000** |
| 197110030min | MIN 1971 | BUF | 64  | 0 | **+5.175** |
| 200012310rav | RAV 2000 | DEN | 177 | 3 | **+4.047** |

The 1971 game vs BUF (64 yards, shutout) is remarkable — the Vikings held a Bills
offense that averaged ~238 yards/game to 64 yards. Per-participant credit: ~+0.52
per starter.

---

## 8. WOWY Is Embedded in the Participation Credit — By Design

**Decision:** `total_credit` (the SUM of per-game credits across all games a player
participated in) is the correct season-level team defense stat for DPVS scoring.
Do not use `per_game_credit` (the arithmetic mean) for ranking.

**How WOWY appears naturally:**

Each game's credit = `TDGS_game / n_participants_game` — computed only for the
games the player actually appeared in. If a player misses a game, that game's
TDGS contributes zero to their total (not a penalty, not a bonus — it simply
doesn't count).

This means two teammates on the same team with different game counts will have
different `per_game_credit` averages, reflecting which specific games each
appeared in:

```
Player A (16 games, played in the bad NYG game): per_game_credit = +0.270
Player B (10 games, missed the NYG game):        per_game_credit = +0.293
```

That +0.023 gap IS the WOWY signal. Player B's average is higher because the
10 games they played were on average better defensive performances than the 16
games Player A played. No separate WOWY calculation needed — it falls out of
the participation accounting automatically.

**For DPVS composite scoring:** use `total_credit` as the team defense input.
It rewards both playing in more games (durability/availability) AND playing in
higher-TDGS games (being on the field for good defensive performances). A player
who played all 17 games on the 1969 Vikings accumulates more than one who
missed 5, even if equally dominant per snap.

**For cross-player comparison:** `per_game_credit` is the correct ERA-comparable
number when comparing players across seasons with different game counts (14-game
vs 16-game vs 17-game schedules). Scale `total_credit` by games played when
needed.

**The compute_wowy() function** in `build_game_defense.py` makes this explicit
by computing avg TDGS with vs. without each player. It formalizes the same
signal that's already embedded in `total_credit` and `per_game_credit`.

---

## Open Questions

- **Eller pre-2001 gamebook supplement:** Use era_plays_all.csv to identify Eller's
  game appearances and add him as a participant. Straightforward but not yet done.
- **Playoff games vs regular season:** Included in TDGS accumulation; opponents
  are more talented in playoffs but opponent season averages already account for this
  partially. Could separate if needed.
- **Special teams effect on pts_allowed:** Pts include defensive TDs by the opponent
  which may inflate pts_allowed in rare games. Not corrected for.
