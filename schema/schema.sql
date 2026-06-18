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
    tackles_source  TEXT,                       -- 'pfr', 'media_guide', 'card_back', 'gamebook', 'pfr_and_media_guide', 'estimate', NULL
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

-- ------------------------------------------------------------
-- Per-game offensive stats (derived from boxscores)
-- One row per team per game — what the offense actually did.
-- Receiving position groups require roster lookup; has_position_data
-- is FALSE when <75% of receiving yards could be matched to a group.
-- NOTE: fumbles are not available in boxscore CSVs.
-- ------------------------------------------------------------

CREATE TABLE team_game_offense (
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    offense_team        TEXT NOT NULL,
    defense_team        TEXT NOT NULL,
    season              SMALLINT NOT NULL,
    -- Passing
    pass_comp           SMALLINT,
    pass_att            SMALLINT,
    pass_yds            SMALLINT,
    pass_td             SMALLINT,
    pass_int            SMALLINT,           -- INTs thrown = turnovers for defense
    comp_pct            NUMERIC(5,2),
    qb_rate             NUMERIC(5,1),       -- recomputed from totals, not averaged
    sacks_taken         SMALLINT,           -- times QB was sacked; positive delta = defense outperformed
    sack_yds_lost       SMALLINT,
    -- Rushing
    rush_att            SMALLINT,
    rush_yds            SMALLINT,
    rush_td             SMALLINT,
    rush_ypc            NUMERIC(4,2),
    -- Receiving totals
    rec_total           SMALLINT,
    rec_yds_total       SMALLINT,
    rec_td_total        SMALLINT,
    -- Receiving by position group (NULL when has_position_data = FALSE)
    rec_rb              SMALLINT,
    rec_yds_rb          SMALLINT,
    rec_td_rb           SMALLINT,
    rec_wr              SMALLINT,
    rec_yds_wr          SMALLINT,
    rec_td_wr           SMALLINT,
    rec_te              SMALLINT,
    rec_yds_te          SMALLINT,
    rec_td_te           SMALLINT,
    has_position_data   BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (game_id, offense_team)
);

CREATE INDEX idx_tgo_season_off  ON team_game_offense (season, offense_team);
CREATE INDEX idx_tgo_season_def  ON team_game_offense (season, defense_team);

-- ------------------------------------------------------------
-- Opponent quality adjustment — detailed, per-game
-- For each defending team + game: what did that offense average
-- (leave-one-out) vs. what they actually did against this defense?
-- delta = actual - avg
--   Passing/rushing/receiving: negative = defense held below average  (good)
--   sacks_taken / pass_int:    positive = defense exceeded average    (good)
-- ------------------------------------------------------------

