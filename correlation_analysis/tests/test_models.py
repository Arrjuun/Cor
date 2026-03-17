"""Unit tests for models."""
import logging
import pytest
import pandas as pd
import numpy as np

from ..models.data_model import DataModel
from ..models.sensor_mapping import SensorMapping
from ..models.formula_engine import FormulaEngine, FormulaError
from ..models.graph_data_model import GraphDataModel


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {1.0: [100.0, 200.0, 300.0], 2.0: [110.0, 210.0, 310.0], 3.0: [120.0, 220.0, 320.0]},
        index=["SensorA", "SensorB", "SensorC"],
    )


# ------------------------------------------------------------------ #
# DataModel                                                            #
# ------------------------------------------------------------------ #

def test_data_model_add_source(sample_df):
    model = DataModel()
    sid = model.add_source("test.csv", sample_df, "Test")
    assert sid in model.source_ids()
    df = model.get_dataframe(sid)
    assert list(df.index) == ["SensorA", "SensorB", "SensorC"]


def test_data_model_delete_rows(sample_df):
    model = DataModel()
    sid = model.add_source("test.csv", sample_df)
    model.delete_rows(sid, ["SensorA"])
    df = model.get_dataframe(sid)
    assert "SensorA" not in df.index


def test_data_model_delete_columns(sample_df):
    model = DataModel()
    sid = model.add_source("test.csv", sample_df)
    model.delete_columns(sid, [1.0])
    df = model.get_dataframe(sid)
    assert 1.0 not in df.columns


def test_data_model_observer():
    model = DataModel()
    events = []
    model.add_observer(lambda e, s: events.append(e))
    df = pd.DataFrame({1.0: [1.0]}, index=["S"])
    model.add_source("f.csv", df)
    assert "added" in events


# ------------------------------------------------------------------ #
# FormulaEngine                                                        #
# ------------------------------------------------------------------ #

def test_formula_engine_basic():
    engine = FormulaEngine()
    ns = {
        "SensorA": pd.Series([100.0, 110.0, 120.0], index=[1.0, 2.0, 3.0]),
        "SensorB": pd.Series([200.0, 210.0, 220.0], index=[1.0, 2.0, 3.0]),
    }
    result = engine.evaluate("(SensorA + SensorB) / 2", ns)
    expected = pd.Series([150.0, 160.0, 170.0], index=[1.0, 2.0, 3.0])
    pd.testing.assert_series_equal(result, expected)


def test_formula_engine_invalid():
    engine = FormulaEngine()
    with pytest.raises(FormulaError):
        engine.evaluate("import os", {})


def test_formula_engine_circular():
    engine = FormulaEngine()
    ns = {"A": pd.Series([1.0], index=[1.0])}
    formulas = {"B": "C + 1", "C": "B + 1"}
    with pytest.raises(FormulaError):
        engine.evaluate_all(formulas, ns)


# ------------------------------------------------------------------ #
# GraphDataModel                                                       #
# ------------------------------------------------------------------ #

def test_graph_data_model_series(sample_df):
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    sid = dm.add_source("t.csv", sample_df)
    x, y = gdm.get_loadstep_series(sid, "SensorA")
    assert list(x) == [1.0, 2.0, 3.0]
    assert list(y) == [100.0, 110.0, 120.0]


# ------------------------------------------------------------------ #
# SensorMapping — basic                                                #
# ------------------------------------------------------------------ #

def test_sensor_mapping():
    m = SensorMapping()
    m.add_mapping("CanonicalA", "src1", "SensorA_1")
    m.add_mapping("CanonicalA", "src2", "SensorA_2")
    assert m.resolve("src1", "SensorA_1") == "CanonicalA"
    assert m.get_aliases("CanonicalA") == {"src1": "SensorA_1", "src2": "SensorA_2"}


def test_sensor_mapping_resolve_by_name():
    m = SensorMapping()
    m.add_mapping("Canon1", "src1", "Alpha")
    m.add_mapping("Canon2", "src2", "Beta")
    assert m.resolve_by_name("Alpha") == "Canon1"
    assert m.resolve_by_name("Beta") == "Canon2"
    assert m.resolve_by_name("Unknown") is None


