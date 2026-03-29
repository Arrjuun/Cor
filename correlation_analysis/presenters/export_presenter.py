"""HTML Export Presenter using Bokeh."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

from ..utils.bokeh_exporter import BokehExporter
from ..utils.csv_exporter import export_csv as _export_csv_util

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

            # ---- Collect regular analysis tabs ----
            tabs = []
            for tab_content in tab_view.all_tabs():
                tab_name = tab_view.get_tab_name(tab_content.tab_id)

                # LoadStep graphs
                loadstep_graphs = []
                for graph in tab_content.get_loadstep_graphs():
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

                # Ratio graphs
                ratio_graphs = []
                for rg in tab_content.get_ratio_graphs():
                    ratio_graphs.append(rg.get_export_data())

                tabs.append({
                    "name": tab_name,
                    "num_columns": tab_content._num_columns,
                    "loadstep_graphs": loadstep_graphs,
                    "ratio_graphs": ratio_graphs,
                })

            # ---- Collect buckling onset tabs ----
            buckling_tabs = []
            for b_tab in tab_view.all_buckling_tabs():
                b_tab_name = tab_view.get_tab_name(b_tab.tab_id)
                onset_cfg = b_tab.get_onset_widget().to_config()

                # Also collect any extra loadstep/ratio graphs added to this buckling tab
                extra_loadstep = []
                for graph in b_tab.get_loadstep_graphs():
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
                    extra_loadstep.append({
                        "title": graph.get_title(),
                        "series": series_list,
                    })

                extra_ratio = []
                for rg in b_tab.get_ratio_graphs():
                    extra_ratio.append(rg.get_export_data())

                buckling_tabs.append({
                    "name": b_tab_name,
                    "onset": onset_cfg,
                    "num_columns": b_tab._num_columns,
                    "extra_loadstep_graphs": extra_loadstep,
                    "extra_ratio_graphs": extra_ratio,
                })

            export_data = {
                "sources": sources,
                "tabs": tabs,
                "buckling_tabs": buckling_tabs,
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
