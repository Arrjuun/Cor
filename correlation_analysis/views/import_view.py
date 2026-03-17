"""Import & Cleanup View."""
from __future__ import annotations

from typing import Optional

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


# ------------------------------------------------------------------ #
# Raw table model (no header consumed, generic "Column N" labels)     #
# ------------------------------------------------------------------ #

class RawTableModel(QAbstractTableModel):
    """
    Simple read-only model wrapping a raw DataFrame (integer index & columns).
    Horizontal headers shown as "Column 1", "Column 2", …
    Vertical headers shown as row numbers "1", "2", …
    """

    def __init__(self, df: pd.DataFrame, parent=None) -> None:
        super().__init__(parent)
        self._df = df.copy()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return len(self._df)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return len(self._df.columns)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        val = self._df.iloc[index.row(), index.column()]
        return "" if (val is None or (isinstance(val, float) and pd.isna(val))) else str(val)

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return f"Column {section + 1}"
        return str(section + 1)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def update_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df.copy()
        self.endResetModel()


# ------------------------------------------------------------------ #
# Import table widget                                                  #
# ------------------------------------------------------------------ #

class ImportTableWidget(QFrame):
    """
    Framed table for the import view.

    Shows all raw CSV data with generic "Column N" column headers.
    Supports row and column deletion via context menus.
    Validation state is shown as a green/red border.
    """

    row_delete_requested = Signal(str, list)      # source_id, list[int] positional indices
    column_delete_requested = Signal(str, list)   # source_id, list[int] positional indices
    scale_strain_requested = Signal(str, float)   # source_id, factor
    add_strain_requested = Signal(str, float)     # source_id, offset
    offset_loadsteps_requested = Signal(str, float)  # source_id, offset

    def __init__(
        self,
        df: pd.DataFrame,
        source_id: str,
        title: str = "",
        is_valid: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._source_id = source_id
        self._is_valid = is_valid
        self._build_ui(df, title)
        self.set_valid(is_valid)

    def _build_ui(self, df: pd.DataFrame, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        if title:
            lbl = QLabel(f"<b>{title}</b>")
            layout.addWidget(lbl)

        self._model = RawTableModel(df)

        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._table_context_menu)
        self._table.clicked.connect(self._on_body_clicked)

        # Horizontal header — Qt auto-calls selectColumn on sectionClicked; we only add context menu
        col_hdr = self._table.horizontalHeader()
        col_hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        col_hdr.customContextMenuRequested.connect(self._col_header_context_menu)
        col_hdr.setSectionsClickable(True)
        col_hdr.setHighlightSections(True)
        col_hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        col_hdr.setStretchLastSection(False)

        # Vertical header — Qt auto-calls selectRow on sectionClicked; we only add context menu
        row_hdr = self._table.verticalHeader()
        row_hdr.setVisible(True)
        row_hdr.setSectionsClickable(True)
        row_hdr.setHighlightSections(True)
        row_hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row_hdr.customContextMenuRequested.connect(self._row_header_context_menu)

        layout.addWidget(self._table)

    def _on_body_clicked(self, index: QModelIndex) -> None:
        """Expand a body-cell click to select the entire row."""
        row = index.row()
        n_cols = self._model.columnCount()
        row_sel = QItemSelection(
            self._model.index(row, 0),
            self._model.index(row, n_cols - 1),
        )
        sel = self._table.selectionModel()
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            sel.select(row_sel, QItemSelectionModel.SelectionFlag.Toggle)
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            anchor = sel.currentIndex()
            start = min(anchor.row(), row) if anchor.isValid() else row
            end = max(anchor.row(), row) if anchor.isValid() else row
            range_sel = QItemSelection(
                self._model.index(start, 0),
                self._model.index(end, n_cols - 1),
            )
            sel.select(range_sel, QItemSelectionModel.SelectionFlag.Select)
        else:
            sel.select(row_sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)

    # ------------------------------------------------------------------ #
    # Column header context menu                                           #
    # ------------------------------------------------------------------ #

    def _col_header_context_menu(self, pos) -> None:
        col = self._table.horizontalHeader().logicalIndexAt(pos)
        if col < 0:
            return
        menu = QMenu(self)
        select_act = menu.addAction(f"Select Column {col + 1}")
        select_act.setToolTip("Ctrl+click header to add to current selection")
        menu.addSeparator()
        delete_act = menu.addAction(f"Delete Column {col + 1}")
        delete_sel_act = menu.addAction("Delete Selected Column(s)")
        if self._is_valid:
            menu.addSeparator()
            offset_ls_act = menu.addAction("Offset Load Steps…")
            offset_ls_act.setToolTip("Add a scalar to all load-step values in the header row")
        else:
            offset_ls_act = None
        action = menu.exec(self._table.horizontalHeader().mapToGlobal(pos))
        if action == select_act:
            self._table.selectColumn(col)
        elif action == delete_act:
            self.column_delete_requested.emit(self._source_id, [col])
        elif action == delete_sel_act:
            self._delete_selected_columns()
        elif offset_ls_act and action == offset_ls_act:
            self._request_offset_loadsteps()

    # ------------------------------------------------------------------ #
    # Row header context menu                                              #
    # ------------------------------------------------------------------ #

    def _row_header_context_menu(self, pos) -> None:
        row = self._table.verticalHeader().logicalIndexAt(pos)
        if row < 0:
            return
        menu = QMenu(self)
        select_act = menu.addAction(f"Select Row {row + 1}")
        menu.addSeparator()
        delete_act = menu.addAction(f"Delete Row {row + 1}")
        delete_sel_act = menu.addAction("Delete Selected Row(s)")
        action = menu.exec(self._table.verticalHeader().mapToGlobal(pos))
        if action == select_act:
            self._table.selectRow(row)
        elif action == delete_act:
            self.row_delete_requested.emit(self._source_id, [row])
        elif action == delete_sel_act:
            self._delete_selected_rows()

    # ------------------------------------------------------------------ #
    # Table body context menu                                              #
    # ------------------------------------------------------------------ #

    def _table_context_menu(self, pos) -> None:
        menu = QMenu(self)
        delete_rows_act = menu.addAction("Delete Selected Row(s)")
        delete_cols_act = menu.addAction("Delete Selected Column(s)")
        delete_rows_act.triggered.connect(self._delete_selected_rows)
        delete_cols_act.triggered.connect(self._delete_selected_columns)
        if self._is_valid:
            menu.addSeparator()
            scale_act = menu.addAction("Multiply Strain Values…")
            scale_act.setToolTip("Multiply all strain values by a scalar")
            add_act = menu.addAction("Add to Strain Values…")
            add_act.setToolTip("Add a scalar to all strain values")
            scale_act.triggered.connect(self._request_scale_strain)
            add_act.triggered.connect(self._request_add_strain)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _delete_selected_rows(self) -> None:
        rows = sorted({idx.row() for idx in self._table.selectedIndexes()})
        if rows:
            self.row_delete_requested.emit(self._source_id, rows)

    def _delete_selected_columns(self) -> None:
        cols = sorted({idx.column() for idx in self._table.selectedIndexes()})
        if cols:
            self.column_delete_requested.emit(self._source_id, cols)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def _request_scale_strain(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        value, ok = QInputDialog.getDouble(
            self, "Multiply Strain Values",
            "Multiply all strain values by:", 1.0, -1e12, 1e12, 6,
        )
        if ok:
            self.scale_strain_requested.emit(self._source_id, value)

    def _request_add_strain(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        value, ok = QInputDialog.getDouble(
            self, "Add to Strain Values",
            "Add to all strain values:", 0.0, -1e12, 1e12, 6,
        )
        if ok:
            self.add_strain_requested.emit(self._source_id, value)

    def _request_offset_loadsteps(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        value, ok = QInputDialog.getDouble(
            self, "Offset Load Steps",
            "Add to all load-step values:", 0.0, -1e12, 1e12, 6,
        )
        if ok:
            self.offset_loadsteps_requested.emit(self._source_id, value)

    def set_valid(self, valid: bool) -> None:
        self._is_valid = valid
        color = "#4CAF50" if valid else "#F44336"
        self.setStyleSheet(
            f"ImportTableWidget {{ border: 2px solid {color}; border-radius: 4px; }}"
        )

    def update_dataframe(self, df: pd.DataFrame) -> None:
        self._model.update_dataframe(df)


# ------------------------------------------------------------------ #
# Import view                                                          #
# ------------------------------------------------------------------ #

class ImportView(QWidget):
    """
    View 1: Data import and cleanup.

    Left panel  – list of imported files (click to view, right-click to remove).
    Right panel – the selected file's data table (one at a time).
    """

    import_csv_requested = Signal()
    import_mapping_requested = Signal()
    remove_mapping_requested = Signal()
    view_mapping_requested = Signal()
    proceed_requested = Signal()
    remove_source_requested = Signal(str)   # source_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._frames: dict[str, ImportTableWidget] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        # ---- Toolbar ----
        toolbar = QHBoxLayout()
        self._btn_import = QPushButton("Import CSV")
        self._btn_mapping = QPushButton("Import Mapping")
        self._btn_view_mapping = QPushButton("View Mapping")
        self._btn_remove_mapping = QPushButton("Remove Mapping")
        self._btn_proceed = QPushButton("Proceed to Analysis →")
        for btn in (self._btn_import, self._btn_mapping, self._btn_view_mapping,
                    self._btn_remove_mapping, self._btn_proceed):
            btn.setCheckable(False)
            toolbar.addWidget(btn)
        toolbar.addStretch()
        self._btn_import.clicked.connect(self.import_csv_requested)
        self._btn_mapping.clicked.connect(self.import_mapping_requested)
        self._btn_view_mapping.clicked.connect(self.view_mapping_requested)
        self._btn_remove_mapping.clicked.connect(self.remove_mapping_requested)
        self._btn_proceed.clicked.connect(self._on_proceed)
        self._btn_proceed.setEnabled(False)
        self._btn_view_mapping.setEnabled(False)
        self._btn_remove_mapping.setEnabled(False)
        outer.addLayout(toolbar)

        # ---- Info label ----
        info = QLabel(
            "Import CSV files where <b>Row 1 = load steps</b>, "
            "<b>Column 1 = sensor names</b>, remaining cells = strain values. "
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
    ) -> ImportTableWidget:
        name = display_name or source_id

        # Add to file list
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, source_id)
        self._file_list.addItem(item)

        # Create import table widget
        widget = ImportTableWidget(df, source_id=source_id, title=name, is_valid=is_valid)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._stack.addWidget(widget)

        self._frames[source_id] = widget
        self._btn_proceed.setEnabled(True)

        # Auto-select the newly imported file
        self._file_list.setCurrentItem(item)
        return widget

    def remove_source_table(self, source_id: str) -> None:
        """Remove the file list entry and its table."""
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == source_id:
                self._file_list.takeItem(i)
                break

        widget = self._frames.pop(source_id, None)
        if widget:
            self._stack.removeWidget(widget)
            widget.deleteLater()

        if not self._frames:
            self._stack.setCurrentWidget(self._placeholder)
            self._btn_proceed.setEnabled(False)

    def update_source_table(self, source_id: str, df: pd.DataFrame) -> None:
        widget = self._frames.get(source_id)
        if widget:
            widget.update_dataframe(df)

    def set_source_valid(self, source_id: str, is_valid: bool) -> None:
        widget = self._frames.get(source_id)
        if widget:
            widget.set_valid(is_valid)

    def set_mapping_info(self, info: str, loaded: bool = False) -> None:
        self._mapping_lbl.setText(info)
        self._btn_view_mapping.setEnabled(loaded)
        self._btn_remove_mapping.setEnabled(loaded)

    def reset(self) -> None:
        """Clear all imported sources and reset mapping state."""
        for source_id in list(self._frames.keys()):
            self.remove_source_table(source_id)
        self.set_mapping_info("No mapping loaded.", loaded=False)
        self._btn_proceed.setEnabled(False)

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

    def _on_proceed(self) -> None:
        if not self._frames:
            QMessageBox.warning(self, "No Data", "Import at least one CSV file first.")
            return
        self.proceed_requested.emit()
