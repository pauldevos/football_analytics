-- ============================================================
-- NFL Defensive Player Value Score — PostgreSQL Schema
-- ============================================================
-- Canonical player ID: pfr_player_id (PFR URL path, e.g. /players/W/WhitRe00.htm)
-- Team abbrevs: PFR style (phi, gnb, min, pit, dal, etc.)
-- Season: integer year of regular season
-- ============================================================

-- ------------------------------------------------------------
-- Core lookup tables
-- ------------------------------------------------------------

CREATE TABLE players (
    pfr_player_id   TEXT PRIMARY KEY,           -- e.g. /players/W/WhitRe00.htm
    player_name     TEXT NOT NULL,
    birth_date      DATE,
    college         TEXT,
    draft_team      TEXT,
    draft_round     SMALLINT,
    draft_pick      SMALLINT,
    draft_year      SMALLINT
);

CREATE INDEX idx_players_name ON players (player_name);

CREATE TABLE teams (
    team_abbrev     TEXT NOT NULL,              -- PFR abbrev: phi, gnb, min, etc.
    season          SMALLINT NOT NULL,
    team_name       TEXT NOT NULL,              -- e.g. "Philadelphia Eagles"
    conference      TEXT,                       -- NFC/AFC
    division        TEXT,                       -- NFC East, etc.
    PRIMARY KEY (team_abbrev, season)
);

CREATE TABLE seasons (
    season          SMALLINT PRIMARY KEY,
    num_teams       SMALLINT NOT NULL,          -- 28 pre-2002, 32 after
    num_weeks       SMALLINT NOT NULL           -- 16 pre-1978, varies
);

-- ------------------------------------------------------------
-- Games
-- ------------------------------------------------------------

