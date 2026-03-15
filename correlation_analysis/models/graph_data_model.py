"""Graph data preparation: transforms DataFrames into plottable structures."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .data_model import DataModel
from .sensor_mapping import SensorMapping


class GraphDataModel:
    """Provides data subsets ready for graph rendering."""

    def __init__(self, data_model: DataModel, mapping: SensorMapping) -> None:
        self._data = data_model
        self._mapping = mapping

    # ------------------------------------------------------------------ #
    # LoadStep vs Strain                                                   #
    # ------------------------------------------------------------------ #

    def get_loadstep_series(
        self,
        source_id: str,
        sensor_name: str,
        interpolate: bool = False,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Return (load_steps, strain_values) arrays for plotting.

        Args:
            source_id: ID of the source dataset.
            sensor_name: Name of the sensor row.
            interpolate: Fill NaN via linear interpolation.

        Returns:
            Tuple of float arrays; raises ValueError if sensor not found.
        """
        df = self._data.get_dataframe(source_id)
        if df is None:
            raise ValueError(f"Source '{source_id}' not found.")
        if sensor_name not in df.index:
            raise ValueError(f"Sensor '{sensor_name}' not in source '{source_id}'.")

        row = df.loc[sensor_name]
        # Only numeric columns (load steps)
        numeric_cols = [c for c in row.index if isinstance(c, (int, float))]
        x = np.array(numeric_cols, dtype=float)
        y = row[numeric_cols].values.astype(float)

        if interpolate:
            mask = np.isnan(y)
            if mask.any() and not mask.all():
                y = np.interp(x, x[~mask], y[~mask])

        return x, y

    def get_mapped_series(
        self,
        canonical_name: str,
    ) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """
        Return series for all sources that have the canonical sensor.

        Returns:
            {source_id: (load_steps, strain_values)}
        """
        aliases = self._mapping.get_aliases(canonical_name)
        result = {}
        for source_id, sensor_name in aliases.items():
            try:
                result[source_id] = self.get_loadstep_series(source_id, sensor_name)
            except ValueError:
                pass
        return result

    # ------------------------------------------------------------------ #
    # Ratio Graph                                                          #
    # ------------------------------------------------------------------ #

    def get_ratio_data(
        self,
        source_id_a: str,
        source_id_b: str,
        load_step: float,
        use_mapping: bool = True,
        interpolate: bool = False,
    ) -> pd.DataFrame:
        """
        Compute ratio (source_a / source_b) at a given load step.

        Returns DataFrame with columns: [sensor, value_a, value_b, ratio]
        """
        df_a = self._data.get_dataframe(source_id_a)
        df_b = self._data.get_dataframe(source_id_b)
        if df_a is None or df_b is None:
            raise ValueError("One or both source IDs are invalid.")

        def _get_value(df: pd.DataFrame, sensor: str, ls: float) -> float:
            if ls in df.columns:
                return float(df.loc[sensor, ls]) if sensor in df.index else np.nan
            if interpolate:
                cols = sorted([c for c in df.columns if isinstance(c, (int, float))])
                if sensor not in df.index or not cols:
                    return np.nan
                y = df.loc[sensor, cols].values.astype(float)
                return float(np.interp(ls, cols, y))
            return np.nan

        rows = []
        if use_mapping and not self._mapping.is_empty():
            for canonical in self._mapping.canonical_names():
                aliases = self._mapping.get_aliases(canonical)
                # Match alias values against each DataFrame's index directly.
                # This works regardless of what the mapping's source_id keys are.
                sensor_a = next(
                    (name for name in aliases.values() if name in df_a.index), None
                )
                sensor_b = next(
                    (name for name in aliases.values() if name in df_b.index), None
                )
                if sensor_a and sensor_b and sensor_a != sensor_b:
                    va = _get_value(df_a, sensor_a, load_step)
                    vb = _get_value(df_b, sensor_b, load_step)
                    ratio = va / vb if vb and not np.isnan(vb) and vb != 0 else np.nan
                    rows.append({"sensor": canonical, "value_a": va,
                                 "value_b": vb, "ratio": ratio})
        else:
            common = df_a.index.intersection(df_b.index)
            for sensor in common:
                va = _get_value(df_a, sensor, load_step)
                vb = _get_value(df_b, sensor, load_step)
                ratio = va / vb if vb and not np.isnan(vb) and vb != 0 else np.nan
                rows.append({"sensor": sensor, "value_a": va,
                             "value_b": vb, "ratio": ratio})

        return pd.DataFrame(rows, columns=["sensor", "value_a", "value_b", "ratio"])

    def get_all_load_steps(self, source_id: str) -> list[float]:
        df = self._data.get_dataframe(source_id)
        if df is None:
            return []
        return [c for c in df.columns if isinstance(c, (int, float))]

    def get_sensor_names(self, source_id: str) -> list[str]:
        df = self._data.get_dataframe(source_id)
        if df is None:
            return []
        return list(df.index)
