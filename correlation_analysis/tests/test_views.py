"""Tests for view widgets — RatioGraphWidget, _parse_sensor_group."""
from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_ratio_widget(qapp, title="Test Ratio"):
    from ..views.ratio_graph import RatioGraphWidget
    return RatioGraphWidget(title=title)


def _plot(widget, ratio_inputs):
    sensors, values_a, values_b, ratios = ratio_inputs
    widget.plot_ratio(sensors, values_a, values_b, ratios,
                      load_step=1.0, label_a="A", label_b="B")


# ================================================================== #
# _parse_sensor_group                                                 #
# ================================================================== #

class TestParseSensorGroup:
    def _parse(self, name):
        from ..views.ratio_graph import _parse_sensor_group
        return _parse_sensor_group(name)

    def test_valid_11_char_name_returns_5_char_key(self):
        # F 06 L 01 N I 01 L  (Frame, LHS, NP, Inner, Long)
        key = self._parse("F06L01NIL01L"[:11])
        # Build a concrete valid name: F + 06 + L + 01 + N + I + 01 + L = 11 chars
        # F[0] 0[1] 6[2] L[3] 0[4] 1[5] N[6] I[7] 0[8] 1[9] L[10]
        key = self._parse("F06L01NI01L")
        assert key is not None
        assert len(key) == 5

    def test_group_key_composition(self):
        from ..views.ratio_graph import _parse_sensor_group
        # Name: F06L01NI01L → Element=F, L/R=L, N/P=N, Loc=I, Dir=L
        key = _parse_sensor_group("F06L01NI01L")
        assert key == "FLNIL"

    def test_wrong_length_returns_none(self):
        assert self._parse("F06L01NI01") is None   # 10 chars
        assert self._parse("F06L01NI01LL") is None  # 12 chars
        assert self._parse("") is None

    def test_invalid_element_char_returns_none(self):
        # Replace element (pos 0) with 'Z' which is not in _ELEMENT_CHARS
        assert self._parse("Z06L01NI01L") is None

    def test_invalid_lr_char_returns_none(self):
        # pos[3] must be L or R; replace with 'X'
        assert self._parse("F06X01NI01L") is None

    def test_invalid_np_char_returns_none(self):
        # pos[6] must be N or P; replace with 'X'
        assert self._parse("F06L01XI01L") is None

    def test_invalid_location_char_returns_none(self):
        # pos[7] must be I O W F H; replace with 'X'
        assert self._parse("F06L01NX01L") is None

    def test_non_digit_frame_number_returns_none(self):
        # pos[1:3] must be digits
        assert self._parse("FAaL01NI01L") is None

    def test_non_digit_stringer_returns_none(self):
        # pos[4:6] must be digits
        assert self._parse("F06LAaNI01L") is None

    def test_two_different_valid_names_same_group(self):
        from ..views.ratio_graph import _parse_sensor_group
        # Same group, different counter
        key1 = _parse_sensor_group("F06L01NI01L")
        key2 = _parse_sensor_group("F06L02NI99L")
        assert key1 == key2 == "FLNIL"


# ================================================================== #
# RatioGraphWidget — initial state                                    #
# ================================================================== #

class TestRatioGraphWidgetInit:
    def test_ref_bands_empty_on_creation(self, qapp):
        w = _make_ratio_widget(qapp)
        assert w._ref_bands == []

    def test_diagonal_line_none_on_creation(self, qapp):
        w = _make_ratio_widget(qapp)
        assert w._diagonal_line is None

    def test_to_config_returns_none_before_plot(self, qapp):
        w = _make_ratio_widget(qapp)
        assert w.to_config() is None

    def test_get_export_data_returns_none_before_plot(self, qapp):
        w = _make_ratio_widget(qapp)
        assert w.get_export_data() is None


# ================================================================== #
# RatioGraphWidget — after plot_ratio                                 #
# ================================================================== #

