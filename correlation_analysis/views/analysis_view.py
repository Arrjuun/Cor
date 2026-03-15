"""Analysis View: left panel data tables + right panel tab graphs."""
from __future__ import annotations

from typing import Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .data_table_widget import DataTableWidget
from .tab_graph_view import TabGraphView


class AnalysisView(QWidget):
    """
    Main analysis workspace.

    Left panel: stacked DataTableWidgets (one per source / derived)
    Right panel: TabGraphView

    Signals pass through from child widgets for the presenter to handle.
    """

    add_derived_row_requested = Signal(str, int)          # source_id, df_insert_position
    formula_changed = Signal(str, str, str)              # source_id, sensor, formula
    row_delete_requested = Signal(str, list)
    column_delete_requested = Signal(str, list)
    sensor_dropped_to_graph = Signal(dict, object)       # payload, graph widget
    filter_changed = Signal(str)                         # filter text

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._table_widgets: dict[str, DataTableWidget] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(6)

        # ---- Left panel ----
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_header = QHBoxLayout()
        left_lbl = QLabel("<b>Data Tables</b>")
        left_header.addWidget(left_lbl)
        left_header.addStretch()
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter sensors…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.setMaximumWidth(200)
        self._filter_edit.textChanged.connect(self.filter_changed)
        left_header.addWidget(self._filter_edit)
        left_layout.addLayout(left_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._tables_container = QWidget()
        self._tables_inner = QVBoxLayout(self._tables_container)
        self._tables_inner.setSpacing(8)
        self._tables_inner.addStretch()
        scroll.setWidget(self._tables_container)
        left_layout.addWidget(scroll)

        splitter.addWidget(left_panel)

        # ---- Right panel ----
        self._tab_graph_view = TabGraphView()
        splitter.addWidget(self._tab_graph_view)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([500, 900])

        main_layout.addWidget(splitter)

        # Wire new graph drops
        self._wire_tab_view()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def add_data_table(
        self,
        source_id: str,
        df: pd.DataFrame,
        formulas: dict | None = None,
        derived_rows: set | None = None,
        title: str = "",
    ) -> DataTableWidget:
        widget = DataTableWidget(
            df,
            source_id=source_id,
            formulas=formulas,
            derived_rows=derived_rows,
            title=title or source_id,
            parent=self,
        )
        widget.formula_changed.connect(self.formula_changed)
        widget.row_delete_requested.connect(self.row_delete_requested)
        widget.column_delete_requested.connect(self.column_delete_requested)
        widget.row_added.connect(self.add_derived_row_requested)

        self._table_widgets[source_id] = widget

        # Insert before stretch
        self._tables_inner.removeItem(
            self._tables_inner.itemAt(self._tables_inner.count() - 1)
        )
        self._tables_inner.addWidget(widget)
        self._tables_inner.addStretch()
        return widget

    def clear_tables(self) -> None:
        """Remove all data table widgets (called before loading a new session)."""
        for widget in list(self._table_widgets.values()):
            self._tables_inner.removeWidget(widget)
            widget.deleteLater()
        self._table_widgets.clear()

    def update_table(self, source_id: str, df: pd.DataFrame) -> None:
        w = self._table_widgets.get(source_id)
        if w:
            w.update_dataframe(df)

    def set_table_filter(self, text: str) -> None:
        """Apply filter text to all table widgets."""
        for w in self._table_widgets.values():
            w.set_sensor_filter(text)

    def set_table_mapped_names(self, source_id: str, mapped: dict) -> None:
        """Set mapped-names dict on a table widget to show the extra column."""
        w = self._table_widgets.get(source_id)
        if w:
            w.set_mapped_names(mapped)

    def get_tab_view(self) -> TabGraphView:
        return self._tab_graph_view

    def get_table_widget(self, source_id: str) -> Optional[DataTableWidget]:
        return self._table_widgets.get(source_id)

    # ------------------------------------------------------------------ #
    # Wire graph drops                                                     #
    # ------------------------------------------------------------------ #

    def _wire_tab_view(self) -> None:
        """Connect series_dropped on all graphs to our signal."""
        # Wire existing tabs (already created in TabGraphView.__init__)
        for tab in self._tab_graph_view.all_tabs():
            self._wire_tab_content(tab)

        # Wire future tabs
        self._tab_graph_view.tab_added.connect(self._wire_new_tab)

    def _wire_tab_content(self, tab) -> None:
        """Wire all current and future graphs in a tab."""
        for g in tab.get_loadstep_graphs():
            self._wire_loadstep_graph(g)
        # Wire graphs added dynamically after the tab is created
        tab.loadstep_graph_added.connect(self._wire_loadstep_graph)

    def _wire_loadstep_graph(self, graph) -> None:
        graph.series_dropped.connect(
            lambda payload, g=graph: self.sensor_dropped_to_graph.emit(payload, g)
        )

    def _wire_new_tab(self, tab_id: str) -> None:
        tab = self._tab_graph_view.get_tab(tab_id)
        if tab:
            self._wire_tab_content(tab)
