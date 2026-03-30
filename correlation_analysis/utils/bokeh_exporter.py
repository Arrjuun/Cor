"""Bokeh HTML export utilities."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

try:
    import pandas as pd
    from bokeh.embed import file_html
    from bokeh.layouts import column, gridplot
    from bokeh.models import (
        Button,
        ColumnDataSource,
        CustomJS,
        DataTable,
        Div,
        HoverTool,
        Legend,
        LegendItem,
        Span,
        TableColumn,
        TabPanel,
        Tabs,
        TextInput,
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
            [Tabs — one tab per source, each with copy-selected button]
            [Analysis Graphs heading]
            [Tabs — all graph/buckling tabs in display order, each with series filter]
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
                TabPanel(child=self._make_data_table_with_copy(src["df"]), title=src["name"])
                for src in sources
            ]
            page_children.append(
                Tabs(tabs=source_panels, sizing_mode="stretch_width")
            )

        # ---- All graph tabs in display order ----
        all_panels = []
        for tab_data in export_data.get("all_tabs", []):
            tab_name = tab_data.get("name", "Tab")
            tab_type = tab_data.get("type", "analysis")
            num_cols = max(1, int(tab_data.get("num_columns", 1)))

            figures: list = []
            all_labeled_renderers: list[tuple[str, object]] = []  # (label, renderer)

            if tab_type == "buckling":
                figs, label_renderers = self._make_buckling_figures(tab_data.get("onset", {}))
                figures.extend(figs)
                all_labeled_renderers.extend(label_renderers)
            else:
                # Unified ordered graph list (new format)
                graph_list = tab_data.get("graphs")
                if graph_list is None:
                    # Backwards-compat: old format had separate lists — interleave as
                    # loadstep-first, then ratio (original behaviour)
                    graph_list = [
                        {"graph_type": "loadstep", **g}
                        for g in tab_data.get("loadstep_graphs", [])
                    ] + [
                        {"graph_type": "ratio", **(g or {})}
                        for g in tab_data.get("ratio_graphs", [])
                    ]

                for g_data in graph_list:
                    g_type = g_data.get("graph_type", "loadstep")
                    if g_type == "loadstep":
                        fig, lr = self._make_loadstep_figure(
                            g_data.get("series", []),
                            g_data.get("title", "LoadStep Graph"),
                        )
                        figures.append(fig)
                        all_labeled_renderers.extend(lr)
                    else:  # ratio
                        if g_data.get("sensors"):
                            figures.append(self._make_ratio_figure(g_data))
                        else:
                            figures.append(
                                figure(title="Ratio Graph — No Data", width=900, height=400,
                                       sizing_mode="stretch_width")
                            )

            if not figures:
                continue

            # Arrange figures into rows of num_cols
            rows = []
            for i in range(0, len(figures), num_cols):
                row = figures[i:i + num_cols]
                while len(row) < num_cols:
                    row.append(None)
                rows.append(row)
            grid = gridplot(rows, sizing_mode="stretch_width", merge_tools=False)

            # Build a series filter input if there are labeled renderers
            panel_children: list = []
            if all_labeled_renderers:
                renderers_js = [r for _, r in all_labeled_renderers]
                labels_js = [lbl for lbl, _ in all_labeled_renderers]
                filter_input = TextInput(
                    placeholder="Filter series by name…",
                    width=320,
                    styles={"margin-bottom": "6px"},
                )
                filter_cb = CustomJS(
                    args=dict(renderers=renderers_js, labels=labels_js),
                    code="""
                        const val = cb_obj.value.toLowerCase().trim();
                        for (let i = 0; i < renderers.length; i++) {
                            renderers[i].visible = (val === '' || labels[i].toLowerCase().includes(val));
                        }
                    """,
                )
                filter_input.js_on_change("value", filter_cb)
                panel_children.append(filter_input)

            panel_children.append(grid)
            panel_layout = column(*panel_children, sizing_mode="stretch_width")
            all_panels.append(TabPanel(child=panel_layout, title=tab_name))

        if all_panels:
            page_children.append(
                Div(text='<p class="section-heading">Analysis Graphs</p>',
                    sizing_mode="stretch_width")
            )
            page_children.append(
                Tabs(tabs=all_panels, sizing_mode="stretch_width")
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
    def _make_data_table_with_copy(df: "pd.DataFrame") -> "column":
        """Build a Bokeh DataTable with a Copy Selected button from a pandas DataFrame."""
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

        table = DataTable(
            source=source,
            columns=columns,
            width=1100,
            height=400,
            index_position=None,
            sizing_mode="stretch_width",
        )

        copy_btn = Button(label="Copy Selected Rows", button_type="default", width=180)
        copy_cb = CustomJS(
            args=dict(source=source),
            code=r"""
                const indices = source.selected.indices;
                if (indices.length === 0) { alert('Select rows first.'); return; }
                const data = source.data;
                const cols = Object.keys(data);
                let text = cols.join('\t') + '\n';
                for (const i of indices) {
                    text += cols.map(c => (data[c][i] != null ? data[c][i] : '')).join('\t') + '\n';
                }
                navigator.clipboard.writeText(text).catch(() => {
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                });
            """,
        )
        copy_btn.js_on_click(copy_cb)

        return column(copy_btn, table, sizing_mode="stretch_width")

    @staticmethod
    def _make_loadstep_figure(
        series_list: list[dict], title: str
    ) -> "tuple[figure, list[tuple[str, object]]]":
        """Build a Bokeh LoadStep vs Strain figure.

        Returns ``(figure, [(label, renderer), ...])`` so callers can wire up
        a series-filter TextInput across all figures in a tab.
        """
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
        labeled_renderers: list[tuple[str, object]] = []
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
            labeled_renderers.append((label, line))

            if marker:
                scatter_fn = getattr(p, marker, None)
                if scatter_fn:
                    sc = scatter_fn(
                        "x", "y", source=src,
                        color=color, size=8, visible=visible,
                    )
                    labeled_renderers.append((label, sc))

            legend_items.append(LegendItem(label=label, renderers=[line]))

        if legend_items:
            legend = Legend(items=legend_items, click_policy="hide")
            p.add_layout(legend, "right")

        return p, labeled_renderers

    @staticmethod
    def _make_ratio_figure(ratio_data: dict) -> "figure":
        """Build a Bokeh scatter figure for a ratio graph.

        Respects per-group colours and marker shapes stored in the export data.
        pyqtgraph symbol codes are mapped to Bokeh marker names.
        """
        # pyqtgraph symbol → Bokeh marker name
        _PG_TO_BOKEH_MARKER = {
            "o":    "circle",
            "s":    "square",
            "t":    "triangle",
            "d":    "diamond",
            "+":    "cross",
            "star": "star",
        }

        sensors = ratio_data["sensors"]
        values_a = ratio_data["values_a"]
        values_b = ratio_data["values_b"]
        label_a = ratio_data.get("label_a", "Source A")
        label_b = ratio_data.get("label_b", "Source B")
        sensor_groups: list[str] = ratio_data.get("sensor_groups", ["Other"] * len(sensors))
        groups_info: list[dict] = ratio_data.get("groups_info", [])
        use_grouping: bool = ratio_data.get("use_grouping", False)

        # Build a lookup: group_key → {color, marker}
        group_style: dict[str, dict] = {}
        for gi, ginfo in enumerate(groups_info):
            key = ginfo["key"]
            color = ginfo.get("color", "#1565C0")
            pg_sym = ginfo.get("symbol", "o")
            marker = _PG_TO_BOKEH_MARKER.get(pg_sym, "circle")
            group_style[key] = {"color": color, "marker": marker, "label": ginfo.get("label", key)}

        # Filter out NaN entries; keep group association
        valid: list[tuple[str, float, float, str]] = []  # (sensor, a, b, group_key)
        for s, a, b, g in zip(sensors, values_a, values_b, sensor_groups):
            try:
                fa, fb = float(a), float(b)
                if not (np.isnan(fa) or np.isnan(fb)):
                    valid.append((s, fa, fb, g))
            except (TypeError, ValueError):
                pass

        if not valid:
            return figure(title="Ratio Graph — No Valid Data", width=900, height=400)

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

        if use_grouping:
            # Group data by key, preserving insertion order from groups_info
            ordered_keys: list[str] = [g["key"] for g in groups_info]
            grouped: dict[str, list] = {k: [] for k in ordered_keys}
            for entry in valid:
                grouped.setdefault(entry[3], []).append(entry)

            legend_items = []
            for key in ordered_keys:
                entries = grouped.get(key, [])
                if not entries:
                    continue
                gstyle = group_style.get(key, {"color": "#1565C0", "marker": "circle", "label": key})
                color = gstyle["color"]
                marker = gstyle["marker"]
                glabel = gstyle["label"]

                src = ColumnDataSource({
                    "x":      [e[1] for e in entries],
                    "y":      [e[2] for e in entries],
                    "sensor": [e[0] for e in entries],
                })
                r = p.scatter("x", "y", source=src, size=10,
                              marker=marker, color=color, alpha=0.8,
                              legend_label=glabel)
                legend_items.append(r)

            if p.legend:
                p.legend.click_policy = "hide"
                p.legend.location = "top_left"
        else:
            # No grouping — single series with the first group's style (or default)
            default_style = group_style.get(sensor_groups[0], {"color": "#1565C0", "marker": "circle"}) \
                if sensor_groups else {"color": "#1565C0", "marker": "circle"}
            src = ColumnDataSource({
                "x":      [e[1] for e in valid],
                "y":      [e[2] for e in valid],
                "sensor": [e[0] for e in valid],
            })
            p.scatter("x", "y", source=src, size=10,
                      marker=default_style["marker"],
                      color=default_style["color"], alpha=0.8)

        # 1:1 reference line
        all_vals = [e[1] for e in valid] + [e[2] for e in valid]
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
            band_label = f"±{pct:.0f}%"
            p.line(ref_x, ref_y_pos,
                   line_color="#F57F17", line_dash="dashed", line_width=1,
                   legend_label=band_label)
            p.line(ref_x, ref_y_neg,
                   line_color="#F57F17", line_dash="dashed", line_width=1)

        return p

    # ------------------------------------------------------------------ #
    # Buckling onset figures                                               #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_buckling_figures(
        cfg: dict,
    ) -> "tuple[list, list[tuple[str, object]]]":
        """Build four Bokeh figures (SUP, INF, Membrane, Bending) from a
        ``BucklingOnsetWidget.to_config()`` dict.

        Returns ``([figures], [(label, renderer), ...])`` for filter wiring.
        """
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
        labeled_renderers: list[tuple[str, object]] = []
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
                sc = p.scatter("x", "y", source=src, color=color, size=6)
                legend_items.append(LegendItem(label=comp, renderers=[line]))
                labeled_renderers.append((comp, line))
                labeled_renderers.append((comp, sc))

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

        return figures_out, labeled_renderers

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
            fig, _ = self._make_loadstep_figure(series_list, tab_id)
            tab_panels.append(TabPanel(child=fig, title=tab_id))

        if not tab_panels:
            tab_panels.append(TabPanel(child=figure(title="No Data"), title="Empty"))

        layout = Tabs(tabs=tab_panels)
        html = file_html(layout, CDN, title="Correlation Analysis Export")
        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(html)
