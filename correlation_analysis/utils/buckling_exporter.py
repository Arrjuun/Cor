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

def _merge_time_series(series_list: list[pd.Series]) -> pd.Series | None:
    """Merge multiple time-indexed Series onto one axis.

    At time points present in more than one series the values are averaged;
    at time points present in only one series the value is taken as-is.
    NaN values are ignored during the merge.
    """
    if not series_list:
        return None
    if len(series_list) == 1:
        return series_list[0]

    time_values: dict[float, list[float]] = {}
    for s in series_list:
        for idx in s.index:
            if not isinstance(idx, (int, float)) or pd.isna(idx):
                continue
            v = s[idx]
            if not pd.isna(v):
                time_values.setdefault(float(idx), []).append(float(v))

    if not time_values:
        return None

    times = sorted(time_values.keys())
    return pd.Series([float(np.mean(time_values[t])) for t in times], index=times)


def generate_csv(selections: list[dict], data_model: DataModel) -> pd.DataFrame:
    """Convert checked-group selections to the buckling analysis CSV format.

    SUP columns are populated from the **left** side of each dialog row and
    INF columns from the **right** side, matching the visual layout regardless
    of which source file each side originates from.

    For rosette groups, all per-source group instances that share the same
    ``rosette_id`` are merged onto a single union time axis before emission.
    Values at time points present in only one source are linearly interpolated
    from that source's data; values at overlapping time points are averaged.

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

    # ── Bucket rosette groups by rosette_id ──────────────────────────────
    # _build_buckling_groups creates one BucklingGroup per rosette×source so
    # that the dialog can show per-source sparklines.  At CSV-generation time
    # we must treat all groups that share a rosette_id as one element and
    # merge their time series, otherwise each source produces a separate block
    # of rows for the same ElementID.
    rosette_buckets: dict[str, list[dict]] = {}
    non_rosette_groups: list[dict] = []
    for group in selections:
        if group.get("is_rosette") and group.get("rosette_id"):
            rosette_buckets.setdefault(group["rosette_id"], []).append(group)
        else:
            non_rosette_groups.append(group)

    # ── Nested helpers ───────────────────────────────────────────────────

    def _fetch(entry: dict) -> pd.Series | None:
        src_id = entry.get("source_id", "")
        sname = entry.get("sensor_name", "")
        if not sname or sname == "—":
            return None
        df = data_model.get_dataframe(src_id)
        if df is None or sname not in df.index:
            return None
        return df.loc[sname]

    def _collect_series(
        groups: list[dict],
    ) -> tuple[dict[str, pd.Series | None], dict[str, pd.Series | None]]:
        """Build merged (cor_sup, cor_inf) from one or more group dicts."""
        sup_lists: dict[str, list[pd.Series]] = {}
        inf_lists: dict[str, list[pd.Series]] = {}
        for group in groups:
            for sensor in group["sensors"]:
                cor = sensor["cor"]
                sources_list: list[dict] = sensor.get("sources", [])
                if len(sources_list) > 0:
                    s = _fetch(sources_list[0])
                    if s is not None:
                        sup_lists.setdefault(cor, []).append(s)
                if len(sources_list) > 1:
                    s = _fetch(sources_list[1])
                    if s is not None:
                        inf_lists.setdefault(cor, []).append(s)
        cor_sup = {cor: _merge_time_series(sl) for cor, sl in sup_lists.items()}
        cor_inf = {cor: _merge_time_series(il) for cor, il in inf_lists.items()}
        return cor_sup, cor_inf

    def _interp_onto(
        series: pd.Series | None, sorted_times: list[float]
    ) -> dict[float, float]:
        """Return {time: value} for *series* interpolated onto *sorted_times*."""
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
    for group in non_rosette_groups:
        left_info = (group["sensors"][0]["sources"] or [{}])[0] if group["sensors"] else {}
        name = left_info.get("sensor_name", "")
        element_id = name if name and name != "—" else group["pair_id"]
        cor_sup, cor_inf = _collect_series([group])
        _emit_element_rows(element_id, False, cor_sup, cor_inf)

    # ── Rosette groups: merge all per-source instances into one element ───
    for rosette_id, bucket in rosette_buckets.items():
        cor_sup, cor_inf = _collect_series(bucket)
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
