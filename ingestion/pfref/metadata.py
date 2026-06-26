"""
Metadata tracker to avoid re-pulling data that has already been scraped.

Stores pull history as JSON at ~/data/pfref/metadata.json.
Each entry records when data was pulled, where it was saved, and how many records it contained.

Usage:
    meta = MetadataTracker()

    # Check before pulling
    if not meta.is_pulled('passing', 2023):
        # ... scrape ...
        meta.mark_pulled('passing', 2023, file_path=path, record_count=145)

    # Find years not yet pulled
    missing = meta.missing_years('passing', range(1950, 2026))

    # Inspect what's been collected
    print(meta.summary())
    print(meta.get_status('passing'))
"""

import json
import pathlib
from datetime import datetime
from typing import Any


class MetadataTracker:
    """
    Tracks scraped datasets to prevent duplicate HTTP requests.

    The metadata file is a JSON dict structured as:
        {
          "<dataset>": {
            "<key>": {
              "pulled_at": "ISO timestamp",
              "file_path": "absolute path string",
              "records": 145,
              ...extra fields
            }
          }
        }

    Args:
        path: Path to the metadata JSON file.
               Defaults to ~/data/pfref/metadata.json
    """

    DEFAULT_PATH = pathlib.Path.home() / "data" / "pfref" / "metadata.json"

    def __init__(self, path: pathlib.Path | None = None):
        self.path = path or self.DEFAULT_PATH
        self._data: dict[str, dict[str, Any]] = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def is_pulled(self, dataset: str, key: str | int) -> bool:
        """Return True if this dataset/key combination has been successfully pulled."""
        entry = self._data.get(dataset, {}).get(str(key), {})
        # Must have a pulled_at timestamp and no unresolved error that overwrote it
        return "pulled_at" in entry

    def mark_pulled(
        self,
        dataset: str,
        key: str | int,
        file_path: pathlib.Path | str | None = None,
        record_count: int | None = None,
        **extra: Any,
    ) -> None:
        """
        Record a successful data pull.

        Args:
            dataset: Category name (e.g. 'passing', 'team_offense', 'boxscores')
            key: Year, game ID, coach ID, etc.
            file_path: Where the data was saved
            record_count: Number of rows saved
            **extra: Any additional metadata to store (e.g. season=2024)
        """
        if dataset not in self._data:
            self._data[dataset] = {}
        entry: dict[str, Any] = {"pulled_at": datetime.now().isoformat()}
        if file_path is not None:
            entry["file_path"] = str(file_path)
        if record_count is not None:
            entry["records"] = record_count
        entry.update({k: str(v) if isinstance(v, pathlib.Path) else v for k, v in extra.items()})
        self._data[dataset][str(key)] = entry
        self._save()

    def mark_failed(self, dataset: str, key: str | int, error: str = "") -> None:
        """
        Record a failed pull attempt. Does NOT mark the entry as successfully pulled,
        so it will be retried on the next run.
        """
        if dataset not in self._data:
            self._data[dataset] = {}
        existing = self._data[dataset].get(str(key), {})
        existing["last_error"] = error
        existing["last_error_at"] = datetime.now().isoformat()
        self._data[dataset][str(key)] = existing
        self._save()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def missing_years(self, dataset: str, years: range | list[int]) -> list[int]:
        """Return the subset of years that have not yet been pulled for a dataset."""
        return [y for y in years if not self.is_pulled(dataset, y)]

    def pulled_years(self, dataset: str, years: range | list[int]) -> list[int]:
        """Return the subset of years that have already been pulled for a dataset."""
        return [y for y in years if self.is_pulled(dataset, y)]

    def get_status(self, dataset: str) -> dict[str, Any]:
        """Return the full metadata dict for a dataset."""
        return dict(self._data.get(dataset, {}))

    def summary(self) -> dict[str, int]:
        """Return a count of successfully pulled keys per dataset."""
        return {
            dataset: sum(1 for v in keys.values() if "pulled_at" in v)
            for dataset, keys in self._data.items()
        }

    def detailed_summary(self) -> None:
        """Print a human-readable summary of all datasets."""
        print(f"{'Dataset':<30} {'Pulled':>8} {'Errors':>8}")
        print("-" * 50)
        for dataset, keys in sorted(self._data.items()):
            pulled = sum(1 for v in keys.values() if "pulled_at" in v)
            errors = sum(1 for v in keys.values() if "last_error" in v and "pulled_at" not in v)
            print(f"{dataset:<30} {pulled:>8} {errors:>8}")

    # ------------------------------------------------------------------
    # Mutation helpers
    # ------------------------------------------------------------------

    def remove(self, dataset: str, key: str | int) -> None:
        """Remove a single entry so it will be re-pulled on next run."""
        if dataset in self._data and str(key) in self._data[dataset]:
            del self._data[dataset][str(key)]
            self._save()

    def remove_dataset(self, dataset: str) -> None:
        """Remove all metadata for a dataset so all years will be re-pulled."""
        if dataset in self._data:
            del self._data[dataset]
            self._save()

    def __repr__(self) -> str:
        total = sum(self.summary().values())
        return f"MetadataTracker(path='{self.path}', total_entries={total})"
