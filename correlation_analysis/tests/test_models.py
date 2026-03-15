"""Unit tests for models."""
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


def test_graph_data_model_series(sample_df):
    dm = DataModel()
    mapping = SensorMapping()
    gdm = GraphDataModel(dm, mapping)
    sid = dm.add_source("t.csv", sample_df)
    x, y = gdm.get_loadstep_series(sid, "SensorA")
    assert list(x) == [1.0, 2.0, 3.0]
    assert list(y) == [100.0, 110.0, 120.0]


def test_sensor_mapping():
    m = SensorMapping()
    m.add_mapping("CanonicalA", "src1", "SensorA_1")
    m.add_mapping("CanonicalA", "src2", "SensorA_2")
    assert m.resolve("src1", "SensorA_1") == "CanonicalA"
    assert m.get_aliases("CanonicalA") == {"src1": "SensorA_1", "src2": "SensorA_2"}
