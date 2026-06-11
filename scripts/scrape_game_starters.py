#!/usr/bin/env python3
"""
Scraper: PFR boxscore pages → game_starters + player_snap_counts + play_by_play_sacks.

For each game, fetches:
  https://www.pro-football-reference.com/boxscores/{game_id}.htm

Parses:
  - Starters section (both teams): Player, specific position (LT, RDE, etc.)
    Coverage: PFR has starters back to ~1950 for most games
  - Snap counts section (both teams): off/def/ST snaps + pct
    Coverage: 2012+ (earlier games have no snap count data)
  - Play-by-play sacks: individual defender → QB attribution
    Coverage: 1978+ (PBP with named players first appears that season)
    Note: sacks appear in boxscore *team* stats from 1960;
          sacks appear in boxscore *individual* defense stats from 1982.

Both starters/snaps tables appear as HTML comments on PFR pages; we strip
comments before parsing so standard BeautifulSoup lookups work.

Team abbreviation extraction: parsed from scorebox team links (/teams/{abbrev}/).
Position side (OFF/DEF): derived from position string, with section-header
fallback if PFR includes a dividing row.

Usage:
  python scripts/scrape_game_starters.py --season 2012
  python scripts/scrape_game_starters.py --season 2012 --game 201211110min
  python scripts/scrape_game_starters.py --seasons 1978-2012
  python scripts/scrape_game_starters.py --seasons 1950-2025    # full history
  python scripts/scrape_game_starters.py --season 2012 --force  # re-scrape
"""

import argparse
import csv
import random
import re
import sys
import time
from pathlib import Path

from bs4 import BeautifulSoup, Comment

sys.path.insert(0, str(Path(__file__).parent))
from db import get_engine
from sqlalchemy import text

PFREF_DATA  = Path("/Users/devos/data/pfref")
BOX_DIR     = PFREF_DATA / "boxscores"
BASE_URL    = "https://www.pro-football-reference.com"

# ── Brave-based scraper (Cloudflare bypass via real browser) ──────────────────

class BraveScraper:
    """
    Playwright + Brave Browser scraper. Passes Cloudflare's Managed Challenge
    natively because it uses the real Brave executable (real TLS fingerprint,
    real JS engine). Profile is persisted so the cf_clearance cookie survives
    across runs — only needs to solve the challenge once.

    Drop-in interface for PFRefScraper: fetch(url, strip_comments) + _sleep().
    """

    _BRAVE_EXE   = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
    _PROFILE_DIR = str(Path(__file__).parent.parent / ".brave_scraper_profile")

    def __init__(self, sleep_min: float = 5.0, sleep_max: float = 9.0):
        self.sleep_min = sleep_min
        self.sleep_max = sleep_max
        self._pw   = None
        self._ctx  = None
        self._page = None

    def _start(self):
        from playwright.sync_api import sync_playwright
        profile = Path(self._PROFILE_DIR)
        profile.mkdir(exist_ok=True)
        self._pw  = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            executable_path=self._BRAVE_EXE,
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-extensions",
            ],
        )
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        print(f"  [BraveScraper] browser started, profile: {self._PROFILE_DIR}")

    def fetch(self, url: str, strip_comments: bool = False) -> BeautifulSoup:
        if self._page is None:
            self._start()

        try:
            self._page.goto(url, wait_until="networkidle", timeout=40_000)
        except Exception:
            # Timeout on networkidle is common for heavy pages; fall back to
            # domcontentloaded + brief pause which is enough for static tables
            self._page.goto(url, wait_until="domcontentloaded", timeout=40_000)
            time.sleep(2)

        title = self._page.title()
        if "just a moment" in title.lower():
            raise PermissionError(
                f"Cloudflare challenge stuck at {url}. "
                "Close all Brave windows, re-run — the fresh profile will solve it."
            )

        html = self._page.content()
        if strip_comments:
            html = html.replace("<!--", "").replace("-->", "")
        return BeautifulSoup(html, "html.parser")

    def _sleep(self):
        time.sleep(random.uniform(self.sleep_min, self.sleep_max))

    def close(self):
        try:
            if self._ctx:
                self._ctx.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

# ── position classification ────────────────────────────────────────────────────

