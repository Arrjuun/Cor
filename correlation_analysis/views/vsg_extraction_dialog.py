"""VSG Extraction dialog."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt
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
    QPushButton,
    QSizePolicy,
    QSpacerItem,
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


class VsgExtractionDialog(QDialog):
    """Dialog for VSG extraction configuration and execution."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VSG Extraction")
        self.setMinimumWidth(500)
        self._input_file: str = ""
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

        logger.info("VSG Extraction requested")
        logger.info("  Abaqus Version   : %s", version)
        logger.info("  Input File       : %s", self._input_file)
        logger.info("  Advanced         : %s", advanced)
        logger.info("  Component Index  : %s", component_index)
        logger.info("  Radius Tolerance : %s", radius_tolerance)
        logger.info("  Intervals        : %s", intervals)
        logger.info("  Angle Step       : %s", angle_step)
        logger.info("  Print VSG        : %s", print_vsg)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _update_extract_button(self) -> None:
        self._extract_btn.setEnabled(bool(self._input_file))
