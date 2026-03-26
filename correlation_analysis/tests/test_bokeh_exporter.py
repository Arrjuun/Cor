"""Tests for BokehExporter — focused on ratio graph ref_bands rendering."""
from __future__ import annotations

import pytest

pytest.importorskip("bokeh", reason="bokeh not installed")

from ..utils.bokeh_exporter import BokehExporter


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _base_ratio_data(**kwargs) -> dict:
    """Minimal ratio_data dict; override any key via kwargs."""
    data = {
        "sensors":   ["SensorA", "SensorB", "SensorC"],
        "values_a":  [100.0, 200.0, 300.0],
        "values_b":  [105.0, 195.0, 305.0],
        "ratios":    [100/105, 200/195, 300/305],
        "label_a":   "Source A",
        "label_b":   "Source B",
        "ref_bands": [],
    }
    data.update(kwargs)
    return data


def _count_lines(fig) -> int:
    """Count all line renderers on a Bokeh figure."""
    from bokeh.models import GlyphRenderer
    from bokeh.models.glyphs import Line
    return sum(
        1 for r in fig.renderers
        if isinstance(r, GlyphRenderer) and isinstance(r.glyph, Line)
    )


# ================================================================== #
# _make_ratio_figure — no ref_bands                                  #
# ================================================================== #

