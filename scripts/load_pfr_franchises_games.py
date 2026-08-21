"""Loads franchises, franchise_aliases, games, and team_game_stats into the
football_db warehouse from PFR's scraped boxscore data (~/data/pfref/).

Franchise identity and season-by-season naming come from
~/data/pfref/franchise_abbrev_map.csv (all known PFR abbreviations -> stable
franchise) and ~/data/pfref/franchise_year_abbrev.csv (team name/abbrev per
season). Games and team_game_stats come from each game's boxscore folder under
~/data/pfref/raw/boxscores/{season}/{game_id}/.

Scope is 1967-present ("Super Bowl Era") -- gamebooks (the source of truth for
individual tackle attribution) don't meaningfully exist before 1967, so earlier
seasons aren't loaded even though PFR has box scores back to 1950.

Run: .venv/bin/python scripts/load_pfr_franchises_games.py
"""
import csv
import os
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

PFREF_DIR = Path.home() / "data" / "pfref"
BOXSCORES_DIR = PFREF_DIR / "raw" / "boxscores"
DB_NAME = "football"
MIN_SEASON = 1967  # Super Bowl Era -- earlier seasons predate usable gamebook coverage


def connect():
    conn = psycopg2.connect(dbname=DB_NAME)
    # No role/database-level default points at gold/silver/internal (confirmed via
    # `SHOW search_path` -- default is just "$user", public), so every statement
    # below that references an unqualified table name (games, franchises, etc.)
    # needs this set explicitly per-session, same as football_db's own lookup
    # scripts and the WAE notebook's football_db query cell.
    with conn.cursor() as cur:
        cur.execute("SET search_path TO gold, silver, internal, public")
    conn.commit()
    return conn


