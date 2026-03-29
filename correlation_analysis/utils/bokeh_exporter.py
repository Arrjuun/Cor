"""Bokeh HTML export utilities."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

try:
    import pandas as pd
    from bokeh.embed import file_html
    from bokeh.layouts import column, gridplot
    from bokeh.models import (
        ColumnDataSource,
        DataTable,
        Div,
        HoverTool,
        Legend,
        LegendItem,
        Span,
        TableColumn,
        TabPanel,
        Tabs,
    )
    from bokeh.plotting import figure
    from bokeh.resources import CDN

    BOKEH_AVAILABLE = True
except ImportError:
    BOKEH_AVAILABLE = False

# Map style names to Bokeh dash patterns
_DASH_MAP = {
    "Solid": "solid",
    "Dashed": "dashed",
    "Dotted": "dotted",
    "DashDot": "dashdot",
}

_MARKER_MAP = {
    "None": None,
    "Circle": "circle",
    "Square": "square",
    "Triangle": "triangle",
    "Diamond": "diamond",
    "Cross": "cross",
}


class BokehExporter:
    """Exports graph and table data to a single interactive HTML file using Bokeh."""

    # ------------------------------------------------------------------ #
    # Main entry point                                                     #
    # ------------------------------------------------------------------ #

    # CSS injected into every export for a clean, wide layout
    _PAGE_STYLE = """
        <style>
            body { margin: 16px; background: #fafafa; font-family: sans-serif; }
            .bk-root { width: 100% !important; }
            .section-heading {
                font-size: 1.2em; font-weight: 600; color: #1565C0;
                border-bottom: 2px solid #1565C0;
                padding-bottom: 4px; margin: 24px 0 8px 0;
            }
        </style>
    """

    def export_full(self, export_data: dict, filepath: str) -> None:
        """
        Export the complete application state to a single HTML file.

        Layout (top → bottom):
            [Data Tables heading]
            [Tabs — one tab per source]
            [Analysis Graphs heading]
            [Tabs — one tab per analysis tab, each containing stacked figures]
        """
        if not BOKEH_AVAILABLE:
            raise RuntimeError("Bokeh is not installed. Run: pip install bokeh")

        page_children = []

        # ---- Data Tables section ----
        sources = export_data.get("sources", [])
        if sources:
            page_children.append(
                Div(text='<p class="section-heading">Data Tables</p>',
                    sizing_mode="stretch_width")
            )
            source_panels = [
                TabPanel(child=self._make_data_table(src["df"]), title=src["name"])
                for src in sources
            ]
            page_children.append(
                Tabs(tabs=source_panels, sizing_mode="stretch_width")
            )

        # ---- Analysis Graphs section ----
        analysis_panels = []
        for tab_data in export_data.get("tabs", []):
            tab_name = tab_data.get("name", "Analysis")
            num_cols = max(1, int(tab_data.get("num_columns", 1)))
            figures = []

            for ls_data in tab_data.get("loadstep_graphs", []):
                series = ls_data.get("series", [])
                figures.append(
                    self._make_loadstep_figure(
                        series, ls_data.get("title", "LoadStep Graph")
                    )
                )

            for rg_data in tab_data.get("ratio_graphs", []):
                if rg_data and rg_data.get("sensors"):
                    figures.append(self._make_ratio_figure(rg_data))
                else:
                    figures.append(
                        figure(title="Ratio Graph — No Data", width=900, height=400,
                               sizing_mode="stretch_width")
                    )

            if figures:
                # Arrange into rows of num_cols
                rows = []
                for i in range(0, len(figures), num_cols):
                    row = figures[i:i + num_cols]
                    # Pad last row with None so gridplot keeps column widths uniform
                    while len(row) < num_cols:
                        row.append(None)
                    rows.append(row)
                grid = gridplot(rows, sizing_mode="stretch_width", merge_tools=False)
                analysis_panels.append(TabPanel(child=grid, title=tab_name))

        if analysis_panels:
            page_children.append(
                Div(text='<p class="section-heading">Analysis Graphs</p>',
                    sizing_mode="stretch_width")
            )
            page_children.append(
                Tabs(tabs=analysis_panels, sizing_mode="stretch_width")
            )

        # ---- Buckling Onset section ----
        buckling_panels = []
        for b_data in export_data.get("buckling_tabs", []):
            tab_name = b_data.get("name", "Buckling")
            onset_cfg = b_data.get("onset", {})
            figures = self._make_buckling_figures(onset_cfg)

            # Append any extra loadstep/ratio graphs added to this buckling tab
            for ls_data in b_data.get("extra_loadstep_graphs", []):
                figures.append(
                    self._make_loadstep_figure(
                        ls_data.get("series", []),
                        ls_data.get("title", "LoadStep Graph"),
                    )
                )
            for rg_data in b_data.get("extra_ratio_graphs", []):
                if rg_data and rg_data.get("sensors"):
                    figures.append(self._make_ratio_figure(rg_data))

            if figures:
                grid = gridplot(
                    [[f] for f in figures],
                    sizing_mode="stretch_width",
                    merge_tools=False,
                )
                buckling_panels.append(TabPanel(child=grid, title=tab_name))

        if buckling_panels:
            page_children.append(
                Div(
                    text='<p class="section-heading">Buckling Onset</p>',
                    sizing_mode="stretch_width",
                )
            )
            page_children.append(
                Tabs(tabs=buckling_panels, sizing_mode="stretch_width")
            )

        if not page_children:
            page_children.append(figure(title="No Data", width=900, height=300))

        root = column(*page_children, sizing_mode="stretch_width")
        html = file_html(root, CDN, title="Correlation Analysis Export")
        # Inject page-level CSS
        html = html.replace("</head>", self._PAGE_STYLE + "</head>", 1)

        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(html)

    # ------------------------------------------------------------------ #
    # Figure builders                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_data_table(df: "pd.DataFrame") -> "DataTable":
        """Build a Bokeh DataTable from a pandas DataFrame (rows = sensors)."""
        data: dict[str, list] = {"sensor": [str(s) for s in df.index]}
        col_names = []
        for col in df.columns:
            safe_key = f"col_{col}"  # avoid numeric keys that confuse ColumnDataSource
            data[safe_key] = [
                float(v) if isinstance(v, (int, float)) and not np.isnan(float(v)) else None
                for v in df[col]
            ]
            col_names.append((safe_key, str(col)))

        source = ColumnDataSource(data)
        columns = [TableColumn(field="sensor", title="Sensor", width=160)]
        for field, title in col_names:
            columns.append(TableColumn(field=field, title=title, width=90))

        return DataTable(
            source=source,
            columns=columns,
            width=1100,
            height=400,
            index_position=None,
            sizing_mode="stretch_width",
        )

    @staticmethod
    def _make_loadstep_figure(series_list: list[dict], title: str) -> "figure":
        """Build a Bokeh LoadStep vs Strain figure from a list of series dicts."""
        p = figure(
            title=title,
            x_axis_label="Load Step",
            y_axis_label="Strain",
            tools="pan,wheel_zoom,box_zoom,reset,save",
            width=900,
            height=400,
            sizing_mode="stretch_width",
        )
        hover = HoverTool(tooltips=[
            ("Sensor", "@sensor_name"),
            ("Load Step", "@x{0.00}"),
            ("Strain", "@y{0.000000}"),
        ])
        p.add_tools(hover)

        legend_items = []
        for series in series_list:
            style_dict = series.get("style", {})
            color = style_dict.get("color", "#1565C0")
            thickness = style_dict.get("thickness", 2)
            dash = _DASH_MAP.get(style_dict.get("line_style", "Solid"), "solid")
            marker = _MARKER_MAP.get(style_dict.get("marker", "None"))
            label = style_dict.get("label") or series["sensor_name"]
            visible = style_dict.get("visible", True)

            x = list(series["x"])
            y = list(series["y"])

            src = ColumnDataSource(data={
                "x": x, "y": y,
                "sensor_name": [label] * len(x),
            })

            line = p.line(
                "x", "y", source=src,
                line_color=color,
                line_width=thickness,
                line_dash=dash,
                visible=visible,
            )

            if marker:
                scatter_fn = getattr(p, marker, None)
                if scatter_fn:
                    scatter_fn(
                        "x", "y", source=src,
                        color=color, size=8, visible=visible,
                    )

            legend_items.append(LegendItem(label=label, renderers=[line]))

        if legend_items:
            legend = Legend(items=legend_items, click_policy="hide")
            p.add_layout(legend, "right")

        return p

    @staticmethod
    def _make_ratio_figure(ratio_data: dict) -> "figure":
        """Build a Bokeh scatter figure for a ratio graph."""
        sensors = ratio_data["sensors"]
        values_a = ratio_data["values_a"]
        values_b = ratio_data["values_b"]
        label_a = ratio_data.get("label_a", "Source A")
        label_b = ratio_data.get("label_b", "Source B")

        # Filter valid (non-NaN) entries
        valid = [
            (s, float(a), float(b))
            for s, a, b in zip(sensors, values_a, values_b)
            if not (np.isnan(float(a)) or np.isnan(float(b)))
        ]
        if not valid:
            return figure(title="Ratio Graph — No Valid Data", width=900, height=400)

        xs = [v[1] for v in valid]
        ys = [v[2] for v in valid]
        sensor_names = [v[0] for v in valid]

        src = ColumnDataSource({"x": xs, "y": ys, "sensor": sensor_names})

        p = figure(
            title=f"Strain Correlation — {label_a} vs {label_b}",
            x_axis_label=f"Strain — {label_a}",
            y_axis_label=f"Strain — {label_b}",
            tools="pan,wheel_zoom,box_zoom,reset,save",
            width=900,
            height=400,
            sizing_mode="stretch_width",
        )
        hover = HoverTool(tooltips=[
            ("Sensor", "@sensor"),
            (label_a, "@x{0.000000}"),
            (label_b, "@y{0.000000}"),
        ])
        p.add_tools(hover)

        p.scatter("x", "y", source=src, size=10, color="#1565C0", alpha=0.8)

        # 1:1 reference line
        all_vals = xs + ys
        lo, hi = min(all_vals), max(all_vals)
        margin = (hi - lo) * 0.05 or 0.01
        ref_x = [lo - margin, hi + margin]
        p.line(ref_x, ref_x,
               line_color="#9E9E9E", line_dash="dashed", line_width=1,
               legend_label="1:1 line")

        # Reference bands
        for pct in ratio_data.get("ref_bands", []):
            factor_pos = 1.0 + pct / 100.0
            factor_neg = 1.0 - pct / 100.0
            ref_y_pos = [v * factor_pos for v in ref_x]
            ref_y_neg = [v * factor_neg for v in ref_x]
            label = f"±{pct:.0f}%"
            p.line(ref_x, ref_y_pos,
                   line_color="#F57F17", line_dash="dashed", line_width=1,
                   legend_label=label)
            p.line(ref_x, ref_y_neg,
                   line_color="#F57F17", line_dash="dashed", line_width=1)

        return p

    # ------------------------------------------------------------------ #
    # Buckling onset figures                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_buckling_figures(cfg: dict) -> list:
        """Build four Bokeh figures (SUP, INF, Membrane, Bending) from a
        ``BucklingOnsetWidget.to_config()`` dict."""
        element_id = cfg.get("element_id", "")
        source_label = cfg.get("source_label", "")
        onset_timesteps = cfg.get("onset_timesteps", [])
        time = np.array(cfg.get("time", []), dtype=float)
        sup_data = {k: np.array(v, dtype=float) for k, v in cfg.get("sup", {}).items()}
        inf_data = {k: np.array(v, dtype=float) for k, v in cfg.get("inf", {}).items()}

        src_tag = f"  [{source_label}]" if source_label else ""

        _SERIES_COLORS = {"e11": "#1565C0", "e22": "#C62828", "e12": "#2E7D32"}
        _ONSET_COLOR = "#FF6F00"

        plot_specs = [
            ("SUP",      "SUP Strain",      "sup"),
            ("INF",      "INF Strain",      "inf"),
            ("Membrane", "Membrane Strain", "membrane"),
            ("Bending",  "Bending Strain",  "bending"),
        ]

        figures_out = []
        for plot_key, y_label, mode in plot_specs:
            title = f"{plot_key} Strain — Element {element_id}{src_tag}"
            p = figure(
                title=title,
                x_axis_label="Step Time",
                y_axis_label=y_label,
                tools="pan,wheel_zoom,box_zoom,reset,save",
                width=900,
                height=400,
                sizing_mode="stretch_width",
            )
            hover = HoverTool(tooltips=[
                ("Component", "@comp"),
                ("Step Time", "@x{0.000000}"),
                ("Strain",    "@y{0.000000}"),
            ])
            p.add_tools(hover)

            legend_items = []
            for comp in ("e11", "e22", "e12"):
                sup_arr = sup_data.get(comp, np.array([]))
                inf_arr = inf_data.get(comp, np.array([]))

                if mode == "sup":
                    if len(sup_arr) != len(time):
                        continue
                    y = sup_arr
                elif mode == "inf":
                    if len(inf_arr) != len(time):
                        continue
                    y = inf_arr
                elif mode == "membrane":
                    if len(sup_arr) != len(time) or len(inf_arr) != len(time):
                        continue
                    y = (sup_arr + inf_arr) / 2.0
                else:  # bending
                    if len(sup_arr) != len(time) or len(inf_arr) != len(time):
                        continue
                    y = (sup_arr - inf_arr) / 2.0

                color = _SERIES_COLORS.get(comp, "#000000")
                src = ColumnDataSource({
                    "x":    time.tolist(),
                    "y":    y.tolist(),
                    "comp": [comp] * len(time),
                })
                line = p.line("x", "y", source=src, line_color=color, line_width=2)
                p.scatter("x", "y", source=src, color=color, size=6)
                legend_items.append(LegendItem(label=comp, renderers=[line]))

            # Dummy line for onset legend entry (Span does not support legend_label)
            if onset_timesteps:
                p.line(
                    [], [],
                    line_color=_ONSET_COLOR,
                    line_dash="dashed",
                    line_width=2,
                    legend_label="Buckling Onset",
                )
                for ts in onset_timesteps:
                    vline = Span(
                        location=ts,
                        dimension="height",
                        line_color=_ONSET_COLOR,
                        line_dash="dashed",
                        line_width=2,
                    )
                    p.add_layout(vline)

            if legend_items:
                legend = Legend(items=legend_items, click_policy="hide")
                p.add_layout(legend, "right")

            figures_out.append(p)

        return figures_out

    # ------------------------------------------------------------------ #
    # Legacy export (kept for backwards compatibility)                     #
    # ------------------------------------------------------------------ #

    def export(self, graph_data: list[dict], filepath: str) -> None:
        """Legacy export — LoadStep series only, grouped by tab_id."""
        if not BOKEH_AVAILABLE:
            raise RuntimeError("Bokeh is not installed. Run: pip install bokeh")

        from collections import defaultdict
        tabs_data: dict[str, list[dict]] = defaultdict(list)
        for series in graph_data:
            tabs_data[series["tab_id"]].append(series)

        tab_panels = []
        for tab_id, series_list in tabs_data.items():
            fig = self._make_loadstep_figure(series_list, tab_id)
            tab_panels.append(TabPanel(child=fig, title=tab_id))

        if not tab_panels:
            tab_panels.append(TabPanel(child=figure(title="No Data"), title="Empty"))

        layout = Tabs(tabs=tab_panels)
        html = file_html(layout, CDN, title="Correlation Analysis Export")
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(html)