_OFF_POSITIONS = {
    # Modern OL
    "LT", "RT", "LG", "RG", "C", "OT", "OG", "OC", "OL",
    # Historical OL (pre-1980s)
    "T", "G",
    # Skill positions
    "QB", "RB", "HB", "WB", "TB", "FB", "B",
    "WR", "FL", "SE", "E", "OE",
    "TE",
}

_DEF_POSITIONS = {
    "LDE", "RDE", "DE", "DT", "3DT", "NT", "UT",
    "LB", "ILB", "OLB", "MLB", "WLB", "SLB",
    "LOLB", "ROLB", "LILB", "RILB",
    "CB", "LCB", "RCB", "NCB",
    "SS", "FS", "S", "DB",
}

# Special teams and coach rows — skip entirely
_SKIP_POSITIONS = {"K", "P", "LS", "KR", "PR", "HC", ""}

# PFR PBP sack format: "{QB}sacked by{Defender(s)}for {N} yards"
# Adjacent player hyperlinks produce no spaces in get_text() output.
_SACK_BY_RE = re.compile(r'sacked\s*by', re.IGNORECASE)
_SACK_YDS_RE = re.compile(r'for\s*-?\s*(\d+)\s+yard', re.IGNORECASE)


def classify_side(position: str) -> str | None:
    """Return 'OFF', 'DEF', or None (skip) for a given position string."""
    p = position.upper().strip()
    if p in _SKIP_POSITIONS:
        return None
    if p in _OFF_POSITIONS:
        return "OFF"
    if p in _DEF_POSITIONS:
        return "DEF"
    return "DEF"  # unknown positions are usually defensive variants


# ── HTML comment extraction ────────────────────────────────────────────────────

def _find_table_in_comments(soup: BeautifulSoup, table_id: str):
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if table_id not in comment:
            continue
        inner = BeautifulSoup(comment, "html.parser")
        tbl = inner.find("table", {"id": table_id})
        if tbl:
            return tbl
    return None


def _find_table(soup: BeautifulSoup, table_id: str):
    tbl = soup.find("table", {"id": table_id})
    if tbl:
        return tbl
    return _find_table_in_comments(soup, table_id)


# ── team abbrev extraction from scorebox ──────────────────────────────────────

def extract_team_abbrevs(soup: BeautifulSoup) -> tuple[str, str]:
    """Return (vis_abbrev, home_abbrev) from scorebox /teams/{abbrev}/ links."""
    scorebox = soup.find("div", class_="scorebox")
    if not scorebox:
        return "", ""
    abbrevs = []
    for a in scorebox.find_all("a", href=True):
        m = re.search(r"/teams/([a-z]{2,4})/\d{4}", a["href"])
        if m:
            abbrev = m.group(1)
            if abbrev not in abbrevs:
                abbrevs.append(abbrev)
        if len(abbrevs) == 2:
            break
    return (abbrevs[0], abbrevs[1]) if len(abbrevs) == 2 else ("", "")


# ── starters table parser ─────────────────────────────────────────────────────

def parse_starters_table(table) -> list[dict]:
    """
    Parse a PFR starters table (home_starters or vis_starters).
    Returns list of {player_name, pfr_player_id, pfr_short_id, starter_position, side}.
    Handles both modern (LT/RDE) and historical (T/G/E/B) position labels.
    """
    rows = []
    current_side = None

    tbody = table.find("tbody")
    if not tbody:
        return rows

    for tr in tbody.find_all("tr"):
        cls = " ".join(tr.get("class", []))

        if "thead" in cls:
            header_text = tr.get_text(strip=True).upper()
            if "OFFENSE" in header_text:
                current_side = "OFF"
            elif "DEFENSE" in header_text:
                current_side = "DEF"
            continue

        cells = tr.find_all(["th", "td"])
        if len(cells) < 2:
            continue

        player_cell  = cells[0]
        pos_cell     = cells[1]
        player_name  = player_cell.get_text(strip=True)
        position_str = pos_cell.get_text(strip=True)

        if not player_name or not position_str:
            continue

        pfr_player_id = ""
        pfr_short_id  = ""
        a_tag = player_cell.find("a", href=True)
        if a_tag and "/players/" in a_tag["href"]:
            pfr_player_id = a_tag["href"].strip()
            m = re.search(r"/players/[A-Z]/([A-Za-z0-9]+)\.htm", pfr_player_id)
            if m:
                pfr_short_id = m.group(1)

        side = current_side or classify_side(position_str)
        if side is None:
            continue

        rows.append({
            "player_name":      player_name,
            "pfr_player_id":    pfr_player_id or None,
            "pfr_short_id":     pfr_short_id or None,
            "starter_position": position_str.upper(),
            "side":             side,
        })

    return rows


