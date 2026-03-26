"""Tests for CSV parsing utilities: parse_sensor_csv, validate_raw_dataframe, finalize_dataframe."""
from __future__ import annotations

import io
import pytest
import pandas as pd

from ..utils.csv_parser import (
    CSVParseError,
    CSVValidationResult,
    finalize_dataframe,
    parse_sensor_csv,
    validate_raw_dataframe,
)


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _write_csv(tmp_path, content: str, name: str = "test.csv") -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


_VALID_CSV = """,1,2,3
SensorA,100,110,120
SensorB,200,210,220
SensorC,300,310,320
"""

_VALID_CSV_FLOAT_LS = """,1.5,2.5,3.5
SG_001,10.0,11.0,12.0
SG_002,20.0,21.0,22.0
"""


# ================================================================== #
# parse_sensor_csv — happy paths                                      #
# ================================================================== #

class TestParseSensorCsvHappy:
    def test_returns_tuple(self, tmp_path):
        path = _write_csv(tmp_path, _VALID_CSV)
        df, result = parse_sensor_csv(path)
        assert isinstance(df, pd.DataFrame)
        assert isinstance(result, CSVValidationResult)

    def test_valid_csv_is_valid(self, tmp_path):
        path = _write_csv(tmp_path, _VALID_CSV)
        _, result = parse_sensor_csv(path)
        assert result.is_valid
        assert result.errors == []

    def test_shape_matches_raw(self, tmp_path):
        path = _write_csv(tmp_path, _VALID_CSV)
        df, _ = parse_sensor_csv(path)
        # 4 rows (1 header + 3 data), 4 cols (1 name + 3 steps)
        assert df.shape == (4, 4)

    def test_integer_index_and_columns(self, tmp_path):
        path = _write_csv(tmp_path, _VALID_CSV)
        df, _ = parse_sensor_csv(path)
        assert list(df.index) == [0, 1, 2, 3]
        assert list(df.columns) == [0, 1, 2, 3]

    def test_float_load_steps_accepted(self, tmp_path):
        path = _write_csv(tmp_path, _VALID_CSV_FLOAT_LS)
        _, result = parse_sensor_csv(path)
        assert result.is_valid


# ================================================================== #
# parse_sensor_csv — error cases                                      #
# ================================================================== #

class TestParseSensorCsvErrors:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(CSVParseError):
            parse_sensor_csv(str(tmp_path / "nonexistent.csv"))

    def test_empty_file_raises(self, tmp_path):
        path = _write_csv(tmp_path, "")
        with pytest.raises(CSVParseError):
            parse_sensor_csv(path)

    def test_single_row_raises(self, tmp_path):
        path = _write_csv(tmp_path, "1,2,3\n")
        with pytest.raises(CSVParseError, match="at least 2 rows"):
            parse_sensor_csv(path)

    def test_single_column_raises(self, tmp_path):
        path = _write_csv(tmp_path, "header\nSensorA\nSensorB\n")
        with pytest.raises(CSVParseError, match="at least 2 columns"):
            parse_sensor_csv(path)

    def test_non_numeric_load_step_gives_error(self, tmp_path):
        content = ",STEP_A,2,3\nSensorA,1,2,3\n"
        path = _write_csv(tmp_path, content)
        _, result = parse_sensor_csv(path)
        assert not result.is_valid
        assert any("STEP_A" in e for e in result.errors)

    def test_non_numeric_data_cell_gives_error(self, tmp_path):
        content = ",1,2,3\nSensorA,1,BAD,3\n"
        path = _write_csv(tmp_path, content)
        _, result = parse_sensor_csv(path)
        assert not result.is_valid
        assert any("non-numeric" in e for e in result.errors)

    def test_empty_load_step_gives_error(self, tmp_path):
        content = ",1,,3\nSensorA,1,2,3\n"
        path = _write_csv(tmp_path, content)
        _, result = parse_sensor_csv(path)
        assert not result.is_valid


# ================================================================== #
# parse_sensor_csv — warnings                                         #
# ================================================================== #

