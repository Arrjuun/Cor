"""Import View Presenter."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from ..models.data_model import DataModel
from ..models.sensor_mapping import SensorMapping
from ..utils.csv_parser import CSVParseError, parse_sensor_csv, validate_raw_dataframe
from ..views.import_view import ImportView

log = logging.getLogger(__name__)


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
        self._view.remove_mapping_requested.connect(self._on_remove_mapping)
        self._view.view_mapping_requested.connect(self._on_view_mapping)
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
        log.info("Importing CSV: %s", filepath)
        try:
            df, result = parse_sensor_csv(filepath)
        except CSVParseError as exc:
            log.error("Failed to import '%s': %s", filepath, exc)
            self._view.show_error(f"Failed to import '{filepath}':\n{str(exc)}")
            return

        if result.warnings:
            log.warning("Warnings for '%s': %s", filepath, "; ".join(result.warnings))
            self._view.show_warning(
                f"Warnings for '{filepath}':\n" + "\n".join(result.warnings)
            )

        import os
        display_name = os.path.basename(filepath)
        source_id = self._data.add_source(filepath, df, display_name)
        log.info("CSV imported as source '%s' (%s): %d rows × %d columns",
                 source_id, display_name, len(df), len(df.columns))

        table_widget = self._view.add_source_table(
            source_id, df, display_name, is_valid=result.is_valid
        )

        # Connect table widget signals
        table_widget.row_delete_requested.connect(self._on_delete_rows)
        table_widget.column_delete_requested.connect(self._on_delete_columns)
        table_widget.scale_strain_requested.connect(self._on_scale_strain)
        table_widget.add_strain_requested.connect(self._on_add_strain)
        table_widget.offset_loadsteps_requested.connect(self._on_offset_loadsteps)
        table_widget.transpose_requested.connect(self._on_transpose)

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

        log.info("Importing mapping file: %s", filepath)
        source_ids = self._data.source_ids()
        try:
            self._mapping.load_from_file(filepath, source_ids)
        except Exception as exc:
            log.error("Failed to load mapping from '%s': %s", filepath, exc)
            self._view.show_error(f"Failed to load mapping: {exc}")
            return

        n = len(self._mapping.canonical_names())
        self._view.set_mapping_info(f"✓ Mapping loaded: {n} canonical sensors.", loaded=True)

        # Build per-source sensor lists using display names for readability
        imported_sensors: dict[str, list[str]] = {}
        for sid in source_ids:
            ds = self._data.get_source(sid)
            if ds is None:
                continue
            df = self._data.get_dataframe(sid)
            if df is None:
                continue
            # Row 0 is the header row; sensor names start from row 1, column 0
            sensor_names = [str(df.iloc[r, 0]) for r in range(1, len(df))
                            if str(df.iloc[r, 0]).strip()]
            imported_sensors[ds.display_name] = sensor_names

        unmapped, incomplete = self._mapping.get_missing_analysis(imported_sensors)

        # Always show the missing-sensors popup so users are informed of gaps
        self._view.show_missing_sensors_dialog(unmapped, incomplete)

        # Show the full mapping table afterwards
        self._view.show_mapping_dialog(
            self._mapping.to_dict(),
            rosette_data=self._mapping.rosette_data() or None,
            sensor_pair_data=self._mapping.sensor_pair_data() or None,
        )

    def on_proceed(self) -> None:
        """Finalize all raw DataFrames (promote row 0 → headers, col 0 → index)."""
        log.info("Proceeding to analysis — finalizing %d source(s).", len(self._data.source_ids()))
        for source_id in self._data.source_ids():
            try:
                self._data.finalize_source(source_id)
                log.debug("Source '%s' finalized.", source_id)
            except Exception as exc:
                log.error("Failed to finalize source '%s': %s", source_id, exc)
                self._view.show_error(
                    f"Cannot proceed — failed to finalize data for source '{source_id}':\n{exc}"
                )
                return

    def _on_delete_rows(self, source_id: str, row_positions: list[int]) -> None:
        labels = [f"Row {p + 1}" for p in row_positions]
        if self._view.confirm_delete(labels, "rows"):
            log.debug("Deleting rows %s from source '%s'.", row_positions, source_id)
            self._data.delete_raw_rows(source_id, row_positions)
            df = self._data.get_dataframe(source_id)
            if df is not None:
                self._view.update_source_table(source_id, df)
                self._view.set_source_valid(source_id, validate_raw_dataframe(df))

    def _on_delete_columns(self, source_id: str, col_positions: list[int]) -> None:
        labels = [f"Column {p + 1}" for p in col_positions]
        if self._view.confirm_delete(labels, "columns"):
            log.debug("Deleting columns %s from source '%s'.", col_positions, source_id)
            self._data.delete_raw_columns(source_id, col_positions)
            df = self._data.get_dataframe(source_id)
            if df is not None:
                self._view.update_source_table(source_id, df)
                self._view.set_source_valid(source_id, validate_raw_dataframe(df))

    def _on_remove_mapping(self) -> None:
        reply = QMessageBox.question(
            self._view,
            "Remove Mapping",
            "Remove the loaded sensor mapping?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._mapping.clear()
            self._view.set_mapping_info("No mapping loaded.", loaded=False)

    def _on_view_mapping(self) -> None:
        if not self._mapping.is_empty():
            self._view.show_mapping_dialog(
                self._mapping.to_dict(),
                rosette_data=self._mapping.rosette_data() or None,
                sensor_pair_data=self._mapping.sensor_pair_data() or None,
            )

    def _on_scale_strain(self, source_id: str, factor: float) -> None:
        self._data.scale_raw_strain(source_id, factor)
        self._refresh_table(source_id)

    def _on_add_strain(self, source_id: str, offset: float) -> None:
        self._data.add_raw_strain(source_id, offset)
        self._refresh_table(source_id)

    def _on_offset_loadsteps(self, source_id: str, offset: float) -> None:
        self._data.offset_raw_loadsteps(source_id, offset)
        self._refresh_table(source_id)

    def _on_transpose(self, source_id: str) -> None:
        self._data.transpose_raw(source_id)
        self._refresh_table(source_id)

    def _refresh_table(self, source_id: str) -> None:
        df = self._data.get_dataframe(source_id)
        if df is not None:
            self._view.update_source_table(source_id, df)
            self._view.set_source_valid(source_id, validate_raw_dataframe(df))

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