# ── snap counts table parser ──────────────────────────────────────────────────

def parse_snap_counts_table(table) -> list[dict]:
    """
    Parse a PFR snap counts table (home_snap_counts or vis_snap_counts).
    Returns list of {player_name, pfr_player_id, pfr_short_id, position,
                     off_snaps, off_snap_pct, def_snaps, def_snap_pct,
                     st_snaps, st_snap_pct}.
    """
    rows = []

    thead = table.find("thead")
    headers = []
    if thead:
        header_cells = thead.find_all(["th", "td"])
        headers = [c.get_text(strip=True).lower() for c in header_cells]

    def _col_idx(names: list[str]) -> int | None:
        for name in names:
            for i, h in enumerate(headers):
                if name in h:
                    return i
        return None

    OFF_NUM_IDX = _col_idx(["off"]) or 2
    COL_OFF_NUM = OFF_NUM_IDX
    COL_OFF_PCT = COL_OFF_NUM + 1
    COL_DEF_NUM = COL_OFF_NUM + 2
    COL_DEF_PCT = COL_OFF_NUM + 3
    COL_ST_NUM  = COL_OFF_NUM + 4
    COL_ST_PCT  = COL_OFF_NUM + 5

    def _int(val: str) -> int | None:
        try:
            return int(val.strip()) if val.strip() else None
        except ValueError:
            return None

    def _pct(val: str) -> float | None:
        try:
            return float(val.strip().rstrip("%")) if val.strip() else None
        except ValueError:
            return None

    tbody = table.find("tbody")
    if not tbody:
        return rows

    for tr in tbody.find_all("tr"):
        cls = " ".join(tr.get("class", []))
        if "thead" in cls:
            continue

        cells = tr.find_all(["th", "td"])
        if len(cells) < 4:
            continue

        player_cell  = cells[0]
        pos_cell     = cells[1] if len(cells) > 1 else None
        player_name  = player_cell.get_text(strip=True)
        position_str = pos_cell.get_text(strip=True) if pos_cell else ""

        if not player_name:
            continue

        pfr_player_id = ""
        pfr_short_id  = ""
        a_tag = player_cell.find("a", href=True)
        if a_tag and "/players/" in a_tag["href"]:
            pfr_player_id = a_tag["href"].strip()
            m = re.search(r"/players/[A-Z]/([A-Za-z0-9]+)\.htm", pfr_player_id)
            if m:
                pfr_short_id = m.group(1)

        def _cell(idx: int) -> str:
            return cells[idx].get_text(strip=True) if idx < len(cells) else ""

        rows.append({
            "player_name":   player_name,
            "pfr_player_id": pfr_player_id or None,
            "pfr_short_id":  pfr_short_id or None,
            "position":      position_str,
            "off_snaps":     _int(_cell(COL_OFF_NUM)),
            "off_snap_pct":  _pct(_cell(COL_OFF_PCT)),
            "def_snaps":     _int(_cell(COL_DEF_NUM)),
            "def_snap_pct":  _pct(_cell(COL_DEF_PCT)),
            "st_snaps":      _int(_cell(COL_ST_NUM)),
            "st_snap_pct":   _pct(_cell(COL_ST_PCT)),
        })

    return rows


# ── play-by-play sack parser ──────────────────────────────────────────────────

