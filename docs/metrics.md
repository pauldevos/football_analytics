# DPVS Metrics Reference

Definitions, formulas, motivation, and worked examples for every metric
produced by the defensive analytics pipeline.

---

## 1. TDGS — Team Defense Game Score

**What it measures:**  
How dominant a defense was in a single game, expressed as a z-score relative
to that season's league distribution. Positive = better than average;
negative = worse. Zero is exactly average.

**Formula:**

```
yds_credit = 0.5 × (league_avg_yds − yds_allowed)
           + 0.5 × (opp_avg_yds   − yds_allowed)

pts_credit = 0.5 × (league_avg_pts − pts_allowed)
           + 0.5 × (opp_avg_pts   − pts_allowed)

TDGS = 0.55 × (yds_credit / season_std_yds)
     + 0.45 × (pts_credit / season_std_pts)
```

**Why this formula:**

*Dual benchmark* — each game's performance is measured against two baselines:
- **vs. league average**: absolute quality ("how good was this defense on any given Sunday?")
- **vs. opponent season average**: relative quality ("how much better than expected, given who they faced?")

Holding a 420-yd/game offense to 300 yards is a completely different defensive
performance than holding a 260-yd/game offense to 300 yards. The 50/50 blend
rewards both dimensions.

*Z-score normalization* enables cross-era comparison. The 1969 NFL had a
standard deviation of 33 yards/game across teams; 2000 had 49 yards/game.
A defense 90 yards below average is more exceptional in the tight-variance era.

*0.55/0.45 yards/points weighting* — yards is a better process signal;
points include scoring-position luck, turnovers, and special teams that
don't purely reflect defensive quality.

**Calibration:**

| Team | Season | TDGS/game | Context |
|------|--------|-----------|---------|
| Kansas City Chiefs | 2000 | −0.040 | Dead average (correct anchor at ≈0) |
| Cleveland Browns | 2000 | −0.855 | Expansion-level bad |
| Baltimore Ravens | 2000 | +1.733 | All-time great modern defense |
| Minnesota Vikings | 1971 | +1.854 | Purple People Eaters peak |
| Minnesota Vikings | 1969 | +2.702 | Best in dataset |

**Best individual games:**

| Game | Def team | Opp | Yds | Pts | OQA-Y | OQA-P | TDGS |
|------|----------|-----|-----|-----|-------|-------|------|
| 196911090min | MIN | CLE | 151 | 3 | +165 | +22.1 | **+5.249** |
| 196910120chi | MIN | CHI | 119 | 0 | +136 | +15.0 | **+5.000** |
| 197110030min | MIN | BUF | 64 | 0 | +84 | +18.5 | **+5.175** |
| 200012310rav | RAV | DEN | 177 | 3 | +52 | +17.1 | **+4.047** |

**Source:** `scripts/build_game_defense.py` → `~/data/silver/game_defense.parquet`

---

## 2. OQA — Opponent Quality Adjustment

**What it measures:**  
How many yards/points above or below the opponent's own season average
the defense allowed. Positive = held them below their average (good).

```
oqa_yds = opp_avg_yds_per_game − yds_allowed_this_game
oqa_pts = opp_avg_pts_per_game − pts_allowed_this_game
```

OQA is not a standalone metric — it feeds into TDGS as one of the two
benchmarks. It is stored separately in `game_defense.parquet` for inspection.

**Why it matters:**  
Context collapses without it. The 1969 Vikings holding Cleveland to 151 yards
is impressive in isolation; knowing Cleveland averaged 316 yards/game that
season (OQA-Y = +165) makes it extraordinary.

**1969 Vikings — Alan Page game log, OQA column:**

```
Game              vs    Yds  Pts  OQA-Y  OQA-P   TDGS
196909210nyg      NYG   320   24     -8   -5.1  -0.778  ← gave up 8 yds MORE than NYG's avg
196909280min      CLT   235   14    +85   +5.9  +2.086
196910050min      GNB   173    7   +118  +12.2  +3.752
196910120chi      CHI   119    0   +136  +15.0  +5.000
196911090min      CLE   151    3   +165  +22.1  +5.249  ← held CLE 165 yds below their avg
196912210atl      ATL   111   10   +161   +9.7  +4.269
```

The NYG game looks terrible (320 yds, 24 pts) AND confirms the OQA says NYG
slightly outgained their own average (−8). When the defense underperformed,
OQA makes it unambiguous.

**Data source:** opponent season offensive averages from
`~/data/pfref/raw/season/team/offense/team_stats/team_stats_{year}.csv`
and `team_scoring_{year}.csv`.

---

## 3. Team Credit Share & Total Credit

**What it measures:**  
How much of the team's defensive performance credit belongs to each individual
defender, accounting for which specific games they appeared in.

