"""Sensor name mapping between multiple data sources."""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from ..utils.csv_parser import parse_mapping_csv

log = logging.getLogger(__name__)

# Column names in mapping CSV treated as metadata (not source aliases)
_ROSETTE_COL = "rosette"
_SENSOR_PAIR_COL = "sensor pair"


class SensorMapping:
    """
    Maps canonical sensor names to per-source aliases.

    Internal structure:
        {canonical_name: {source_id: source_sensor_name}}

    Optional rosette/pair metadata (present only when the mapping CSV
    contains 'Rosette' / 'Sensor Pair' columns):
        _rosette:      {canonical_name: rosette_group_id}
        _sensor_pair:  {canonical_name: pair_id}
    """

    def __init__(self) -> None:
        self._mapping: dict[str, dict[str, str]] = {}
        # Reverse lookup: {source_id: {source_name: canonical_name}}
        self._reverse: dict[str, dict[str, str]] = {}
        # Rosette / sensor-pair metadata (may be empty if not in CSV)
        self._rosette: dict[str, str] = {}
        self._sensor_pair: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #

    def load_from_file(self, filepath: str, source_ids: list[str]) -> None:
        """
        Load mapping from CSV.
        Columns should match source_ids (or be a subset).
        First column is the canonical name (used as index by csv_parser).

        Special columns 'Rosette' and 'Sensor Pair' (case-insensitive) are
        treated as metadata rather than source aliases.  They are optional —
        if absent the rosette/pair dicts will be empty.
        """
        df = parse_mapping_csv(filepath)
        self._mapping.clear()
        self._reverse.clear()
        self._rosette.clear()
        self._sensor_pair.clear()

        # Identify special metadata columns by normalised name
        special: dict[str, str] = {}  # normalised_lower -> actual col name
        for col in df.columns:
            norm = str(col).strip().lower()
            if norm in (_ROSETTE_COL, _SENSOR_PAIR_COL):
                special[norm] = col

        # Extract rosette and sensor-pair metadata
        if _ROSETTE_COL in special:
            col = special[_ROSETTE_COL]
            for canonical in df.index:
                val = df.loc[canonical, col]
                if pd.notna(val) and str(val).strip():
                    self._rosette[str(canonical)] = str(val).strip()

        if _SENSOR_PAIR_COL in special:
            col = special[_SENSOR_PAIR_COL]
            for canonical in df.index:
                val = df.loc[canonical, col]
                if pd.notna(val) and str(val).strip():
                    self._sensor_pair[str(canonical)] = str(val).strip()

        # Build alias mapping from all non-special columns
        alias_cols = [c for c in df.columns if c not in special.values()]
        for canonical in df.index:
            aliases: dict[str, str] = {}
            for col in alias_cols:
                val = df.loc[canonical, col]
                if pd.notna(val) and str(val).strip():
                    aliases[str(col)] = str(val).strip()
            self._mapping[str(canonical)] = aliases

        self._rebuild_reverse()
        log.info(
            "Mapping loaded from '%s': %d canonical sensors across %d source column(s)"
            " (rosette entries: %d, sensor-pair entries: %d).",
            filepath,
            len(self._mapping),
            len({src for aliases in self._mapping.values() for src in aliases}),
            len(self._rosette),
            len(self._sensor_pair),
        )

    def load_from_dict(self, data: dict) -> None:
        """Load mapping from a session dict.

        Accepts both the legacy format ``{canonical: {src: alias}}`` and the
        extended format ``{"aliases": {...}, "rosette": {...}, "sensor_pair": {...}}``.
        """
        self._rosette.clear()
        self._sensor_pair.clear()
        if "aliases" in data:
            # Extended session format
            self._mapping = {k: dict(v) for k, v in data["aliases"].items()}
            self._rosette = dict(data.get("rosette", {}))
            self._sensor_pair = dict(data.get("sensor_pair", {}))
        else:
            # Legacy format — plain aliases dict
            self._mapping = {k: dict(v) for k, v in data.items()}
        self._rebuild_reverse()

    def _rebuild_reverse(self) -> None:
        self._reverse.clear()
        for canonical, aliases in self._mapping.items():
            for source_id, sensor_name in aliases.items():
                self._reverse.setdefault(source_id, {})[sensor_name] = canonical

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    def resolve(self, source_id: str, sensor_name: str) -> Optional[str]:
        """Return canonical name for a source sensor, or None if unmapped."""
        return self._reverse.get(source_id, {}).get(sensor_name)

    def resolve_by_name(self, sensor_name: str) -> Optional[str]:
        """Find canonical name by searching *sensor_name* across all source columns.

        Useful when the source_id in the data model does not match the column
        name used in the mapping CSV.
        """
        for canonical, aliases in self._mapping.items():
            if sensor_name in aliases.values():
                return canonical
        return None

    def get_aliases(self, canonical_name: str) -> dict[str, str]:
        """Return {source_id: sensor_name} for a canonical name."""
        return dict(self._mapping.get(canonical_name, {}))

    def canonical_names(self) -> list[str]:
        return list(self._mapping.keys())

    def add_mapping(self, canonical: str, source_id: str, sensor_name: str) -> None:
        self._mapping.setdefault(canonical, {})[source_id] = sensor_name
        self._reverse.setdefault(source_id, {})[sensor_name] = canonical

    def is_empty(self) -> bool:
        return len(self._mapping) == 0

    # ------------------------------------------------------------------ #
    # Rosette / Sensor-pair metadata                                       #
    # ------------------------------------------------------------------ #

    def get_rosette(self, canonical: str) -> str:
        """Return the rosette group ID for *canonical*, or '' if not part of a rosette."""
        return self._rosette.get(canonical, "")

    def get_sensor_pair(self, canonical: str) -> str:
        """Return the sensor-pair ID for *canonical*, or '' if not set."""
        return self._sensor_pair.get(canonical, "")

    def rosette_data(self) -> dict[str, str]:
        """Return a copy of the rosette metadata dict."""
        return dict(self._rosette)

    def sensor_pair_data(self) -> dict[str, str]:
        """Return a copy of the sensor-pair metadata dict."""
        return dict(self._sensor_pair)

    def has_rosette_data(self) -> bool:
        """True if the loaded mapping contained a Rosette column."""
        return bool(self._rosette)

    def has_sensor_pair_data(self) -> bool:
        """True if the loaded mapping contained a Sensor Pair column."""
        return bool(self._sensor_pair)

    # ------------------------------------------------------------------ #
    # Serialization                                                        #
    # ------------------------------------------------------------------ #

    def get_missing_analysis(
        self,
        imported_sensors_by_source: dict[str, list[str]],
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """Identify coverage gaps between loaded mapping and imported data.

        Args:
            imported_sensors_by_source: ``{display_name: [sensor_name, ...]}``
                for every imported CSV source.

        Returns:
            A 2-tuple of:

            * ``unmapped`` — ``{display_name: [sensor_names]}`` — sensors that
              appear in the imported data but are **not referenced** by any
              mapping entry (across all mapping source columns).

            * ``incomplete_canonicals`` — ``{canonical_name: [source_cols]}``
              — canonical sensors that are missing an alias entry for at least
              one mapping source column.
        """
        # All sensor names that appear as values anywhere in the mapping
        all_mapped_sensor_names: set[str] = set()
        for aliases in self._mapping.values():
            all_mapped_sensor_names.update(aliases.values())

        # All source-column labels present in the mapping CSV
        all_mapping_source_cols: list[str] = sorted(
            {src for aliases in self._mapping.values() for src in aliases}
        )

        # Sensors in imported CSVs that have no mapping entry
        unmapped: dict[str, list[str]] = {}
        for display_name, sensors in imported_sensors_by_source.items():
            missing = [s for s in sensors if s not in all_mapped_sensor_names]
            if missing:
                unmapped[display_name] = missing

        # Canonical sensors missing an alias for ≥1 mapping source column
        incomplete_canonicals: dict[str, list[str]] = {}
        for canonical, aliases in self._mapping.items():
            missing_srcs = [s for s in all_mapping_source_cols if s not in aliases]
            if missing_srcs:
                incomplete_canonicals[canonical] = missing_srcs

        log.info(
            "Missing analysis: %d source(s) have unmapped sensors, "
            "%d canonical(s) are incomplete across source columns.",
            len(unmapped),
            len(incomplete_canonicals),
        )
        return unmapped, incomplete_canonicals

    def clear(self) -> None:
        """Remove all mappings."""
        self._mapping.clear()
        self._reverse.clear()
        self._rosette.clear()
        self._sensor_pair.clear()
        log.debug("SensorMapping cleared.")

    def to_dict(self) -> dict:
        """Return aliases dict only (used for the mapping dialog view)."""
        return {k: dict(v) for k, v in self._mapping.items()}

    def to_session_dict(self) -> dict:
        """Return full serializable dict including rosette/pair metadata."""
        d: dict = {"aliases": self.to_dict()}
        if self._rosette:
            d["rosette"] = dict(self._rosette)
        if self._sensor_pair:
            d["sensor_pair"] = dict(self._sensor_pair)
        return d
