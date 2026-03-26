"""Export settings dialog for the buckling analysis output files."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..utils.buckling_exporter import BucklingExportSettings


class BucklingExportDialog(QDialog):
    """Dialog for configuring CSV / YAML export before running buckling analysis.

    Collects:
    - CSV output file path
    - Results output directory
    - Analysis strategy and its parameters
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Buckling Analysis — Export Settings")
        self.setMinimumWidth(560)
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- Output files ----
        files_box = QGroupBox("Output Files")
        files_form = QFormLayout(files_box)
        files_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # CSV path
        csv_row = QHBoxLayout()
        self._csv_edit = QLineEdit()
        self._csv_edit.setPlaceholderText("Select CSV output file…")
        csv_browse = QPushButton("Browse…")
        csv_browse.setCheckable(False)
        csv_browse.setFixedWidth(80)
        csv_browse.clicked.connect(self._browse_csv)
        csv_row.addWidget(self._csv_edit)
        csv_row.addWidget(csv_browse)
        files_form.addRow("CSV file:", csv_row)

        # Output directory
        dir_row = QHBoxLayout()
        self._dir_edit = QLineEdit()
        self._dir_edit.setPlaceholderText("Select results output directory…")
        dir_browse = QPushButton("Browse…")
        dir_browse.setCheckable(False)
        dir_browse.setFixedWidth(80)
        dir_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(self._dir_edit)
        dir_row.addWidget(dir_browse)
        files_form.addRow("Results directory:", dir_row)

        layout.addWidget(files_box)

        # ---- Analysis strategy ----
        strategy_box = QGroupBox("Analysis Strategy")
        strategy_form = QFormLayout(strategy_box)
        strategy_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._strategy_combo = QComboBox()
        self._strategy_combo.addItems(["hybrid", "minima", "acceleration"])
        strategy_form.addRow("Active strategy:", self._strategy_combo)

        layout.addWidget(strategy_box)

        # ---- Strategy parameters ----
        params_box = QGroupBox("Strategy Parameters")
        params_form = QFormLayout(params_box)
        params_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # minima
        self._minima_prominence = QDoubleSpinBox()
        self._minima_prominence.setRange(0.0, 1e6)
        self._minima_prominence.setDecimals(4)
        self._minima_prominence.setValue(0.0)
        self._minima_prominence.setToolTip("Minima strategy: minima_prominence")
        params_form.addRow("Minima prominence:", self._minima_prominence)

        # acceleration
        self._window_length = QSpinBox()
        self._window_length.setRange(1, 999)
        self._window_length.setSingleStep(2)
        self._window_length.setValue(7)
        self._window_length.setToolTip("Acceleration strategy: Savitzky-Golay window length (must be odd)")
        params_form.addRow("Window length:", self._window_length)

        self._polyorder = QSpinBox()
        self._polyorder.setRange(1, 10)
        self._polyorder.setValue(2)
        self._polyorder.setToolTip("Acceleration strategy: Savitzky-Golay polynomial order")
        params_form.addRow("Poly order:", self._polyorder)

        # hybrid
        self._jerk_threshold = _ScientificSpinBox(default=1.0e-5)
        self._jerk_threshold.setToolTip("Hybrid strategy: acceleration_jerk_threshold")
        params_form.addRow("Jerk threshold:", self._jerk_threshold)

        self._magnitude_threshold = _ScientificSpinBox(default=1.0e-6)
        self._magnitude_threshold.setToolTip("Hybrid strategy: min_principal_magnitude_threshold")
        params_form.addRow("Magnitude threshold:", self._magnitude_threshold)

        layout.addWidget(params_box)

        # ---- Python executable ----
        script_box = QGroupBox("Run Analysis (optional)")
        script_form = QFormLayout(script_box)
        script_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        script_row = QHBoxLayout()
        self._script_edit = QLineEdit()
        self._script_edit.setPlaceholderText(
            "Full path to python.exe with fembuckling installed — leave blank to export only"
        )
        script_browse = QPushButton("Browse…")
        script_browse.setCheckable(False)
        script_browse.setFixedWidth(80)
        script_browse.clicked.connect(self._browse_script)
        script_row.addWidget(self._script_edit)
        script_row.addWidget(script_browse)
        script_form.addRow("Python executable:", script_row)

        layout.addWidget(script_box)

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    def _browse_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Buckling CSV",
            filter="CSV Files (*.csv);;All Files (*)",
        )
        if path:
            if not path.lower().endswith(".csv"):
                path += ".csv"
            self._csv_edit.setText(path)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Results Directory")
        if path:
            self._dir_edit.setText(path)

    def _browse_script(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Python Executable",
            filter="Executables (*.exe);;All Files (*)",
        )
        if path:
            self._script_edit.setText(path)

    def _on_accept(self) -> None:
        csv_path = self._csv_edit.text().strip()
        out_dir = self._dir_edit.text().strip()
        if not csv_path:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Missing Input", "Please specify a CSV output file path.")
            return
        if not out_dir:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Missing Input", "Please specify a results output directory.")
            return
        self.accept()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get_settings(self) -> BucklingExportSettings:
        """Return the current form values as a ``BucklingExportSettings`` object."""
        return BucklingExportSettings(
            csv_path=self._csv_edit.text().strip(),
            output_dir=self._dir_edit.text().strip(),
            active_strategy=self._strategy_combo.currentText(),
            minima_prominence=self._minima_prominence.value(),
            window_length=self._window_length.value(),
            polyorder=self._polyorder.value(),
            acceleration_jerk_threshold=self._jerk_threshold.value(),
            min_principal_magnitude_threshold=self._magnitude_threshold.value(),
            python_exe_path=self._script_edit.text().strip(),
        )


# ------------------------------------------------------------------ #
# Helper: scientific-notation double spin box                          #
# ------------------------------------------------------------------ #

class _ScientificSpinBox(QWidget):
    """A simple QLineEdit that accepts and displays values in scientific notation."""

    def __init__(self, default: float = 1.0e-5, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._edit = QLineEdit(f"{default:.1e}")
        self._edit.setFixedWidth(120)
        layout.addWidget(self._edit)
        layout.addStretch()
        self._default = default

    def value(self) -> float:
        try:
            return float(self._edit.text().strip())
        except ValueError:
            return self._default

    def setValue(self, v: float) -> None:
        self._edit.setText(f"{v:.1e}")

    def setToolTip(self, tip: str) -> None:  # type: ignore[override]
        self._edit.setToolTip(tip)
