"""VSG Extraction dialog."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

ABAQUS_VERSIONS = ["2019", "2020_1", "2020_2", "2020_3"]

DEFAULTS = {
    "component_index": 1,
    "radius_tolerance": 3,
    "intervals": 100,
    "angle_step": 10,
}

from ..utils.paths import get_app_root

# Path to vsg_extraction.py: resolved from the app root so it works regardless
# of the current working directory or whether the app is frozen.
_SCRIPT_PATH = get_app_root() / "correlation_analysis" / "vsg_extraction" / "vsg_extraction.py"


class VsgExtractionDialog(QDialog):
    """Dialog for VSG extraction configuration and execution."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VSG Extraction")
        self.setMinimumWidth(560)
        self._input_file: str = ""
        self._process: Optional[QProcess] = None
        self._build_ui()
        self._update_extract_button()

    # ------------------------------------------------------------------ #
    # UI construction                                                      #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ---- Main content group ----
        content_group = QGroupBox("Extraction Settings")
        form_layout = QFormLayout(content_group)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setSpacing(10)

        # Abaqus Version
        self._version_combo = QComboBox()
        self._version_combo.addItems(ABAQUS_VERSIONS)
        form_layout.addRow("Abaqus Version:", self._version_combo)

        # Input file
        file_row = QWidget()
        file_row_layout = QVBoxLayout(file_row)
        file_row_layout.setContentsMargins(0, 0, 0, 0)
        file_row_layout.setSpacing(6)

        self._select_btn = QPushButton("Select Input File…")
        self._select_btn.clicked.connect(self._on_select_file)
        file_row_layout.addWidget(self._select_btn)

        # File path display (hidden until a file is chosen)
        self._file_tag_widget = QWidget()
        file_tag_layout = QHBoxLayout(self._file_tag_widget)
        file_tag_layout.setContentsMargins(0, 0, 0, 0)
        file_tag_layout.setSpacing(4)

        self._file_path_label = QLabel()
        self._file_path_label.setWordWrap(True)
        self._file_path_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        file_tag_layout.addWidget(self._file_path_label)

        remove_btn = QPushButton("✕")
        remove_btn.setFixedSize(24, 24)
        remove_btn.setToolTip("Remove selected file")
        remove_btn.clicked.connect(self._on_remove_file)
        file_tag_layout.addWidget(remove_btn)

        file_row_layout.addWidget(self._file_tag_widget)
        self._file_tag_widget.setVisible(False)

        form_layout.addRow("Input File:", file_row)

        root.addWidget(content_group)

        root.addSpacerItem(QSpacerItem(0, 8, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))

        # ---- Advanced panel (hidden until checkbox is ticked) ----
        self._advanced_panel = self._build_advanced_panel()
        self._advanced_panel.setVisible(False)
        root.addWidget(self._advanced_panel)

        # ---- Output panel ----
        self._output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(self._output_group)
        output_layout.setContentsMargins(8, 8, 8, 8)

        self._output_edit = QTextEdit()
        self._output_edit.setReadOnly(True)
        self._output_edit.setMinimumHeight(120)
        self._output_edit.setFont(self._output_edit.font())  # monospace via stylesheet
        self._output_edit.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        output_layout.addWidget(self._output_edit)

        self._output_group.setVisible(False)
        root.addWidget(self._output_group)

        # ---- Bottom row: Extract (left) | Advanced checkbox (right) ----
        bottom_row = QHBoxLayout()

        self._extract_btn = QPushButton("Extract")
        self._extract_btn.setEnabled(False)
        self._extract_btn.clicked.connect(self._on_extract)
        bottom_row.addWidget(self._extract_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        bottom_row.addStretch()

        self._advanced_chk = QCheckBox("Advanced")
        self._advanced_chk.toggled.connect(self._advanced_panel.setVisible)
        bottom_row.addWidget(self._advanced_chk, alignment=Qt.AlignmentFlag.AlignRight)

        root.addLayout(bottom_row)

    def _build_advanced_panel(self) -> QGroupBox:
        group = QGroupBox("Advanced Options")
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self._component_index_edit = QLineEdit(str(DEFAULTS["component_index"]))
        self._component_index_edit.setPlaceholderText("e.g. 1")
        form.addRow("Component Index:", self._component_index_edit)

        self._radius_tolerance_edit = QLineEdit(str(DEFAULTS["radius_tolerance"]))
        self._radius_tolerance_edit.setPlaceholderText("e.g. 3")
        form.addRow("Radius Tolerance:", self._radius_tolerance_edit)

        self._intervals_edit = QLineEdit(str(DEFAULTS["intervals"]))
        self._intervals_edit.setPlaceholderText("e.g. 100")
        form.addRow("Intervals:", self._intervals_edit)

        self._angle_step_edit = QLineEdit(str(DEFAULTS["angle_step"]))
        self._angle_step_edit.setPlaceholderText("e.g. 10")
        form.addRow("Angle Step:", self._angle_step_edit)

        self._print_vsg_chk = QCheckBox("Print VSG extraction")
        form.addRow("", self._print_vsg_chk)

        return group

    # ------------------------------------------------------------------ #
    # Handlers                                                             #
    # ------------------------------------------------------------------ #

    def _on_select_file(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Input File", filter="Text Files (*.txt);;All Files (*)"
        )
        if filepath:
            self._input_file = filepath
            self._file_path_label.setText(filepath)
            self._file_tag_widget.setVisible(True)
            self._update_extract_button()

    def _on_remove_file(self) -> None:
        self._input_file = ""
        self._file_path_label.clear()
        self._file_tag_widget.setVisible(False)
        self._update_extract_button()

    def _on_extract(self) -> None:
        if self._process and self._process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.warning(self, "Busy", "An extraction is already running.")
            return

        version = self._version_combo.currentText()
        advanced = self._advanced_chk.isChecked()

        if advanced:
            component_index = self._component_index_edit.text().strip() or str(DEFAULTS["component_index"])
            radius_tolerance = self._radius_tolerance_edit.text().strip() or str(DEFAULTS["radius_tolerance"])
            intervals = self._intervals_edit.text().strip() or str(DEFAULTS["intervals"])
            angle_step = self._angle_step_edit.text().strip() or str(DEFAULTS["angle_step"])
            print_vsg = self._print_vsg_chk.isChecked()
        else:
            component_index = str(DEFAULTS["component_index"])
            radius_tolerance = str(DEFAULTS["radius_tolerance"])
            intervals = str(DEFAULTS["intervals"])
            angle_step = str(DEFAULTS["angle_step"])
            print_vsg = False

        args = self._build_abaqus_args(
            version=version,
            input_file=self._input_file,
            component_index=component_index,
            radius_tolerance=radius_tolerance,
            intervals=intervals,
            angle_step=angle_step,
            print_vsg=print_vsg,
        )

        logger.info("Launching: abaqus %s", " ".join(args))
        self._output_edit.clear()
        self._output_group.setVisible(True)
        self._append_output(f"$ abaqus {' '.join(args)}\n")

        self._extract_btn.setEnabled(False)

        self._process = QProcess(self)
        self._process.setWorkingDirectory(os.getcwd())
        self._process.readyReadStandardOutput.connect(self._on_stdout)
        self._process.readyReadStandardError.connect(self._on_stderr)
        self._process.finished.connect(self._on_process_finished)

        self._process.start("abaqus", args)

        if not self._process.waitForStarted(3000):
            self._append_output("[ERROR] Failed to start abaqus process.\n")
            logger.error("Failed to start abaqus process")
            self._extract_btn.setEnabled(True)

    def _on_stdout(self) -> None:
        if self._process:
            text = bytes(self._process.readAllStandardOutput()).decode("utf-8", errors="replace")
            self._append_output(text)

    def _on_stderr(self) -> None:
        if self._process:
            text = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace")
            self._append_output(text)

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self._append_output("\n[Process completed successfully]\n")
            logger.info("VSG extraction process finished (exit code 0)")
        else:
            self._append_output(f"\n[Process exited with code {exit_code}]\n")
            logger.warning("VSG extraction process finished with exit code %d", exit_code)
        self._update_extract_button()

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_abaqus_args(
        version: str,
        input_file: str,
        component_index: str,
        radius_tolerance: str,
        intervals: str,
        angle_step: str,
        print_vsg: bool,
    ) -> list[str]:
        """Build the argument list for the abaqus process.

        Mirrors the C# launcher:
            abaqus [--version=<ver>] python <script> <file> [advanced args...]
        """
        args: list[str] = []

        if version:
            args.append(f"--version={version}")

        args.extend([
            "python",
            str(_SCRIPT_PATH),
            input_file,
            f"--component-index={component_index}",
            f"--radius-tolerance={radius_tolerance}",
            f"--intervals={intervals}",
            f"--angle-step={angle_step}",
        ])

        if print_vsg:
            args.append("--print-vsg")

        return args

    def _append_output(self, text: str) -> None:
        self._output_edit.moveCursor(self._output_edit.textCursor().MoveOperation.End)
        self._output_edit.insertPlainText(text)
        self._output_edit.ensureCursorVisible()

    def _update_extract_button(self) -> None:
        running = bool(
            self._process and self._process.state() != QProcess.ProcessState.NotRunning
        )
        self._extract_btn.setEnabled(bool(self._input_file) and not running)
