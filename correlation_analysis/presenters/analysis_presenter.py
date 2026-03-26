"""Analysis View Presenter."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QEventLoop, QProcess, Qt
from PySide6.QtWidgets import QInputDialog, QLineEdit, QMessageBox, QProgressDialog

from ..models.data_model import DataModel
from ..models.formula_engine import FormulaEngine, FormulaError
from ..models.graph_data_model import GraphDataModel
from ..models.sensor_mapping import SensorMapping
from ..utils.buckling_exporter import write_export
from ..views.analysis_view import AnalysisView
from ..views.buckling_dialog import BucklingDialog, BucklingGroup, SensorEntry, SourceInfo
from ..views.buckling_export_dialog import BucklingExportDialog
from .graph_presenter import GraphPresenter

log = logging.getLogger(__name__)


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
        self._view.buckling_requested.connect(self._on_buckling_requested)
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

    def _on_filter_changed(self, text: str, regex: bool = False) -> None:
        """Filter is handled in each SensorTableModel using sensor name + mapped names."""
        self._view.set_table_filter(text, regex)

    def _on_data_changed(self, event: str, source_id: str) -> None:
        if event in ("updated", "loaded") and source_id:
            df = self._data.get_dataframe(source_id)
            if df is not None:
                self._view.update_table(source_id, df)

    @property
    def graph_presenter(self) -> GraphPresenter:
        return self._graph_presenter

    # ------------------------------------------------------------------ #
    # Buckling analysis                                                    #
    # ------------------------------------------------------------------ #

    def _on_buckling_requested(self) -> None:
        """Build buckling groups from the loaded mapping and open the dialog."""
        if self._mapping.is_empty():
            QMessageBox.warning(
                self._view,
                "No Mapping",
                "Please import a sensor mapping file before running buckling analysis.",
            )
            return

        if not self._mapping.has_sensor_pair_data():
            QMessageBox.warning(
                self._view,
                "No Sensor Pair Data",
                "The loaded mapping does not contain a 'Sensor Pair' column.\n\n"
                "Add a 'Sensor Pair' column to your mapping CSV to enable buckling analysis.",
            )
            return

        groups = self._build_buckling_groups()
        if not groups:
            QMessageBox.information(
                self._view,
                "Buckling Analysis",
                "No sensor pair groups could be built from the current mapping and data.",
            )
            return

        dlg = BucklingDialog(groups, parent=self._view)
        dlg.analyze_requested.connect(self._on_buckling_analyze)
        dlg.exec()

    def _on_buckling_analyze(self, selections: list) -> None:
        """Open the export settings dialog, write CSV/YAML, optionally run the script."""
        log.info("Buckling export requested for %d group(s).", len(selections))

        export_dlg = BucklingExportDialog(parent=self._view)
        if export_dlg.exec() != BucklingExportDialog.DialogCode.Accepted:
            return

        settings = export_dlg.get_settings()
        try:
            csv_path, yaml_path = write_export(selections, self._data, settings)
        except Exception as exc:
            log.exception("Buckling export failed: %s", exc)
            QMessageBox.critical(
                self._view,
                "Export Failed",
                f"Could not write buckling analysis files:\n{exc}",
            )
            return

        log.info("Buckling CSV written to '%s'.", csv_path)
        log.info("Buckling YAML written to '%s'.", yaml_path)

        if not settings.script_path:
            QMessageBox.information(
                self._view,
                "Export Complete",
                f"Buckling analysis files written:\n\nCSV:  {csv_path}\nYAML: {yaml_path}",
            )
            return

        self._run_buckling_script(settings.script_path, yaml_path, csv_path, settings.output_dir)

    def _run_buckling_script(
        self,
        script_path: str,
        yaml_path: str,
        input_csv_path: str,
        output_dir: str,
    ) -> None:
        """Launch the external fembuckling_onset script and process its output on success."""
        script = Path(script_path)
        if script.suffix.lower() == ".py":
            program = sys.executable
            args = [str(script), yaml_path]
        else:
            program = str(script)
            args = [yaml_path]

        progress = QProgressDialog(
            "Running buckling onset analysis…",
            "Cancel",
            0,
            0,
            self._view,
        )
        progress.setWindowTitle("Buckling Analysis")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)

        process = QProcess(self._view)
        loop = QEventLoop(self._view)

        process.finished.connect(loop.quit)
        progress.canceled.connect(process.kill)
        progress.canceled.connect(loop.quit)

        process.start(program, args)
        if not process.waitForStarted(5000):
            progress.close()
            QMessageBox.critical(
                self._view,
                "Script Error",
                f"Could not start the analysis script:\n{script_path}",
            )
            return

        progress.show()
        loop.exec()
        progress.close()

        exit_code = process.exitCode()
        if exit_code != 0:
            stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace")
            QMessageBox.critical(
                self._view,
                "Script Failed",
                f"The buckling onset script exited with code {exit_code}.\n\n"
                f"{stderr[:800]}",
            )
            return

        log.info("Buckling onset script finished with exit code 0.")
        self._load_onset_results(input_csv_path, output_dir)

    def _load_onset_results(self, input_csv_path: str, output_dir: str) -> None:
        """Find the onset CSV in *output_dir*, parse it, and create per-element onset tabs."""
        output_path = Path(output_dir)

        # Search for a CSV file in the output directory that has the expected onset columns
        onset_csv_path: Path | None = None
        required_cols = {"element_id", "timestep"}
        for candidate in sorted(output_path.glob("*.csv")):
            try:
                header = pd.read_csv(candidate, nrows=0)
                if required_cols.issubset({c.lower() for c in header.columns}):
                    onset_csv_path = candidate
                    break
            except Exception:
                continue

        if onset_csv_path is None:
            QMessageBox.warning(
                self._view,
                "No Onset Results",
                f"No onset results CSV found in:\n{output_dir}\n\n"
                "The script ran successfully but produced no onset CSV with "
                "'element_id' and 'timestep' columns.",
            )
            return

        log.info("Parsing onset results from '%s'.", onset_csv_path)
        onset_df = pd.read_csv(onset_csv_path)
        # Normalise column names to lower-case for robustness
        onset_df.columns = [c.strip().lower() for c in onset_df.columns]

        try:
            input_df = pd.read_csv(input_csv_path)
        except Exception as exc:
            QMessageBox.critical(
                self._view,
                "Read Error",
                f"Could not read the buckling input CSV:\n{input_csv_path}\n\n{exc}",
            )
            return

        # Normalise ElementID column name
        input_df.columns = [c.strip() for c in input_df.columns]
        elem_id_col = next(
            (c for c in input_df.columns if c.lower() == "elementid"),
            None,
        )
        if elem_id_col is None:
            QMessageBox.critical(
                self._view,
                "Format Error",
                "The buckling input CSV does not contain an 'ElementID' column.",
            )
            return

        tab_view = self._view.get_tab_view()
        count = 0

        for element_id, onset_rows in onset_df.groupby("element_id"):
            elem_data = input_df[input_df[elem_id_col].astype(str) == str(element_id)]
            if elem_data.empty:
                log.warning("No input data rows found for element_id '%s'.", element_id)
                continue

            # Sort by time to ensure correct line plots
            time_col = next((c for c in elem_data.columns if c.lower() == "time"), None)
            if time_col is None:
                log.warning("No 'Time' column in input CSV for element '%s'.", element_id)
                continue
            elem_data = elem_data.sort_values(time_col)
            time = elem_data[time_col].values.astype(float)

            sup: dict[str, np.ndarray] = {}
            inf: dict[str, np.ndarray] = {}
            for comp in ("e11", "e22", "e12"):
                sup_col = f"SUP_{comp}"
                inf_col = f"INF_{comp}"
                if sup_col in elem_data.columns:
                    sup[comp] = elem_data[sup_col].values.astype(float)
                if inf_col in elem_data.columns:
                    inf[comp] = elem_data[inf_col].values.astype(float)

            onset_timesteps = onset_rows["timestep"].tolist()

            from ..views.buckling_onset_widget import BucklingOnsetWidget
            widget = BucklingOnsetWidget(
                element_id=str(element_id),
                time=time,
                sup=sup,
                inf=inf,
                onset_timesteps=onset_timesteps,
            )
            tab_view.add_raw_tab(widget, f"Onset: {element_id}")
            count += 1

        if count == 0:
            QMessageBox.information(
                self._view,
                "No Onset Detected",
                "The analysis completed but no buckling onset was matched to input data.",
            )
        else:
            QMessageBox.information(
                self._view,
                "Onset Analysis Complete",
                f"Buckling onset detected for {count} element(s).\n"
                "New tabs have been created for each element.",
            )

    def _build_buckling_groups(self) -> list[BucklingGroup]:
        """Build BucklingGroup objects from mapping sensor-pair data and loaded DataFrames.

        Rosette groups
        --------------
        For each rosette that maps to another rosette (via the Sensor Pair column),
        one ``BucklingGroup`` is created *per imported source*.  Within each group:

        * Left column  — sensors of the **own** rosette taken from that source.
        * Right column — sensors of the **paired** rosette taken from the same source.

        The ``source_headers`` use the rosette IDs as column labels rather than
        source display names, while ``source_label`` carries the source filename
        for display in the card header.

        Individual groups
        -----------------
        Sensors without a rosette keep the original behaviour: one group showing
        all sources as side-by-side columns.
        """
        sensor_pairs = self._mapping.sensor_pair_data()   # {canonical: pair_id}
        rosette_data = self._mapping.rosette_data()        # {canonical: rosette_id}
        all_sources = list(self._data.all_sources())
        _cor_defaults = ["e11", "e12", "e22"]

        # ── Group canonicals by their own rosette ID ──────────────────────
        rosette_to_canonicals: dict[str, list[str]] = {}
        for canonical, rosette_id in rosette_data.items():
            if rosette_id:
                rosette_to_canonicals.setdefault(rosette_id, []).append(canonical)

        groups: list[BucklingGroup] = []

        # ── Rosette groups (one per own-rosette × source) ─────────────────
        for own_rosette, own_canonicals in rosette_to_canonicals.items():
            # Determine which rosette the own-rosette maps TO
            paired_rosette: str | None = None
            for c in own_canonicals:
                pair_val = sensor_pairs.get(c, "")
                if pair_val and pair_val != own_rosette and pair_val in rosette_to_canonicals:
                    paired_rosette = pair_val
                    break

            if paired_rosette is None:
                continue  # no valid cross-rosette mapping found

            paired_canonicals = rosette_to_canonicals[paired_rosette]

            for src in all_sources:
                sensors: list[SensorEntry] = []
                for idx, (own_can, paired_can) in enumerate(
                    zip(own_canonicals, paired_canonicals)
                ):
                    own_name, own_data = self._sensor_in_source(own_can, src)
                    paired_name, paired_data = self._sensor_in_source(paired_can, src)

                    default_cor = (
                        _cor_defaults[idx] if idx < len(_cor_defaults)
                        else f"e{idx + 1}{idx + 1}"
                    )
                    sensors.append(SensorEntry(
                        canonical=own_can,
                        default_cor=default_cor,
                        sources=[
                            SourceInfo(
                                source_id=src.source_id,
                                display_name=own_rosette,
                                sensor_name=own_name,
                                data=own_data,
                            ),
                            SourceInfo(
                                source_id=src.source_id,
                                display_name=paired_rosette,
                                sensor_name=paired_name,
                                data=paired_data,
                            ),
                        ],
                    ))

                groups.append(BucklingGroup(
                    pair_id=f"{own_rosette} → {paired_rosette}",
                    is_rosette=True,
                    rosette_id=own_rosette,
                    source_label=src.display_name,
                    sensors=sensors,
                    source_headers=[("left", own_rosette), ("right", paired_rosette)],
                ))

        # ── Individual groups (no rosette, old behaviour) ─────────────────
        individual_canonicals = [
            c for c in sensor_pairs if not rosette_data.get(c)
        ]
        source_headers_all = [(s.source_id, s.display_name) for s in all_sources]

        for canonical in individual_canonicals:
            src_infos: list[SourceInfo] = []
            for src in all_sources:
                name, data = self._sensor_in_source(canonical, src)
                src_infos.append(SourceInfo(
                    source_id=src.source_id,
                    display_name=src.display_name,
                    sensor_name=name,
                    data=data,
                ))
            groups.append(BucklingGroup(
                pair_id=canonical,
                is_rosette=False,
                rosette_id="",
                source_label="",
                sensors=[SensorEntry(
                    canonical=canonical,
                    default_cor="e11",
                    sources=src_infos,
                )],
                source_headers=source_headers_all,
            ))

        log.info(
            "Built %d buckling group(s) (%d rosette×source, %d individual).",
            len(groups),
            sum(1 for g in groups if g.is_rosette),
            sum(1 for g in groups if not g.is_rosette),
        )
        return groups

    def _sensor_in_source(
        self, canonical: str, src
    ) -> tuple[str, pd.Series | None]:
        """Return ``(sensor_name, data)`` for *canonical* in *src*, or ``("—", None)``."""
        alias_names = set(self._mapping.get_aliases(canonical).values())
        df_idx_set = set(src.df.index.astype(str))
        for alias in alias_names:
            if alias in df_idx_set:
                return alias, src.df.loc[alias]
        return "—", None