```
team_credit_share (per game) = TDGS_this_game / n_participants_this_game

total_credit (season)        = SUM of team_credit_share across all games played
per_game_credit              = total_credit / games_played
```

**Participation** = named starter in `starters.csv` OR ≥4 defensive stat
events in `player_defense.csv` for that game.

**Why equal split (not weighted by tackles/stats):**  
Correlation between per-game stat events and per-game TDGS = **r = 0.054**
(2000 NFL season, 259 games, all teams). Essentially zero. Defenses that
allow fewer yards also generate fewer tackle events (opponent doesn't sustain
drives), so weighting by stats would paradoxically *penalize* the better defense.

**The game-by-game credit varies enormously:**

```
Alan Page, 1969 MIN — per-game credit:
  Best game  vs CLE  TDGS=+5.249 → credit = +5.249/10 = +0.525
  Worst game vs NYG  TDGS=−0.778 → credit = −0.778/10 = −0.078
  Ratio best/worst: 6.7×
```

`per_game_credit = +0.270` in the season report is the *arithmetic mean* of
17 very different per-game values — not a uniform per-game rate.

**For DPVS scoring, use `total_credit`** (not per_game_credit). It rewards
both durability (playing in more games) and being on the field for good
defensive performances. When comparing across seasons with different game
counts (14-game vs 16-game vs 17-game schedules), normalize by games played.

**Source:** `scripts/build_game_defense.py` → `~/data/silver/player_game_defense.parquet`

---

## 4. WOWY — With Or Without You

**What it measures:**  
The average team TDGS in games the player participated in vs games they
did not. The delta reveals how much the defense changed when they were
absent.

```
wowy_delta = avg_TDGS_games_with_player − avg_TDGS_games_without_player
```

**Why it matters:**  
A dominant defender who misses 3 games due to injury creates a natural
experiment. If the defense drops from +2.5 to +0.8 in those games,
WOWY delta = +1.7 — strong evidence of individual impact.

**WOWY is embedded in `total_credit` by design:**  
Since credits only accumulate for games the player appeared in, two
teammates with different participation sets will have different
`per_game_credit` averages. That difference IS the WOWY signal. The
explicit `compute_wowy()` function formalizes what's already embedded.

```python
# From compute_wowy() in build_game_defense.py
wowy_delta = avg_TDGS(games player IN) − avg_TDGS(games player OUT)
```

**Limitation:** Works best for players who miss multiple games. For a
player who appeared in all 17 games, `games_out = 0` and wowy_delta = None.
In that case, compare their `per_game_credit` across seasons (how did the
defense trend when they arrived or left?).

**Source:** `scripts/build_game_defense.py` → `~/data/silver/player_season_wowy.parquet`

---

## 5. Era Adjustment — Why Z-Scores

**The problem:** Raw yards and points allowed are not comparable across eras.
The 1969 NFL had much lower offensive variance than 2001. A defense allowing
194 yards/game in 1969 and one allowing 165 yards/game in 2000 are both
historically exceptional, but the raw numbers look different.

**Z-score approach:** Express every game as standard deviations below the
season mean. The 1969 Vikings (−3.2σ in yards) and 2000 Ravens (−3.2σ in
yards) are equally dominant relative to their eras.

**The tradeoff:**

| Measure | Use case |
|---------|----------|
| Raw yards/pts allowed | "Which defense literally allowed fewer yards?" |
| TDGS z-score | "Which defense was more dominant relative to what was possible in their era?" |

DPVS uses z-scores because cross-era player comparison is the core problem.
If you need to assert "the Ravens were the best defense in the data," use
raw numbers. If you need to compare Carl Eller's 1969 season to a 2000
defender, use TDGS.

**Calibration check:** Both the 1969 Vikings and 2000 Ravens score −3.2σ
in yards. Their TDGS difference (+2.702 vs +1.733) comes primarily from
the points component: the Vikings allowed 10.8 ppg in an era where the
league std was 3.4 pts — 3.0σ below average. The Ravens allowed 9.4 ppg
when the league std was 5.2 pts — 2.2σ below average. The Vikings' points
defense was more exceptional for its era.

---

## Output Files

| File | Rows (pilot) | Description |
|------|-------------|-------------|
| `~/data/silver/game_defense.parquet` | 1 per game×team | TDGS, OQA columns, raw yds/pts |
| `~/data/silver/player_game_defense.parquet` | 1 per game×player | team_credit_share per game |
| `~/data/silver/player_season_wowy.parquet` | 1 per player×season | total_credit, wowy_delta |

Build command:
```bash
cd ~/github/football/football_analytics
python scripts/build_game_defense.py --seasons 1969-2000 --report min rav atl
```
