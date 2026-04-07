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
    method: list = field(default_factory=lambda: ["acceleration"])
    chain: bool = False
    savgol_window: int = 7
    polynomial_degree: int = 4
    acceleration_prominence: float = 0.1
    reversal_prominence: float = 0.0005
    workers: int = 4
    log_level: str = "INFO"
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

    Both rosette and individual-sensor groups now share the same per-source
    structure produced by ``_build_buckling_groups``:

    * ``sources[0]`` of each SensorEntry  → SUP (own sensor in that source).
    * ``sources[1]`` of each SensorEntry  → INF (paired sensor in that source).
    * Both sides come from the **same** source file — no cross-source mixing.
    * The time axis is the union of the own and paired sensors' time steps
      within that source; values at time points present in only one sensor
      are linearly interpolated from that sensor's data.

    If the same logical ElementID (rosette ID or canonical name) would appear
    more than once in the output (because multiple sources contain the same
    element), a ``_N`` suffix is appended to each occurrence so the
    fembuckling tool sees distinct elements.

    Parameters
    ----------
    selections:
        List of group-selection dicts from ``BucklingDialog.analyze_requested``.
    data_model:
        Used to look up sensor strain series by source_id and sensor name.

    Returns
    -------
    tuple of:
      * pd.DataFrame with columns ``LoadCase, ElementID, Time,
        SUP_e11, SUP_e22, SUP_e12, INF_e11, INF_e22, INF_e12``.
      * dict mapping each final ElementID to
        ``{"source_label": str, "sensor_names": list[str]}`` where
        *sensor_names* holds the actual SUP sensor names from the source.
    """
    rows: list[dict] = []
    # Maps each final ElementID to source info:
    #   {"source_label": str, "sensor_names": list[str]}
    # where sensor_names contains the actual per-source sensor names used for SUP.
    element_source_map: dict[str, dict] = {}

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
        """Return {time: value} for *series* interpolated onto *sorted_times*.

        Values at time points that already exist in the series are returned
        unchanged.  Values at intermediate time points are linearly
        interpolated.  Time points outside the series range return NaN.
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

    # ── Determine raw ElementID for each group ────────────────────────────
    # Rosette groups use the rosette_id; individual groups use the canonical
    # name of the first (own) sensor so that the ID is stable across sources.

    def _raw_element_id(group: dict) -> str:
        if group.get("is_rosette") and group.get("rosette_id"):
            return group["rosette_id"]
        if group.get("sensors"):
            return group["sensors"][0].get("canonical", "") or group["pair_id"]
        return group["pair_id"]

    # ── Count occurrences to decide when _N suffixes are needed ──────────
    raw_ids = [_raw_element_id(g) for g in selections]
    id_counts: dict[str, int] = {}
    for rid in raw_ids:
        id_counts[rid] = id_counts.get(rid, 0) + 1
    id_next_idx: dict[str, int] = {}

    # ── Process each group ────────────────────────────────────────────────
    # All groups (rosette and individual) now share the same structure:
    # sources[0] → own (SUP), sources[1] → paired (INF), both same source.
    for group in selections:
        raw_id = _raw_element_id(group)
        if id_counts[raw_id] > 1:
            id_next_idx[raw_id] = id_next_idx.get(raw_id, 0) + 1
            element_id = f"{raw_id}_{id_next_idx[raw_id]}"
        else:
            element_id = raw_id

        is_rosette = group.get("is_rosette", False)
        source_label = group.get("source_label", "")
        element_source_map[element_id] = {
            "source_label": source_label,
            "sensor_names": [],
            "sup_names": {},   # {cor: sensor_name} for SUP series
            "inf_names": {},   # {cor: sensor_name} for INF series
        }

        cor_sup: dict[str, pd.Series | None] = {}
        cor_inf: dict[str, pd.Series | None] = {}

        for sensor in group["sensors"]:
            cor = sensor["cor"]
            sources_list: list[dict] = sensor.get("sources", [])
            if len(sources_list) > 0:
                sname = sources_list[0].get("sensor_name", "")
                if sname and sname != "—":
                    element_source_map[element_id]["sensor_names"].append(sname)
                    element_source_map[element_id]["sup_names"][cor] = sname
                s = _fetch(sources_list[0])
                if s is not None:
                    cor_sup[cor] = s
            if len(sources_list) > 1:
                sname_inf = sources_list[1].get("sensor_name", "")
                if sname_inf and sname_inf != "—":
                    element_source_map[element_id]["inf_names"][cor] = sname_inf
                s = _fetch(sources_list[1])
                if s is not None:
                    cor_inf[cor] = s

        _emit_element_rows(element_id, is_rosette, cor_sup, cor_inf)

    df = pd.DataFrame(rows, columns=_CSV_COLUMNS) if rows else pd.DataFrame(columns=_CSV_COLUMNS)
    return df, element_source_map