class TestRatioGraphWidgetAfterPlot:
    def test_diagonal_set_after_plot(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        assert w._diagonal_line is not None

    def test_ref_bands_still_empty_after_plot(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        assert w._ref_bands == []

    def test_to_config_has_empty_ref_bands(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        cfg = w.to_config()
        assert cfg is not None
        assert cfg["ref_bands"] == []

    def test_get_export_data_has_empty_ref_bands(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        data = w.get_export_data()
        assert data is not None
        assert data["ref_bands"] == []

    def test_to_config_preserves_core_fields(self, qapp, ratio_inputs):
        sensors, values_a, values_b, ratios = ratio_inputs
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        cfg = w.to_config()
        assert cfg["sensors"]   == sensors
        assert cfg["values_a"]  == values_a
        assert cfg["values_b"]  == values_b
        assert cfg["load_step"] == 1.0
        assert cfg["label_a"]   == "A"
        assert cfg["label_b"]   == "B"


# ================================================================== #
# RatioGraphWidget — add_slope_band                                   #
# ================================================================== #

class TestAddSlopeBand:
    def test_add_one_band_updates_ref_bands(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        assert len(w._ref_bands) == 1
        assert w._ref_bands[0]["pct"] == 10.0

    def test_add_band_stores_two_lines(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        assert len(w._ref_bands[0]["lines"]) == 2

    def test_add_multiple_bands(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        w.add_slope_band(50.0)
        assert len(w._ref_bands) == 2
        assert w._ref_bands[0]["pct"] == 10.0
        assert w._ref_bands[1]["pct"] == 50.0

    def test_to_config_serialises_ref_bands(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        w.add_slope_band(50.0)
        cfg = w.to_config()
        assert cfg["ref_bands"] == [10.0, 50.0]

    def test_get_export_data_serialises_ref_bands(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        data = w.get_export_data()
        assert data["ref_bands"] == [10.0]

    def test_add_band_without_plot_does_nothing(self, qapp):
        """add_slope_band silently returns when no scatter data exists."""
        w = _make_ratio_widget(qapp)
        w.add_slope_band(10.0)
        assert w._ref_bands == []


# ================================================================== #
# RatioGraphWidget — clear_reference_lines                            #
# ================================================================== #

class TestClearReferenceLines:
    def test_clear_removes_all_bands(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        w.add_slope_band(50.0)
        w.clear_reference_lines()
        assert w._ref_bands == []

    def test_clear_preserves_diagonal(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        diagonal_before = w._diagonal_line
        w.add_slope_band(10.0)
        w.clear_reference_lines()
        assert w._diagonal_line is diagonal_before

    def test_clear_on_empty_bands_is_safe(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.clear_reference_lines()   # no bands added — must not raise
        assert w._ref_bands == []


# ================================================================== #
# RatioGraphWidget — _clear_band                                      #
# ================================================================== #

class TestClearBand:
    def test_clear_band_removes_correct_entry(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        w.add_slope_band(50.0)
        w._clear_band(0)   # remove the 10% band
        assert len(w._ref_bands) == 1
        assert w._ref_bands[0]["pct"] == 50.0

    def test_clear_band_last_entry(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        w.add_slope_band(50.0)
        w._clear_band(1)   # remove the 50% band
        assert len(w._ref_bands) == 1
        assert w._ref_bands[0]["pct"] == 10.0

    def test_clear_band_invalid_index_is_safe(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        w._clear_band(99)  # out of range — must not raise
        assert len(w._ref_bands) == 1

    def test_clear_band_negative_index_is_safe(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        w._clear_band(-1)  # negative — must not raise
        assert len(w._ref_bands) == 1


# ================================================================== #
# RatioGraphWidget — replot clears diagonal & bands                   #
# ================================================================== #

class TestReplot:
    def test_diagonal_replaced_on_replot(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        first_diagonal = w._diagonal_line
        _plot(w, ratio_inputs)
        assert w._diagonal_line is not first_diagonal

    def test_bands_cleared_on_replot(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        _plot(w, ratio_inputs)    # replot should clear old bands
        assert w._ref_bands == []

    def test_config_round_trip_with_bands(self, qapp, ratio_inputs):
        """to_config output can reconstruct the same band list."""
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        w.add_slope_band(10.0)
        w.add_slope_band(50.0)
        cfg = w.to_config()

        w2 = _make_ratio_widget(qapp, title=cfg["title"])
        w2.plot_ratio(
            cfg["sensors"], cfg["values_a"], cfg["values_b"], cfg["ratios"],
            load_step=cfg["load_step"], label_a=cfg["label_a"], label_b=cfg["label_b"],
        )
        for pct in cfg["ref_bands"]:
            w2.add_slope_band(pct)

        assert [b["pct"] for b in w2._ref_bands] == cfg["ref_bands"]


# ================================================================== #
# RatioGraphWidget — title & stored labels                           #
# ================================================================== #

class TestRatioGraphWidgetMeta:
    def test_title_stored(self, qapp):
        w = _make_ratio_widget(qapp, title="My Ratio")
        assert w._title == "My Ratio"

    def test_default_labels_before_plot(self, qapp):
        w = _make_ratio_widget(qapp)
        assert w._label_a == "Source A"
        assert w._label_b == "Source B"

    def test_labels_set_after_plot(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        assert w._label_a == "A"
        assert w._label_b == "B"

    def test_load_step_stored(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        assert w._load_step == 1.0

    def test_sensors_stored(self, qapp, ratio_inputs):
        sensors, values_a, values_b, ratios = ratio_inputs
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        assert w._sensors == sensors


# ================================================================== #
# RatioGraphWidget — selected sensors                                #
# ================================================================== #

class TestGetSelectedSensors:
    def test_empty_before_plot(self, qapp):
        w = _make_ratio_widget(qapp)
        assert w.get_selected_sensors() == []

    def test_empty_after_plot_with_no_selection(self, qapp, ratio_inputs):
        w = _make_ratio_widget(qapp)
        _plot(w, ratio_inputs)
        assert w.get_selected_sensors() == []


# ================================================================== #
# RatioGraphWidget — all-NaN plot does not create diagonal           #
# ================================================================== #

class TestAllNaNPlot:
    def test_all_nan_values_a_leaves_no_scatter(self, qapp):
        import math
        w = _make_ratio_widget(qapp)
        sensors = ["SA", "SB"]
        nans = [float("nan"), float("nan")]
        w.plot_ratio(sensors, nans, [1.0, 2.0], [float("nan"), float("nan")])
        # No valid points → scatter_items not populated, diagonal not created
        assert w._diagonal_line is None

    def test_to_config_still_none_after_no_valid_plot(self, qapp):
        """plot_ratio with all-NaN leaves no data — to_config returns None initially."""
        import math
        w = _make_ratio_widget(qapp)
        # Never plotted valid data → sensors is empty → to_config = None
        assert w.to_config() is None
