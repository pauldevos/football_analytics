"""
Directory manager for Pro Football Reference data.

Canonical layout under ~/data/pfref/:
    manifest/                        — scrape tracking (not raw data)
    raw/
        boxscores/{year}/{game_id}/  — game-level tables (canonical source)
        coaches/                     — coaching records and trees
        team-history/                — per-team franchise history pages
        season/
            gamelogs/                — season game ID lists
            draft/                   — draft picks by year
            standings/               — season standings
            all_pro/                 — end-of-season awards
            rosters/                 — team rosters by season
            player/{stat_type}/      — player season totals
            team/
                offense/{subtype}/   — team offensive season stats
                defense/{subtype}/   — team defensive season stats

Usage:
    dm = DirectoryManager()
    dm.raw                          # ~/data/pfref/raw
    dm.season                       # ~/data/pfref/raw/season
    dm.gamelogs                     # ~/data/pfref/raw/season/gamelogs
    dm.player("defense")            # ~/data/pfref/raw/season/player/defense
    dm.team_offense("passing")      # ~/data/pfref/raw/season/team/offense/passing
    dm.team_defense("overall")      # ~/data/pfref/raw/season/team/defense/overall
    dm.boxscores(2024)              # ~/data/pfref/raw/boxscores/2024
"""

import pathlib
from typing import Optional


class DirectoryManager:
    """
    Builds and caches paths to every node in the pfref data tree.
    Calls mkdir(parents=True, exist_ok=True) on first access.
    """

    def __init__(self, base_path: Optional[pathlib.Path] = None):
        self.base_path = base_path or pathlib.Path.home() / "data" / "pfref"
        self._cache: dict[str, pathlib.Path] = {}

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _dir(self, *parts: str) -> pathlib.Path:
        key = "/".join(parts)
        if key not in self._cache:
            path = self.base_path.joinpath(*parts)
            path.mkdir(parents=True, exist_ok=True)
            self._cache[key] = path
        return self._cache[key]

    # ------------------------------------------------------------------
    # Top-level nodes
    # ------------------------------------------------------------------

    @property
    def manifest(self) -> pathlib.Path:
        return self._dir("manifest")

    @property
    def raw(self) -> pathlib.Path:
        return self._dir("raw")

    # ------------------------------------------------------------------
    # Raw sub-nodes (non-season)
    # ------------------------------------------------------------------

    def boxscores(self, season: Optional[int] = None) -> pathlib.Path:
        if season is not None:
            return self._dir("raw", "boxscores", str(season))
        return self._dir("raw", "boxscores")

    @property
    def coaches(self) -> pathlib.Path:
        return self._dir("raw", "coaches")

    @property
    def team_history(self) -> pathlib.Path:
        return self._dir("raw", "team-history")

    # ------------------------------------------------------------------
    # Season sub-nodes
    # ------------------------------------------------------------------

    @property
    def season(self) -> pathlib.Path:
        return self._dir("raw", "season")

    @property
    def gamelogs(self) -> pathlib.Path:
        return self._dir("raw", "season", "gamelogs")

    @property
    def draft(self) -> pathlib.Path:
        return self._dir("raw", "season", "draft")

    @property
    def standings(self) -> pathlib.Path:
        return self._dir("raw", "season", "standings")

    @property
    def all_pro(self) -> pathlib.Path:
        return self._dir("raw", "season", "all_pro")

    @property
    def rosters(self) -> pathlib.Path:
        return self._dir("raw", "season", "rosters")

    # ------------------------------------------------------------------
    # Player season stats
    # ------------------------------------------------------------------

    PLAYER_STAT_TYPES = frozenset([
        "passing", "rushing", "receiving", "scrimmage",
        "defense", "kicking", "punting", "returns", "scoring",
    ])

    def player(self, stat_type: str) -> pathlib.Path:
        if stat_type not in self.PLAYER_STAT_TYPES:
            raise ValueError(f"Unknown player stat type '{stat_type}'. "
                             f"Valid: {sorted(self.PLAYER_STAT_TYPES)}")
        return self._dir("raw", "season", "player", stat_type)

    # ------------------------------------------------------------------
    # Team season stats
    # ------------------------------------------------------------------

    TEAM_OFFENSE_TYPES = frozenset([
        "overall", "passing", "rushing", "scoring", "kicking", "punting", "returns",
    ])
    TEAM_DEFENSE_TYPES = frozenset([
        "overall", "passing", "rushing", "scoring", "kicking",
    ])

    def team_offense(self, subtype: str) -> pathlib.Path:
        if subtype not in self.TEAM_OFFENSE_TYPES:
            raise ValueError(f"Unknown offense subtype '{subtype}'. "
                             f"Valid: {sorted(self.TEAM_OFFENSE_TYPES)}")
        return self._dir("raw", "season", "team", "offense", subtype)

    def team_defense(self, subtype: str) -> pathlib.Path:
        if subtype not in self.TEAM_DEFENSE_TYPES:
            raise ValueError(f"Unknown defense subtype '{subtype}'. "
                             f"Valid: {sorted(self.TEAM_DEFENSE_TYPES)}")
        return self._dir("raw", "season", "team", "defense", subtype)

    # ------------------------------------------------------------------
    # Legacy get() shim — keeps old call sites working during transition
    # ------------------------------------------------------------------

    def get(self, directory: str, season: Optional[int] = None) -> pathlib.Path:
        """Legacy shim: dm.get('gamelogs') / dm.get('boxscores', season=2024)."""
        mapping = {
            "season-gamelogs": self.gamelogs,
            "gamelogs": self.gamelogs,
            "boxscores": self.boxscores(season) if season else self.boxscores(),
            "coaches": self.coaches,
            "team-history": self.team_history,
            "standings": self.standings,
            "draft": self.draft,
            "draft-data": self.draft,
            "rosters": self.rosters,
            "team-rosters": self.rosters,
            "all_pro": self.all_pro,
        }
        if directory in mapping:
            return mapping[directory]
        # Fallback: treat as raw/season/{directory}
        return self._dir("raw", "season", directory)

    def __repr__(self):
        return f"DirectoryManager(base_path='{self.base_path}')"
