"""HTML Export Presenter using Bokeh."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

from ..utils.bokeh_exporter import BokehExporter
from ..utils.csv_exporter import export_csv as _export_csv_util
from ..views.tab_graph_view import BucklingTabContent, GraphTabContent

if TYPE_CHECKING:
    from ..views.main_window import MainWindow
    from .analysis_presenter import AnalysisPresenter


class ExportPresenter:
    """Coordinates HTML export via Bokeh."""

    def __init__(
        self,
        window: "MainWindow",
        analysis_presenter: "AnalysisPresenter",
    ) -> None:
        self._window = window
        self._analysis = analysis_presenter
        self._connect_signals()

    def _connect_signals(self) -> None:
        self._window.export_html_requested.connect(self.export_html)
        self._window.export_csv_requested.connect(self.export_csv)

    def export_html(self, filepath: str) -> None:
        try:
            data_model = self._analysis._data
            tab_view = self._window.analysis_view.get_tab_view()

            # ---- Collect source DataFrames ----
            sources = []
            for ds in data_model.all_sources():
                sources.append({
                    "name": ds.display_name or ds.source_id,
                    "df": ds.df,
                })

            # ---- Collect all tabs in display order ----
            all_tabs_data = []
            for widget, tab_name in tab_view.all_tabs_ordered():
                if isinstance(widget, BucklingTabContent):
                    onset_cfg = widget.get_onset_widget().to_config()
                    all_tabs_data.append({
                        "type": "buckling",
                        "name": tab_name,
                        "num_columns": widget._num_columns,
                        "onset": onset_cfg,
                    })
                elif isinstance(widget, GraphTabContent):
                    loadstep_graphs = []
                    for graph in widget.get_loadstep_graphs():
                        series_list = []
                        for key in graph.series_keys():
                            info = graph.get_series_info(key)
                            if info:
                                series_list.append({
                                    "sensor_name": info["sensor_name"],
                                    "source_id": info["source_id"],
                                    "x": info["x"].tolist(),
                                    "y": info["y"].tolist(),
                                    "style": info["style"].to_dict(),
                                })
                        loadstep_graphs.append({
                            "title": graph.get_title(),
                            "series": series_list,
                        })

                    ratio_graphs = []
                    for rg in widget.get_ratio_graphs():
                        ratio_graphs.append(rg.get_export_data())

                    all_tabs_data.append({
                        "type": "analysis",
                        "name": tab_name,
                        "num_columns": widget._num_columns,
                        "loadstep_graphs": loadstep_graphs,
                        "ratio_graphs": ratio_graphs,
                    })

            export_data = {
                "sources": sources,
                "all_tabs": all_tabs_data,
            }

            exporter = BokehExporter()
            exporter.export_full(export_data, filepath)

            self._window.show_status(f"Exported to HTML: {filepath}")
            QMessageBox.information(
                self._window,
                "Export Complete",
                f"Successfully exported to:\n{filepath}",
            )
        except Exception as exc:
            self._window.show_error(f"Export failed:\n{exc}")

    def export_csv(self, filepath: str) -> None:
        try:
            tab_view = self._window.analysis_view.get_tab_view()
            data_model = self._analysis._data
            buckling_tabs = tab_view.all_buckling_tabs()
            _export_csv_util(filepath, tab_view, data_model, buckling_tabs)
            self._window.show_status(f"Exported to CSV: {filepath}")
            QMessageBox.information(
                self._window,
                "Export Complete",
                f"Successfully exported to:\n{filepath}",
            )
        except Exception as exc:
            self._window.show_error(f"CSV export failed:\n{exc}")
