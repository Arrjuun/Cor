"""CSV parsing utilities for sensor strain data."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


class CSVParseError(Exception):
    """Raised when a CSV file cannot be parsed as sensor data."""


@dataclass
class CSVValidationResult:
    """Result of validating a sensor CSV file."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_sensor_csv(filepath: str) -> tuple[pd.DataFrame, CSVValidationResult]:
    """
    Parse a CSV file as raw data with no header or index consumed.

    Returns a DataFrame with integer index (0, 1, 2, …) and integer columns
    (0, 1, 2, …) where all cell values are strings.

    Validation checks (by position, not by header):
      - Row 0, cols 1+: must be numeric (load step identifiers)
      - Col 0, rows 1+: must be non-empty strings (sensor names)
      - All other cells (rows 1+, cols 1+): must be numeric (strain values)

    Raises:
        CSVParseError on unrecoverable IO or structural errors.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        df_raw = pd.read_csv(filepath, header=None, dtype=str)
    except Exception as exc:
        raise CSVParseError(f"Cannot read CSV file: {exc}") from exc

    if df_raw.empty:
        raise CSVParseError("CSV file is empty.")
    if len(df_raw) < 2:
        raise CSVParseError("CSV must have at least 2 rows (one header row + one data row).")
    if len(df_raw.columns) < 2:
        raise CSVParseError("CSV must have at least 2 columns (sensor name column + one load step).")

    # Validate row 0 cols 1+ — must be numeric load step values
    for col_idx in range(1, len(df_raw.columns)):
        val = df_raw.iloc[0, col_idx]
        if pd.isna(val) or str(val).strip() == "":
            errors.append(f"Row 1, Column {col_idx + 1}: empty load step value.")
        else:
            try:
                float(str(val).strip())
            except (ValueError, TypeError):
                errors.append(
                    f"Row 1, Column {col_idx + 1}: '{val}' is not a numeric load step."
                )

    # Validate col 0 rows 1+ — sensor names must be non-empty
    for row_idx in range(1, len(df_raw)):
        val = df_raw.iloc[row_idx, 0]
        if pd.isna(val) or str(val).strip() == "":
            warnings.append(f"Column 1, Row {row_idx + 1}: empty sensor name.")

    # Warn on duplicate sensor names (col 0, rows 1+)
    sensor_series = df_raw.iloc[1:, 0].dropna().astype(str)
    dupes = sensor_series[sensor_series.duplicated()].tolist()
    if dupes:
        warnings.append(f"Duplicate sensor names detected: {dupes}")

    # Validate data cells (rows 1+, cols 1+) — must be numeric
    data_section = df_raw.iloc[1:, 1:]
    for col_offset in range(data_section.shape[1]):
        col_series = data_section.iloc[:, col_offset]
        non_numeric = (
            pd.to_numeric(col_series, errors="coerce").isna() & col_series.notna()
        )
        if non_numeric.any():
            bad_display_rows = [r + 2 for r in non_numeric[non_numeric].index.tolist()]
            errors.append(
                f"Column {col_offset + 2} has non-numeric values in rows: {bad_display_rows}"
            )

    # Reset integer index/columns to guarantee 0-based sequential integers
    df_raw = df_raw.reset_index(drop=True)
    df_raw.columns = range(len(df_raw.columns))

    is_valid = len(errors) == 0
    return df_raw, CSVValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


def validate_raw_dataframe(df: pd.DataFrame) -> bool:
    """
    Return True if the raw DataFrame passes positional validation:
      - Row 0, cols 1+: numeric
      - Data cells (rows 1+, cols 1+): numeric
    Used to re-validate after row/column deletions in the import view.
    """
    if len(df) < 2 or len(df.columns) < 2:
        return False
    for col_idx in range(1, len(df.columns)):
        val = df.iloc[0, col_idx]
        if pd.isna(val) or str(val).strip() == "":
            return False
        try:
            float(str(val).strip())
        except (ValueError, TypeError):
            return False
    data_section = df.iloc[1:, 1:]
    for col_offset in range(data_section.shape[1]):
        non_numeric = (
            pd.to_numeric(data_section.iloc[:, col_offset], errors="coerce").isna()
            & data_section.iloc[:, col_offset].notna()
        )
        if non_numeric.any():
            return False
    return True


def finalize_dataframe(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    Convert a raw import DataFrame to the analysis format expected by DataModel.

    - Row 0 values (cols 1+) become column names (load steps, coerced to float).
    - Col 0 values (rows 1+) become the index (sensor names).
    - Data section (rows 1+, cols 1+) is coerced to float.

    Raises:
        CSVParseError if the raw DataFrame cannot be finalized.
    """
    if len(df_raw) < 2 or len(df_raw.columns) < 2:
        raise CSVParseError(
            "Cannot finalize: DataFrame must have at least 2 rows and 2 columns."
        )

    # Build column names from row 0, cols 1+
    col_names: list = []
    for val in df_raw.iloc[0, 1:]:
        try:
            col_names.append(float(str(val).strip()))
        except (ValueError, TypeError):
            col_names.append(str(val))

    # Build sensor name index from col 0, rows 1+
    sensor_names = df_raw.iloc[1:, 0].astype(str).tolist()

    # Extract data section
    data = df_raw.iloc[1:, 1:].copy()
    data.columns = col_names
    data.index = sensor_names
    data = data.apply(pd.to_numeric, errors="coerce")
    data.index.name = "Sensor"

    return data


def parse_mapping_csv(filepath: str) -> pd.DataFrame:
    """
    Parse a sensor mapping CSV file.

    Expected format:
        canonical_name, source_A_name, source_B_name, ...
    Returns a DataFrame with canonical names as index.
    """
    try:
        df = pd.read_csv(filepath, index_col=0, header=0)
    except Exception as exc:
        raise CSVParseError(f"Cannot read mapping CSV: {exc}") from exc
    return df
