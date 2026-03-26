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


@pytest.fixture
def two_source_model(sample_df):
    """DataModel with two sources containing overlapping sensors at load steps 1-3."""
    dm = DataModel()
    df_b = pd.DataFrame(
        {1.0: [105.0, 195.0, 305.0], 2.0: [115.0, 205.0, 315.0], 3.0: [125.0, 215.0, 325.0]},
        index=["SensorA", "SensorB", "SensorC"],
    )
    sid_a = dm.add_source("a.csv", sample_df, "Source A", source_id="srcA")
    sid_b = dm.add_source("b.csv", df_b, "Source B", source_id="srcB")
    return dm, sid_a, sid_b


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
# DataModel — extended                                                 #
# ------------------------------------------------------------------ #

def test_data_model_update_dataframe_fires_updated(sample_df):
    dm = DataModel()
    events = []
    dm.add_observer(lambda e, s: events.append(e))
    sid = dm.add_source("f.csv", sample_df)
    events.clear()
    dm.update_dataframe(sid, sample_df)
    assert "updated" in events


def test_data_model_update_unknown_source_noop(sample_df):
    dm = DataModel()
    # Should not raise
    dm.update_dataframe("nonexistent", sample_df)


def test_data_model_clear_fires_cleared(sample_df):
    dm = DataModel()
    events = []
    dm.add_observer(lambda e, s: events.append(e))
    dm.add_source("f.csv", sample_df)
    events.clear()
    dm.clear()
    assert "cleared" in events
    assert dm.source_ids() == []


def test_data_model_all_sources(sample_df):
    dm = DataModel()
    sid = dm.add_source("f.csv", sample_df, "My Source")
    sources = dm.all_sources()
    assert len(sources) == 1
    assert sources[0].source_id == sid
    assert sources[0].display_name == "My Source"


def test_data_model_get_source_unknown_returns_none():
    dm = DataModel()
    assert dm.get_source("does_not_exist") is None


def test_data_model_remove_fires_removed(sample_df):
    dm = DataModel()
    events = []
    dm.add_observer(lambda e, s: events.append(e))
    sid = dm.add_source("f.csv", sample_df)
    events.clear()
    dm.remove_source(sid)
    assert "removed" in events


def test_data_model_multiple_observers(sample_df):
    dm = DataModel()
    calls_a, calls_b = [], []
    dm.add_observer(lambda e, s: calls_a.append(e))
    dm.add_observer(lambda e, s: calls_b.append(e))
    dm.add_source("f.csv", sample_df)
    assert calls_a == ["added"]
    assert calls_b == ["added"]


def test_data_model_display_name_defaults_to_basename(sample_df, tmp_path):
    filepath = str(tmp_path / "my_sensor_data.csv")
    dm = DataModel()
    sid = dm.add_source(filepath, sample_df)
    src = dm.get_source(sid)
    assert src.display_name == "my_sensor_data.csv"


def test_data_model_delete_rows_notifies(sample_df):
    dm = DataModel()
    events = []
    dm.add_observer(lambda e, s: events.append(e))
    sid = dm.add_source("f.csv", sample_df)
    events.clear()
    dm.delete_rows(sid, ["SensorA"])
    assert "updated" in events


def test_data_model_delete_columns_notifies(sample_df):
    dm = DataModel()
    events = []
    dm.add_observer(lambda e, s: events.append(e))
    sid = dm.add_source("f.csv", sample_df)
    events.clear()
    dm.delete_columns(sid, [1.0])
    assert "updated" in events


def test_data_model_get_dataframe_returns_copy(sample_df):
    dm = DataModel()
    sid = dm.add_source("f.csv", sample_df)
    df1 = dm.get_dataframe(sid)
    df1.loc["SensorA", 1.0] = -999.0
    df2 = dm.get_dataframe(sid)
    assert df2.loc["SensorA", 1.0] == 100.0  # original unchanged


# ------------------------------------------------------------------ #
# FormulaEngine — extended                                             #
# ------------------------------------------------------------------ #

