"""
Shared parser utilities for PFR boxscore table extraction.

All parsers receive a BeautifulSoup object for a fully comment-stripped page
(i.e. the caller has already run html.replace('<!--','').replace('-->',''))
plus the game metadata: game_id, season, home_abbrev, vis_abbrev.

Column naming strategy
-----------------------
We always use `data-stat` attribute values as column names, never visible
header text.  This keeps column names stable across seasons even though PFR
changes displayed text (e.g. 'MIN' vs 'SEA' in scoring/pbp score columns).

Columns whose data-stat starts with 'header_' are group-label cells in
double-decker headers — they are skipped.

Every output DataFrame gets four leading metadata columns:
    game_id, season, home_abbrev, vis_abbrev
Player rows also get a pfr_player_id column (href from the player link).
"""

from __future__ import annotations

import re
import pandas as pd
from bs4 import BeautifulSoup, Tag


# ---------------------------------------------------------------------------
# Table location
# ---------------------------------------------------------------------------

def find_table(soup: BeautifulSoup, table_id: str) -> Tag | None:
    """Return the first <table id=table_id> found anywhere in soup."""
    return soup.find("table", {"id": table_id})


# ---------------------------------------------------------------------------
# Standard row tables  (single-header and double-decker)
# ---------------------------------------------------------------------------

def _thead_stats(table: Tag) -> list[str]:
    """
    Return ordered data-stat values from thead, skipping header_* group cells.
    For double-decker tables the meaningful stats are on the last thead row.
    """
    thead = table.find("thead")
    if not thead:
        return []
    stats: list[str] = []
    seen: set[str] = set()
    # Iterate all th/td in thead; last occurrence of a data-stat wins
    # (handles double-decker where the same stat may appear in both rows)
    for th in thead.find_all(["th", "td"]):
        ds = th.get("data-stat", "").strip()
        if not ds or ds.startswith("header_") or ds == "onecell":
            continue
        if ds not in seen:
            stats.append(ds)
            seen.add(ds)
    return stats


def parse_standard_table(
    table: Tag,
    game_id: str,
    season: int,
    home_abbrev: str,
    vis_abbrev: str,
    team_side: str | None = None,   # 'home' | 'vis' | None (for split tables)
) -> pd.DataFrame | None:
    """
    Parse a standard PFR stat table (single or double-decker header).

    Returns a DataFrame or None if the table has no data rows.
    Adds: game_id, season, home_abbrev, vis_abbrev, [team_side].
    Extracts pfr_player_id from player cell <a> href where present.
    """
    col_stats = _thead_stats(table)
    if not col_stats:
        return None

    rows: list[dict] = []
    tbody = table.find("tbody")
    if not tbody:
        return None

    for tr in tbody.find_all("tr"):
        cls = " ".join(tr.get("class", []))
        if "thead" in cls:
            continue
        if "divider" in cls:
            # PFR uses 'divider' on data rows to draw section borders (e.g., first
            # defensive starter in starters table). Only skip genuinely empty rows.
            if not any(td.get_text(strip=True) for td in tr.find_all(["th", "td"])):
                continue

        cells = {td.get("data-stat", ""): td for td in tr.find_all(["th", "td"])}
        if not any(cells):
            continue

        row: dict = {}
        has_data = False

        for ds in col_stats:
            td = cells.get(ds)
            if td is None:
                row[ds] = None
                continue
            val = td.get_text(" ", strip=True)
            row[ds] = val if val else None
            if val:
                has_data = True

            # Pull player link href for player cells
            if ds == "player":
                a = td.find("a", href=True)
                row["pfr_player_id"] = a["href"].strip() if a else None

        if not has_data:
            continue

        rows.append(row)

    if not rows:
        return None

    df = pd.DataFrame(rows)

    # Prepend metadata columns
    df.insert(0, "game_id", game_id)
    df.insert(1, "season", season)
    df.insert(2, "home_abbrev", home_abbrev)
    df.insert(3, "vis_abbrev", vis_abbrev)
    if team_side is not None:
        df.insert(4, "team_side", team_side)

    return df


# ---------------------------------------------------------------------------
# Key-value tables  (game_info, officials, team_stats)
# ---------------------------------------------------------------------------

def _to_snake(text: str) -> str:
    """'Won Toss' → 'won_toss', 'Over/Under' → 'over_under'"""
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def parse_key_value_table(
    table: Tag,
    game_id: str,
    season: int,
    home_abbrev: str,
    vis_abbrev: str,
) -> pd.DataFrame | None:
    """
    Parse a PFR key-value table (game_info, officials) into a single-row DataFrame.
    Keys are snake_cased; values are raw strings.
    """
    record: dict = {
        "game_id": game_id,
        "season": season,
        "home_abbrev": home_abbrev,
        "vis_abbrev": vis_abbrev,
    }

    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        texts = [c.get_text(" ", strip=True) for c in cells]
        if len(texts) >= 2 and texts[0]:
            key = _to_snake(texts[0])
            val = texts[1].strip()
            if key and key not in ("game_info", "officials"):
                record[key] = val if val else None

    if len(record) <= 4:   # only metadata, no actual data
        return None

    return pd.DataFrame([record])


# ---------------------------------------------------------------------------
# Weather parsing  (applied to game_info 'weather' field post-extraction)
# ---------------------------------------------------------------------------

_TEMP_RE     = re.compile(r"(\d+)\s*degree",  re.I)
_HUMID_RE    = re.compile(r"humidity\s+(\d+)%", re.I)
_WIND_RE     = re.compile(r"wind\s+(\d+)\s*mph", re.I)
_NO_WIND_RE  = re.compile(r"no wind",          re.I)
_INDOOR_RE   = re.compile(r"(indoor|retractable|dome|controlled)",  re.I)
_PRECIP_RE   = re.compile(r"(rain|snow|sleet|fog|drizzle|flurries)", re.I)


def parse_weather(raw: str | None) -> dict:
    """
    Decompose a raw weather string into structured fields.
    Returns dict with keys: weather_raw, temp_f, humidity_pct, wind_mph,
                            is_indoor, precip_type.
    """
    out: dict = {
        "weather_raw":   raw,
        "temp_f":        None,
        "humidity_pct":  None,
        "wind_mph":      None,
        "is_indoor":     False,
        "precip_type":   None,
    }
    if not raw:
        return out

    if _INDOOR_RE.search(raw):
        out["is_indoor"] = True

    m = _TEMP_RE.search(raw)
    if m:
        out["temp_f"] = int(m.group(1))

    m = _HUMID_RE.search(raw)
    if m:
        out["humidity_pct"] = int(m.group(1))

    if _NO_WIND_RE.search(raw):
        out["wind_mph"] = 0
    else:
        m = _WIND_RE.search(raw)
        if m:
            out["wind_mph"] = int(m.group(1))

    m = _PRECIP_RE.search(raw)
    if m:
        out["precip_type"] = m.group(1).lower()

    return out


# ---------------------------------------------------------------------------
# Dedup helper  (PFR renders each table twice: live DOM + stripped comment)
# ---------------------------------------------------------------------------

def first_table(soup: BeautifulSoup, table_id: str) -> Tag | None:
    """Return the first occurrence of a table by id (avoids duplicates)."""
    return soup.find("table", {"id": table_id})
