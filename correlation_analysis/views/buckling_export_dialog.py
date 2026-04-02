"""Export settings dialog for the buckling analysis output files."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..utils.buckling_exporter import BucklingExportSettings

# Root of the project (…/Correlation/) — two levels up from this file's package
_SCRIPT_ROOT = Path(__file__).resolve().parents[2]

# Fixed paths relative to the script root
_PYTHON_ENV_REL = "../../Envs/env"
_FEMBUCKLING_REL = "../../Buckling/fembuckling"


def _make_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _auto_csv_path(ts: str) -> Path:
    """<cwd>/Buckling_Exports/buckling_<ts>.csv"""
    return Path.cwd() / "Buckling_Exports" / f"buckling_{ts}.csv"


def _auto_output_dir(ts: str) -> Path:
    """<cwd>/Buckling_Exports/results_<ts>/"""
    return Path.cwd() / "Buckling_Exports" / f"results_{ts}"


def _auto_env_path() -> Path:
    return (_SCRIPT_ROOT / _PYTHON_ENV_REL).resolve()


def _auto_fembuckling_path() -> Path:
    return (_SCRIPT_ROOT / _FEMBUCKLING_REL).resolve()


class BucklingExportDialog(QDialog):
    """Dialog for configuring buckling analysis export settings.

    Auto-generated paths (CSV, output dir, Python env, fembuckling dir) are
    shown read-only.  Only analysis parameters are editable.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Buckling Analysis — Export Settings")
        self.setMinimumWidth(620)

        self._ts = _make_timestamp()
        self._csv_path = _auto_csv_path(self._ts)
        self._output_dir = _auto_output_dir(self._ts)
        self._env_path = _auto_env_path()
        self._fembuckling_path = _auto_fembuckling_path()

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- Auto-generated paths (read-only) ----
        paths_box = QGroupBox("Auto-generated Paths")
        paths_form = QFormLayout(paths_box)
        paths_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._csv_display = self._ro_field(str(self._csv_path))
        paths_form.addRow("CSV file:", self._csv_display)

        self._dir_display = self._ro_field(str(self._output_dir))
        paths_form.addRow("Results directory:", self._dir_display)

        self._env_display = self._ro_field(str(self._env_path))
        paths_form.addRow("Python environment:", self._env_display)

        self._fb_display = self._ro_field(str(self._fembuckling_path))
        paths_form.addRow("fembuckling dir:", self._fb_display)

        layout.addWidget(paths_box)

        # ---- Analysis settings ----
        analysis_box = QGroupBox("Analysis Settings")
        analysis_form = QFormLayout(analysis_box)
        analysis_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Detection methods
        method_row = QHBoxLayout()
        self._method_acceleration = QCheckBox("acceleration")
        self._method_acceleration.setChecked(True)
        self._method_reversal = QCheckBox("reversal")
        self._method_reversal.setChecked(False)
        method_row.addWidget(self._method_acceleration)
        method_row.addWidget(self._method_reversal)
        method_row.addStretch()
        method_label = QLabel("method:")
        method_label.setToolTip(
            "Detection method(s). Generates: method: [acceleration] or "
            "method: [reversal, acceleration]"
        )
        analysis_form.addRow(method_label, method_row)

        # Chain
        self._chain_check = QCheckBox()
        self._chain_check.setChecked(False)
        self._chain_check.setToolTip(
            "An element is only considered buckled if every selected method detects it."
        )
        analysis_form.addRow("chain:", self._chain_check)

        # savgol_window
        self._savgol_window = QSpinBox()
        self._savgol_window.setRange(1, 999)
        self._savgol_window.setSingleStep(2)
        self._savgol_window.setValue(7)
        self._savgol_window.setToolTip("Window size for Savitzky-Golay filter (must be odd)")
        analysis_form.addRow("savgol_window:", self._savgol_window)

        # polynomial_degree
        self._polynomial_degree = QSpinBox()
        self._polynomial_degree.setRange(1, 10)
        self._polynomial_degree.setValue(4)
        self._polynomial_degree.setToolTip("Polynomial order for Savitzky-Golay filter")
        analysis_form.addRow("polynomial_degree:", self._polynomial_degree)

        # acceleration_prominence
        self._acceleration_prominence = QDoubleSpinBox()
        self._acceleration_prominence.setRange(0.0, 1e6)
        self._acceleration_prominence.setDecimals(4)
        self._acceleration_prominence.setValue(0.1)
        self._acceleration_prominence.setToolTip(
            "Minimum relative acceleration prominence (2nd derivative) for a peak"
        )
        analysis_form.addRow("acceleration_prominence:", self._acceleration_prominence)

        # reversal_prominence
        self._reversal_prominence = QDoubleSpinBox()
        self._reversal_prominence.setRange(0.0, 1e6)
        self._reversal_prominence.setDecimals(6)
        self._reversal_prominence.setValue(0.0005)
        self._reversal_prominence.setSingleStep(0.0001)
        self._reversal_prominence.setToolTip(
            "Minimum relative strain prominence at a reversal point"
        )
        analysis_form.addRow("reversal_prominence:", self._reversal_prominence)

        # workers
        self._workers = QSpinBox()
        self._workers.setRange(1, 64)
        self._workers.setValue(4)
        self._workers.setToolTip("Number of parallel worker processes")
        analysis_form.addRow("workers:", self._workers)

        # log_level
        self._log_level = QComboBox()
        self._log_level.addItems(["INFO", "DEBUG", "WARNING", "ERROR"])
        self._log_level.setCurrentText("INFO")
        analysis_form.addRow("log_level:", self._log_level)

        layout.addWidget(analysis_box)

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _ro_field(text: str) -> QLineEdit:
        """Read-only, non-editable line edit."""
        edit = QLineEdit(text)
        edit.setReadOnly(True)
        edit.setStyleSheet("QLineEdit { background: #F5F5F5; color: #616161; }")
        return edit

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    def _on_accept(self) -> None:
        if not self._method_acceleration.isChecked() and not self._method_reversal.isChecked():
            QMessageBox.warning(self, "Missing Input", "Please select at least one detection method.")
            return
        self.accept()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_settings(self) -> BucklingExportSettings:
        """Return the current form values as a ``BucklingExportSettings`` object."""
        methods: list[str] = []
        if self._method_acceleration.isChecked():
            methods.append("acceleration")
        if self._method_reversal.isChecked():
            methods.append("reversal")

        return BucklingExportSettings(
            csv_path=str(self._csv_path),
            output_dir=str(self._output_dir),
            method=methods,
            chain=self._chain_check.isChecked(),
            savgol_window=self._savgol_window.value(),
            polynomial_degree=self._polynomial_degree.value(),
            acceleration_prominence=self._acceleration_prominence.value(),
            reversal_prominence=self._reversal_prominence.value(),
            workers=self._workers.value(),
            log_level=self._log_level.currentText(),
            python_env_dir=str(self._env_path),
            fembuckling_dir=str(self._fembuckling_path),
        )
