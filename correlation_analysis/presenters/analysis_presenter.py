"""Analysis View Presenter."""
from __future__ import annotations

import logging
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
            csv_path, yaml_path, element_source_map = write_export(selections, self._data, settings)
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

        if not settings.python_env_dir:
            QMessageBox.information(
                self._view,
                "Export Complete",
                f"Buckling analysis files written:\n\nCSV:  {csv_path}\nYAML: {yaml_path}",
            )
            return

        # Resolve python executable from the environment directory
        env_path = Path(settings.python_env_dir)
        python_exe = env_path / "python.exe"
        if not python_exe.exists():
            python_exe = env_path / "Scripts" / "python.exe"
        if not python_exe.exists():
            python_exe = env_path / "bin" / "python"
        if not python_exe.exists():
            QMessageBox.critical(
                self._view,
                "Python Not Found",
                f"Could not locate a Python executable in:\n{settings.python_env_dir}",
            )
            return

        self._run_buckling_script(
            str(python_exe),
            yaml_path,
            csv_path,
            settings.output_dir,
            settings.fembuckling_dir,
            element_source_map,
        )

    def _run_buckling_script(
        self,
        python_exe_path: str,
        yaml_path: str,
        input_csv_path: str,
        output_dir: str,
        fembuckling_dir: str = "",
        element_source_map: dict | None = None,
    ) -> None:
        """Launch fembuckling.onset via the specified Python executable and process its output.

        Sets PYTHONPATH to the parent of *fembuckling_dir* so the module can be
        found even when it is not installed in the environment.
        """
        from PySide6.QtCore import QProcessEnvironment

        program = python_exe_path
        args = ["-m", "fembuckling.onset", yaml_path]

        process = QProcess(self._view)

        if fembuckling_dir:
            package_parent = str(Path(fembuckling_dir).parent)
            env = QProcessEnvironment.systemEnvironment()
            existing_pythonpath = env.value("PYTHONPATH", "")
            sep = ";" if Path(python_exe_path).suffix.lower() == ".exe" else ":"
            new_pythonpath = (
                package_parent + sep + existing_pythonpath
                if existing_pythonpath
                else package_parent
            )
            env.insert("PYTHONPATH", new_pythonpath)
            process.setProcessEnvironment(env)

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
                f"Could not start the Python executable:\n{python_exe_path}\n\n"
                "Ensure the environment path is correct and the fembuckling directory is set.",
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
        self._load_onset_results(input_csv_path, output_dir, element_source_map or {})

    @staticmethod
    def _undot(s: str) -> str:
        """Reverse the per-character dot-insertion that fembuckling applies to element IDs.

        fembuckling encodes ``Sensor_123`` as ``S.e.n.s.o.r._.1.2.3`` in its
        output CSV.  Removing all dots recovers the original ID.
        """
        return s.replace(".", "")

    def _load_onset_results(
        self,
        input_csv_path: str,
        output_dir: str,
        element_source_map: dict[str, dict] | None = None,
    ) -> None:
        """Find the onset CSV in *output_dir*, parse it, and create per-element onset tabs."""
        if element_source_map is None:
            element_source_map = {}
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

        # Build a reverse lookup so that fembuckling's dot-encoded element IDs
        # (e.g. "S.e.n.s.o.r._.1.2.3" for "Sensor_123") can be resolved back
        # to the original element ID that was written to the input CSV.
        undot_to_original: dict[str, str] = {}
        for orig in element_source_map:
            undot_to_original[orig] = orig                       # exact match
            undot_to_original[self._undot(orig)] = orig          # dot-decoded match

        for element_id_raw, onset_rows in onset_df.groupby("element_id"):
            raw_str = str(element_id_raw)
            # Resolve dotted form → original element ID
            original_id = (
                undot_to_original.get(raw_str)
                or undot_to_original.get(self._undot(raw_str))
                or raw_str
            )

            elem_data = input_df[input_df[elem_id_col].astype(str) == original_id]
            if elem_data.empty:
                log.warning(
                    "No input data rows found for element_id '%s' (raw: '%s').",
                    original_id, raw_str,
                )
                continue

            # Sort by time to ensure correct line plots
            time_col = next((c for c in elem_data.columns if c.lower() == "time"), None)
            if time_col is None:
                log.warning("No 'Time' column in input CSV for element '%s'.", original_id)
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

            # Resolve display name: use source-specific sensor names when available
            elem_info = element_source_map.get(original_id, {})
            if isinstance(elem_info, dict):
                source_label = elem_info.get("source_label", "")
                sensor_names: list[str] = elem_info.get("sensor_names", [])
            else:
                # Legacy plain-string fallback
                source_label = str(elem_info)
                sensor_names = []

            display_id = sensor_names[0] if sensor_names else original_id

            from ..views.buckling_onset_widget import BucklingOnsetWidget
            widget = BucklingOnsetWidget(
                element_id=display_id,
                time=time,
                sup=sup,
                inf=inf,
                onset_timesteps=onset_timesteps,
                source_label=source_label,
            )
            tab_view.add_raw_tab(widget, f"Onset: {display_id}")
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

        # ── Individual sensor groups (per-source pairs) ───────────────────
        # Identify canonical pairs from the sensor_pair column.
        # Supports both cross-reference (A.pair = B, B.pair = A) and
        # shared-ID patterns (A.pair = "EL_01", B.pair = "EL_01").
        individual_canonicals = [c for c in sensor_pairs if not rosette_data.get(c)]
        ind_canonical_set = set(individual_canonicals)
        already_paired: set[str] = set()
        individual_pairs: list[tuple[str, str]] = []

        for own_can in individual_canonicals:
            if own_can in already_paired:
                continue
            pair_val = sensor_pairs.get(own_can, "")
            if not pair_val or pair_val == own_can:
                continue  # self-referential — no usable pair

            if pair_val in ind_canonical_set:
                # pair_val is itself a canonical → direct cross-reference
                paired_can = pair_val
            else:
                # pair_val is a shared group ID; find another canonical with the same value
                partners = [
                    c for c in individual_canonicals
                    if c != own_can and sensor_pairs.get(c) == pair_val
                    and c not in already_paired
                ]
                if not partners:
                    continue
                paired_can = partners[0]

            individual_pairs.append((own_can, paired_can))
            already_paired.add(own_can)
            already_paired.add(paired_can)

        for own_can, paired_can in individual_pairs:
            for src in all_sources:
                own_name, own_data = self._sensor_in_source(own_can, src)
                paired_name, paired_data = self._sensor_in_source(paired_can, src)
                groups.append(BucklingGroup(
                    pair_id=f"{own_can} → {paired_can}",
                    is_rosette=False,
                    rosette_id="",
                    source_label=src.display_name,
                    sensors=[SensorEntry(
                        canonical=own_can,
                        default_cor="e11",
                        sources=[
                            SourceInfo(source_id=src.source_id, display_name=own_can,
                                       sensor_name=own_name, data=own_data),
                            SourceInfo(source_id=src.source_id, display_name=paired_can,
                                       sensor_name=paired_name, data=paired_data),
                        ],
                    )],
                    source_headers=[(own_can, own_can), (paired_can, paired_can)],
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