def load_franchises(conn):
    """Populate franchises + franchise_aliases from the PFR reference CSVs.

    Guarded: this INSERTs unconditionally (no ON CONFLICT), so re-running the
    script to backfill game_type/week/round (the actual reason for a re-run --
    see classify_season_games()) must not re-run this step, or every franchise
    and alias row would be duplicated. games/team_game_stats already reference
    the existing franchise_ids, so skip straight to using them if present.
    """
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM franchises")
    if cur.fetchone()[0] > 0:
        print("franchises already populated -- skipping load_franchises()")
        return {}, {}

    abbrev_map_path = PFREF_DIR / "franchise_abbrev_map.csv"
    year_abbrev_path = PFREF_DIR / "franchise_year_abbrev.csv"

    # franchise_key -> {canonical_name, nfl_code}
    franchise_info = {}
    # any pfr_abbrev (historical or current) -> franchise_key
    abbrev_to_key = {}
    with open(abbrev_map_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = row["franchise_key"]
            franchise_info[key] = {
                "canonical_name": row["canonical_name"],
                "nfl_code": row["nfl_code"].lower(),
            }
            abbrev_to_key[row["pfr_abbrev"].lower()] = key

    # franchise_key -> list of (year, team_name, abbrev), sorted by year
    year_rows = defaultdict(list)
    with open(year_abbrev_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            abbrev = row["abbrev"].lower()
            key = abbrev_to_key.get(abbrev)
            if key is None:
                # fall back to matching on current_franchise_slug via nfl_code guess
                continue
            year_rows[key].append((int(row["year"]), row["team_name"], abbrev))

    cur = conn.cursor()
    key_to_franchise_id = {}
    for key, info in sorted(franchise_info.items()):
        cur.execute(
            """
            INSERT INTO franchises (current_city, current_team_name, current_abbreviation)
            VALUES (%s, %s, %s)
            RETURNING franchise_id
            """,
            (
                info["canonical_name"].rsplit(" ", 1)[0],
                info["canonical_name"],
                info["nfl_code"],
            ),
        )
        key_to_franchise_id[key] = cur.fetchone()[0]
    conn.commit()
    print(f"Inserted {len(key_to_franchise_id)} franchises")

    alias_rows = []
    for key, franchise_id in key_to_franchise_id.items():
        rows = sorted(year_rows.get(key, []))
        if not rows:
            continue
        # collapse consecutive years with the same (team_name, abbrev) into one
        # alias era; only add a new row when the name/abbrev actually changes
        era_start_year, era_name, era_abbrev = rows[0]
        prev_year = era_start_year
        for year, name, abbrev in rows[1:]:
            if (name, abbrev) != (era_name, era_abbrev):
                alias_rows.append((franchise_id, era_name, True, era_start_year, prev_year))
                alias_rows.append((franchise_id, era_abbrev, True, era_start_year, prev_year))
                era_start_year, era_name, era_abbrev = year, name, abbrev
            prev_year = year
        # final open-ended era (season_end = NULL = still current)
        alias_rows.append((franchise_id, era_name, True, era_start_year, None))
        alias_rows.append((franchise_id, era_abbrev, True, era_start_year, None))

    execute_values(
        cur,
        """
        INSERT INTO franchise_aliases (franchise_id, alias_text, is_primary, season_start, season_end)
        VALUES %s
        """,
        alias_rows,
    )
    conn.commit()
    print(f"Inserted {len(alias_rows)} franchise_aliases rows")

    return key_to_franchise_id, abbrev_to_key


def build_abbrev_resolver(conn):
    """Returns a function (abbrev, season) -> franchise_id using franchise_aliases."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT lower(alias_text), franchise_id, season_start, season_end
        FROM franchise_aliases
        """
    )
    rows = cur.fetchall()
    by_alias = defaultdict(list)
    for alias_text, franchise_id, season_start, season_end in rows:
        by_alias[alias_text].append((season_start, season_end, franchise_id))

    def resolve(abbrev, season):
        candidates = by_alias.get(abbrev.lower(), [])
        for season_start, season_end, franchise_id in candidates:
            if (season_start is None or season_start <= season) and (
                season_end is None or season_end >= season
            ):
                return franchise_id
        return None

    return resolve


RUSH_RE = re.compile(r"^(\d+)-(-?\d+)-(\d+)$")
PASS_RE = re.compile(r"^(\d+)-(\d+)-(-?\d+)-(\d+)-(\d+)$")
SACK_RE = re.compile(r"^(\d+)-(-?\d+)$")
FUMBLE_RE = re.compile(r"^(\d+)-(\d+)$")
PENALTY_RE = re.compile(r"^(\d+)-(-?\d+)$")
CONV_RE = re.compile(r"^(\d+)-(\d+)$")


def parse_time_of_possession(val):
    if not val or ":" not in val:
        return None
    m, s = val.split(":")
    return int(m) * 60 + int(s)


def parse_team_stats_row(stat_name, value):
    """Returns a dict of column updates for one stat_name/value pair."""
    if value is None or value == "":
        return {}
    if stat_name == "First Downs":
        return {"first_downs": int(value)}
    if stat_name == "Rush-Yds-TDs":
        m = RUSH_RE.match(value)
        if m:
            return {"rush_attempts": int(m[1]), "rush_yards": int(m[2]), "rush_tds": int(m[3])}
    if stat_name == "Cmp-Att-Yd-TD-INT":
        m = PASS_RE.match(value)
        if m:
            return {
                "pass_completions": int(m[1]),
                "pass_attempts": int(m[2]),
                "pass_yards": int(m[3]),
                "pass_tds": int(m[4]),
                "pass_ints": int(m[5]),
            }
    if stat_name == "Sacked-Yards":
        m = SACK_RE.match(value)
        if m:
            return {"times_sacked": int(m[1]), "sack_yards_lost": int(m[2])}
    if stat_name == "Net Pass Yards":
        return {"net_pass_yards": int(value)}
    if stat_name == "Total Yards":
        return {"total_yards": int(value)}
    if stat_name == "Fumbles-Lost":
        m = FUMBLE_RE.match(value)
        if m:
            return {"fumbles": int(m[1]), "fumbles_lost": int(m[2])}
    if stat_name == "Turnovers":
        return {"turnovers": int(value)}
    if stat_name == "Penalties-Yards":
        m = PENALTY_RE.match(value)
        if m:
            return {"penalties": int(m[1]), "penalty_yards": int(m[2])}
    if stat_name == "Third Down Conv.":
        m = CONV_RE.match(value)
        if m:
            return {"third_down_conv": int(m[1]), "third_down_att": int(m[2])}
    if stat_name == "Fourth Down Conv.":
        m = CONV_RE.match(value)
        if m:
            return {"fourth_down_conv": int(m[1]), "fourth_down_att": int(m[2])}
    if stat_name == "Time of Possession":
        return {"time_of_possession_sec": parse_time_of_possession(value)}
    return {}


# Historically-known regular-season game counts per team. No local raw source
# (game_info.csv, team_stats.csv, pbp.csv, scoring.csv, starters.csv) carries an
# explicit week/round/game_type field -- checked directly, none of PFR's scraped
# per-game CSVs under ~/data/pfref/raw/boxscores/ have one. This mirrors the
# known-working fallback already used by gamebooks_boxscores/parse_pfr_pbp.py's
# label_game_types_for_year(): sort each franchise's games chronologically and
# cut at the known regular-season game count for that season/era.
REGULAR_SEASON_GAMES = {1982: 9, 1987: 15}


def regular_season_games(season):
    if season in REGULAR_SEASON_GAMES:
        return REGULAR_SEASON_GAMES[season]
    if season < 1978:
        return 14  # 1967-1977 (post-merger scheduling through the last 14-game season)
    if season >= 2021:
        return 17
    return 16  # 1978-2020 (minus the two strike-year exceptions above)


def classify_season_games(season, season_dir, resolve_franchise):
    """Returns {game_id_str: {'game_type', 'week', 'round'}} for every game in one
    season's boxscore directory.

    game_type/round come from date-sorting (see REGULAR_SEASON_GAMES above) --
    the only reliable signal available locally. week is NOT simply "the team's
    Nth game" (that undercounts once bye weeks appear, 1990+) -- it's a calendar
    bucket: the season's earliest regular-season game date anchors week 1, and
    every other regular-season game is bucketed by whole weeks elapsed since
    then. This survives byes because a bye just leaves a bucket empty for that
    team, it doesn't shift anything.

    round is assigned backward from the end of the season: the last cluster of
    playoff dates (games within ~4 days of each other) is always the Super Bowl,
    the previous cluster the Conference Championship, then Divisional, then Wild
    Card -- true regardless of how many rounds existed that era (2 rounds in the
    pre-1970 merger seasons, up to 4 rounds in the modern era), since the games
    that decide who plays in the Super Bowl are always the second-to-last date
    cluster, etc.
    """
    games_by_fid = defaultdict(list)  # fid -> [(date, game_id_str)]
    game_dates = {}  # game_id_str -> date

    for game_dir in sorted(season_dir.iterdir()):
        game_id_str = game_dir.name
        m = re.match(r"^(\d{4})(\d{2})(\d{2})", game_id_str)
        if not m:
            continue
        game_date = date(int(m[1]), int(m[2]), int(m[3]))

        team_stats_path = game_dir / "team_stats.csv"
        if not team_stats_path.exists():
            continue
        with open(team_stats_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            continue
        home_fid = resolve_franchise(rows[0]["home_abbrev"], season)
        away_fid = resolve_franchise(rows[0]["vis_abbrev"], season)
        if home_fid is None or away_fid is None:
            continue

        games_by_fid[home_fid].append((game_date, game_id_str))
        games_by_fid[away_fid].append((game_date, game_id_str))
        game_dates[game_id_str] = game_date

    n_reg = regular_season_games(season)
    game_type = {}
    for fid, glist in games_by_fid.items():
        glist.sort()
        for i, (d, gid) in enumerate(glist):
            label = "regular" if i < n_reg else "playoff"
            if game_type.get(gid) == "playoff":
                continue  # already flagged playoff by the other side
            if label == "playoff":
                game_type[gid] = "playoff"
            else:
                game_type.setdefault(gid, "regular")

    week = {}
    reg_dates = sorted(d for gid, d in game_dates.items() if game_type.get(gid) == "regular")
    if reg_dates:
        anchor = reg_dates[0]
        # Rank by distinct 7-day bucket *that has at least one game somewhere in the
        # league*, not raw elapsed weeks. A single team's bye leaves its own bucket
        # empty but other teams still play that week, so it stays a distinct rank --
        # byes are preserved correctly. A league-wide stoppage (the 1982 strike:
        # weeks 3-10 canceled entirely, nobody played) leaves buckets with zero games
        # league-wide, which get skipped rather than inflating week numbers past what
        # the league's own post-strike schedule (weeks 1-9) actually used.
        buckets_with_games = sorted({(d - anchor).days // 7 for d in reg_dates})
        bucket_rank = {b: i + 1 for i, b in enumerate(buckets_with_games)}
        for gid, d in game_dates.items():
            if game_type.get(gid) == "regular":
                week[gid] = bucket_rank[(d - anchor).days // 7]

    round_of = {}
    playoff_dates = sorted({d for gid, d in game_dates.items() if game_type.get(gid) == "playoff"})
    if playoff_dates:
        clusters = [[playoff_dates[0]]]
        for d in playoff_dates[1:]:
            if (d - clusters[-1][-1]).days > 4:
                clusters.append([d])
            else:
                clusters[-1].append(d)
        labels_from_end = ["sb", "conf", "div", "wc"]
        cluster_label = {}
        for idx, cluster in enumerate(reversed(clusters)):
            label = labels_from_end[idx] if idx < len(labels_from_end) else "wc"
            for d in cluster:
                cluster_label[d] = label
        for gid, d in game_dates.items():
            if game_type.get(gid) == "playoff":
                round_of[gid] = cluster_label[d]

    return {
        gid: {
            "game_type": game_type.get(gid, "regular"),
            "week": week.get(gid),
            "round": round_of.get(gid),
        }
        for gid in game_dates
    }


def load_games_and_team_stats(conn, resolve_franchise):
    cur = conn.cursor()
    games_inserted = 0
    games_skipped = 0
    team_stats_inserted = 0
    seasons = sorted(os.listdir(BOXSCORES_DIR))

    for season_str in seasons:
        season_dir = BOXSCORES_DIR / season_str
        if not season_dir.is_dir():
            continue
        try:
            season = int(season_str)
        except ValueError:
            continue
        if season < MIN_SEASON:
            continue

        season_classification = classify_season_games(season, season_dir, resolve_franchise)

        for game_dir in sorted(season_dir.iterdir()):
            game_id_str = game_dir.name
            date_match = re.match(r"^(\d{8})", game_id_str)
            if not date_match:
                games_skipped += 1
                continue
            date_raw = date_match.group(1)
            game_date = f"{date_raw[0:4]}-{date_raw[4:6]}-{date_raw[6:8]}"

            team_stats_path = game_dir / "team_stats.csv"
            scoring_path = game_dir / "scoring.csv"
            if not team_stats_path.exists():
                games_skipped += 1
                continue

            with open(team_stats_path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                games_skipped += 1
                continue
            home_abbrev = rows[0]["home_abbrev"]
            vis_abbrev = rows[0]["vis_abbrev"]

            home_fid = resolve_franchise(home_abbrev, season)
            away_fid = resolve_franchise(vis_abbrev, season)
            if home_fid is None or away_fid is None:
                games_skipped += 1
                continue

            home_score = away_score = None
            if scoring_path.exists():
                with open(scoring_path, newline="", encoding="utf-8") as f:
                    srows = list(csv.DictReader(f))
                if srows:
                    home_score = int(srows[-1]["home_team_score"])
                    away_score = int(srows[-1]["vis_team_score"])

            # game_type/week/round: see classify_season_games() above. Was previously
            # `"playoff" if not re.search(r"wk\d", game_id_str) else "regular"` -- PFR's
            # raw boxscore-folder game_id (e.g. "199509030atl") never contains "wk\d" at
            # all, so that regex never matched and every single row silently fell through
            # to "playoff" with week left NULL. Confirmed against the live DB: 14,016/14,016
            # rows were game_type='playoff', 0 had a non-null week.
            classification = season_classification.get(game_id_str, {})
            game_type = classification.get("game_type", "regular")
            week = classification.get("week")
            round_ = classification.get("round")
            # External id (game_id_str) never lives on games itself -- looked up/
            # recorded via internal.game_xref only, same as internal.player_xref.
            cur.execute(
                "SELECT game_id FROM internal.game_xref WHERE source_system='pfr' AND source_game_id=%s",
                (game_id_str,),
            )
            xref_row = cur.fetchone()
            if xref_row:
                game_id = xref_row[0]
                cur.execute(
                    """
                    UPDATE games SET home_score=%s, away_score=%s, game_type=%s, week=%s, round=%s
                    WHERE game_id=%s
                    """,
                    (home_score, away_score, game_type, week, round_, game_id),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO games (season, game_date, home_franchise_id,
                                        away_franchise_id, home_score, away_score,
                                        game_type, week, round)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING game_id
                    """,
                    (season, game_date, home_fid, away_fid, home_score, away_score,
                     game_type, week, round_),
                )
                game_id = cur.fetchone()[0]
                cur.execute(
                    """
                    INSERT INTO internal.game_xref (game_id, source_system, source_game_id, match_confidence)
                    VALUES (%s, 'pfr', %s, 'confirmed')
                    """,
                    (game_id, game_id_str),
                )
            games_inserted += 1

            team_updates = {home_fid: {}, away_fid: {}}
            for row in rows:
                stat_name = row["stat_name"]
                home_updates = parse_team_stats_row(stat_name, row["home_value"])
                vis_updates = parse_team_stats_row(stat_name, row["vis_value"])
                team_updates[home_fid].update(home_updates)
                team_updates[away_fid].update(vis_updates)

            for franchise_id, cols in team_updates.items():
                if not cols:
                    continue
                col_names = list(cols.keys())
                col_values = [cols[c] for c in col_names]
                placeholders = ", ".join(col_names)
                value_placeholders = ", ".join(["%s"] * len(col_names))
                update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in col_names)
                cur.execute(
                    f"""
                    INSERT INTO team_game_stats (game_id, franchise_id, {placeholders})
                    VALUES (%s, %s, {value_placeholders})
                    ON CONFLICT (game_id, franchise_id) DO UPDATE SET {update_clause}
                    """,
                    [game_id, franchise_id] + col_values,
                )
                team_stats_inserted += 1

            if games_inserted % 1000 == 0:
                conn.commit()
                print(f"...{games_inserted} games loaded ({season_str} in progress)")

    conn.commit()
    print(f"Games inserted: {games_inserted}, skipped: {games_skipped}")
    print(f"Team-game-stat rows inserted: {team_stats_inserted}")


def main():
    conn = connect()
    load_franchises(conn)
    resolve_franchise = build_abbrev_resolver(conn)
    load_games_and_team_stats(conn, resolve_franchise)
    conn.close()


if __name__ == "__main__":
    main()