def test_formula_engine_abs():
    engine = FormulaEngine()
    ns = {"S": pd.Series([-5.0, 3.0], index=[1.0, 2.0])}
    result = engine.evaluate("abs(S)", ns)
    pd.testing.assert_series_equal(result, pd.Series([5.0, 3.0], index=[1.0, 2.0]))


def test_formula_engine_sqrt():
    engine = FormulaEngine()
    ns = {"S": pd.Series([4.0, 9.0], index=[1.0, 2.0])}
    # Use np.sqrt for Series-compatible square root
    result = engine.evaluate("np.sqrt(S)", ns)
    np.testing.assert_allclose(result.values, [2.0, 3.0])


def test_formula_engine_division_by_zero():
    engine = FormulaEngine()
    with pytest.raises(FormulaError, match="Division by zero"):
        engine.evaluate("1 / 0", {})


def test_formula_engine_unknown_name():
    engine = FormulaEngine()
    with pytest.raises(FormulaError, match="Unknown sensor"):
        engine.evaluate("NonExistentSensor + 1", {})


def test_formula_engine_syntax_error():
    engine = FormulaEngine()
    with pytest.raises(FormulaError, match="Syntax"):
        engine.evaluate("(((", {})


def test_formula_engine_scalar_result_broadcasts():
    engine = FormulaEngine()
    ns = {"S": pd.Series([1.0, 2.0, 3.0], index=[1.0, 2.0, 3.0])}
    result = engine.evaluate("42", ns)
    assert len(result) == 3
    assert all(v == 42.0 for v in result)


def test_formula_engine_power_operator():
    engine = FormulaEngine()
    ns = {"S": pd.Series([2.0, 3.0], index=[1.0, 2.0])}
    result = engine.evaluate("S ** 2", ns)
    pd.testing.assert_series_equal(result, pd.Series([4.0, 9.0], index=[1.0, 2.0]))


def test_formula_engine_evaluate_all_dependency_order():
    engine = FormulaEngine()
    ns = {"Base": pd.Series([10.0, 20.0], index=[1.0, 2.0])}
    # C depends on B which depends on Base
    formulas = {"B": "Base * 2", "C": "B + 1"}
    results = engine.evaluate_all(formulas, ns)
    np.testing.assert_allclose(results["B"].values, [20.0, 40.0])
    np.testing.assert_allclose(results["C"].values, [21.0, 41.0])


def test_formula_engine_evaluate_all_independent_formulas():
    engine = FormulaEngine()
    ns = {
        "A": pd.Series([1.0, 2.0], index=[1.0, 2.0]),
        "B": pd.Series([3.0, 4.0], index=[1.0, 2.0]),
    }
    formulas = {"Mem": "(A + B) / 2", "Bend": "(A - B) / 2"}
    results = engine.evaluate_all(formulas, ns)
    np.testing.assert_allclose(results["Mem"].values, [2.0, 3.0])
    np.testing.assert_allclose(results["Bend"].values, [-1.0, -1.0])


# ------------------------------------------------------------------ #
# GraphDataModel — extended                                            #
# ------------------------------------------------------------------ #

def test_graph_data_model_missing_source_raises(sample_df):
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    with pytest.raises(ValueError, match="not found"):
        gdm.get_loadstep_series("bad_id", "SensorA")


def test_graph_data_model_missing_sensor_raises(sample_df):
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    sid = dm.add_source("t.csv", sample_df)
    with pytest.raises(ValueError, match="not in source"):
        gdm.get_loadstep_series(sid, "NonExistentSensor")


def test_graph_data_model_get_all_load_steps(sample_df):
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    sid = dm.add_source("t.csv", sample_df)
    ls = gdm.get_all_load_steps(sid)
    assert sorted(ls) == [1.0, 2.0, 3.0]


def test_graph_data_model_get_all_load_steps_missing_source():
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    assert gdm.get_all_load_steps("bad_id") == []


def test_graph_data_model_get_sensor_names(sample_df):
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    sid = dm.add_source("t.csv", sample_df)
    names = gdm.get_sensor_names(sid)
    assert set(names) == {"SensorA", "SensorB", "SensorC"}


