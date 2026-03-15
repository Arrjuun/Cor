"""Analysis View Presenter."""
from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox

from ..models.data_model import DataModel
from ..models.formula_engine import FormulaEngine, FormulaError
from ..models.graph_data_model import GraphDataModel
from ..models.sensor_mapping import SensorMapping
from ..views.analysis_view import AnalysisView
from .graph_presenter import GraphPresenter


class AnalysisPresenter:
    """Manages the analysis view interactions."""

    def __init__(
        self,
        view: AnalysisView,
        data_model: DataModel,
        mapping: SensorMapping,
        formula_engine: FormulaEngine,
        graph_data_model: GraphDataModel,
    ) -> None:
        self._view = view
        self._data = data_model
        self._mapping = mapping
        self._formula_engine = formula_engine
        self._graph_data = graph_data_model
        self._graph_presenter = GraphPresenter(view, data_model, mapping, graph_data_model)
        self._connect_signals()

    def _connect_signals(self) -> None:
        self._view.formula_changed.connect(self._on_formula_changed)
        self._view.row_delete_requested.connect(self._on_delete_rows)
        self._view.column_delete_requested.connect(self._on_delete_columns)
        self._view.add_derived_row_requested.connect(self._on_add_derived_row)
        self._view.filter_changed.connect(self._on_filter_changed)
        self._data.add_observer(self._on_data_changed)

    # ------------------------------------------------------------------ #
    # Initialization from existing data                                    #
    # ------------------------------------------------------------------ #

    def initialize_from_model(self) -> None:
        """Populate the analysis view from current data model state."""
        for ds in self._data.all_sources():
            formulas = self._data.get_formulas(ds.source_id)
            derived_rows = set(formulas.keys())
            self._view.add_data_table(
                source_id=ds.source_id,
                df=ds.df,
                formulas=formulas,
                derived_rows=derived_rows,
                title=ds.display_name,
            )
            # Set mapped-names column if a mapping is loaded
            if not self._mapping.is_empty():
                mapped = self._build_mapped_names(ds.source_id, ds.df)
                self._view.set_table_mapped_names(ds.source_id, mapped)

    def _build_mapped_names(self, source_id: str, df) -> dict[str, str]:
        """Build {sensor_name: "canonical | alias_b | alias_c"} for one source."""
        result: dict[str, str] = {}
        for sensor_name in df.index:
            sname = str(sensor_name)
            # Try exact source_id match first, then fall back to searching by value
            canonical = (
                self._mapping.resolve(source_id, sname)
                or self._mapping.resolve_by_name(sname)
            )
            if canonical:
                aliases = self._mapping.get_aliases(canonical)
                # Parts = canonical name + all aliases except the current sensor's own name
                parts = [canonical] + [v for v in aliases.values() if v != sname]
                result[sname] = " | ".join(parts)
        return result

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    def _on_formula_changed(
        self, source_id: str, sensor_name: str, formula: str
    ) -> None:
        if not formula.strip():
            return

        df = self._data.get_dataframe(source_id)
        if df is None:
            return

        # Build namespace from raw sensor rows (non-derived)
        formulas_dict = self._data.get_formulas(source_id)
        raw_sensors = [s for s in df.index if s not in formulas_dict]
        namespace: dict[str, pd.Series] = {}
        for s in raw_sensors:
            row = df.loc[s]
            numeric_cols = [c for c in row.index if isinstance(c, (int, float))]
            namespace[s] = row[numeric_cols]

        # Also include other derived rows that are already computed
        for other_sensor, other_formula in formulas_dict.items():
            if other_sensor != sensor_name and other_sensor in df.index:
                row = df.loc[other_sensor]
                numeric_cols = [c for c in row.index if isinstance(c, (int, float))]
                namespace[other_sensor] = row[numeric_cols]

        try:
            result = self._formula_engine.evaluate(formula, namespace)
        except FormulaError as exc:
            QMessageBox.warning(self._view, "Formula Error", str(exc))
            return

        self._data.add_derived_row(source_id, sensor_name, formula, result)
        widget = self._view.get_table_widget(source_id)
        if widget:
            widget.update_derived_row(sensor_name, result)

    def _on_delete_rows(self, source_id: str, sensors: list[str]) -> None:
        reply = QMessageBox.question(
            self._view,
            "Delete Rows",
            f"Delete {len(sensors)} sensor row(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._data.delete_rows(source_id, sensors)

    def _on_delete_columns(self, source_id: str, load_steps: list[float]) -> None:
        reply = QMessageBox.question(
            self._view,
            "Delete Columns",
            f"Delete {len(load_steps)} load step column(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._data.delete_columns(source_id, load_steps)

    def _on_add_derived_row(self, source_id: str, df_pos: int) -> None:
        name, ok = QInputDialog.getText(
            self._view,
            "Add Derived Row",
            "Enter name for the new derived sensor:",
            QLineEdit.EchoMode.Normal,
            "Derived_1",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        # Add to model at the specified position
        self._data.add_derived_row(source_id, name, "", position=df_pos)
        # Add to view table (df already updated via observer; this registers derived status)
        widget = self._view.get_table_widget(source_id)
        if widget:
            widget.add_derived_row(name, position=df_pos)

    def _on_filter_changed(self, text: str) -> None:
        """Filter is handled in each SensorTableModel using sensor name + mapped names."""
        self._view.set_table_filter(text)

    def _on_data_changed(self, event: str, source_id: str) -> None:
        if event in ("updated", "loaded") and source_id:
            df = self._data.get_dataframe(source_id)
            if df is not None:
                self._view.update_table(source_id, df)

    @property
    def graph_presenter(self) -> GraphPresenter:
        return self._graph_presenter
