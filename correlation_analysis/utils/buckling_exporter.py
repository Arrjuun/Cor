"""Buckling analysis export utilities.

Generates the CSV data file and YAML configuration consumed by the external
`fembuckling_onset` analysis tool.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

    The first imported source maps to SUP (superior/simulation) columns and
    the second to INF (inferior/test-measurement) columns.

    Parameters
    ----------
    selections:
        List of group-selection dicts as emitted by ``BucklingDialog.analyze_requested``.
        Each entry has keys: ``pair_id``, ``is_rosette``, ``rosette_id``, ``sensors``
        where ``sensors`` is a list of ``{"canonical", "cor", "sources": {sid: name}}``.
    data_model:
        The application's ``DataModel`` used to look up sensor strain series.

    Returns
    -------
    pd.DataFrame with columns ``LoadCase, ElementID, Time,
    SUP_e11, SUP_e22, SUP_e12, INF_e11, INF_e22, INF_e12``.
    """
    source_ids_ordered = list(data_model.source_ids())
    sup_id = source_ids_ordered[0] if len(source_ids_ordered) > 0 else None
    inf_id = source_ids_ordered[1] if len(source_ids_ordered) > 1 else None

    rows: list[dict] = []

    for group in selections:
        pair_id = group["pair_id"]

        # Build {cor: {source_id: pd.Series}} from the selection
        cor_series: dict[str, dict[str, pd.Series]] = {}
        for sensor in group["sensors"]:
            cor = sensor["cor"]
            cor_series.setdefault(cor, {})
            for source_id, sensor_name in sensor["sources"].items():
                if not sensor_name or sensor_name == "—":
                    continue
                df = data_model.get_dataframe(source_id)
                if df is None:
                    continue
                if sensor_name in df.index:
                    cor_series[cor][source_id] = df.loc[sensor_name]

        # Collect all numeric load steps across every series in this group
        all_load_steps: set[float] = set()
        for src_dict in cor_series.values():
            for series in src_dict.values():
                numeric_ls = [
                    v for v in series.index
                    if isinstance(v, (int, float)) and not pd.isna(v)
                ]
                all_load_steps.update(numeric_ls)

        for ls in sorted(all_load_steps):
            row: dict[str, Any] = {
                "LoadCase": "LC1",
                "ElementID": pair_id,
                "Time": ls,
            }
            for cor in _COR_TYPES:
                for prefix, src_id in [("SUP", sup_id), ("INF", inf_id)]:
                    col = f"{prefix}_{cor}"
                    val = float("nan")
                    if src_id and cor in cor_series and src_id in cor_series[cor]:
                        series = cor_series[cor][src_id]
                        if ls in series.index:
                            val = series[ls]
                    row[col] = val
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