# ------------------------------------------------------------------ #
# YAML generation                                                      #
# ------------------------------------------------------------------ #

def generate_yaml(settings: BucklingExportSettings) -> str:
    """Return the YAML config string for the fembuckling_onset tool."""
    csv_path = Path(settings.csv_path).as_posix()
    out_dir = Path(settings.output_dir).as_posix()

    method_list = ", ".join(settings.method) if settings.method else "acceleration"
    chain_str = "True" if settings.chain else "False"

    return (
        f"# vt_s_fembucklingonset\n"
        f"# post processing module intended to detect the onset of buckling"
        f" coming from the strain evolution in shells\n"
        f"\n"
        f"fembuckling_onset:\n"
        f"  # --- Input Files ---\n"
        f"  inputs:\n"
        f"    femresult: \"{csv_path}\"\n"
        f"\n"
        f"  # --- Output settings ---\n"
        f"  outputs:\n"
        f"    directory: \"{out_dir}\"\n"
        f"\n"
        f"  # --- Analysis settings ---\n"
        f"  analysis:\n"
        f"    # Detection method(s): 'reversal', 'acceleration', or both separated by comma"
        f" (note, keep the brackets)\n"
        f"    method: [{method_list}]\n"
        f"\n"
        f"    # Chain detection methods: an element is only considered buckled if every method detects it.\n"
        f"    chain: {chain_str}\n"
        f"\n"
        f"    # Window size for Savitzky-Golay filter (must be odd)\n"
        f"    savgol_window: {settings.savgol_window}\n"
        f"\n"
        f"    # Polynomial order for filter\n"
        f"    polynomial_degree: {settings.polynomial_degree}\n"
        f"\n"
        f"    # Minimum relative acceleration prominence (2nd derivative) for a peak\n"
        f"    acceleration_prominence: {settings.acceleration_prominence}\n"
        f"\n"
        f"    # Minimum relative strain prominence at a reversal point\n"
        f"    reversal_prominence: {settings.reversal_prominence}\n"
        f"\n"
        f"    # Parallel execution settings\n"
        f"    workers: {settings.workers}\n"
        f"\n"
        f"log_level: {settings.log_level}\n"
    )


def write_export(
    selections: list[dict],
    data_model: DataModel,
    settings: BucklingExportSettings,
) -> tuple[str, str, dict[str, str]]:
    """Generate and write both the CSV and YAML files.

    Returns
    -------
    (csv_path, yaml_path, element_source_map) where *element_source_map* maps
    each ElementID written to the CSV to the source display-name it came from.
    """
    # CSV
    df, element_source_map = generate_csv(selections, data_model)
    csv_path = Path(settings.csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    # YAML — same stem as CSV, same directory
    yaml_path = csv_path.with_suffix(".yaml")
    yaml_path.write_text(generate_yaml(settings), encoding="utf-8")

    return str(csv_path), str(yaml_path), element_source_map
