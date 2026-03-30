"""CSV export for LoadStep vs Strain graphs across all tabs."""
from __future__ import annotations

import csv
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.data_model import DataModel
    from ..views.tab_graph_view import BucklingTabContent, TabGraphView

_MAX_POINTS = 32
_MAX_GRAPHS_PER_PANEL = 4

# Fixed column order
_HEADERS = (
    ["Channel name", "X Channel name", "Panel layout file",
     "New panel name", "Panel object name", "Plot nr", "Chart title", "Formula"]
    + [f"x{i}" for i in range(1, _MAX_POINTS + 1)]
    + [f"y{i}" for i in range(1, _MAX_POINTS + 1)]
)


def _pad(values: list, length: int = _MAX_POINTS) -> list:
    """Extend *values* to *length* with empty strings.

    Note: time-series longer than _MAX_POINTS are silently truncated.
    """
    result = list(values)
    while len(result) < length:
        result.append("")
    return result[:length]


def _panel_layout(n_graphs: int) -> str:
    return "2x2.PLF" if n_graphs > 2 else "1x2.PLF"


def export_csv(
    filepath: str,
    tab_view: "TabGraphView",
    data_model: "DataModel",
    buckling_tabs: "list[BucklingTabContent] | None" = None,
) -> None:
    """
    Write a CSV file containing one row per series across all LoadStep graphs
    and buckling onset plots.

    Each tab is split into panels of at most 4 graphs.  The first panel for a
    tab takes the tab name as *New panel name*; subsequent panels append a
    counter (e.g. "Analysis 1 2", "Analysis 1 3", …).
    """
    rows: list[dict] = []

    # ---- Regular LoadStep graphs ----
    for tab_content in tab_view.all_tabs():
        tab_name = tab_view.get_tab_name(tab_content.tab_id)
        ls_graphs = tab_content.get_loadstep_graphs()

        # Split into chunks of _MAX_GRAPHS_PER_PANEL
        chunks = [
            ls_graphs[i: i + _MAX_GRAPHS_PER_PANEL]
            for i in range(0, max(len(ls_graphs), 1), _MAX_GRAPHS_PER_PANEL)
        ]

        for chunk_idx, chunk in enumerate(chunks):
            panel_name = tab_name if chunk_idx == 0 else f"{tab_name} {chunk_idx + 1}"
            plf = _panel_layout(len(chunk))

            for graph_idx, graph in enumerate(chunk):
                panel_object = f"GRAPH_{graph_idx + 1}"
                chart_title = graph.get_title()
                for plot_nr, key in enumerate(graph.series_keys(), start=1):
                    info = graph.get_series_info(key)
                    if not info:
                        continue

                    sensor_name: str = info["sensor_name"]
                    source_id: str = info["source_id"]
                    x_vals = list(info["x"])
                    y_vals = list(info["y"])

                    formula = data_model.get_formulas(source_id).get(sensor_name, "")

                    row = {
                        "Channel name": sensor_name,
                        "X Channel name": "Loadstep",
                        "Panel layout file": plf,
                        "New panel name": panel_name,
                        "Panel object name": panel_object,
                        "Plot nr": plot_nr,
                        "Chart title": chart_title,
                        "Formula": formula,
                    }
                    for i, v in enumerate(_pad(x_vals), start=1):
                        row[f"x{i}"] = v
                    for i, v in enumerate(_pad(y_vals), start=1):
                        row[f"y{i}"] = v

                    rows.append(row)

    # ---- Buckling onset plots ----
    for b_tab in (buckling_tabs or []):
        tab_name = tab_view.get_tab_name(b_tab.tab_id)
        onset_cfg = b_tab.get_onset_widget().to_config()
        element_id = onset_cfg.get("element_id", "")
        time_vals = list(onset_cfg.get("time", []))
        sup = onset_cfg.get("sup", {})
        inf = onset_cfg.get("inf", {})

        # Build 4 plots mirroring the Bokeh layout: SUP, INF, Membrane, Bending.
        # Each plot contains up to 3 series (e11, e22, e12), matching the
        # LoadStep-Strain export structure (one panel per plot, multiple Plot nr rows).
        _plot_specs = [
            ("SUP",      f"Buckling SUP — {element_id}"),
            ("INF",      f"Buckling INF — {element_id}"),
            ("Membrane", f"Buckling Membrane — {element_id}"),
            ("Bending",  f"Buckling Bending — {element_id}"),
        ]
        plots: list[tuple[str, list[tuple[str, list]]]] = []
        for mode, chart_title in _plot_specs:
            series_for_plot: list[tuple[str, list]] = []
            for comp in ("e11", "e22", "e12"):
                sup_arr = list(sup.get(comp, []))
                inf_arr = list(inf.get(comp, []))
                if mode == "SUP":
                    if len(sup_arr) != len(time_vals):
                        continue
                    y_vals: list = sup_arr
                elif mode == "INF":
                    if len(inf_arr) != len(time_vals):
                        continue
                    y_vals = inf_arr
                elif mode == "Membrane":
                    if len(sup_arr) != len(time_vals) or len(inf_arr) != len(time_vals):
                        continue
                    y_vals = [(s + i_v) / 2.0 for s, i_v in zip(sup_arr, inf_arr)]
                else:  # Bending
                    if len(sup_arr) != len(time_vals) or len(inf_arr) != len(time_vals):
                        continue
                    y_vals = [(s - i_v) / 2.0 for s, i_v in zip(sup_arr, inf_arr)]
                series_for_plot.append((comp, y_vals))
            if series_for_plot:
                plots.append((chart_title, series_for_plot))

        chunks = [
            plots[i: i + _MAX_GRAPHS_PER_PANEL]
            for i in range(0, max(len(plots), 1), _MAX_GRAPHS_PER_PANEL)
        ]
        for chunk_idx, chunk in enumerate(chunks):
            panel_name = tab_name if chunk_idx == 0 else f"{tab_name} {chunk_idx + 1}"
            plf = _panel_layout(len(chunk))
            for graph_idx, (chart_title, series_for_plot) in enumerate(chunk):
                panel_object = f"GRAPH_{graph_idx + 1}"
                for plot_nr, (channel_name, y_vals) in enumerate(series_for_plot, start=1):
                    row = {
                        "Channel name": channel_name,
                        "X Channel name": "Step Time",
                        "Panel layout file": plf,
                        "New panel name": panel_name,
                        "Panel object name": panel_object,
                        "Plot nr": plot_nr,
                        "Chart title": chart_title,
                        "Formula": "",
                    }
                    for i, v in enumerate(_pad(time_vals), start=1):
                        row[f"x{i}"] = v
                    for i, v in enumerate(_pad(y_vals), start=1):
                        row[f"y{i}"] = v
                    rows.append(row)

        # Also export any extra loadstep graphs added to this buckling tab
        ls_graphs = b_tab.get_loadstep_graphs()
        chunks_ls = [
            ls_graphs[i: i + _MAX_GRAPHS_PER_PANEL]
            for i in range(0, max(len(ls_graphs), 1), _MAX_GRAPHS_PER_PANEL)
        ]
        for chunk_idx, chunk in enumerate(chunks_ls):
            panel_name = (
                f"{tab_name} (extra)" if chunk_idx == 0
                else f"{tab_name} (extra) {chunk_idx + 1}"
            )
            plf = _panel_layout(len(chunk))
            for graph_idx, graph in enumerate(chunk):
                panel_object = f"GRAPH_{graph_idx + 1}"
                for plot_nr, key in enumerate(graph.series_keys(), start=1):
                    info = graph.get_series_info(key)
                    if not info:
                        continue
                    sensor_name = info["sensor_name"]
                    source_id = info["source_id"]
                    x_vals = list(info["x"])
                    y_vals = list(info["y"])
                    formula = data_model.get_formulas(source_id).get(sensor_name, "")
                    row = {
                        "Channel name": sensor_name,
                        "X Channel name": "Loadstep",
                        "Panel layout file": plf,
                        "New panel name": panel_name,
                        "Panel object name": panel_object,
                        "Plot nr": plot_nr,
                        "Chart title": graph.get_title(),
                        "Formula": formula,
                    }
                    for i, v in enumerate(_pad(x_vals), start=1):
                        row[f"x{i}"] = v
                    for i, v in enumerate(_pad(y_vals), start=1):
                        row[f"y{i}"] = v
                    rows.append(row)

    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