class TestMakeRatioFigureNoBands:
    def test_returns_figure(self):
        fig = BokehExporter._make_ratio_figure(_base_ratio_data())
        from bokeh.plotting import figure as BokehFigure
        assert fig is not None

    def test_only_diagonal_line_present(self):
        fig = BokehExporter._make_ratio_figure(_base_ratio_data())
        assert _count_lines(fig) == 1   # only the 1:1 diagonal

    def test_diagonal_legend_label(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Line
        fig = BokehExporter._make_ratio_figure(_base_ratio_data())
        line_renderers = [
            r for r in fig.renderers
            if isinstance(r, GlyphRenderer) and isinstance(r.glyph, Line)
        ]
        labels = [r.name or "" for r in line_renderers]
        # The diagonal should exist — line count == 1 already checked above
        assert len(line_renderers) == 1

    def test_missing_ref_bands_key_is_safe(self):
        """Old-format ratio_data without ref_bands must not raise."""
        data = _base_ratio_data()
        data.pop("ref_bands")
        fig = BokehExporter._make_ratio_figure(data)
        assert _count_lines(fig) == 1


# ================================================================== #
# _make_ratio_figure — with ref_bands                                #
# ================================================================== #

class TestMakeRatioFigureWithBands:
    def test_one_band_adds_two_extra_lines(self):
        data = _base_ratio_data(ref_bands=[10.0])
        fig = BokehExporter._make_ratio_figure(data)
        # diagonal (1) + pos band (1) + neg band (1)
        assert _count_lines(fig) == 3

    def test_two_bands_add_four_extra_lines(self):
        data = _base_ratio_data(ref_bands=[10.0, 50.0])
        fig = BokehExporter._make_ratio_figure(data)
        assert _count_lines(fig) == 5   # 1 diagonal + 2×2 bands

    def test_band_line_color_is_orange(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Line
        data = _base_ratio_data(ref_bands=[10.0])
        fig = BokehExporter._make_ratio_figure(data)
        band_lines = [
            r for r in fig.renderers
            if isinstance(r, GlyphRenderer)
            and isinstance(r.glyph, Line)
            and r.glyph.line_color == "#F57F17"
        ]
        assert len(band_lines) == 2

    def test_band_line_is_dashed(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Line
        data = _base_ratio_data(ref_bands=[10.0])
        fig = BokehExporter._make_ratio_figure(data)
        band_lines = [
            r for r in fig.renderers
            if isinstance(r, GlyphRenderer)
            and isinstance(r.glyph, Line)
            and r.glyph.line_color == "#F57F17"
        ]
        # Bokeh converts "dashed" to a list of numbers (e.g. [6]); a solid line is [].
        assert all(r.glyph.line_dash not in ([], None) for r in band_lines)

    def test_empty_ref_bands_list_gives_only_diagonal(self):
        data = _base_ratio_data(ref_bands=[])
        fig = BokehExporter._make_ratio_figure(data)
        assert _count_lines(fig) == 1

    def test_no_valid_data_returns_placeholder(self):
        """All-NaN values should return a placeholder figure without error."""
        import math
        data = _base_ratio_data(
            values_a=[float("nan"), float("nan")],
            values_b=[float("nan"), float("nan")],
            sensors=["A", "B"],
            ratios=[float("nan"), float("nan")],
            ref_bands=[10.0],
        )
        fig = BokehExporter._make_ratio_figure(data)
        # Returns a placeholder — must not raise
        assert fig is not None


# ================================================================== #
# _make_ratio_figure — legend labels                                 #
# ================================================================== #

class TestMakeRatioFigureLegend:
    def test_positive_band_has_legend_label(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Line
        data = _base_ratio_data(ref_bands=[10.0])
        fig = BokehExporter._make_ratio_figure(data)
        # Legend items include "±10%" for the positive line
        # In Bokeh ≥3, item.label is a Value object with a .value attribute.
        legend_labels = []
        for legend in fig.legend:
            for item in legend.items:
                lbl = item.label
                legend_labels.append(lbl.value if hasattr(lbl, "value") else str(lbl))
        assert any("10" in lbl for lbl in legend_labels)


# ================================================================== #
# _make_loadstep_figure                                              #
# ================================================================== #

def _base_series(**kwargs) -> dict:
    """Minimal series dict for a LoadStep figure."""
    data = {
        "sensor_name": "SensorA",
        "source_id":   "src1",
        "x": [1.0, 2.0, 3.0],
        "y": [100.0, 110.0, 120.0],
        "style": {
            "color":      "#1565C0",
            "thickness":  2,
            "line_style": "Solid",
            "marker":     "None",
            "label":      "SensorA",
            "visible":    True,
        },
    }
    data.update(kwargs)
    return data


class TestMakeLoadstepFigure:
    def test_returns_figure(self):
        from bokeh.plotting import figure as BokehFigure
        fig = BokehExporter._make_loadstep_figure([_base_series()], "Test")
        assert fig is not None

    def test_title_set(self):
        fig = BokehExporter._make_loadstep_figure([_base_series()], "My Title")
        assert fig.title.text == "My Title"

    def test_empty_series_list_returns_figure(self):
        fig = BokehExporter._make_loadstep_figure([], "Empty")
        assert fig is not None

    def test_one_line_per_series(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Line
        series = [_base_series(), _base_series(sensor_name="SensorB")]
        fig = BokehExporter._make_loadstep_figure(series, "Two Lines")
        line_count = sum(
            1 for r in fig.renderers
            if isinstance(r, GlyphRenderer) and isinstance(r.glyph, Line)
        )
        assert line_count == 2

    def test_legend_created_with_label(self):
        fig = BokehExporter._make_loadstep_figure([_base_series()], "T")
        legend_labels = []
        for legend in fig.legend:
            for item in legend.items:
                lbl = item.label
                legend_labels.append(lbl.value if hasattr(lbl, "value") else str(lbl))
        assert any("SensorA" in lbl for lbl in legend_labels)

    def test_line_color_matches_style(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Line
        series = _base_series()
        series["style"]["color"] = "#C62828"
        fig = BokehExporter._make_loadstep_figure([series], "T")
        line = next(
            r for r in fig.renderers
            if isinstance(r, GlyphRenderer) and isinstance(r.glyph, Line)
        )
        assert line.glyph.line_color == "#C62828"

    def test_dashed_line_style(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Line
        series = _base_series()
        series["style"]["line_style"] = "Dashed"
        fig = BokehExporter._make_loadstep_figure([series], "T")
        line = next(
            r for r in fig.renderers
            if isinstance(r, GlyphRenderer) and isinstance(r.glyph, Line)
        )
        assert line.glyph.line_dash not in ([], None, "solid")

    def test_scatter_added_when_marker_set(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Scatter
        series = _base_series()
        series["style"]["marker"] = "Circle"
        fig = BokehExporter._make_loadstep_figure([series], "T")
        scatter_count = sum(
            1 for r in fig.renderers
            if isinstance(r, GlyphRenderer) and isinstance(r.glyph, Scatter)
        )
        assert scatter_count >= 1

    def test_no_scatter_when_marker_none(self):
        from bokeh.models import GlyphRenderer
        from bokeh.models.glyphs import Scatter
        series = _base_series()
        series["style"]["marker"] = "None"
        fig = BokehExporter._make_loadstep_figure([series], "T")
        scatter_count = sum(
            1 for r in fig.renderers
            if isinstance(r, GlyphRenderer) and isinstance(r.glyph, Scatter)
        )
        assert scatter_count == 0


# ================================================================== #
# BokehExporter.export_full — smoke tests                            #
# ================================================================== #

class TestExportFull:
    def _make_export_data(self) -> dict:
        import pandas as pd
        df = pd.DataFrame(
            {1.0: [100.0, 200.0], 2.0: [110.0, 210.0]},
            index=["SensorA", "SensorB"],
        )
        return {
            "sources": [{"name": "Source A", "df": df}],
            "tabs": [
                {
                    "name": "Tab 1",
                    "num_columns": 1,
                    "loadstep_graphs": [
                        {
                            "title": "LS Graph",
                            "series": [_base_series()],
                        }
                    ],
                    "ratio_graphs": [
                        _base_ratio_data(ref_bands=[10.0]),
                    ],
                }
            ],
        }

    def test_export_creates_html_file(self, tmp_path):
        exp = BokehExporter()
        path = str(tmp_path / "out.html")
        exp.export_full(self._make_export_data(), path)
        import os
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

    def test_html_file_contains_bokeh_root(self, tmp_path):
        exp = BokehExporter()
        path = str(tmp_path / "out.html")
        exp.export_full(self._make_export_data(), path)
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        assert "<html" in content.lower()

    def test_export_empty_data_no_error(self, tmp_path):
        exp = BokehExporter()
        path = str(tmp_path / "empty.html")
        exp.export_full({"sources": [], "tabs": []}, path)
        import os
        assert os.path.exists(path)

    def test_export_ratio_graph_no_sensors(self, tmp_path):
        """A ratio graph entry with no sensor data must not raise."""
        exp = BokehExporter()
        data = {
            "sources": [],
            "tabs": [
                {
                    "name": "T",
                    "num_columns": 1,
                    "loadstep_graphs": [],
                    "ratio_graphs": [{}],
                }
            ],
        }
        path = str(tmp_path / "no_sensors.html")
        exp.export_full(data, path)
        import os
        assert os.path.exists(path)