def parse_pbp_sacks(soup: BeautifulSoup, vis_abbrev: str, home_abbrev: str,
                    game_id: str, season: int) -> list[dict]:
    """
    Extract individual sack events from the PFR play-by-play table.

    Data availability:
      1978+  — individual defenders named in PBP sack descriptions
      1960–  — sacks appear in boxscore QB stats (not here, see team_game_offense)
      1982+  — individual defensive sack totals in boxscore defense section

    For shared sacks ("X and Y sacked QB for N yards"), creates one row per sacker
    with the same play_seq. Primary key is (game_id, play_seq, sacker_name).
    """
    if season < 1978:
        return []

    table = _find_table(soup, "pbp")
    if not table:
        return []

    sacks = []
    play_seq = 0
    current_qtr = None

    tbody = table.find("tbody")
    if not tbody:
        return []

    for tr in tbody.find_all("tr"):
        cls = " ".join(tr.get("class", []))
        if "thead" in cls or "divider" in cls:
            continue

        cells = tr.find_all(["th", "td"])
        if not cells:
            continue

        # Build lookup by data-stat attribute (more reliable than positional index)
        cell_map = {c.get("data-stat", f"_col{i}"): c for i, c in enumerate(cells)}

        tm_cell     = cell_map.get("team_abbr") or (cells[0] if cells else None)
        qtr_cell    = cell_map.get("quarter") or (cells[1] if len(cells) > 1 else None)
        detail_cell = cell_map.get("detail") or (cells[6] if len(cells) > 6 else None)

        if not detail_cell:
            continue

        detail_text = detail_cell.get_text(strip=True)
        if not detail_text or "sack" not in detail_text.lower():
            continue

        # Track current quarter (may be blank on continuation rows)
        if qtr_cell:
            qt = qtr_cell.get_text(strip=True)
            if qt.isdigit():
                current_qtr = int(qt)
            elif qt.upper().startswith("OT"):
                current_qtr = 5

        # Determine offense/defense teams from "Tm" column
        tm_text = (tm_cell.get_text(strip=True) if tm_cell else "").lower().strip()
        if tm_text == vis_abbrev.lower():
            offense_team = vis_abbrev
            defense_team = home_abbrev
        elif tm_text == home_abbrev.lower():
            offense_team = home_abbrev
            defense_team = vis_abbrev
        else:
            offense_team = tm_text or None
            defense_team = None

        # PFR PBP format: "{QB}sacked by{Defender(s)}for {N} yards[...]"
        # Player names are hyperlinked with no spaces between adjacent tags.
        # Use HTML character position to split: links BEFORE "sacked by" = QB,
        # links BETWEEN "sacked by" and "for N yards" = sacker(s).
        cell_html = str(detail_cell)
        cell_html_lower = cell_html.lower()

        sb_match = _SACK_BY_RE.search(cell_html_lower)
        if not sb_match:
            continue
        sb_pos    = sb_match.start()
        sb_end    = sb_match.end()

        yds_match = _SACK_YDS_RE.search(cell_html_lower, sb_end)
        for_pos   = yds_match.start() if yds_match else len(cell_html)
        yds_lost  = int(yds_match.group(1)) if yds_match else None

        sacked_players: list[tuple[str, str | None, str | None]] = []
        sacker_players: list[tuple[str, str | None, str | None]] = []

        for a in detail_cell.find_all("a", href=True):
            if "/players/" not in a["href"]:
                continue
            link_html = str(a)
            lpos = cell_html.find(link_html)
            pid  = a["href"].strip()
            sm   = re.search(r"/players/[A-Z]/([A-Za-z0-9]+)\.htm", pid)
            sid  = sm.group(1) if sm else None
            name = a.get_text(strip=True)

            if lpos < sb_pos:
                sacked_players.append((name, pid, sid))
            elif lpos < for_pos:
                sacker_players.append((name, pid, sid))
            # players after "for N yards" are fumble recoverers etc. — ignore

        if not sacker_players:
            continue

        sacked_name  = sacked_players[0][0] if sacked_players else detail_text[:30]
        sacked_id    = sacked_players[0][1] if sacked_players else None
        sacked_short = sacked_players[0][2] if sacked_players else None

        play_seq += 1
        for sacker_name, sacker_id, sacker_short in sacker_players:
            sacks.append({
                "game_id":         game_id,
                "play_seq":        play_seq,
                "quarter":         current_qtr,
                "offense_team":    offense_team,
                "defense_team":    defense_team,
                "sacker_name":     sacker_name,
                "sacker_pfr_id":   sacker_id,
                "sacker_short_id": sacker_short,
                "sacked_name":     sacked_name,
                "sacked_pfr_id":   sacked_id,
                "sacked_short_id": sacked_short,
                "yds_lost":        yds_lost,
                "description":     detail_text[:500],
            })

    return sacks


