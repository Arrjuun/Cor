"""Shared pytest fixtures for the correlation_analysis test suite."""
from __future__ import annotations

import sys
import pytest
import pandas as pd


@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication instance for the entire test session."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def sample_df():
    """3-sensor × 3-loadstep DataFrame used by multiple test modules."""
    return pd.DataFrame(
        {
            1.0: [100.0, 200.0, 300.0],
            2.0: [110.0, 210.0, 310.0],
            3.0: [120.0, 220.0, 320.0],
        },
        index=["SensorA", "SensorB", "SensorC"],
    )


@pytest.fixture
def ratio_inputs():
    """Minimal parallel lists suitable for RatioGraphWidget.plot_ratio."""
    sensors  = ["SensorA", "SensorB", "SensorC"]
    values_a = [100.0, 200.0, 300.0]
    values_b = [105.0, 195.0, 305.0]
    ratios   = [a / b for a, b in zip(values_a, values_b)]
    return sensors, values_a, values_b, ratios
