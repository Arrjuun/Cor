"""Graph Presenter – handles data-to-graph wiring."""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..models.data_model import DataModel
from ..models.graph_data_model import GraphDataModel
from ..models.sensor_mapping import SensorMapping
from ..views.analysis_view import AnalysisView
from ..views.customization_dialog import CustomizationDialog, SeriesStyle
from ..views.loadstep_graph import LoadStepGraphWidget
from ..views.ratio_graph import RatioGraphWidget


class GraphPresenter:
    """Handles dropping sensors onto graphs and updating graph data."""

    def __init__(
        self,
        analysis_view: AnalysisView,
        data_model: DataModel,
        mapping: SensorMapping,
        graph_data_model: GraphDataModel,
    ) -> None:
        self._view = analysis_view
        self._data = data_model
        self._mapping = mapping
        self._graph_data = graph_data_model
        self._connect_signals()

    def _connect_signals(self) -> None:
        self._view.sensor_dropped_to_graph.connect(self._on_sensor_dropped)

        # Wire ratio graphs in all already-existing tabs
        tab_view = self._view.get_tab_view()
        for tab in tab_view.all_tabs():
            self._wire_tab_ratio_graphs(tab)
            # Wire future ratio graphs added dynamically to this tab
            tab.ratio_graph_added.connect(
                lambda rg, t=tab: self._wire_single_ratio_graph(rg, t)
            )
        tab_view.tab_added.connect(self._wire_new_tab_ratio)

    def _wire_new_tab_ratio(self, tab_id: str) -> None:
        tab = self._view.get_tab_view().get_tab(tab_id)
        if tab:
            self._wire_tab_ratio_graphs(tab)
            # Wire future ratio graphs added dynamically to this tab
            tab.ratio_graph_added.connect(
                lambda rg, t=tab: self._wire_single_ratio_graph(rg, t)
            )
            # NOTE: loadstep graphs are already wired via AnalysisView.sensor_dropped_to_graph

    def _wire_tab_ratio_graphs(self, tab) -> None:
        for rg in tab.get_ratio_graphs():
            self._wire_single_ratio_graph(rg, tab)

    def _wire_single_ratio_graph(self, rg, tab) -> None:
        rg.loadstep_dropped.connect(
            lambda payload, r=rg: self._on_loadstep_dropped_to_ratio(payload, r)
        )
        rg.points_selected_for_plot.connect(
            lambda sensors, target, t=tab: self._on_selected_to_graph(sensors, t)
        )

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    def _on_sensor_dropped(self, payload: dict, graph: LoadStepGraphWidget) -> None:
        """Handle a sensor row drop onto a LoadStep graph."""
        sensor_name = payload.get("sensor_name", "")
        source_id = payload.get("source_id", "")

        if not sensor_name or not source_id:
            return

        try:
            x, y = self._graph_data.get_loadstep_series(source_id, sensor_name)
        except ValueError:
            return

        graph.add_series(sensor_name, source_id, x, y)

        # Also ask about mapped sensors
        if not self._mapping.is_empty():
            canonical = (
                self._mapping.resolve(source_id, sensor_name)
                or self._mapping.resolve_by_name(sensor_name)
            )
            if canonical:
                self._offer_mapped_sensors(canonical, graph, exclude_source=source_id)

    def _offer_mapped_sensors(
        self,
        canonical: str,
        graph: LoadStepGraphWidget,
        exclude_source: str = "",
    ) -> None:
        from PySide6.QtWidgets import QMessageBox
        # Collect all alias names for this canonical sensor
        alias_names = set(self._mapping.get_aliases(canonical).values())

        # Find every source (other than the dropped one) that contains any alias
        others: dict[str, str] = {}  # {source_id: matching_sensor_name}
        for source_id in self._data.source_ids():
            if source_id == exclude_source:
                continue
            df = self._data.get_dataframe(source_id)
            if df is None:
                continue
            df_index = set(df.index.astype(str))
            for alias in alias_names:
                if alias in df_index:
                    others[source_id] = alias
                    break

        if not others:
            return

        src = self._data.get_source(exclude_source)
        exclude_name = src.display_name if src else exclude_source
        names = "\n".join(
            f"  {self._data.get_source(sid).display_name if self._data.get_source(sid) else sid}: {sname}"
            for sid, sname in others.items()
        )
        reply = QMessageBox.question(
            self._view,
            "Plot Mapped Sensors",
            f"Sensor '{canonical}' also exists in other sources:\n{names}\n\n"
            "Plot them as well?",
        )
        if reply == QMessageBox.StandardButton.Yes:
            for sid, sname in others.items():
                try:
                    x, y = self._graph_data.get_loadstep_series(sid, sname)
                    src_obj = self._data.get_source(sid)
                    label = f"{sname} ({src_obj.display_name if src_obj else sid})"
                    style = SeriesStyle(label=label)
                    graph.add_series(sname, sid, x, y, style)
                except ValueError:
                    pass

    def _on_loadstep_dropped_to_ratio(self, payload: dict, rg=None) -> None:
        """Handle a load-step column drop onto a Ratio graph."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QComboBox, QFormLayout, QMessageBox
        load_step_str = payload.get("load_step", "")
        source_id = payload.get("source_id", "")

        try:
            load_step = float(load_step_str)
        except ValueError:
            return

        source_ids = self._data.source_ids()
        source_names = {
            sid: (self._data.get_source(sid).display_name if self._data.get_source(sid) else sid)
            for sid in source_ids
        }

        if rg is None:
            tab = self._view.get_tab_view().current_tab()
            if not tab:
                return
            ratio_graphs = tab.get_ratio_graphs()
            if not ratio_graphs:
                return
            rg = ratio_graphs[-1]

        # Single source: no ratio possible — inform user
        if len(source_ids) == 1:
            QMessageBox.information(
                self._view, "Ratio Graph",
                "A ratio plot requires two data sources.\n"
                "Import a second CSV file to enable ratio plotting."
            )
            return

        # Two or more sources: ask user which pair to compare
        dlg = QDialog(self._view)
        dlg.setWindowTitle("Select Sources for Ratio")
        dlg.setMinimumWidth(320)
        form = QFormLayout(dlg)

        numerator_cb = QComboBox()
        denominator_cb = QComboBox()
        for sid in source_ids:
            name = source_names[sid]
            numerator_cb.addItem(name, sid)
            denominator_cb.addItem(name, sid)

        # Default: drag source = numerator
        drag_idx = source_ids.index(source_id) if source_id in source_ids else 0
        numerator_cb.setCurrentIndex(drag_idx)
        denominator_cb.setCurrentIndex(1 if drag_idx == 0 else 0)

        form.addRow("Numerator (A):", numerator_cb)
        form.addRow("Denominator (B):", denominator_cb)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        sid_a = numerator_cb.currentData()
        sid_b = denominator_cb.currentData()
        if sid_a == sid_b:
            QMessageBox.warning(self._view, "Ratio Graph", "Numerator and denominator must be different sources.")
            return

        try:
            ratio_df = self._graph_data.get_ratio_data(
                sid_a, sid_b, load_step,
                use_mapping=not self._mapping.is_empty(),
            )
        except ValueError as exc:
            QMessageBox.warning(self._view, "Ratio Error", str(exc))
            return

        if ratio_df.empty:
            QMessageBox.information(self._view, "Ratio Graph",
                                    "No common sensors found between selected sources.")
            return

        sensors = ratio_df["sensor"].tolist()
        values_a = ratio_df["value_a"].tolist()
        values_b = ratio_df["value_b"].tolist()
        ratios = ratio_df["ratio"].tolist()
        rg.plot_ratio(
            sensors, values_a, values_b, ratios,
            load_step=load_step,
            label_a=source_names[sid_a],
            label_b=source_names[sid_b],
        )

    def _on_selected_to_graph(self, sensors: list[str], tab) -> None:
        """Plot box-selected sensors into an existing LoadStep graph chosen by the user.

        ``sensors`` are canonical/ratio names. For each source we try:
          1. The name directly (works when no mapping or names match).
          2. All alias values for that canonical name in the mapping.
        """
        from PySide6.QtWidgets import (
            QDialog, QDialogButtonBox, QLabel, QListWidget, QVBoxLayout,
        )

        loadstep_graphs = tab.get_loadstep_graphs()
        if not loadstep_graphs:
            target_graph = tab.add_loadstep_graph("Selection Analysis")
        else:
            dlg = QDialog(self._view)
            dlg.setWindowTitle("Select Target Graph")
            dlg.setMinimumWidth(320)
            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel("Select the LoadStep graph to add sensors to:"))
            list_widget = QListWidget()
            for i, g in enumerate(loadstep_graphs):
                list_widget.addItem(g.get_title() or f"LoadStep Graph {i + 1}")
            list_widget.setCurrentRow(0)
            layout.addWidget(list_widget)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dlg.accept)
            buttons.rejected.connect(dlg.reject)
            layout.addWidget(buttons)

            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            idx = list_widget.currentRow()
            if idx < 0:
                return
            target_graph = loadstep_graphs[idx]

        self._populate_graph_from_sensors(target_graph, sensors)

    def _populate_graph_from_sensors(
        self, graph: LoadStepGraphWidget, sensors: list[str]
    ) -> None:
        """Add series for each sensor (canonical name or direct name) to *graph*."""
        for source_id in self._data.source_ids():
            source = self._data.get_source(source_id)
            if source is None:
                continue
            df_index = set(source.df.index.astype(str))

            for canonical in sensors:
                candidates = [canonical]
                if not self._mapping.is_empty():
                    aliases = self._mapping.get_aliases(canonical)
                    candidates.extend(aliases.values())

                for candidate in candidates:
                    if candidate in df_index:
                        try:
                            x, y = self._graph_data.get_loadstep_series(
                                source_id, candidate
                            )
                            graph.add_series(candidate, source_id, x, y)
                        except ValueError:
                            pass
                        break

    # ------------------------------------------------------------------ #
    # Session restore                                                      #
    # ------------------------------------------------------------------ #

    def restore_graphs_from_config(self, tabs_config: list[dict]) -> None:
        """Recreate all tabs and graphs from a saved session config."""
        tab_view = self._view.get_tab_view()
        tab_view.clear_all_tabs()

        for tab_cfg in tabs_config:
            tab_name = tab_cfg.get("tab_name", "Analysis")
            tab = tab_view.add_tab(tab_name)
            # The tab was just created with default graphs; replace with saved ones.
            tab.clear_graphs()
            if "num_columns" in tab_cfg:
                tab.set_columns(tab_cfg["num_columns"])

            for ls_cfg in tab_cfg.get("loadstep_graphs", []):
                # Handle old format (list of series) and new format (dict)
                if isinstance(ls_cfg, list):
                    ls_cfg = {"title": "", "series": ls_cfg}
                graph = tab.add_loadstep_graph(ls_cfg.get("title", ""))
                for s in ls_cfg.get("series", []):
                    try:
                        x, y = self._graph_data.get_loadstep_series(
                            s["source_id"], s["sensor_name"]
                        )
                        style = SeriesStyle.from_dict(s.get("style", {}))
                        graph.add_series(s["sensor_name"], s["source_id"], x, y, style)
                    except (ValueError, KeyError):
                        pass

            for rg_cfg in tab_cfg.get("ratio_graphs", []):
                if not rg_cfg:
                    continue
                rg = tab.add_ratio_graph(rg_cfg.get("title", ""))
                if rg_cfg.get("sensors"):
                    rg.plot_ratio(
                        rg_cfg["sensors"],
                        rg_cfg["values_a"],
                        rg_cfg["values_b"],
                        rg_cfg["ratios"],
                        load_step=rg_cfg.get("load_step", 0.0),
                        label_a=rg_cfg.get("label_a", "Source A"),
                        label_b=rg_cfg.get("label_b", "Source B"),
                    )

    # ------------------------------------------------------------------ #
    # Series customization                                                 #
    # ------------------------------------------------------------------ #

    def customize_series_in_graph(
        self, graph: LoadStepGraphWidget, series_key: str
    ) -> None:
        graph.customize_series(series_key)