CREATE TABLE oqa_game_detail (
    game_id                 TEXT NOT NULL REFERENCES games(game_id),
    defending_team          TEXT NOT NULL,
    offense_team            TEXT NOT NULL,
    season                  SMALLINT NOT NULL,
    games_in_avg            SMALLINT,           -- games in the leave-one-out denominator
    -- Opponent leave-one-out season averages (recomputed from raw totals)
    opp_avg_pass_yds        NUMERIC(6,2),
    opp_avg_pass_td         NUMERIC(5,2),
    opp_avg_comp_pct        NUMERIC(5,2),
    opp_avg_qb_rate         NUMERIC(5,1),
    opp_avg_rush_yds        NUMERIC(6,2),
    opp_avg_rush_td         NUMERIC(5,2),
    opp_avg_rush_ypc        NUMERIC(4,2),
    opp_avg_sacks_taken     NUMERIC(4,2),
    opp_avg_pass_int        NUMERIC(4,2),
    opp_avg_rec_total       NUMERIC(5,2),
    opp_avg_rec_yds_total   NUMERIC(6,2),
    opp_avg_rec_td_total    NUMERIC(4,2),
    opp_avg_rec_rb          NUMERIC(5,2),
    opp_avg_rec_yds_rb      NUMERIC(6,2),
    opp_avg_rec_td_rb       NUMERIC(4,2),
    opp_avg_rec_wr          NUMERIC(5,2),
    opp_avg_rec_yds_wr      NUMERIC(6,2),
    opp_avg_rec_td_wr       NUMERIC(4,2),
    opp_avg_rec_te          NUMERIC(5,2),
    opp_avg_rec_yds_te      NUMERIC(6,2),
    opp_avg_rec_td_te       NUMERIC(4,2),
    -- Actual values in this game
    actual_pass_yds         SMALLINT,
    actual_pass_td          SMALLINT,
    actual_comp_pct         NUMERIC(5,2),
    actual_qb_rate          NUMERIC(5,1),
    actual_rush_yds         SMALLINT,
    actual_rush_td          SMALLINT,
    actual_rush_ypc         NUMERIC(4,2),
    actual_sacks_taken      SMALLINT,
    actual_pass_int         SMALLINT,
    actual_rec_total        SMALLINT,
    actual_rec_yds_total    SMALLINT,
    actual_rec_td_total     SMALLINT,
    actual_rec_rb           SMALLINT,
    actual_rec_yds_rb       SMALLINT,
    actual_rec_td_rb        SMALLINT,
    actual_rec_wr           SMALLINT,
    actual_rec_yds_wr       SMALLINT,
    actual_rec_td_wr        SMALLINT,
    actual_rec_te           SMALLINT,
    actual_rec_yds_te       SMALLINT,
    actual_rec_td_te        SMALLINT,
    -- Deltas (actual - avg)
    delta_pass_yds          NUMERIC(6,2),
    delta_pass_td           NUMERIC(5,2),
    delta_comp_pct          NUMERIC(5,2),
    delta_qb_rate           NUMERIC(5,1),
    delta_rush_yds          NUMERIC(6,2),
    delta_rush_td           NUMERIC(5,2),
    delta_rush_ypc          NUMERIC(4,2),
    delta_sacks_taken       NUMERIC(4,2),
    delta_pass_int          NUMERIC(4,2),
    delta_rec_total         NUMERIC(5,2),
    delta_rec_yds_total     NUMERIC(6,2),
    delta_rec_td_total      NUMERIC(4,2),
    delta_rec_rb            NUMERIC(5,2),
    delta_rec_yds_rb        NUMERIC(6,2),
    delta_rec_td_rb         NUMERIC(4,2),
    delta_rec_wr            NUMERIC(5,2),
    delta_rec_yds_wr        NUMERIC(6,2),
    delta_rec_td_wr         NUMERIC(4,2),
    delta_rec_te            NUMERIC(5,2),
    delta_rec_yds_te        NUMERIC(6,2),
    delta_rec_td_te         NUMERIC(4,2),
    PRIMARY KEY (game_id, defending_team)
);

CREATE INDEX idx_oqa_detail_season ON oqa_game_detail (season, defending_team);

-- ============================================================
-- Offensive Line Analysis Tables
-- ============================================================

-- ------------------------------------------------------------
-- Team offense season aggregates (pass + rush combined)
-- Source: team-offense/team-passing/ + team-rushing/ CSVs
-- Pass/rush ratio and ranks computed in ETL.
-- ------------------------------------------------------------

CREATE TABLE team_offense_season (
    team_abbrev         TEXT NOT NULL,
    season              SMALLINT NOT NULL,
    games               SMALLINT,
    -- Passing
    pass_comp           SMALLINT,
    pass_att            SMALLINT,
    pass_yds            INTEGER,
    pass_td             SMALLINT,
    pass_int            SMALLINT,
    comp_pct            NUMERIC(5,2),
    qb_rating           NUMERIC(5,1),
    sacks_taken         SMALLINT,
    sack_yds_lost       SMALLINT,
    sack_pct            NUMERIC(5,2),
    -- Rushing
    rush_att            SMALLINT,
    rush_yds            INTEGER,
    rush_td             SMALLINT,
    rush_ypc            NUMERIC(4,2),
    -- Derived
    total_plays         SMALLINT,               -- pass_att + rush_att
    pass_run_ratio      NUMERIC(5,3),           -- pass_att / total_plays
    -- Ranks within season peer group (1 = best)
    pass_yds_rank       SMALLINT,               -- 1 = most passing yards (best offense)
    rush_ypc_rank       SMALLINT,               -- 1 = highest yards per carry
    sacks_taken_rank    SMALLINT,               -- 1 = fewest sacks taken (best pass pro)
    rush_yds_rank       SMALLINT,               -- 1 = most rush yards
    PRIMARY KEY (team_abbrev, season)
);

