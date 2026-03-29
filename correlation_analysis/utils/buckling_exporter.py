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

    SUP columns are populated from the **left** side of each dialog row and
    INF columns from the **right** side, matching the visual layout regardless
    of which source file each side originates from.

    Load steps are taken as the union of all time values across left and right
    sensors; values at time points that exist only on one side are linearly
    interpolated from that side's data.

    Parameters
    ----------
    selections:
        List of group-selection dicts from ``BucklingDialog.analyze_requested``.
        ``sensors[*]["sources"]`` is an ordered list where index 0 = left (SUP)
        and index 1 = right (INF).
    data_model:
        Used to look up sensor strain series by source_id and sensor name.

    Returns
    -------
    pd.DataFrame with columns ``LoadCase, ElementID, Time,
    SUP_e11, SUP_e22, SUP_e12, INF_e11, INF_e22, INF_e12``.
    """
    rows: list[dict] = []

    for group in selections:
        # ---- ElementID --------------------------------------------------
        if group.get("is_rosette") and group.get("rosette_id"):
            element_id = group["rosette_id"]
        else:
            left_info = (group["sensors"][0]["sources"] or [{}])[0] if group["sensors"] else {}
            name = left_info.get("sensor_name", "")
            element_id = name if name and name != "—" else group["pair_id"]

        # ---- Collect left (SUP) and right (INF) series per cor ----------
        # cor_sup / cor_inf: {cor_type: pd.Series}
        cor_sup: dict[str, pd.Series] = {}
        cor_inf: dict[str, pd.Series] = {}

        for sensor in group["sensors"]:
            cor = sensor["cor"]
            sources_list: list[dict] = sensor.get("sources", [])

            def _fetch(entry: dict) -> pd.Series | None:
                src_id = entry.get("source_id", "")
                sname = entry.get("sensor_name", "")
                if not sname or sname == "—":
                    return None
                df = data_model.get_dataframe(src_id)
                if df is None or sname not in df.index:
                    return None
                return df.loc[sname]

            if len(sources_list) > 0:
                s = _fetch(sources_list[0])
                if s is not None:
                    cor_sup[cor] = s
            if len(sources_list) > 1:
                s = _fetch(sources_list[1])
                if s is not None:
                    cor_inf[cor] = s

        # ---- Union time axis --------------------------------------------
        all_times: set[float] = set()
        for series in list(cor_sup.values()) + list(cor_inf.values()):
            all_times.update(
                float(v) for v in series.index
                if isinstance(v, (int, float)) and not pd.isna(v)
            )

        if not all_times:
            continue

        sorted_times = sorted(all_times)

        # ---- Pre-interpolate each series onto the common time axis ------
        def _interp_series(series: pd.Series | None) -> dict[float, float]:
            """Return {time: value} interpolated onto sorted_times."""
            if series is None:
                return {}
            x = np.array([float(v) for v in series.index
                          if isinstance(v, (int, float)) and not pd.isna(v)],
                         dtype=float)
            y = np.array([series[v] for v in series.index
                          if isinstance(v, (int, float)) and not pd.isna(v)],
                         dtype=float)
            if len(x) == 0:
                return {}
            # Only interpolate within the data range; outside → NaN
            result = {}
            for t in sorted_times:
                if t < x[0] or t > x[-1]:
                    result[t] = float("nan")
                else:
                    result[t] = float(np.interp(t, x, y))
            return result

        sup_lookup: dict[str, dict[float, float]] = {
            cor: _interp_series(cor_sup.get(cor)) for cor in _COR_TYPES
        }
        inf_lookup: dict[str, dict[float, float]] = {
            cor: _interp_series(cor_inf.get(cor)) for cor in _COR_TYPES
        }

        # ---- Build rows -------------------------------------------------
        is_rosette = group.get("is_rosette", False)
        for t in sorted_times:
            row: dict[str, Any] = {
                "LoadCase": "LC1",
                "ElementID": element_id,
                "Time": t,
            }
            for cor in _COR_TYPES:
                missing_fill = float("nan") if is_rosette else 0.0
                row[f"SUP_{cor}"] = sup_lookup[cor].get(t, missing_fill)
                row[f"INF_{cor}"] = inf_lookup[cor].get(t, missing_fill)
            rows.append(row)

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