# ── DB writes ─────────────────────────────────────────────────────────────────

STARTER_UPSERT = text("""
    INSERT INTO game_starters
        (game_id, team_abbrev, side, starter_position,
         pfr_player_id, pfr_short_id, player_name)
    VALUES
        (:game_id, :team_abbrev, :side, :starter_position,
         :pfr_player_id, :pfr_short_id, :player_name)
    ON CONFLICT (game_id, team_abbrev, side, starter_position) DO UPDATE SET
        pfr_player_id = COALESCE(EXCLUDED.pfr_player_id, game_starters.pfr_player_id),
        pfr_short_id  = COALESCE(EXCLUDED.pfr_short_id,  game_starters.pfr_short_id),
        player_name   = EXCLUDED.player_name
""")

SNAP_UPSERT = text("""
    INSERT INTO player_snap_counts
        (game_id, team_abbrev, pfr_player_id, pfr_short_id, player_name, position,
         off_snaps, off_snap_pct, def_snaps, def_snap_pct, st_snaps, st_snap_pct)
    VALUES
        (:game_id, :team_abbrev, :pfr_player_id, :pfr_short_id, :player_name, :position,
         :off_snaps, :off_snap_pct, :def_snaps, :def_snap_pct, :st_snaps, :st_snap_pct)
    ON CONFLICT (game_id, team_abbrev, player_name) DO UPDATE SET
        pfr_player_id = COALESCE(EXCLUDED.pfr_player_id, player_snap_counts.pfr_player_id),
        pfr_short_id  = COALESCE(EXCLUDED.pfr_short_id,  player_snap_counts.pfr_short_id),
        position      = EXCLUDED.position,
        off_snaps     = EXCLUDED.off_snaps,
        off_snap_pct  = EXCLUDED.off_snap_pct,
        def_snaps     = EXCLUDED.def_snaps,
        def_snap_pct  = EXCLUDED.def_snap_pct,
        st_snaps      = EXCLUDED.st_snaps,
        st_snap_pct   = EXCLUDED.st_snap_pct
""")

SACK_UPSERT = text("""
    INSERT INTO play_by_play_sacks
        (game_id, play_seq, quarter, offense_team, defense_team,
         sacker_name, sacker_pfr_id, sacker_short_id,
         sacked_name, sacked_pfr_id, sacked_short_id,
         yds_lost, description)
    VALUES
        (:game_id, :play_seq, :quarter, :offense_team, :defense_team,
         :sacker_name, :sacker_pfr_id, :sacker_short_id,
         :sacked_name, :sacked_pfr_id, :sacked_short_id,
         :yds_lost, :description)
    ON CONFLICT (game_id, play_seq, sacker_name) DO UPDATE SET
        quarter          = EXCLUDED.quarter,
        offense_team     = EXCLUDED.offense_team,
        defense_team     = EXCLUDED.defense_team,
        sacker_pfr_id    = COALESCE(EXCLUDED.sacker_pfr_id,   play_by_play_sacks.sacker_pfr_id),
        sacker_short_id  = COALESCE(EXCLUDED.sacker_short_id, play_by_play_sacks.sacker_short_id),
        sacked_name      = EXCLUDED.sacked_name,
        sacked_pfr_id    = COALESCE(EXCLUDED.sacked_pfr_id,   play_by_play_sacks.sacked_pfr_id),
        yds_lost         = EXCLUDED.yds_lost,
        description      = EXCLUDED.description
""")