CREATE INDEX idx_tos_season ON team_offense_season (season);

-- ------------------------------------------------------------
-- Player awards / accolades (All-Pro, Pro Bowl, All-Conf, PFF)
-- Source: all_pro/*.csv  — covers all positions, all eras
-- award_class normalizes across orgs so you can filter on it.
-- ------------------------------------------------------------

CREATE TABLE player_awards (
    pfr_short_id        TEXT NOT NULL,          -- e.g. "KaliMa99"
    pfr_player_id       TEXT REFERENCES players(pfr_player_id),  -- resolved; nullable
    player_name         TEXT NOT NULL,
    season              SMALLINT NOT NULL,
    team_abbrev         TEXT NOT NULL,          -- upper-case PFR abbrev (GNB, MIN, etc.)
    position            TEXT,
    org                 TEXT NOT NULL,          -- AP | FW | SN | PFF
    designation         TEXT NOT NULL,          -- "1st Tm", "2nd Tm", "1st Tm All-Conf.", etc.
    award_class         TEXT NOT NULL,          -- ALL_PRO_1 | ALL_PRO_2 | ALL_CONF | PFF_1 | PFF_2 | PRO_BOWL | OTHER
    PRIMARY KEY (pfr_short_id, season, org, designation)
);

CREATE INDEX idx_awards_season_pos ON player_awards (season, position);
CREATE INDEX idx_awards_player     ON player_awards (pfr_short_id, season);
CREATE INDEX idx_awards_class      ON player_awards (award_class, season);

-- ------------------------------------------------------------
-- Per-game starters by position (both teams, from boxscore pages)
-- Scraped from: /boxscores/{game_id}.htm  — starters section
-- Gives specific positional slots: LT, LG, C, RG, RT, LDE, NT, RDE, etc.
-- Coverage reliable ~1994+; earlier years have partial data.
-- ------------------------------------------------------------

CREATE TABLE game_starters (
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    team_abbrev         TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('OFF', 'DEF')),
    starter_position    TEXT NOT NULL,          -- LT, LG, C, RG, RT, QB, WR, LDE, NT, RDE, etc.
    pfr_player_id       TEXT REFERENCES players(pfr_player_id),   -- nullable until resolved
    pfr_short_id        TEXT,                   -- e.g. "KaliMa99"
    player_name         TEXT NOT NULL,
    PRIMARY KEY (game_id, team_abbrev, side, starter_position)
);

CREATE INDEX idx_gs_team_season ON game_starters (team_abbrev, game_id);
CREATE INDEX idx_gs_player      ON game_starters (pfr_player_id);
CREATE INDEX idx_gs_position    ON game_starters (starter_position, game_id);

-- ------------------------------------------------------------
-- Per-game snap counts (all players who appeared, both teams)
-- Scraped from: /boxscores/{game_id}.htm  — snap counts section
-- off_snaps=NULL means snap count data unavailable for that game.
-- ------------------------------------------------------------

CREATE TABLE player_snap_counts (
    game_id             TEXT NOT NULL REFERENCES games(game_id),
    team_abbrev         TEXT NOT NULL,
    pfr_player_id       TEXT REFERENCES players(pfr_player_id),
    pfr_short_id        TEXT,
    player_name         TEXT NOT NULL,
    position            TEXT,                   -- general position (T, G, C, DE, etc.)
    off_snaps           SMALLINT,
    off_snap_pct        NUMERIC(5,1),
    def_snaps           SMALLINT,
    def_snap_pct        NUMERIC(5,1),
    st_snaps            SMALLINT,
    st_snap_pct         NUMERIC(5,1),
    PRIMARY KEY (game_id, team_abbrev, player_name)
);

CREATE INDEX idx_psc_player ON player_snap_counts (pfr_player_id, game_id);
CREATE INDEX idx_psc_game   ON player_snap_counts (game_id, team_abbrev);

-- ------------------------------------------------------------
-- Play-by-play sack attribution (individual defenders, 1978+)
-- Scraped from PFR boxscore pages — play-by-play section.
-- Available as PBP data from 1978; boxscore defense stats 1982+.
-- FK on game_id intentionally omitted: scraped before games ETL.
-- For shared sacks, one row per sacker (play_seq is shared).
-- ------------------------------------------------------------

CREATE TABLE play_by_play_sacks (
    game_id             TEXT NOT NULL,
    play_seq            SMALLINT NOT NULL,  -- running sack-play # within game (1,2,3…)
    quarter             SMALLINT,
    offense_team        TEXT,               -- team whose QB was sacked
    defense_team        TEXT,               -- team that recorded the sack
    sacker_name         TEXT NOT NULL,
    sacker_pfr_id       TEXT,               -- /players/X/XxxxXx00.htm — nullable until resolved
    sacker_short_id     TEXT,               -- e.g. "TaylLa56"
    sacked_name         TEXT,               -- QB who was sacked
    sacked_pfr_id       TEXT,
    sacked_short_id     TEXT,
    yds_lost            SMALLINT,
    description         TEXT,               -- raw play text (truncated to 500 chars)
    PRIMARY KEY (game_id, play_seq, sacker_name)
);

CREATE INDEX idx_pbs_game        ON play_by_play_sacks (game_id);
CREATE INDEX idx_pbs_sacker      ON play_by_play_sacks (sacker_short_id, game_id);
CREATE INDEX idx_pbs_defense     ON play_by_play_sacks (defense_team, game_id);

-- ============================================================
-- Individual offensive player game stats
-- ============================================================

-- One row per player per regular-season game.
-- position_group: QB / RB / WR / TE (mapped from roster position).
-- is_primary: TRUE for the player with most rec_yds among TEs/WRs on that team that game
--             (or most pass_att for QBs, most rush_yds for RBs) — useful for TE/QB analysis.
-- targets available from ~2002+; NULL for earlier eras.
CREATE TABLE player_game_offense (
    game_id         TEXT NOT NULL,
    pfr_player_id   TEXT NOT NULL,
    player_name     TEXT NOT NULL,
    team_abbrev     TEXT NOT NULL,
    defense_team    TEXT NOT NULL,
    season          SMALLINT NOT NULL,
    position_group  TEXT NOT NULL CHECK (position_group IN ('QB','RB','WR','TE')),
    is_primary      BOOLEAN DEFAULT FALSE,  -- top producer at position for this team/game
    -- QB stats (non-zero only for QBs)
    pass_comp       SMALLINT NOT NULL DEFAULT 0,
    pass_att        SMALLINT NOT NULL DEFAULT 0,
    pass_yds        SMALLINT NOT NULL DEFAULT 0,
    pass_td         SMALLINT NOT NULL DEFAULT 0,
    pass_int        SMALLINT NOT NULL DEFAULT 0,
    sacks_taken     SMALLINT NOT NULL DEFAULT 0,
    qb_rate         NUMERIC(5,1),           -- NULL when pass_att = 0
    -- Rush stats
    rush_att        SMALLINT NOT NULL DEFAULT 0,
    rush_yds        SMALLINT NOT NULL DEFAULT 0,
    rush_td         SMALLINT NOT NULL DEFAULT 0,
    -- Receiving stats
    targets         SMALLINT,               -- NULL pre-~2002
    rec             SMALLINT NOT NULL DEFAULT 0,
    rec_yds         SMALLINT NOT NULL DEFAULT 0,
    rec_td          SMALLINT NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, pfr_player_id)
);

CREATE INDEX idx_pgo_player  ON player_game_offense (pfr_player_id, season);
CREATE INDEX idx_pgo_season  ON player_game_offense (season, position_group);
CREATE INDEX idx_pgo_defense ON player_game_offense (defense_team, season);
CREATE INDEX idx_pgo_primary ON player_game_offense (season, position_group, is_primary);

-- ============================================================
-- Defense season-average allowed (LOO, defense perspective)
-- For each (game_id, defending_team): average stats that defense
-- allowed in all OTHER regular-season games that season.
-- Negative deltas (actual < avg) = defense held offense below their norm.
-- Sacks/INT: positive delta = defense exceeded average (good).
-- ============================================================
CREATE TABLE defense_loo_avg (
    game_id             TEXT NOT NULL,
    defending_team      TEXT NOT NULL,
    season              SMALLINT NOT NULL,
    games_in_avg        SMALLINT NOT NULL,
    -- Passing allowed
    def_avg_pass_yds    NUMERIC(6,2),
    def_avg_pass_td     NUMERIC(5,2),
    def_avg_pass_int    NUMERIC(4,2),       -- INTs forced
    def_avg_qb_rate     NUMERIC(5,1),
    def_avg_comp_pct    NUMERIC(5,2),
    def_avg_sacks       NUMERIC(4,2),       -- sacks generated
    -- Rushing allowed
    def_avg_rush_yds    NUMERIC(6,2),
    def_avg_rush_td     NUMERIC(5,2),
    def_avg_rush_ypc    NUMERIC(4,2),
    -- Receiving allowed by position group
    def_avg_rec_yds_total NUMERIC(6,2),
    def_avg_rec_yds_rb  NUMERIC(6,2),
    def_avg_rec_yds_wr  NUMERIC(6,2),
    def_avg_rec_yds_te  NUMERIC(6,2),
    def_avg_rec_rb      NUMERIC(5,2),
    def_avg_rec_wr      NUMERIC(5,2),
    def_avg_rec_te      NUMERIC(5,2),
    def_avg_rec_td_rb   NUMERIC(4,2),
    def_avg_rec_td_wr   NUMERIC(4,2),
    def_avg_rec_td_te   NUMERIC(4,2),
    PRIMARY KEY (game_id, defending_team)
);

CREATE INDEX idx_dla_defense ON defense_loo_avg (defending_team, season);

-- ============================================================
-- Player OQA season rollup (individual, position-aware)
-- Aggregated from player_game_offense + defense_loo_avg.
-- For each player-season: total and per-game-average deltas.
-- ============================================================
CREATE TABLE player_oqa_season (
    pfr_player_id       TEXT NOT NULL,
    player_name         TEXT NOT NULL,
    team_abbrev         TEXT NOT NULL,
    season              SMALLINT NOT NULL,
    position_group      TEXT NOT NULL,
    games               SMALLINT NOT NULL,  -- games with qualifying stats
    -- Actual season totals
    total_pass_yds      INTEGER,
    total_pass_td       SMALLINT,
    total_pass_int      SMALLINT,
    avg_qb_rate         NUMERIC(5,1),       -- season passer rating (recomputed from totals)
    total_rush_yds      INTEGER,
    total_rush_td       SMALLINT,
    total_rec_yds       INTEGER,
    total_rec           SMALLINT,
    total_rec_td        SMALLINT,
    -- OQA deltas (actual - defense's LOO average allowed)
    -- QB
    delta_pass_yds_total    NUMERIC(7,1),   -- sum of per-game deltas
    delta_pass_yds_pg       NUMERIC(6,2),   -- per-game average
    delta_pass_td_total     NUMERIC(5,1),
    delta_pass_td_pg        NUMERIC(5,3),
    delta_pass_int_total    NUMERIC(5,1),   -- negative = good (fewer picks than defense avg forces)
    delta_pass_int_pg       NUMERIC(5,3),
    delta_qb_rate_total     NUMERIC(7,1),
    delta_qb_rate_pg        NUMERIC(6,2),
    -- RB
    delta_rush_yds_total    NUMERIC(7,1),
    delta_rush_yds_pg       NUMERIC(6,2),
    delta_rush_td_total     NUMERIC(5,1),
    delta_rush_td_pg        NUMERIC(5,3),
    -- WR/TE (receiving)
    delta_rec_yds_total     NUMERIC(7,1),
    delta_rec_yds_pg        NUMERIC(6,2),
    delta_rec_total_d       NUMERIC(5,1),
    delta_rec_pg            NUMERIC(5,3),
    delta_rec_td_total      NUMERIC(5,1),
    delta_rec_td_pg         NUMERIC(5,3),
    -- WR note: compared against defense's total WR yards allowed (position group, not individual)
    -- TE note: uses is_primary=TRUE games only for opponent TE baseline (when available)
    has_position_data   BOOLEAN DEFAULT TRUE,   -- FALSE if >25% games lack roster pos match
    PRIMARY KEY (pfr_player_id, team_abbrev, season)
);

CREATE INDEX idx_poqa_season ON player_oqa_season (season, position_group);
CREATE INDEX idx_poqa_player ON player_oqa_season (pfr_player_id);

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

-- ------------------------------------------------------------
-- OL season profile: every OL starter-season with team offense
-- context + accolades. Works back to ~1960 (just uses roster GS).
-- pass/rush/sack ranks: 1 = best; NULL when season data missing.
-- ------------------------------------------------------------
CREATE VIEW v_ol_season_profile AS
SELECT
    r.team_abbrev,
    r.season,
    r.player_name,
    r.pfr_player_id,
    r.position,
    r.games,
    r.games_started,
    r.approx_value                              AS av,
    tos.pass_att,
    tos.pass_yds,
    tos.pass_yds_rank,
    tos.sacks_taken,
    tos.sacks_taken_rank,
    tos.sack_pct,
    tos.rush_yds,
    tos.rush_ypc,
    tos.rush_ypc_rank,
    tos.rush_yds_rank,
    tos.pass_run_ratio,
    -- Award flags (any org)
    MAX(CASE WHEN a.award_class = 'ALL_PRO_1'  THEN 1 ELSE 0 END) AS is_all_pro_1,
    MAX(CASE WHEN a.award_class = 'ALL_PRO_2'  THEN 1 ELSE 0 END) AS is_all_pro_2,
    MAX(CASE WHEN a.award_class = 'ALL_CONF'   THEN 1 ELSE 0 END) AS is_all_conf,
    MAX(CASE WHEN a.award_class = 'PRO_BOWL'   THEN 1 ELSE 0 END) AS is_pro_bowl,
    MAX(CASE WHEN a.award_class = 'PFF_1'      THEN 1 ELSE 0 END) AS is_pff_1,
    MAX(CASE WHEN a.award_class = 'PFF_2'      THEN 1 ELSE 0 END) AS is_pff_2
FROM rosters r
JOIN team_offense_season tos
    ON r.team_abbrev = tos.team_abbrev
    AND r.season = tos.season
LEFT JOIN player_awards a
    ON UPPER(r.team_abbrev) = a.team_abbrev
    AND r.season = a.season
    AND r.position = a.position
    AND (r.player_name = a.player_name
         OR r.pfr_player_id = a.pfr_player_id)
WHERE r.position IN ('T', 'OT', 'G', 'OG', 'C', 'OL', 'LT', 'RT', 'LG', 'RG')
  AND r.games_started > 0
GROUP BY
    r.team_abbrev, r.season, r.player_name, r.pfr_player_id, r.position,
    r.games, r.games_started, r.approx_value,
    tos.pass_att, tos.pass_yds, tos.pass_yds_rank,
    tos.sacks_taken, tos.sacks_taken_rank, tos.sack_pct,
    tos.rush_yds, tos.rush_ypc, tos.rush_ypc_rank, tos.rush_yds_rank,
    tos.pass_run_ratio
ORDER BY r.season, r.team_abbrev, r.games_started DESC;

-- ------------------------------------------------------------
-- OL game context: per-game team offense for games the player
-- started (requires game_starters data, ~1994+).
-- Joins starter position back to team_game_offense for that game.
-- ------------------------------------------------------------
CREATE VIEW v_ol_game_context AS
SELECT
    gs.game_id,
    gs.team_abbrev,
    gs.starter_position,
    gs.player_name,
    gs.pfr_player_id,
    g.season,
    g.game_date,
    g.week,
    g.home_team,
    g.away_team,
    CASE WHEN gs.team_abbrev = g.home_team THEN g.away_team ELSE g.home_team END AS opponent,
    tgo.pass_att,
    tgo.pass_yds,
    tgo.pass_td,
    tgo.sacks_taken,
    tgo.sack_yds_lost,
    tgo.rush_att,
    tgo.rush_yds,
    tgo.rush_td,
    tgo.rush_ypc,
    tgo.pass_run_ratio,
    -- Snap count for this player this game
    psc.off_snaps,
    psc.off_snap_pct
FROM game_starters gs
JOIN games g         ON gs.game_id = g.game_id
JOIN team_game_offense tgo
    ON tgo.game_id = gs.game_id
    AND tgo.offense_team = gs.team_abbrev
LEFT JOIN player_snap_counts psc
    ON psc.game_id = gs.game_id
    AND psc.team_abbrev = gs.team_abbrev
    AND psc.player_name = gs.player_name
WHERE gs.side = 'OFF'
  AND gs.starter_position IN ('LT', 'RT', 'LG', 'RG', 'C');

-- ------------------------------------------------------------
-- DL vs OL positional matchup inference (~1994+)
-- Standard NFL positional pairings:
--   RDE  <-> opposing LT    (most important pass rush matchup)
--   LDE  <-> opposing RT
--   3DT  <-> opposing RG    (3-technique, strong-side DT in 4-3)
--   NT   <-> opposing C     (nose tackle in 3-4 or 4-3 under)
--   UT   <-> opposing LG    (under tackle / 1-tech variant)
-- dl_pos: position the DL player started at this game
-- ol_pos: inferred opposing OL position
-- ol_player: who lined up across from them
-- ------------------------------------------------------------
CREATE VIEW v_dl_ol_matchup AS
SELECT
    dl.game_id,
    dl.team_abbrev                              AS dl_team,
    dl.starter_position                         AS dl_pos,
    dl.player_name                              AS dl_player,
    dl.pfr_player_id                            AS dl_player_id,
    -- inferred opposing OL position
    CASE dl.starter_position
        WHEN 'RDE'  THEN 'LT'
        WHEN 'LOLB' THEN 'LT'   -- 3-4 edge rusher from left maps to LT
        WHEN 'LDE'  THEN 'RT'
        WHEN 'ROLB' THEN 'RT'
        WHEN '3DT'  THEN 'RG'
        WHEN 'DT'   THEN 'RG'   -- assume 3-tech unless known NT
        WHEN 'NT'   THEN 'C'
        WHEN 'UT'   THEN 'LG'
        ELSE NULL
    END                                         AS inferred_ol_pos,
    ol.player_name                              AS ol_player,
    ol.pfr_player_id                            AS ol_player_id,
    ol.team_abbrev                              AS ol_team,
    g.season,
    g.game_date,
    g.week
FROM game_starters dl
JOIN games g ON dl.game_id = g.game_id
JOIN game_starters ol
    ON ol.game_id = dl.game_id
    AND ol.team_abbrev != dl.team_abbrev
    AND ol.side = 'OFF'
    AND ol.starter_position = CASE dl.starter_position
        WHEN 'RDE'  THEN 'LT'
        WHEN 'LOLB' THEN 'LT'
        WHEN 'LDE'  THEN 'RT'
        WHEN 'ROLB' THEN 'RT'
        WHEN '3DT'  THEN 'RG'
        WHEN 'DT'   THEN 'RG'
        WHEN 'NT'   THEN 'C'
        WHEN 'UT'   THEN 'LG'
        ELSE '??'
    END
WHERE dl.side = 'DEF'
  AND dl.starter_position IN ('RDE', 'LDE', 'DT', '3DT', 'NT', 'UT', 'LOLB', 'ROLB');

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
