"""Sensor name mapping between multiple data sources."""
from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from ..utils.csv_parser import parse_mapping_csv

log = logging.getLogger(__name__)


class SensorMapping:
    """
    Maps canonical sensor names to per-source aliases.

    Internal structure:
        {canonical_name: {source_id: source_sensor_name}}
    """

    def __init__(self) -> None:
        self._mapping: dict[str, dict[str, str]] = {}
        # Reverse lookup: {source_id: {source_name: canonical_name}}
        self._reverse: dict[str, dict[str, str]] = {}

    # ------------------------------------------------------------------ #
    # Loading                                                              #
    # ------------------------------------------------------------------ #

    def load_from_file(self, filepath: str, source_ids: list[str]) -> None:
        """
        Load mapping from CSV.
        Columns should match source_ids (or be a subset).
        First column is the canonical name (used as index by csv_parser).
        """
        df = parse_mapping_csv(filepath)
        self._mapping.clear()
        self._reverse.clear()

        for canonical in df.index:
            aliases: dict[str, str] = {}
            for col in df.columns:
                val = df.loc[canonical, col]
                if pd.notna(val) and str(val).strip():
                    aliases[str(col)] = str(val).strip()
            self._mapping[str(canonical)] = aliases

        self._rebuild_reverse()
        log.info(
            "Mapping loaded from '%s': %d canonical sensors across %d source column(s).",
            filepath,
            len(self._mapping),
            len({src for aliases in self._mapping.values() for src in aliases}),
        )

    def load_from_dict(self, data: dict[str, dict[str, str]]) -> None:
        """Load mapping from a plain dict (e.g. from session file)."""
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
        log.debug("SensorMapping cleared.")

    def to_dict(self) -> dict:
        return {k: dict(v) for k, v in self._mapping.items()}