class TestParseSensorCsvWarnings:
    def test_duplicate_sensor_warning(self, tmp_path):
        content = ",1,2\nSensorA,1,2\nSensorA,3,4\n"
        path = _write_csv(tmp_path, content)
        _, result = parse_sensor_csv(path)
        assert any("Duplicate" in w for w in result.warnings)

    def test_empty_sensor_name_warning(self, tmp_path):
        content = ",1,2\n,1,2\nSensorB,3,4\n"
        path = _write_csv(tmp_path, content)
        _, result = parse_sensor_csv(path)
        assert any("empty sensor name" in w for w in result.warnings)

    def test_no_warnings_for_clean_csv(self, tmp_path):
        path = _write_csv(tmp_path, _VALID_CSV)
        _, result = parse_sensor_csv(path)
        assert result.warnings == []


# ================================================================== #
# validate_raw_dataframe                                              #
# ================================================================== #

class TestValidateRawDataframe:
    def _make_valid_raw(self) -> pd.DataFrame:
        return pd.DataFrame(
            [["", "1", "2", "3"],
             ["SensorA", "100", "110", "120"],
             ["SensorB", "200", "210", "220"]],
            columns=[0, 1, 2, 3],
        )

    def test_valid_raw_df_returns_true(self):
        assert validate_raw_dataframe(self._make_valid_raw())

    def test_too_few_rows_returns_false(self):
        df = pd.DataFrame([[" ", "1"]], columns=[0, 1])
        assert not validate_raw_dataframe(df)

    def test_too_few_columns_returns_false(self):
        df = pd.DataFrame([["hdr"], ["S"]], columns=[0])
        assert not validate_raw_dataframe(df)

    def test_non_numeric_header_returns_false(self):
        df = pd.DataFrame(
            [["", "STEP", "2"],
             ["SensorA", "1", "2"]],
            columns=[0, 1, 2],
        )
        assert not validate_raw_dataframe(df)

    def test_non_numeric_data_returns_false(self):
        df = pd.DataFrame(
            [["", "1", "2"],
             ["SensorA", "not_a_number", "2"]],
            columns=[0, 1, 2],
        )
        assert not validate_raw_dataframe(df)

    def test_empty_header_cell_returns_false(self):
        df = pd.DataFrame(
            [["", "", "2"],
             ["SensorA", "1", "2"]],
            columns=[0, 1, 2],
        )
        assert not validate_raw_dataframe(df)


# ================================================================== #
# finalize_dataframe                                                  #
# ================================================================== #

class TestFinalizeDataframe:
    def _make_raw(self) -> pd.DataFrame:
        return pd.DataFrame(
            [["", "1", "2", "3"],
             ["SensorA", "100", "110", "120"],
             ["SensorB", "200", "210", "220"]],
            columns=[0, 1, 2, 3],
        )

    def test_returns_dataframe(self):
        result = finalize_dataframe(self._make_raw())
        assert isinstance(result, pd.DataFrame)

    def test_index_is_sensor_names(self):
        result = finalize_dataframe(self._make_raw())
        assert list(result.index) == ["SensorA", "SensorB"]

    def test_columns_are_float_load_steps(self):
        result = finalize_dataframe(self._make_raw())
        assert list(result.columns) == [1.0, 2.0, 3.0]

    def test_values_are_numeric(self):
        result = finalize_dataframe(self._make_raw())
        assert all(pd.api.types.is_numeric_dtype(result[c]) for c in result.columns)

    def test_values_correct(self):
        result = finalize_dataframe(self._make_raw())
        assert result.loc["SensorA", 1.0] == 100.0
        assert result.loc["SensorB", 3.0] == 220.0

    def test_too_few_rows_raises(self):
        df = pd.DataFrame([["", "1"]], columns=[0, 1])
        with pytest.raises(CSVParseError):
            finalize_dataframe(df)

    def test_non_numeric_values_become_nan(self):
        raw = pd.DataFrame(
            [["", "1", "2"],
             ["SensorA", "100", "bad_value"]],
            columns=[0, 1, 2],
        )
        result = finalize_dataframe(raw)
        import numpy as np
        assert np.isnan(result.loc["SensorA", 2.0])
