"""Tests for presenter logic — focused on session config round-trip for ref_bands."""
from __future__ import annotations

import pytest


# ================================================================== #
# Session config round-trip via RatioGraphWidget                     #
# (GraphPresenter.restore_graphs_from_config replays to_config output)
# ================================================================== #

class TestSessionConfigRoundTrip:
    """
    These tests verify the contract between to_config() and
    restore_graphs_from_config():  any ref_bands saved by the widget
    must survive serialisation and be re-applied on restore.

    We exercise this at the widget level because the presenter's restore
    path calls rg.plot_ratio(...) then rg.add_slope_band(pct) for each
    saved band — identical to what these tests do manually.
    """

    def _make_widget(self, qapp):
        from ..views.ratio_graph import RatioGraphWidget
        return RatioGraphWidget()

    def _plot(self, widget):
        widget.plot_ratio(
            ["SA", "SB", "SC"],
            [100.0, 200.0, 300.0],
            [105.0, 195.0, 305.0],
            [100/105, 200/195, 300/305],
            load_step=2.0,
            label_a="Src A",
            label_b="Src B",
        )

    def test_config_with_no_bands_round_trips(self, qapp):
        w = self._make_widget(qapp)
        self._plot(w)
        cfg = w.to_config()
        assert cfg["ref_bands"] == []

        w2 = self._make_widget(qapp)
        w2.plot_ratio(
            cfg["sensors"], cfg["values_a"], cfg["values_b"], cfg["ratios"],
            load_step=cfg["load_step"], label_a=cfg["label_a"], label_b=cfg["label_b"],
        )
        for pct in cfg["ref_bands"]:
            w2.add_slope_band(pct)
        assert w2._ref_bands == []

    def test_config_with_one_band_round_trips(self, qapp):
        w = self._make_widget(qapp)
        self._plot(w)
        w.add_slope_band(10.0)
        cfg = w.to_config()
        assert cfg["ref_bands"] == [10.0]

        w2 = self._make_widget(qapp)
        w2.plot_ratio(
            cfg["sensors"], cfg["values_a"], cfg["values_b"], cfg["ratios"],
            load_step=cfg["load_step"], label_a=cfg["label_a"], label_b=cfg["label_b"],
        )
        for pct in cfg["ref_bands"]:
            w2.add_slope_band(pct)
        assert [b["pct"] for b in w2._ref_bands] == [10.0]

    def test_config_with_multiple_bands_round_trips(self, qapp):
        w = self._make_widget(qapp)
        self._plot(w)
        w.add_slope_band(10.0)
        w.add_slope_band(50.0)
        cfg = w.to_config()
        assert cfg["ref_bands"] == [10.0, 50.0]

        w2 = self._make_widget(qapp)
        w2.plot_ratio(
            cfg["sensors"], cfg["values_a"], cfg["values_b"], cfg["ratios"],
            load_step=cfg["load_step"], label_a=cfg["label_a"], label_b=cfg["label_b"],
        )
        for pct in cfg["ref_bands"]:
            w2.add_slope_band(pct)
        assert [b["pct"] for b in w2._ref_bands] == [10.0, 50.0]

    def test_old_config_without_ref_bands_key_is_safe(self, qapp):
        """Configs saved before ref_bands was added must not crash on restore."""
        w = self._make_widget(qapp)
        self._plot(w)
        cfg = w.to_config()
        cfg.pop("ref_bands")   # simulate old session file

        w2 = self._make_widget(qapp)
        w2.plot_ratio(
            cfg["sensors"], cfg["values_a"], cfg["values_b"], cfg["ratios"],
            load_step=cfg["load_step"], label_a=cfg["label_a"], label_b=cfg["label_b"],
        )
        for pct in cfg.get("ref_bands", []):   # presenter uses .get(..., [])
            w2.add_slope_band(pct)
        assert w2._ref_bands == []

    def test_export_data_ref_bands_matches_config(self, qapp):
        """get_export_data ref_bands must equal to_config ref_bands."""
        w = self._make_widget(qapp)
        self._plot(w)
        w.add_slope_band(10.0)
        w.add_slope_band(50.0)
        assert w.get_export_data()["ref_bands"] == w.to_config()["ref_bands"]


# ================================================================== #
# Import / session presenter — smoke tests                           #
# ================================================================== #

class TestImportPresenterSmoke:
    """Light smoke tests — verify core models wire up without error."""

    def test_data_model_add_and_remove(self):
        import pandas as pd
        from ..models.data_model import DataModel

        dm = DataModel()
        df = pd.DataFrame({1.0: [1.0, 2.0]}, index=["S1", "S2"])
        sid = dm.add_source("f.csv", df, "Test")
        assert sid in dm.source_ids()
        dm.remove_source(sid)
        assert sid not in dm.source_ids()

    def test_session_model_save_load(self, tmp_path):
        from ..models.session_model import SessionModel

        sm = SessionModel()
        state = {
            "sources": {},
            "mapping": {},
            "tabs": [
                {
                    "tab_name": "Tab 1",
                    "num_columns": 1,
                    "graphs": [
                        {
                            "type": "ratio",
                            "title": "R1",
                            "sensors": ["SA", "SB"],
                            "values_a": [1.0, 2.0],
                            "values_b": [1.1, 1.9],
                            "ratios": [1/1.1, 2/1.9],
                            "label_a": "A",
                            "label_b": "B",
                            "load_step": 1.0,
                            "ref_bands": [10.0, 50.0],
                        }
                    ],
                }
            ],
        }
        filepath = str(tmp_path / "test_session.csa")
        sm.save(filepath, state)
        loaded = sm.load(filepath)

        graph_cfg = loaded["tabs"][0]["graphs"][0]
        assert graph_cfg["ref_bands"] == [10.0, 50.0]

    def test_session_model_old_format_no_ref_bands(self, tmp_path):
        """Session files without ref_bands (pre-feature) load without error."""
        from ..models.session_model import SessionModel

        sm = SessionModel()
        state = {
            "sources": {},
            "mapping": {},
            "tabs": [
                {
                    "tab_name": "Tab 1",
                    "num_columns": 1,
                    "graphs": [
                        {
                            "type": "ratio",
                            "title": "R1",
                            "sensors": ["SA"],
                            "values_a": [1.0],
                            "values_b": [1.1],
                            "ratios": [1/1.1],
                            "label_a": "A",
                            "label_b": "B",
                            "load_step": 1.0,
                            # no ref_bands key
                        }
                    ],
                }
            ],
        }
        filepath = str(tmp_path / "old_session.csa")
        sm.save(filepath, state)
        loaded = sm.load(filepath)

        graph_cfg = loaded["tabs"][0]["graphs"][0]
        # restore path uses .get("ref_bands", []) — absence is valid
        assert graph_cfg.get("ref_bands", []) == []