def write_game(conn, game_id: str, vis_abbrev: str, home_abbrev: str,
               vis_starters, home_starters, vis_snaps, home_snaps,
               sacks: list[dict]) -> dict:
    """Write starters, snap counts, and PBP sacks for one game. Returns counts."""
    counts = {"starters": 0, "snaps": 0, "sacks": 0}

    for abbrev, starters in [(vis_abbrev, vis_starters), (home_abbrev, home_starters)]:
        if not abbrev or not starters:
            continue
        for row in starters:
            conn.execute(STARTER_UPSERT, {
                "game_id":          game_id,
                "team_abbrev":      abbrev,
                "side":             row["side"],
                "starter_position": row["starter_position"],
                "pfr_player_id":    row["pfr_player_id"],
                "pfr_short_id":     row["pfr_short_id"],
                "player_name":      row["player_name"],
            })
            counts["starters"] += 1

    for abbrev, snap_rows in [(vis_abbrev, vis_snaps), (home_abbrev, home_snaps)]:
        if not abbrev or not snap_rows:
            continue
        for row in snap_rows:
            conn.execute(SNAP_UPSERT, {
                "game_id":       game_id,
                "team_abbrev":   abbrev,
                "pfr_player_id": row["pfr_player_id"],
                "pfr_short_id":  row["pfr_short_id"],
                "player_name":   row["player_name"],
                "position":      row["position"],
                "off_snaps":     row["off_snaps"],
                "off_snap_pct":  row["off_snap_pct"],
                "def_snaps":     row["def_snaps"],
                "def_snap_pct":  row["def_snap_pct"],
                "st_snaps":      row["st_snaps"],
                "st_snap_pct":   row["st_snap_pct"],
            })
            counts["snaps"] += 1

    for row in sacks:
        conn.execute(SACK_UPSERT, row)
        counts["sacks"] += 1

    return counts


# ── game ID discovery ─────────────────────────────────────────────────────────

def get_all_game_ids(season: int) -> list[str]:
    """
    Return all game IDs for a season (regular season + playoffs), sorted by date.

    Reads game_id from the first row of each boxscore CSV. Falls back to the
    filename stem if the CSV has no game_id column (very old seasons). Includes
    playoff games — the games table's is_playoff flag handles filtering later.
    """
    season_dir = BOX_DIR / str(season)
    if not season_dir.is_dir():
        return []

    files = sorted(season_dir.glob("*.csv"), key=lambda f: f.name)
    ids: list[str] = []
    seen: set[str] = set()

    for f in files:
        gid = None
        try:
            with open(f) as fh:
                reader = csv.DictReader(fh)
                first = next(reader, None)
                if first and first.get("game_id"):
                    gid = first["game_id"].strip() or None
        except Exception:
            pass
        if not gid:
            gid = f.stem
        if gid and gid not in seen:
            ids.append(gid)
            seen.add(gid)

    return ids


def get_scraped_ids(engine) -> set[str]:
    """Return game_ids already present in game_starters."""
    with engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT DISTINCT game_id FROM game_starters"))
            return {r[0] for r in result}
        except Exception:
            return set()


# ── main scrape loop ──────────────────────────────────────────────────────────

