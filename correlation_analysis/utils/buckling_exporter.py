"""Buckling analysis export utilities.

Generates the CSV data file and YAML configuration consumed by the external
`fembuckling_onset` analysis tool.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..models.data_model import DataModel


# ------------------------------------------------------------------ #
# Settings                                                             #
# ------------------------------------------------------------------ #

@dataclass
class BucklingExportSettings:
    csv_path: str = ""
    output_dir: str = ""
    active_strategy: str = "hybrid"
    minima_prominence: float = 0.0
    window_length: int = 7
    polyorder: int = 2
    acceleration_jerk_threshold: float = 1.0e-5
    min_principal_magnitude_threshold: float = 1.0e-6
    python_env_dir: str = ""
    fembuckling_dir: str = ""


# Column order expected by the FEM buckling tool
_CSV_COLUMNS = [
    "LoadCase", "ElementID", "Time",
    "SUP_e11", "SUP_e22", "SUP_e12",
    "INF_e11", "INF_e22", "INF_e12",
]
_COR_TYPES = ["e11", "e22", "e12"]


# ------------------------------------------------------------------ #
# CSV generation                                                       #
# ------------------------------------------------------------------ #

def generate_csv(selections: list[dict], data_model: DataModel) -> pd.DataFrame:
    """Convert checked-group selections to the buckling analysis CSV format.

    SUP columns are populated from **data source A** (the first loaded source)
    and INF columns from **data source B** (the second loaded source).

    For rosette groups, ``_build_buckling_groups`` creates one entry per
    rosette×source so that the dialog can show per-source sparklines.  At
    CSV-generation time all entries sharing the same ``rosette_id`` are
    combined into one element with a single union time axis:

    * SUP series ← own-rosette sensor from the **first** source group (A).
    * INF series ← own-rosette sensor from the **second** source group (B).
    * Values at time points that exist in a source are written as-is.
    * Values at time points that exist only in the other source are linearly
      interpolated from that side's data — no cross-source mixing or averaging.

    For individual (non-rosette) groups the original behaviour is preserved:
    ``sources[0]`` → SUP (source A), ``sources[1]`` → INF (source B).

    Parameters
    ----------
    selections:
        List of group-selection dicts from ``BucklingDialog.analyze_requested``.
    data_model:
        Used to look up sensor strain series by source_id and sensor name.

    Returns
    -------
    pd.DataFrame with columns ``LoadCase, ElementID, Time,
    SUP_e11, SUP_e22, SUP_e12, INF_e11, INF_e22, INF_e12``.
    """
    rows: list[dict] = []

    # ── Bucket rosette groups by rosette_id ──────────────────────────────
    # _build_buckling_groups creates one BucklingGroup per rosette×source so
    # the dialog can show per-source sparklines.  Here we re-group them so
    # that each unique rosette emits exactly one block of CSV rows.
    # Bucket order preserves source-import order: bucket[0] = source A, etc.
    rosette_buckets: dict[str, list[dict]] = {}
    non_rosette_groups: list[dict] = []
    for group in selections:
        if group.get("is_rosette") and group.get("rosette_id"):
            rosette_buckets.setdefault(group["rosette_id"], []).append(group)
        else:
            non_rosette_groups.append(group)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _fetch(entry: dict) -> pd.Series | None:
        src_id = entry.get("source_id", "")
        sname = entry.get("sensor_name", "")
        if not sname or sname == "—":
            return None
        df = data_model.get_dataframe(src_id)
        if df is None or sname not in df.index:
            return None
        return df.loc[sname]

    def _interp_onto(
        series: pd.Series | None, sorted_times: list[float]
    ) -> dict[float, float]:
        """Interpolate *series* onto *sorted_times*.

        Existing data points are returned unchanged.  Time points that fall
        between existing points are linearly interpolated.  Time points outside
        the series range produce NaN (no extrapolation).
        """
        if series is None:
            return {}
        x = np.array(
            [float(v) for v in series.index if isinstance(v, (int, float)) and not pd.isna(v)],
            dtype=float,
        )
        y = np.array(
            [series[v] for v in series.index if isinstance(v, (int, float)) and not pd.isna(v)],
            dtype=float,
        )
        if len(x) == 0:
            return {}
        result: dict[float, float] = {}
        for t in sorted_times:
            if t < x[0] or t > x[-1]:
                result[t] = float("nan")
            else:
                result[t] = float(np.interp(t, x, y))
        return result

    def _emit_element_rows(
        element_id: str,
        is_rosette: bool,
        cor_sup: dict[str, pd.Series | None],
        cor_inf: dict[str, pd.Series | None],
    ) -> None:
        all_times: set[float] = set()
        for series in list(cor_sup.values()) + list(cor_inf.values()):
            if series is not None:
                all_times.update(
                    float(v) for v in series.index
                    if isinstance(v, (int, float)) and not pd.isna(v)
                )
        if not all_times:
            return

        sorted_times = sorted(all_times)
        sup_lookup = {cor: _interp_onto(cor_sup.get(cor), sorted_times) for cor in _COR_TYPES}
        inf_lookup = {cor: _interp_onto(cor_inf.get(cor), sorted_times) for cor in _COR_TYPES}
        missing_fill = float("nan") if is_rosette else 0.0

        for t in sorted_times:
            row: dict[str, Any] = {"LoadCase": "LC1", "ElementID": element_id, "Time": t}
            for cor in _COR_TYPES:
                row[f"SUP_{cor}"] = sup_lookup[cor].get(t, missing_fill)
                row[f"INF_{cor}"] = inf_lookup[cor].get(t, missing_fill)
            rows.append(row)

    # ── Non-rosette (individual sensor) groups ───────────────────────────
    # sources[0] = source A → SUP, sources[1] = source B → INF.
    # Each individual canonical has a single BucklingGroup containing all
    # sources in its sources list, so no bucketing is needed here.
    for group in non_rosette_groups:
        cor_sup: dict[str, pd.Series | None] = {}
        cor_inf: dict[str, pd.Series | None] = {}
        first_sup_entry: dict = {}

        for sensor in group["sensors"]:
            cor = sensor["cor"]
            sources_list: list[dict] = sensor.get("sources", [])
            if len(sources_list) > 0:
                if not first_sup_entry:
                    first_sup_entry = sources_list[0]
                s = _fetch(sources_list[0])
                if s is not None:
                    cor_sup[cor] = s
            if len(sources_list) > 1:
                s = _fetch(sources_list[1])
                if s is not None:
                    cor_inf[cor] = s

        name = first_sup_entry.get("sensor_name", "")
        element_id = name if name and name != "—" else group["pair_id"]
        _emit_element_rows(element_id, False, cor_sup, cor_inf)

    # ── Rosette groups: source A → SUP, source B → INF ───────────────────
    # bucket[0] = group from source A (SUP), bucket[1] = group from source B (INF).
    # Within each per-source group, sources[0] is the own-rosette sensor.
    # The two sides are kept strictly separate — no cross-source mixing.
    # The union time axis covers all time steps from both sources; each side
    # is independently interpolated onto it so existing values are unchanged.
    for rosette_id, bucket in rosette_buckets.items():
        cor_sup = {}
        cor_inf = {}

        if len(bucket) >= 2:
            # Two or more sources: source A (bucket[0]) → SUP, source B (bucket[1]) → INF.
            for sensor in bucket[0]["sensors"]:
                cor = sensor["cor"]
                sources_list = sensor.get("sources", [])
                if sources_list:
                    s = _fetch(sources_list[0])
                    if s is not None:
                        cor_sup[cor] = s
            for sensor in bucket[1]["sensors"]:
                cor = sensor["cor"]
                sources_list = sensor.get("sources", [])
                if sources_list:
                    s = _fetch(sources_list[0])
                    if s is not None:
                        cor_inf[cor] = s
        else:
            # Single source: own rosette (sources[0]) → SUP, paired rosette (sources[1]) → INF.
            for sensor in bucket[0]["sensors"]:
                cor = sensor["cor"]
                sources_list = sensor.get("sources", [])
                if len(sources_list) > 0:
                    s = _fetch(sources_list[0])
                    if s is not None:
                        cor_sup[cor] = s
                if len(sources_list) > 1:
                    s = _fetch(sources_list[1])
                    if s is not None:
                        cor_inf[cor] = s

        _emit_element_rows(rosette_id, True, cor_sup, cor_inf)

    if rows:
        return pd.DataFrame(rows, columns=_CSV_COLUMNS)
    return pd.DataFrame(columns=_CSV_COLUMNS)


# ------------------------------------------------------------------ #
# YAML generation                                                      #
# ------------------------------------------------------------------ #

def generate_yaml(settings: BucklingExportSettings) -> str:
    """Return the YAML config string for the fembuckling_onset tool."""
    csv_path = Path(settings.csv_path).as_posix()
    out_dir = Path(settings.output_dir).as_posix()

    jerk = f"{settings.acceleration_jerk_threshold:.1e}"
    mag = f"{settings.min_principal_magnitude_threshold:.1e}"

    return (
        f"fembuckling_onset:\n"
        f"  inputs:\n"
        f"    # Point to the CSV file.\n"
        f"    femresult: \"{csv_path}\"\n"
        f"\n"
        f"  outputs:\n"
        f"    # This path determines where the results folder is created.\n"
        f"    directory: \"{out_dir}\"\n"
        f"\n"
        f"  analysis:\n"
        f"    active_strategy: \"{settings.active_strategy}\"\n"
        f"    strategy_settings:\n"
        f"      minima:\n"
        f"        minima_prominence: {settings.minima_prominence}\n"
        f"      acceleration:\n"
        f"        window_length: {settings.window_length}\n"
        f"        polyorder: {settings.polyorder}\n"
        f"      hybrid:\n"
        f"        acceleration_jerk_threshold: {jerk}\n"
        f"        min_principal_magnitude_threshold: {mag}\n"
    )


def write_export(
    selections: list[dict],
    data_model: DataModel,
    settings: BucklingExportSettings,
) -> tuple[str, str]:
    """Generate and write both the CSV and YAML files.

    Returns
    -------
    (csv_path, yaml_path) absolute paths of the written files.
    """
    # CSV
    df = generate_csv(selections, data_model)
    csv_path = Path(settings.csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    # YAML — same stem as CSV, same directory
    yaml_path = csv_path.with_suffix(".yaml")
    yaml_path.write_text(generate_yaml(settings), encoding="utf-8")

    return str(csv_path), str(yaml_path)