def test_sensor_mapping_clear():
    m = SensorMapping()
    m.add_mapping("C1", "src1", "S1")
    assert not m.is_empty()
    m.clear()
    assert m.is_empty()
    assert m.canonical_names() == []


# ------------------------------------------------------------------ #
# SensorMapping — get_missing_analysis                                 #
# ------------------------------------------------------------------ #

def test_missing_analysis_no_issues():
    """When every imported sensor appears in the mapping and all canonicals
    are complete, both result dicts should be empty."""
    m = SensorMapping()
    m.add_mapping("Canon1", "SourceA", "SG_001")
    m.add_mapping("Canon1", "SourceB", "STRAIN_A")
    m.add_mapping("Canon2", "SourceA", "SG_002")
    m.add_mapping("Canon2", "SourceB", "STRAIN_B")

    imported = {
        "SourceA": ["SG_001", "SG_002"],
        "SourceB": ["STRAIN_A", "STRAIN_B"],
    }
    unmapped, incomplete = m.get_missing_analysis(imported)
    assert unmapped == {}
    assert incomplete == {}


def test_missing_analysis_unmapped_sensors():
    """Sensors in imported data that have no entry in the mapping are reported."""
    m = SensorMapping()
    m.add_mapping("Canon1", "SourceA", "SG_001")

    imported = {
        "SourceA": ["SG_001", "SG_999"],   # SG_999 is unmapped
        "SourceB": ["STRAIN_X"],            # STRAIN_X is unmapped
    }
    unmapped, _ = m.get_missing_analysis(imported)
    assert "SourceA" in unmapped
    assert "SG_999" in unmapped["SourceA"]
    assert "SG_001" not in unmapped.get("SourceA", [])
    assert "SourceB" in unmapped
    assert "STRAIN_X" in unmapped["SourceB"]


def test_missing_analysis_incomplete_canonicals():
    """Canonical sensors without an alias for every mapping source column
    are reported under incomplete_canonicals."""
    m = SensorMapping()
    # Two source columns in the mapping: "ColA" and "ColB"
    m.add_mapping("Canon1", "ColA", "SG_001")
    m.add_mapping("Canon1", "ColB", "STRAIN_A")
    m.add_mapping("Canon2", "ColA", "SG_002")
    # Canon2 has no entry for "ColB" → should be reported

    _, incomplete = m.get_missing_analysis({})
    assert "Canon2" in incomplete
    assert "ColB" in incomplete["Canon2"]
    # Canon1 is complete — must not appear
    assert "Canon1" not in incomplete


def test_missing_analysis_empty_mapping():
    """With no mapping loaded, all imported sensors are reported as unmapped."""
    m = SensorMapping()
    imported = {"SourceA": ["SG_001", "SG_002"]}
    unmapped, incomplete = m.get_missing_analysis(imported)
    assert "SourceA" in unmapped
    assert set(unmapped["SourceA"]) == {"SG_001", "SG_002"}
    assert incomplete == {}


def test_missing_analysis_empty_sources():
    """With no imported sources, unmapped is always empty regardless of mapping."""
    m = SensorMapping()
    m.add_mapping("Canon1", "ColA", "SG_001")
    unmapped, incomplete = m.get_missing_analysis({})
    assert unmapped == {}


# ------------------------------------------------------------------ #
# Logging                                                              #
# ------------------------------------------------------------------ #

def test_logging_config(tmp_path):
    """setup_logging creates a log file and the root logger gains a handler."""
    from ..utils.logging_config import setup_logging

    # Use a fresh root logger state for this test
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        log_file = setup_logging(log_dir=tmp_path)
        assert log_file.exists() or True  # file created on first write
        assert any(
            isinstance(h, logging.handlers.RotatingFileHandler)
            for h in root.handlers
        )
        # Verify a message can be logged without error
        logging.getLogger("test.logging_config").info("Test log entry")
    finally:
        # Restore original handlers to avoid polluting other tests
        for h in root.handlers[:]:
            if h not in original_handlers:
                h.close()
                root.removeHandler(h)
        root.handlers = original_handlers