def scrape_game(scraper: BraveScraper, game_id: str, season: int) -> dict:
    """
    Fetch and parse one boxscore page.

    Returns dict with keys:
      vis_abbrev, home_abbrev,
      vis_starters, home_starters,
      vis_snaps, home_snaps,
      sacks   (empty list if season < 1978)
    """
    url  = f"{BASE_URL}/boxscores/{game_id}.htm"
    soup = scraper.fetch(url, strip_comments=True)

    vis_abbrev, home_abbrev = extract_team_abbrevs(soup)

    vis_starter_tbl  = _find_table(soup, "vis_starters")
    home_starter_tbl = _find_table(soup, "home_starters")
    vis_snap_tbl     = _find_table(soup, "vis_snap_counts")
    home_snap_tbl    = _find_table(soup, "home_snap_counts")

    vis_starters  = parse_starters_table(vis_starter_tbl)  if vis_starter_tbl  else []
    home_starters = parse_starters_table(home_starter_tbl) if home_starter_tbl else []
    vis_snaps     = parse_snap_counts_table(vis_snap_tbl)   if vis_snap_tbl    else []
    home_snaps    = parse_snap_counts_table(home_snap_tbl)  if home_snap_tbl   else []

    sacks = parse_pbp_sacks(soup, vis_abbrev, home_abbrev, game_id, season)

    return {
        "vis_abbrev":   vis_abbrev,
        "home_abbrev":  home_abbrev,
        "vis_starters": vis_starters,
        "home_starters": home_starters,
        "vis_snaps":    vis_snaps,
        "home_snaps":   home_snaps,
        "sacks":        sacks,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Scrape PFR boxscore starters, snap counts, and PBP sacks.\n"
                    "Starters: 1950+  |  Snap counts: 2012+  |  PBP sacks: 1978+"
    )
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--season",  type=int, help="Single season year (e.g. 2012)")
    grp.add_argument("--seasons", help="Inclusive range: e.g. 1950-2025")
    grp.add_argument("--game",    help="Single game_id (e.g. 201211110min)")
    ap.add_argument("--force",   action="store_true", help="Re-scrape already-done games")
    ap.add_argument("--dry-run", action="store_true", help="Parse HTML but don't write to DB")
    args = ap.parse_args()

    engine  = get_engine()
    scraper = BraveScraper(sleep_min=5.0, sleep_max=9.0)

    # Build season → game_id list
    if args.game:
        # Infer season from game_id prefix (format: YYYYMMDDTEAM)
        inferred_season = int(args.game[:4]) if args.game[:4].isdigit() else 0
        season_games: list[tuple[int, str]] = [(inferred_season, args.game)]
    elif args.season:
        ids = get_all_game_ids(args.season)
        print(f"Season {args.season}: {len(ids)} games found")
        season_games = [(args.season, g) for g in ids]
    else:
        lo, hi = map(int, args.seasons.split("-"))
        season_games = []
        for y in range(lo, hi + 1):
            ids = get_all_game_ids(y)
            print(f"  {y}: {len(ids)} games")
            season_games.extend((y, g) for g in ids)
        print(f"Total: {len(season_games)} games across {hi - lo + 1} seasons")

    # Skip already-done unless --force
    if not args.force and not args.game:
        done   = get_scraped_ids(engine)
        before = len(season_games)
        season_games = [(y, g) for y, g in season_games if g not in done]
        skipped = before - len(season_games)
        if skipped:
            print(f"Skipping {skipped} already-scraped games; {len(season_games)} remaining")

    if not season_games:
        print("Nothing to scrape.")
        return

    total_starters = total_snaps = total_sacks = 0
    errors = []

    try:
        for i, (season, game_id) in enumerate(season_games, 1):
            print(f"[{i}/{len(season_games)}] {game_id} ...", end=" ", flush=True)
            try:
                result = scrape_game(scraper, game_id, season)

                va = result["vis_abbrev"]
                ha = result["home_abbrev"]

                if not va or not ha:
                    print("WARN: could not extract team abbrevs")
                    errors.append((game_id, "no team abbrevs"))
                    scraper._sleep()
                    continue

                if not result["vis_starters"] and not result["home_starters"]:
                    print("WARN: no starters found (no lineup data on page)")
                    errors.append((game_id, "no starters"))
                    scraper._sleep()
                    continue

                if args.dry_run:
                    ns = len(result["vis_starters"]) + len(result["home_starters"])
                    nn = len(result["vis_snaps"])     + len(result["home_snaps"])
                    nk = len(result["sacks"])
                    print(f"DRY-RUN {va}@{ha}: {ns} starters, {nn} snap rows, {nk} sacks")
                else:
                    with engine.begin() as conn:
                        counts = write_game(
                            conn, game_id, va, ha,
                            result["vis_starters"], result["home_starters"],
                            result["vis_snaps"],    result["home_snaps"],
                            result["sacks"],
                        )
                    total_starters += counts["starters"]
                    total_snaps    += counts["snaps"]
                    total_sacks    += counts["sacks"]
                    sack_note = f", {counts['sacks']} sacks" if counts["sacks"] else ""
                    print(f"{va}@{ha}: {counts['starters']} starters, "
                          f"{counts['snaps']} snap rows{sack_note}")

            except PermissionError as e:
                print(f"\nCLOUDFLARE BLOCK: {e}")
                break
            except Exception as e:
                print(f"ERROR: {e}")
                errors.append((game_id, str(e)))

            scraper._sleep()

    finally:
        scraper.close()

    print(f"\n{'='*60}")
    print(f"Done. Games attempted: {len(season_games)}")
    if not args.dry_run:
        print(f"  Starter rows written:    {total_starters}")
        print(f"  Snap count rows written: {total_snaps}")
        print(f"  PBP sack rows written:   {total_sacks}")
    if errors:
        print(f"  Errors ({len(errors)}):")
        for gid, msg in errors[:20]:
            print(f"    {gid}: {msg}")
        if len(errors) > 20:
            print(f"    ... and {len(errors) - 20} more")


if __name__ == "__main__":
    main()
