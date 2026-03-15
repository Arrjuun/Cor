"""Import View Presenter."""
from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from ..models.data_model import DataModel
from ..models.sensor_mapping import SensorMapping
from ..utils.csv_parser import CSVParseError, parse_sensor_csv
from ..views.import_view import ImportView


class ImportPresenter:
    """Coordinates the ImportView with DataModel and SensorMapping."""

    def __init__(
        self,
        view: ImportView,
        data_model: DataModel,
        mapping: SensorMapping,
    ) -> None:
        self._view = view
        self._data = data_model
        self._mapping = mapping
        self._connect_signals()

    def _connect_signals(self) -> None:
        self._view.import_csv_requested.connect(self.on_import_csv)
        self._view.import_mapping_requested.connect(self.on_import_mapping)
        self._view.proceed_requested.connect(self.on_proceed)
        self._view.remove_source_requested.connect(self._on_remove_source)

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    def on_import_csv(self) -> None:
        filepaths, _ = QFileDialog.getOpenFileNames(
            self._view,
            "Import CSV Files",
            filter="CSV Files (*.csv);;All Files (*)",
        )
        for filepath in filepaths:
            self._import_single_csv(filepath)

    def _import_single_csv(self, filepath: str) -> None:
        try:
            df, result = parse_sensor_csv(filepath)
        except CSVParseError as exc:
            self._view.show_error(f"Failed to import '{filepath}':\n{str(exc)}")
            return

        if result.warnings:
            self._view.show_warning(
                f"Warnings for '{filepath}':\n" + "\n".join(result.warnings)
            )

        import os
        display_name = os.path.basename(filepath)
        source_id = self._data.add_source(filepath, df, display_name)

        table_widget = self._view.add_source_table(
            source_id, df, display_name, is_valid=result.is_valid
        )

        # Connect table widget signals
        table_widget.row_delete_requested.connect(self._on_delete_rows)
        table_widget.column_delete_requested.connect(self._on_delete_columns)

        if not result.is_valid:
            self._view.show_warning(
                f"Validation issues in '{display_name}':\n"
                + "\n".join(result.errors)
            )

    def on_import_mapping(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self._view,
            "Import Sensor Mapping",
            filter="CSV Files (*.csv);;All Files (*)",
        )
        if not filepath:
            return

        source_ids = self._data.source_ids()
        try:
            self._mapping.load_from_file(filepath, source_ids)
        except Exception as exc:
            self._view.show_error(f"Failed to load mapping: {exc}")
            return

        n = len(self._mapping.canonical_names())
        self._view.set_mapping_info(f"✓ Mapping loaded: {n} canonical sensors.")

        # Build display-friendly mapping dict for the dialog
        # Keys = canonical names, values = {source_col_name: alias}
        mapping_display = self._mapping.to_dict()
        self._view.show_mapping_dialog(mapping_display)

    def on_proceed(self) -> None:
        # Implemented by connecting to main window's show_view
        pass

    def _on_delete_rows(self, source_id: str, sensors: list[str]) -> None:
        if self._view.confirm_delete(sensors, "sensors"):
            self._data.delete_rows(source_id, sensors)
            df = self._data.get_dataframe(source_id)
            if df is not None:
                self._view.update_source_table(source_id, df)

    def _on_delete_columns(self, source_id: str, load_steps: list[float]) -> None:
        items = [str(ls) for ls in load_steps]
        if self._view.confirm_delete(items, "load steps"):
            self._data.delete_columns(source_id, load_steps)
            df = self._data.get_dataframe(source_id)
            if df is not None:
                self._view.update_source_table(source_id, df)

    def _on_remove_source(self, source_id: str) -> None:
        source = self._data.get_source(source_id)
        if source is None:
            return
        reply = QMessageBox.question(
            self._view,
            "Remove Source",
            f"Remove '{source.display_name}' and all its data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._data.remove_source(source_id)
            self._view.remove_source_table(source_id)
