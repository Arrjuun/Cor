"""CSV parsing utilities for sensor strain data."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Optional

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
    Parse a CSV file where rows=sensors, columns=load steps.

    Returns:
        (DataFrame with sensor names as index, float load-step columns,
         CSVValidationResult with any errors/warnings)
    Raises:
        CSVParseError on unrecoverable IO or structural errors.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        df_raw = pd.read_csv(filepath, index_col=0, header=0)
    except Exception as exc:
        raise CSVParseError(f"Cannot read CSV file: {exc}") from exc

    if df_raw.empty:
        raise CSVParseError("CSV file is empty.")

    # Attempt to coerce column headers to float (load steps)
    new_columns = []
    for col in df_raw.columns:
        try:
            new_columns.append(float(col))
        except (ValueError, TypeError):
            errors.append(f"Column header '{col}' is not a numeric load step value.")
            new_columns.append(col)
    df_raw.columns = new_columns

    # Check sensor names (index) – warn on duplicates
    if df_raw.index.duplicated().any():
        dupes = df_raw.index[df_raw.index.duplicated()].tolist()
        warnings.append(f"Duplicate sensor names detected: {dupes}")

    # Coerce cell values to numeric
    numeric_errors: list[str] = []
    for col in df_raw.columns:
        non_numeric = pd.to_numeric(df_raw[col], errors='coerce').isna() & df_raw[col].notna()
        if non_numeric.any():
            bad = df_raw.index[non_numeric].tolist()
            numeric_errors.append(f"Column '{col}' has non-numeric values in rows: {bad}")
    if numeric_errors:
        errors.extend(numeric_errors)

    df = df_raw.apply(pd.to_numeric, errors='coerce')
    df.index.name = "Sensor"

    is_valid = len(errors) == 0
    return df, CSVValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


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
