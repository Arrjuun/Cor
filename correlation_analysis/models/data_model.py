"""Core data model managing all imported sensor DataFrames."""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pandas as pd


@dataclass
class SourceDataset:
    """Represents a single imported CSV source."""
    source_id: str
    filepath: str
    display_name: str
    df: pd.DataFrame  # index=sensor names, columns=load steps (float)


class DataModel:
    """
    Registry for all imported sensor DataFrames.

    Observers are plain callables notified on any change:
        observer(event: str, source_id: str)
    """

    def __init__(self) -> None:
        self._sources: dict[str, SourceDataset] = {}
        self._observers: list[Callable[[str, str], None]] = []

    # ------------------------------------------------------------------ #
    # Observer management                                                  #
    # ------------------------------------------------------------------ #

    def add_observer(self, observer: Callable[[str, str], None]) -> None:
        self._observers.append(observer)

    def remove_observer(self, observer: Callable[[str, str], None]) -> None:
        self._observers.discard(observer)

    def _notify(self, event: str, source_id: str) -> None:
        for obs in list(self._observers):
            try:
                obs(event, source_id)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # CRUD                                                                 #
    # ------------------------------------------------------------------ #

    def add_source(self, filepath: str, df: pd.DataFrame,
                   display_name: str = "", source_id: str = "") -> str:
        """Add a new data source. Returns the assigned source_id."""
        sid = source_id or str(uuid.uuid4())[:8]
        if not display_name:
            import os
            display_name = os.path.basename(filepath)
        dataset = SourceDataset(
            source_id=sid,
            filepath=filepath,
            display_name=display_name,
            df=df.copy(),
        )
        self._sources[sid] = dataset
        self._notify("added", sid)
        return sid

    def get_source(self, source_id: str) -> Optional[SourceDataset]:
        return self._sources.get(source_id)

    def get_dataframe(self, source_id: str) -> Optional[pd.DataFrame]:
        ds = self._sources.get(source_id)
        return ds.df.copy() if ds else None

    def update_dataframe(self, source_id: str, df: pd.DataFrame) -> None:
        if source_id in self._sources:
            self._sources[source_id].df = df.copy()
            self._notify("updated", source_id)

    def remove_source(self, source_id: str) -> None:
        if source_id in self._sources:
            del self._sources[source_id]
            self._notify("removed", source_id)

    def all_sources(self) -> list[SourceDataset]:
        return list(self._sources.values())

    def source_ids(self) -> list[str]:
        return list(self._sources.keys())

    # ------------------------------------------------------------------ #
    # Row / Column operations                                              #
    # ------------------------------------------------------------------ #

    def delete_rows(self, source_id: str, sensor_names: list[str]) -> None:
        ds = self._sources.get(source_id)
        if ds is None:
            return
        df = ds.df.drop(index=[s for s in sensor_names if s in ds.df.index],
                        errors="ignore")
        self._sources[source_id].df = df
        self._notify("updated", source_id)

    def delete_columns(self, source_id: str, load_steps: list[float]) -> None:
        ds = self._sources.get(source_id)
        if ds is None:
            return
        cols_to_drop = [c for c in load_steps if c in ds.df.columns]
        df = ds.df.drop(columns=cols_to_drop, errors="ignore")
        self._sources[source_id].df = df
        self._notify("updated", source_id)

    def add_derived_row(self, source_id: str, sensor_name: str,
                        formula: str, values: Optional[pd.Series] = None,
                        position: Optional[int] = None) -> None:
        """Add or update a derived (formula) row.

        When *sensor_name* is new, inserts at *position* (appends if None).
        When *sensor_name* already exists, updates its values in-place.
        """
        ds = self._sources.get(source_id)
        if ds is None:
            return
        df = ds.df.copy()
        saved_attrs = dict(df.attrs)

        if sensor_name in df.index:
            # Update existing row in-place
            if values is not None:
                df.loc[sensor_name] = values
        else:
            # Build a float NaN row and insert at the requested position
            if values is not None:
                row_data = values
            else:
                row_data = pd.Series(np.nan, index=df.columns, dtype=float)
            new_row = row_data.rename(sensor_name).to_frame().T
            if position is not None and 0 <= position <= len(df):
                df = pd.concat([df.iloc[:position], new_row, df.iloc[position:]])
            else:
                df = pd.concat([df, new_row])

        df.attrs.update(saved_attrs)
        df.attrs.setdefault("formulas", {})[sensor_name] = formula
        self._sources[source_id].df = df
        self._notify("updated", source_id)

    def get_formulas(self, source_id: str) -> dict[str, str]:
        ds = self._sources.get(source_id)
        if ds is None:
            return {}
        return dict(ds.df.attrs.get("formulas", {}))

    def set_formula(self, source_id: str, sensor_name: str, formula: str) -> None:
        ds = self._sources.get(source_id)
        if ds is None:
            return
        ds.df.attrs.setdefault("formulas", {})[sensor_name] = formula
        self._notify("formula_updated", source_id)

    # ------------------------------------------------------------------ #
    # Serialization helpers                                                #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        result = {}
        for sid, ds in self._sources.items():
            result[sid] = {
                "filepath": ds.filepath,
                "display_name": ds.display_name,
                # orient='split' preserves column dtypes (float load steps) and
                # index values (sensor names) exactly across save/load cycles.
                "data": ds.df.to_json(orient="split"),
                "formulas": ds.df.attrs.get("formulas", {}),
            }
        return result

    def from_dict(self, data: dict) -> None:
        self._sources.clear()
        for sid, info in data.items():
            raw = info["data"]
            # pandas 2.x treats bare strings as file paths; wrap in StringIO.
            # Try split orient first (current format); fall back to default orient
            # for session files saved by older versions of the app.
            try:
                df = pd.read_json(io.StringIO(raw), orient="split")
            except Exception:
                df = pd.read_json(io.StringIO(raw))
            # Coerce column labels to float (load steps) — JSON keys are always
            # strings, so "1.0" / "1" both need to become float 1.0.
            float_cols = {}
            for col in df.columns:
                try:
                    float_cols[col] = float(col)
                except (TypeError, ValueError):
                    pass
            if float_cols:
                df = df.rename(columns=float_cols)
            df.attrs["formulas"] = info.get("formulas", {})
            self._sources[sid] = SourceDataset(
                source_id=sid,
                filepath=info["filepath"],
                display_name=info["display_name"],
                df=df,
            )
        self._notify("loaded", "")