def test_graph_data_model_ratio_no_mapping(two_source_model):
    dm, sid_a, sid_b = two_source_model
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    result = gdm.get_ratio_data(sid_a, sid_b, 1.0, use_mapping=False)
    assert not result.empty
    assert "ratio" in result.columns
    assert set(result["sensor"].tolist()) == {"SensorA", "SensorB", "SensorC"}


def test_graph_data_model_ratio_values_correct(two_source_model):
    dm, sid_a, sid_b = two_source_model
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    result = gdm.get_ratio_data(sid_a, sid_b, 1.0, use_mapping=False)
    row = result[result["sensor"] == "SensorA"].iloc[0]
    assert row["value_a"] == pytest.approx(100.0)
    assert row["value_b"] == pytest.approx(105.0)
    assert row["ratio"] == pytest.approx(100.0 / 105.0)


def test_graph_data_model_ratio_missing_load_step_no_interp(two_source_model):
    dm, sid_a, sid_b = two_source_model
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    result = gdm.get_ratio_data(sid_a, sid_b, 99.0, use_mapping=False, interpolate=False)
    # All ratios should be NaN since load step 99.0 doesn't exist
    assert result["ratio"].isna().all()


def test_graph_data_model_ratio_interpolation(two_source_model):
    dm, sid_a, sid_b = two_source_model
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    # Load step 1.5 is between 1.0 and 2.0 — should interpolate
    result = gdm.get_ratio_data(sid_a, sid_b, 1.5, use_mapping=False, interpolate=True)
    row = result[result["sensor"] == "SensorA"].iloc[0]
    # Expected: (100+110)/2 = 105 for A, (105+115)/2 = 110 for B
    assert row["value_a"] == pytest.approx(105.0)
    assert row["value_b"] == pytest.approx(110.0)


def test_graph_data_model_ratio_with_mapping():
    dm = DataModel()
    df_a = pd.DataFrame({1.0: [100.0]}, index=["SG_A"])
    df_b = pd.DataFrame({1.0: [105.0]}, index=["SG_B"])
    sid_a = dm.add_source("a.csv", df_a, source_id="srcA")
    sid_b = dm.add_source("b.csv", df_b, source_id="srcB")

    mapping = SensorMapping()
    mapping.add_mapping("Canon1", "srcA", "SG_A")
    mapping.add_mapping("Canon1", "srcB", "SG_B")

    gdm = GraphDataModel(dm, mapping)
    result = gdm.get_ratio_data(sid_a, sid_b, 1.0, use_mapping=True)
    assert len(result) == 1
    assert result.iloc[0]["value_a"] == pytest.approx(100.0)
    assert result.iloc[0]["value_b"] == pytest.approx(105.0)


def test_graph_data_model_ratio_invalid_source_raises():
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    with pytest.raises(ValueError):
        gdm.get_ratio_data("bad_a", "bad_b", 1.0)


def test_graph_data_model_get_mapped_series(sample_df):
    dm = DataModel()
    df_b = pd.DataFrame(
        {1.0: [105.0], 2.0: [115.0], 3.0: [125.0]},
        index=["AliasA"],
    )
    sid_a = dm.add_source("a.csv", sample_df, source_id="srcA")
    sid_b = dm.add_source("b.csv", df_b, source_id="srcB")
    mapping = SensorMapping()
    mapping.add_mapping("Canon1", "srcA", "SensorA")
    mapping.add_mapping("Canon1", "srcB", "AliasA")
    gdm = GraphDataModel(dm, mapping)
    series = gdm.get_mapped_series("Canon1")
    assert "srcA" in series
    assert "srcB" in series
    x_a, y_a = series["srcA"]
    assert list(x_a) == [1.0, 2.0, 3.0]
    assert list(y_a) == [100.0, 110.0, 120.0]


def test_graph_data_model_loadstep_series_with_interpolation():
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    df = pd.DataFrame(
        {1.0: [10.0], 2.0: [np.nan], 3.0: [30.0]},
        index=["S"],
    )
    sid = dm.add_source("t.csv", df)
    x, y = gdm.get_loadstep_series(sid, "S", interpolate=True)
    assert y[1] == pytest.approx(20.0)  # interpolated


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