CREATE TABLE games (
    game_id         TEXT PRIMARY KEY,           -- PFR game ID e.g. 198809110phi
    season          SMALLINT NOT NULL REFERENCES seasons(season),
    game_date       DATE NOT NULL,
    week            SMALLINT,
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    home_score      SMALLINT,
    away_score      SMALLINT,
    is_playoff      BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_games_season ON games (season);
CREATE INDEX idx_games_home ON games (home_team, season);
CREATE INDEX idx_games_away ON games (away_team, season);

-- ------------------------------------------------------------
-- Team defense — season aggregates
-- ------------------------------------------------------------

CREATE TABLE team_defense_season (
    team_abbrev         TEXT NOT NULL,
    season              SMALLINT NOT NULL,
    games               SMALLINT NOT NULL,
    pts_against         SMALLINT,
    yds_against         INTEGER,
    rush_yds_against    INTEGER,
    pass_yds_against    INTEGER,
    total_plays         INTEGER,
    yards_per_play      NUMERIC(4,2),
    takeaways           SMALLINT,
    fumble_recoveries   SMALLINT,
    interceptions       SMALLINT,
    sacks               NUMERIC(5,1),           -- may be fractional (shared sacks)
    pts_against_rank    SMALLINT,               -- 1 = best (least pts allowed)
    yds_against_rank    SMALLINT,               -- 1 = best (fewest yds allowed)
    -- Opponent-quality adjusted ranks (computed, filled later)
    oqa_pts_rank        NUMERIC(5,3),           -- 0.0-1.0, higher = better adjusted
    oqa_yds_rank        NUMERIC(5,3),
    PRIMARY KEY (team_abbrev, season)
);

-- ------------------------------------------------------------
-- Per-game team defensive output (derived from boxscores)
-- ------------------------------------------------------------

CREATE TABLE team_game_defense (
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    defending_team      TEXT NOT NULL,
    opponent_team       TEXT NOT NULL,
    pts_allowed         SMALLINT,
    pass_yds_allowed    SMALLINT,
    rush_yds_allowed    SMALLINT,
    total_yds_allowed   SMALLINT,
    pass_att_faced      SMALLINT,               -- opponent pass attempts
    rush_att_faced      SMALLINT,               -- opponent rush attempts
    team_sacks          NUMERIC(4,1),           -- total sacks by defending team in this game
    team_ints           SMALLINT,
    -- Opponent's season averages at time of game (excluding this game — filled in ETL)
    opp_season_avg_pass_yds     NUMERIC(6,2),
    opp_season_avg_rush_yds     NUMERIC(6,2),
    opp_season_avg_pts          NUMERIC(5,2),
    opp_season_avg_pass_att     NUMERIC(5,2),
    -- Computed deltas (actual - opponent avg) — negative = defense outperformed
    delta_pass_yds      NUMERIC(6,2),
    delta_rush_yds      NUMERIC(6,2),
    delta_total_yds     NUMERIC(6,2),
    delta_pts           NUMERIC(5,2),
    PRIMARY KEY (game_id, defending_team)
);

-- ------------------------------------------------------------
-- Individual player season stats (defensive)
-- ------------------------------------------------------------

CREATE TABLE player_defense_season (
    pfr_player_id   TEXT NOT NULL REFERENCES players(pfr_player_id),
    season          SMALLINT NOT NULL,
    team_abbrev     TEXT NOT NULL,
    age             SMALLINT,
    position        TEXT,                       -- LDE, RDE, DT, LB, CB, S, etc.
    games           SMALLINT,
    games_started   SMALLINT,
    interceptions   SMALLINT DEFAULT 0,
    int_yards       SMALLINT DEFAULT 0,
    int_td          SMALLINT DEFAULT 0,
    forced_fumbles  SMALLINT DEFAULT 0,
    fumble_recoveries SMALLINT DEFAULT 0,
    fr_yards        SMALLINT DEFAULT 0,
    fr_td           SMALLINT DEFAULT 0,
    sacks           NUMERIC(5,1) DEFAULT 0,
    solo_tackles    SMALLINT,                   -- NULL if pre-2001 (unreliable)
    ast_tackles     SMALLINT,                   -- NULL if pre-2001
    comb_tackles    SMALLINT,                   -- NULL if pre-2001
    safeties        SMALLINT DEFAULT 0,
    approx_value    SMALLINT,                   -- PFR AV
    awards          TEXT,                       -- raw string: "PB,AP-1,AP DPoY-2"
    is_pro_bowl     BOOLEAN DEFAULT FALSE,
    is_all_pro_1    BOOLEAN DEFAULT FALSE,
    is_all_pro_2    BOOLEAN DEFAULT FALSE,
    is_dpoy         BOOLEAN DEFAULT FALSE,
    tackles_source  TEXT,                       -- 'pfr_2001+', 'gamebook', 'estimate', NULL
    PRIMARY KEY (pfr_player_id, season, team_abbrev)
);

CREATE INDEX idx_pds_season ON player_defense_season (season);
CREATE INDEX idx_pds_team ON player_defense_season (team_abbrev, season);
CREATE INDEX idx_pds_position ON player_defense_season (position, season);

-- ------------------------------------------------------------
-- Individual player game stats (defensive) — sparse pre-2001
-- ------------------------------------------------------------

CREATE TABLE player_defense_game (
    pfr_player_id   TEXT NOT NULL REFERENCES players(pfr_player_id),
    game_id         TEXT NOT NULL REFERENCES games(game_id),
    team_abbrev     TEXT NOT NULL,
    position        TEXT,
    sacks           NUMERIC(4,1) DEFAULT 0,
    solo_tackles    SMALLINT,
    ast_tackles     SMALLINT,
    interceptions   SMALLINT DEFAULT 0,
    forced_fumbles  SMALLINT DEFAULT 0,
    fumble_recoveries SMALLINT DEFAULT 0,
    safeties        SMALLINT DEFAULT 0,
    data_source     TEXT NOT NULL,              -- 'pfr_gamelog', 'gamebook_mistral', 'gamebook_tesseract'
    PRIMARY KEY (pfr_player_id, game_id)
);

CREATE INDEX idx_pdg_game ON player_defense_game (game_id);

-- ------------------------------------------------------------
-- Gamebook play-by-play (raw structured plays)
-- ------------------------------------------------------------

CREATE TABLE gamebook_plays (
    id              SERIAL PRIMARY KEY,
    game_id         TEXT,                       -- matched game ID if resolvable
    gamebook_file   TEXT NOT NULL,              -- original filename
    season          SMALLINT,
    visitor_team    TEXT,
    home_team       TEXT,
    era             TEXT,                       -- ERA1 / ERA2 / ERA3
    period          SMALLINT,
    down            SMALLINT,
    distance        SMALLINT,
    yardline        SMALLINT,
    yardline_side   TEXT,
    clock           TEXT,
    play_type       TEXT,                       -- RUN/PASS/SACK/TFL/INTERCEPTION/FUMBLE/etc.
    player_role     TEXT,                       -- SOLO_TACKLE/ASSISTED_TACKLE/SACK/etc.
    player_name     TEXT,                       -- as named in gamebook
    pfr_player_id   TEXT REFERENCES players(pfr_player_id),  -- resolved, nullable
    is_solo         BOOLEAN,
    co_tacklers     TEXT,                       -- comma-separated names
    ocr_conf        TEXT,                       -- HIGH/MEDIUM/LOW
    description     TEXT,
    play_text       TEXT                        -- raw OCR text
);

CREATE INDEX idx_gbp_game ON gamebook_plays (game_id);
CREATE INDEX idx_gbp_player ON gamebook_plays (pfr_player_id);
CREATE INDEX idx_gbp_season ON gamebook_plays (season);

-- ------------------------------------------------------------
-- Gamebook tackle share (per game, per player)
-- From tackle_share.csv and extended pipeline
-- ------------------------------------------------------------

CREATE TABLE gamebook_tackle_share (
    gamebook_file   TEXT NOT NULL,
    season          SMALLINT NOT NULL,
    game_id         TEXT,
    pfr_player_id   TEXT REFERENCES players(pfr_player_id),
    player_name     TEXT,
    player_credits  SMALLINT NOT NULL DEFAULT 0,  -- plays credited to this player
    total_credits   SMALLINT NOT NULL DEFAULT 0,  -- total plays credited on team
    tackle_share    NUMERIC(6,4),                 -- player_credits / total_credits
    players_credited SMALLINT,                    -- distinct players receiving credit
    PRIMARY KEY (gamebook_file, player_name)
);

-- ------------------------------------------------------------
-- Roster (per team per season)
-- ------------------------------------------------------------

CREATE TABLE rosters (
    team_abbrev     TEXT NOT NULL,
    season          SMALLINT NOT NULL,
    pfr_player_id   TEXT REFERENCES players(pfr_player_id),
    jersey_number   SMALLINT,
    player_name     TEXT NOT NULL,
    age             SMALLINT,
    position        TEXT,
    games           SMALLINT,
    games_started   SMALLINT,
    weight_lbs      SMALLINT,
    height_in       SMALLINT,
    college         TEXT,
    experience_yrs  SMALLINT,
    approx_value    SMALLINT,
    PRIMARY KEY (team_abbrev, season, player_name)
);

CREATE INDEX idx_rosters_player ON rosters (pfr_player_id, season);

-- ------------------------------------------------------------
-- Opponent quality adjustment (per game, per team)
-- ------------------------------------------------------------
-- Pre-computed from ETL: for each game, how did the opponent perform
-- vs. their season average (excluding this game)?
-- Negative values mean the defense held them below their average.
-- ------------------------------------------------------------

CREATE TABLE opponent_quality_adjustment (
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    defending_team      TEXT NOT NULL,
    opp_team            TEXT NOT NULL,
    opp_season_rank_pts SMALLINT,               -- opponent's offense rank in pts scored
    opp_season_rank_yds SMALLINT,               -- opponent's offense rank in total yds
    delta_pts           NUMERIC(5,2),           -- actual pts - opp season avg (negative = held below avg)
    delta_pass_yds      NUMERIC(6,2),
    delta_rush_yds      NUMERIC(6,2),
    delta_total_yds     NUMERIC(6,2),
    delta_pass_att      NUMERIC(5,2),           -- fewer attempts = forced more punts/3-and-outs
    oqa_game_score      NUMERIC(6,4),           -- composite 0-1 for this game
    PRIMARY KEY (game_id, defending_team)
);

-- ------------------------------------------------------------
-- Position matchup grades (per player, per game)
-- ------------------------------------------------------------

CREATE TABLE matchup_grades (
    pfr_player_id       TEXT NOT NULL REFERENCES players(pfr_player_id),
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    season              SMALLINT NOT NULL,
    defender_position   TEXT,                   -- LDE, CB, etc.
    opponent_position   TEXT,                   -- RT, LT, QB, WR1, etc.
    opponent_player_id  TEXT REFERENCES players(pfr_player_id),   -- nullable if unknown
    opponent_player_name TEXT,
    ol_grade            NUMERIC(5,4),           -- 0-1, quality of blocking opponent
    qb_grade            NUMERIC(5,4),           -- 0-1, for pass rushers
    coverage_opp_grade  NUMERIC(5,4),           -- 0-1, for DBs
    opponent_pro_bowl   BOOLEAN DEFAULT FALSE,
    opponent_all_pro    BOOLEAN DEFAULT FALSE,
    combined_omg        NUMERIC(5,4),           -- weighted combined matchup grade
    PRIMARY KEY (pfr_player_id, game_id)
);

-- ------------------------------------------------------------
-- WOWY — With Or Without You (year pairs)
-- ------------------------------------------------------------

CREATE TABLE wowy_pairs (
    pfr_player_id           TEXT NOT NULL REFERENCES players(pfr_player_id),
    team_abbrev             TEXT NOT NULL,
    season_with             SMALLINT NOT NULL,  -- season player was on team
    season_without          SMALLINT NOT NULL,  -- comparison season (with or without)
    without_direction       TEXT NOT NULL,      -- 'BEFORE' | 'AFTER'
    -- Team defense ranks
    pts_rank_with           SMALLINT,
    pts_rank_without        SMALLINT,
    yds_rank_with           SMALLINT,
    yds_rank_without        SMALLINT,
    -- Percentile versions (0-1, higher = better defense)
    pts_pct_with            NUMERIC(5,4),
    pts_pct_without         NUMERIC(5,4),
    yds_pct_with            NUMERIC(5,4),
    yds_pct_without         NUMERIC(5,4),
    -- Deltas (with - without); positive = better defense with player
    pts_pct_delta           NUMERIC(6,4),
    yds_pct_delta           NUMERIC(6,4),
    -- OQA-adjusted versions
    oqa_pts_pct_with        NUMERIC(5,4),
    oqa_pts_pct_without     NUMERIC(5,4),
    oqa_yds_pct_with        NUMERIC(5,4),
    oqa_yds_pct_without     NUMERIC(5,4),
    oqa_pts_delta           NUMERIC(6,4),
    oqa_yds_delta           NUMERIC(6,4),
    -- Confidence
    roster_overlap_score    NUMERIC(4,3),       -- % of defenders retained yr-over-yr
    coaching_change         BOOLEAN DEFAULT FALSE,
    other_key_additions     TEXT,               -- names of other significant additions
    confidence              TEXT,               -- HIGH / MEDIUM / LOW
    PRIMARY KEY (pfr_player_id, team_abbrev, season_with, season_without)
);

-- ------------------------------------------------------------
-- DPVS component scores (per player, per season)
-- ------------------------------------------------------------

CREATE TABLE dpvs_components (
    pfr_player_id       TEXT NOT NULL REFERENCES players(pfr_player_id),
    season              SMALLINT NOT NULL,
    team_abbrev         TEXT NOT NULL,
    position_group      TEXT NOT NULL,          -- pass_rusher | run_stopper | coverage
    -- Individual Stat Shares
    sack_share_season   NUMERIC(5,4),
    sack_share_pg_avg   NUMERIC(5,4),
    tackle_share_season NUMERIC(5,4),           -- NULL if pre-2001 and no gamebook
    tackle_share_source TEXT,                   -- 'pfr', 'gamebook', NULL
    disruption_score    NUMERIC(5,4),           -- INT/FF/FR combined rate
    sack_rate_vs_opp    NUMERIC(6,4),           -- team sack rate vs. each opponent
    -- Opponent Quality
    oqa_season_score    NUMERIC(5,4),           -- mean OQA across all games played
    omg_season_avg      NUMERIC(5,4),           -- mean matchup grade across games
    -- WOWY
    wowy_pts_delta      NUMERIC(6,4),           -- best available WOWY pts delta
    wowy_yds_delta      NUMERIC(6,4),           -- best available WOWY yds delta
    wowy_confidence     TEXT,
    -- Composite
    dpvs_raw            NUMERIC(6,4),           -- weighted sum before normalization
    dpvs_100            NUMERIC(5,2),           -- 0-100 normalized within position group + season
    position_group_rank SMALLINT,               -- rank within position group that season
    -- Metadata
    games_played        SMALLINT,
    data_completeness   NUMERIC(4,3),           -- fraction of components that are non-null
    PRIMARY KEY (pfr_player_id, season, team_abbrev)
);

CREATE INDEX idx_dpvs_season ON dpvs_components (season, position_group);
CREATE INDEX idx_dpvs_score ON dpvs_components (dpvs_100 DESC);

-- ------------------------------------------------------------
-- Career DPVS (aggregated across seasons)
-- ------------------------------------------------------------

CREATE TABLE dpvs_career (
    pfr_player_id       TEXT PRIMARY KEY REFERENCES players(pfr_player_id),
    primary_position    TEXT,
    position_group      TEXT,
    seasons_played      SMALLINT,
    peak_dpvs           NUMERIC(5,2),           -- max single-season dpvs_100
    peak_season         SMALLINT,
    prime_dpvs          NUMERIC(5,2),           -- mean of top-3 seasons
    career_dpvs         NUMERIC(5,2),           -- games-started-weighted mean
    total_sacks         NUMERIC(6,1),
    total_ints          SMALLINT,
    total_ff            SMALLINT,
    pro_bowl_count      SMALLINT,
    all_pro_1_count     SMALLINT,
    dpoy_count          SMALLINT,
    last_updated        TIMESTAMP DEFAULT NOW()
);

-- ============================================================
-- Views
-- ============================================================

-- Sack share per team per season (derived from player_defense_season)
CREATE VIEW v_team_sack_totals AS
SELECT
    season,
    team_abbrev,
    SUM(sacks) AS team_sacks,
    COUNT(DISTINCT pfr_player_id) AS players_with_sacks
FROM player_defense_season
WHERE sacks > 0
GROUP BY season, team_abbrev;

-- Per-game team sacks derived from boxscore (from team_game_defense)
CREATE VIEW v_game_sack_share AS
SELECT
    pdg.pfr_player_id,
    pdg.game_id,
    pdg.team_abbrev,
    pdg.sacks AS player_sacks,
    tgd.team_sacks,
    CASE WHEN tgd.team_sacks > 0
         THEN pdg.sacks / tgd.team_sacks
         ELSE NULL
    END AS sack_share
FROM player_defense_game pdg
JOIN team_game_defense tgd
    ON pdg.game_id = tgd.game_id
    AND pdg.team_abbrev = tgd.defending_team;

-- DPVS leaderboard per season
CREATE VIEW v_dpvs_leaderboard AS
SELECT
    dc.season,
    dc.position_group,
    dc.position_group_rank,
    p.player_name,
    dc.team_abbrev,
    pds.position,
    dc.dpvs_100,
    dc.sack_share_season,
    dc.tackle_share_season,
    dc.wowy_yds_delta,
    dc.wowy_pts_delta,
    pds.is_all_pro_1,
    pds.is_pro_bowl,
    pds.is_dpoy
FROM dpvs_components dc
JOIN players p USING (pfr_player_id)
JOIN player_defense_season pds
    ON dc.pfr_player_id = pds.pfr_player_id
    AND dc.season = pds.season
    AND dc.team_abbrev = pds.team_abbrev
ORDER BY dc.season, dc.position_group, dc.position_group_rank;
