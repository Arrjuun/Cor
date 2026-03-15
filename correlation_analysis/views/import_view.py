"""Import & Cleanup View."""
from __future__ import annotations

from typing import Optional

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .data_table_widget import DataTableWidget


class SourceTableFrame(QFrame):
    """Framed container for a DataTableWidget with a validation border."""

    def __init__(self, widget: DataTableWidget, title: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._widget = widget
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        if title:
            lbl = QLabel(f"<b>{title}</b>")
            layout.addWidget(lbl)
        layout.addWidget(widget)

    def set_valid(self, valid: bool) -> None:
        color = "#4CAF50" if valid else "#F44336"
        self.setStyleSheet(
            f"SourceTableFrame {{ border: 2px solid {color}; border-radius: 4px; }}"
        )

    def data_widget(self) -> DataTableWidget:
        return self._widget


class ImportView(QWidget):
    """
    View 1: Data import and cleanup.

    Left panel  – list of imported files (click to view, right-click to remove).
    Right panel – the selected file's data table (one at a time).
    """

    import_csv_requested = Signal()
    import_mapping_requested = Signal()
    proceed_requested = Signal()
    remove_source_requested = Signal(str)   # source_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._frames: dict[str, SourceTableFrame] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        # ---- Toolbar ----
        toolbar = QHBoxLayout()
        self._btn_import = QPushButton("Import CSV")
        self._btn_mapping = QPushButton("Import Mapping")
        self._btn_proceed = QPushButton("Proceed to Analysis →")
        for btn in (self._btn_import, self._btn_mapping, self._btn_proceed):
            btn.setCheckable(False)
            toolbar.addWidget(btn)
        toolbar.addStretch()
        self._btn_import.clicked.connect(self.import_csv_requested)
        self._btn_mapping.clicked.connect(self.import_mapping_requested)
        self._btn_proceed.clicked.connect(self._on_proceed)
        self._btn_proceed.setEnabled(False)
        outer.addLayout(toolbar)

        # ---- Info label ----
        info = QLabel(
            "Import CSV files where <b>rows = sensors</b>, <b>columns = load steps</b>. "
            "Green border = valid format.  Red border = format issues."
        )
        info.setWordWrap(True)
        outer.addWidget(info)

        # ---- Main splitter: file list | table view ----
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(5)

        # Left: file list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.addWidget(QLabel("<b>Imported Files</b>"))

        self._file_list = QListWidget()
        self._file_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._file_list.customContextMenuRequested.connect(self._file_list_context_menu)
        self._file_list.currentItemChanged.connect(self._on_file_selected)
        self._file_list.setToolTip("Click to preview · Right-click to remove")
        left_layout.addWidget(self._file_list)

        left_panel.setMinimumWidth(140)
        left_panel.setMaximumWidth(260)
        splitter.addWidget(left_panel)

        # Right: stacked widget — one table per file, shown when selected
        self._stack = QStackedWidget()
        self._placeholder = QLabel("Select a file from the list to view its data.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #9E9E9E; font-style: italic;")
        self._stack.addWidget(self._placeholder)
        splitter.addWidget(self._stack)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, stretch=1)

        # ---- Mapping info label ----
        self._mapping_lbl = QLabel("No mapping loaded.")
        self._mapping_lbl.setStyleSheet("color: #757575;")
        outer.addWidget(self._mapping_lbl)

    # ------------------------------------------------------------------ #
    # File list interactions                                               #
    # ------------------------------------------------------------------ #

    def _on_file_selected(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            self._stack.setCurrentWidget(self._placeholder)
            return
        source_id = current.data(Qt.ItemDataRole.UserRole)
        frame = self._frames.get(source_id)
        if frame:
            self._stack.setCurrentWidget(frame)

    def _file_list_context_menu(self, pos) -> None:
        item = self._file_list.itemAt(pos)
        if item is None:
            return
        source_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        remove_act = menu.addAction(f"Remove  '{item.text()}'")
        action = menu.exec(self._file_list.mapToGlobal(pos))
        if action == remove_act:
            self.remove_source_requested.emit(source_id)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def add_source_table(
        self, source_id: str, df: pd.DataFrame,
        display_name: str = "", is_valid: bool = True,
    ) -> DataTableWidget:
        name = display_name or source_id

        # Add to file list
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, source_id)
        self._file_list.addItem(item)

        # Create table widget — no formula column in import view
        table_widget = DataTableWidget(
            df, source_id=source_id, title=name, show_formula=False,
        )
        frame = SourceTableFrame(table_widget, title="")
        frame.set_valid(is_valid)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._stack.addWidget(frame)

        self._frames[source_id] = frame
        self._btn_proceed.setEnabled(True)

        # Auto-select the newly imported file
        self._file_list.setCurrentItem(item)
        return table_widget

    def remove_source_table(self, source_id: str) -> None:
        """Remove the file list entry and its table."""
        # Remove from file list
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == source_id:
                self._file_list.takeItem(i)
                break

        # Remove from stack
        frame = self._frames.pop(source_id, None)
        if frame:
            self._stack.removeWidget(frame)
            frame.deleteLater()

        if not self._frames:
            self._stack.setCurrentWidget(self._placeholder)
            self._btn_proceed.setEnabled(False)

    def update_source_table(self, source_id: str, df: pd.DataFrame) -> None:
        frame = self._frames.get(source_id)
        if frame:
            frame.data_widget().update_dataframe(df)

    def set_source_valid(self, source_id: str, is_valid: bool) -> None:
        frame = self._frames.get(source_id)
        if frame:
            frame.set_valid(is_valid)

    def set_mapping_info(self, info: str) -> None:
        self._mapping_lbl.setText(info)

    def show_mapping_dialog(self, mapping_data: dict) -> None:
        """Show a read-only table of canonical → per-source aliases."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Sensor Mapping")
        dlg.setMinimumSize(640, 420)
        layout = QVBoxLayout(dlg)

        sources: list[str] = []
        for aliases in mapping_data.values():
            for src in aliases:
                if src not in sources:
                    sources.append(src)

        table = QTableWidget(len(mapping_data), 1 + len(sources))
        headers = ["Canonical Name"] + sources
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)

        from PySide6.QtGui import QColor as _QColor
        for row, (canonical, aliases) in enumerate(mapping_data.items()):
            it = QTableWidgetItem(canonical)
            it.setBackground(_QColor("#E3F2FD"))
            table.setItem(row, 0, it)
            for col_idx, src in enumerate(sources):
                alias = aliases.get(src, "—")
                cell = QTableWidgetItem(alias)
                if alias == "—":
                    cell.setForeground(_QColor("#BDBDBD"))
                table.setItem(row, 1 + col_idx, cell)

        table.resizeColumnsToContents()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(QLabel(
            f"<b>{len(mapping_data)}</b> canonical sensors mapped across "
            f"<b>{len(sources)}</b> source column(s):"
        ))
        layout.addWidget(table)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)
        dlg.exec()

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def show_warning(self, message: str) -> None:
        QMessageBox.warning(self, "Warning", message)

    def confirm_delete(self, items: list[str], item_type: str = "items") -> bool:
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {len(items)} {item_type}?\n\n" + "\n".join(str(x) for x in items[:10]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def get_table_widget(self, source_id: str) -> Optional[DataTableWidget]:
        frame = self._frames.get(source_id)
        return frame.data_widget() if frame else None

    def _on_proceed(self) -> None:
        if not self._frames:
            QMessageBox.warning(self, "No Data", "Import at least one CSV file first.")
            return
        self.proceed_requested.emit()
