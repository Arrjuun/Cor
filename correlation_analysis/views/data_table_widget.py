"""DataTableWidget – sensor table with optional formula column, mapped-names column,
text-based filtering, and drag-and-drop."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

import numpy as np
import pandas as pd
from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QPoint,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QTableView,
    QVBoxLayout,
    QWidget,
)

SENSOR_COL = 0
FORMULA_COL = 1       # only valid when show_formula=True
LOADSTEP_START = 2    # column index when show_formula=True

_MIME_ROW = "application/x-sensor-row"
_MIME_COL = "application/x-loadstep-column"


# ------------------------------------------------------------------ #
# Draggable header for column drag                                    #
# ------------------------------------------------------------------ #

class DraggableHeaderView(QHeaderView):
    """
    QHeaderView that initiates a drag on load-step columns and shows a
    right-click context menu for column deletion.
    """

    column_drag_started = Signal(int)
    column_clicked = Signal(int)
    column_delete_requested = Signal(int)

    _DRAG_THRESHOLD = 6

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setDragEnabled(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._header_context_menu)
        self._drag_col: Optional[int] = None
        self._press_pos: Optional[QPoint] = None

    def _is_loadstep(self, col: int) -> bool:
        model = self.parent().model() if self.parent() else None
        if model is None:
            return col >= LOADSTEP_START
        is_ls = getattr(model, "is_loadstep_col", None)
        if callable(is_ls):
            return is_ls(col)
        return col >= LOADSTEP_START

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_col = self.logicalIndexAt(event.pos())
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_col is not None
            and self._press_pos is not None
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and (event.pos() - self._press_pos).manhattanLength() > self._DRAG_THRESHOLD
            and self._is_loadstep(self._drag_col)
        ):
            model = self.parent().model() if self.parent() else None
            if model is None:
                return
            header_text = str(model.headerData(
                self._drag_col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
            ))
            source_id = getattr(model, "_source_id", "")
            mime = QMimeData()
            payload = json.dumps({"load_step": header_text, "source_id": source_id})
            mime.setData(_MIME_COL, QByteArray(payload.encode()))
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
            self._drag_col = None
            self._press_pos = None
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._drag_col is not None
            and self._is_loadstep(self._drag_col)
            and self._press_pos is not None
            and (event.pos() - self._press_pos).manhattanLength() <= self._DRAG_THRESHOLD
        ):
            self.column_clicked.emit(self._drag_col)
        self._drag_col = None
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def _header_context_menu(self, pos) -> None:
        col = self.logicalIndexAt(pos)
        if not self._is_loadstep(col):
            return
        col_name = self.model().headerData(col, Qt.Orientation.Horizontal)
        menu = QMenu(self)
        delete_act = menu.addAction(f"Delete Column '{col_name}'")
        sel_act = menu.addAction(f"Select Column '{col_name}'")
        action = menu.exec(self.mapToGlobal(pos))
        if action == delete_act:
            self.column_delete_requested.emit(col)
        elif action == sel_act:
            self.column_clicked.emit(col)


# ------------------------------------------------------------------ #
# Table model                                                         #
# ------------------------------------------------------------------ #

class SensorTableModel(QAbstractTableModel):
    """
    QAbstractTableModel wrapping a pandas DataFrame.

    Column layout when show_formula=True:
        [Sensor Name, Formula, LoadStep1, ..., LoadStepN, (Mapped Names)]
    Column layout when show_formula=False:
        [Sensor Name, LoadStep1, ..., LoadStepN, (Mapped Names)]

    "Mapped Names" column appears when set_mapped_names() has been called.
    Text-based filtering via set_filter(text).
    """

    formula_changed = Signal(str, str)  # sensor_name, formula

    def __init__(
        self,
        df: pd.DataFrame,
        formulas: dict[str, str] | None = None,
        derived_rows: set[str] | None = None,
        source_id: str = "",
        show_formula: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._df = df.copy()
        self._formulas: dict[str, str] = formulas or {}
        self._derived: set[str] = derived_rows or set()
        self._source_id = source_id
        self._show_formula = show_formula
        self._mapped_names: dict[str, str] = {}   # sensor_name → "canonical | alias | ..."
        self._filter_text: str = ""
        self._filter_regex: bool = False
        self._row_indices: list[int] = list(range(len(self._df)))

    # ------------------------------------------------------------------ #
    # Column layout helpers                                               #
    # ------------------------------------------------------------------ #

    @property
    def _ls_start(self) -> int:
        """Column index where load steps begin."""
        return 2 if self._show_formula else 1

    def is_loadstep_col(self, col_idx: int) -> bool:
        return self._ls_start <= col_idx < self._ls_start + len(self._df.columns)

    @property
    def _mapped_col(self) -> int:
        """Column index of the Mapped Names column, or -1 if not shown."""
        return self._ls_start + len(self._df.columns) if self._mapped_names else -1

    # ------------------------------------------------------------------ #
    # Filtering                                                           #
    # ------------------------------------------------------------------ #

    def set_filter(self, text: str, regex: bool = False) -> None:
        """Filter rows by text (checks sensor name and mapped names)."""
        self.beginResetModel()
        self._filter_text = text.strip() if regex else text.strip().lower()
        self._filter_regex = regex
        self._rebuild_row_indices()
        self.endResetModel()

    def set_mapped_names(self, mapped: dict[str, str]) -> None:
        """Set mapped-names dict and refresh the extra column."""
        self.beginResetModel()
        self._mapped_names = dict(mapped)
        self._rebuild_row_indices()
        self.endResetModel()

    def _rebuild_row_indices(self) -> None:
        if not self._filter_text:
            self._row_indices = list(range(len(self._df)))
            return
        t = self._filter_text
        if self._filter_regex:
            try:
                pattern = re.compile(t, re.IGNORECASE)
            except re.error:
                # Invalid regex – show all rows rather than crash
                self._row_indices = list(range(len(self._df)))
                return
            indices = []
            for i, name in enumerate(self._df.index):
                if pattern.search(str(name)):
                    indices.append(i)
                    continue
                mapped = self._mapped_names.get(str(name), "")
                if pattern.search(mapped):
                    indices.append(i)
        else:
            indices = []
            for i, name in enumerate(self._df.index):
                sname = str(name).lower()
                if t in sname:
                    indices.append(i)
                    continue
                mapped = self._mapped_names.get(str(name), "").lower()
                if t in mapped:
                    indices.append(i)
        self._row_indices = indices

    # ------------------------------------------------------------------ #
    # Required overrides                                                   #
    # ------------------------------------------------------------------ #

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return len(self._row_indices)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        extra = 1 if self._mapped_names else 0
        return self._ls_start + len(self._df.columns) + extra

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        df_row = self._row_indices[index.row()]
        col = index.column()
        sensor = self._df.index[df_row]
        sname = str(sensor)

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == SENSOR_COL:
                return sname
            if self._show_formula and col == FORMULA_COL:
                return self._formulas.get(sname, "")
            if self.is_loadstep_col(col):
                val = self._df.iloc[df_row, col - self._ls_start]
                return "" if pd.isna(val) else f"{val:.6g}"
            if col == self._mapped_col:
                return self._mapped_names.get(sname, "")
            return None

        if role == Qt.ItemDataRole.BackgroundRole:
            if sensor in self._derived:
                return QBrush(QColor("#E3F2FD"))
            if self._show_formula and col == FORMULA_COL and sensor not in self._derived:
                return QBrush(QColor("#F5F5F5"))
            if col == self._mapped_col:
                return QBrush(QColor("#FFF8E1"))  # light amber for mapped names

        if role == Qt.ItemDataRole.ToolTipRole:
            if self._show_formula and col == FORMULA_COL and sensor in self._derived:
                return self._formulas.get(sname, "")
            if col == self._mapped_col:
                return self._mapped_names.get(sname, "")
        return None

    def headerData(self, section: int, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if section == SENSOR_COL:
                return "Sensor"
            if self._show_formula and section == FORMULA_COL:
                return "Formula"
            if self.is_loadstep_col(section):
                ls_idx = section - self._ls_start
                return str(self._df.columns[ls_idx])
            if section == self._mapped_col:
                return "Mapped Names"
        else:
            return str(section + 1)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not index.isValid():
            return base
        df_row = self._row_indices[index.row()]
        sensor = self._df.index[df_row]
        col = index.column()
        # Mapped names column: read-only, not draggable
        if col == self._mapped_col:
            return base
        # Formula column: editable only for derived rows
        if self._show_formula and col == FORMULA_COL and sensor in self._derived:
            return base | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled
        return base | Qt.ItemFlag.ItemIsDragEnabled

    def setData(self, index: QModelIndex, value: Any, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        df_row = self._row_indices[index.row()]
        sensor = str(self._df.index[df_row])
        col = index.column()
        if self._show_formula and col == FORMULA_COL and sensor in self._derived:
            self._formulas[sensor] = str(value)
            self.dataChanged.emit(index, index, [role])
            self.formula_changed.emit(sensor, str(value))
            return True
        return False

    # ------------------------------------------------------------------ #
    # Public helpers                                                       #
    # ------------------------------------------------------------------ #

    def update_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df.copy()
        self._rebuild_row_indices()
        self.endResetModel()

    def add_derived_row(self, sensor_name: str, formula: str = "",
                        position: int = None) -> None:
        self.beginResetModel()
        if sensor_name not in self._df.index:
            empty = pd.Series(np.nan, index=self._df.columns, dtype=float)
            new_row = empty.rename(sensor_name).to_frame().T
            if position is not None and 0 <= position <= len(self._df):
                self._df = pd.concat(
                    [self._df.iloc[:position], new_row, self._df.iloc[position:]]
                )
            else:
                self._df = pd.concat([self._df, new_row])
        self._derived.add(sensor_name)
        self._formulas[sensor_name] = formula
        # Clear filter so new derived row is always visible
        self._filter_text = ""
        self._rebuild_row_indices()
        self.endResetModel()

    def update_derived_row(self, sensor_name: str, values: pd.Series) -> None:
        if sensor_name in self._df.index:
            self._df.loc[sensor_name] = values
            df_row = list(self._df.index).index(sensor_name)
            if df_row in self._row_indices:
                visible_row = self._row_indices.index(df_row)
                top_left = self.index(visible_row, self._ls_start)
                bot_right = self.index(visible_row, self.columnCount() - 1)
                self.dataChanged.emit(top_left, bot_right)

    def sensor_name(self, row: int) -> str:
        return str(self._df.index[self._row_indices[row]])

    def is_derived(self, row: int) -> bool:
        return self._df.index[self._row_indices[row]] in self._derived

    def get_source_id(self) -> str:
        return self._source_id

    def get_df(self) -> pd.DataFrame:
        return self._df.copy()

    # ------------------------------------------------------------------ #
    # Drag MIME data                                                       #
    # ------------------------------------------------------------------ #

    def mimeTypes(self) -> list[str]:
        return [_MIME_ROW, "text/plain"]

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction

    def mimeData(self, indexes) -> QMimeData:
        rows = list(dict.fromkeys(idx.row() for idx in indexes if idx.isValid()))
        if not rows:
            return QMimeData()
        payloads = []
        for row in rows:
            sensor = self.sensor_name(row)
            payloads.append({
                "sensor_name": sensor,
                "source_id": self._source_id,
                "is_derived": self.is_derived(row),
                "formula": self._formulas.get(sensor, ""),
            })
        mime = QMimeData()
        mime.setData(_MIME_ROW, QByteArray(json.dumps(payloads).encode()))
        mime.setText(", ".join(p["sensor_name"] for p in payloads))
        return mime


# ------------------------------------------------------------------ #
# Widget                                                              #
# ------------------------------------------------------------------ #

class DataTableWidget(QWidget):
    """
    Sensor data table with optional formula support, context menu,
    and drag-and-drop (rows → LoadStep graph, columns → Ratio graph).

    Parameters
    ----------
    show_formula : bool
        When False the Formula column is hidden (use in Import view).
    """

    row_delete_requested = Signal(str, list)
    column_delete_requested = Signal(str, list)
    formula_changed = Signal(str, str, str)   # source_id, sensor_name, formula
    row_added = Signal(str, int)              # source_id, df_insert_position

    def __init__(
        self,
        df: pd.DataFrame,
        source_id: str = "",
        formulas: dict[str, str] | None = None,
        derived_rows: set[str] | None = None,
        title: str = "",
        show_formula: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._source_id = source_id
        self._show_formula = show_formula
        self._build_ui(df, formulas, derived_rows, title)

    def _build_ui(self, df, formulas, derived_rows, title) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if title:
            lbl = QLabel(f"<b>{title}</b>")
            layout.addWidget(lbl)

        self._model = SensorTableModel(
            df, formulas, derived_rows, self._source_id,
            show_formula=self._show_formula,
        )
        self._model.formula_changed.connect(
            lambda sensor, formula: self.formula_changed.emit(
                self._source_id, sensor, formula
            )
        )

        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setDragEnabled(True)
        self._table.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.verticalHeader().setVisible(False)

        drag_header = DraggableHeaderView(Qt.Orientation.Horizontal, self._table)
        drag_header.column_delete_requested.connect(self._delete_column_by_index)
        drag_header.column_clicked.connect(self._select_column)
        self._table.setHorizontalHeader(drag_header)

        layout.addWidget(self._table)

    # ------------------------------------------------------------------ #
    # Context menu                                                         #
    # ------------------------------------------------------------------ #

    def _context_menu(self, pos) -> None:
        index = self._table.indexAt(pos)
        menu = QMenu(self)

        if self._show_formula:
            add_above = menu.addAction("Add Derived Row Above")
            add_below = menu.addAction("Add Derived Row Below")
            add_above.triggered.connect(
                lambda: self._add_derived_row(index.row(), above=True))
            add_below.triggered.connect(
                lambda: self._add_derived_row(index.row(), above=False))
            menu.addSeparator()

        delete_rows = menu.addAction("Delete Selected Row(s)")
        delete_cols = menu.addAction("Delete Selected Column(s)")
        delete_rows.triggered.connect(self._delete_selected_rows)
        delete_cols.triggered.connect(self._delete_selected_columns)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _add_derived_row(self, ref_row: int, above: bool) -> None:
        model = self._model
        n = model.rowCount()
        if n == 0 or ref_row < 0 or ref_row >= n:
            df_insert_pos = len(model._df)
        else:
            df_row = model._row_indices[ref_row]
            df_insert_pos = df_row if above else df_row + 1
        self.row_added.emit(self._source_id, df_insert_pos)

    def _select_column(self, col: int) -> None:
        # Track which column was explicitly selected via header click
        self._header_selected_cols = {col}
        model = self._model
        top = model.index(0, col)
        bottom = model.index(model.rowCount() - 1, col)
        self._table.selectionModel().select(
            QItemSelection(top, bottom),
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )

    def _delete_selected_rows(self) -> None:
        rows = {idx.row() for idx in self._table.selectedIndexes()}
        sensors = [self._model.sensor_name(r) for r in sorted(rows)]
        if sensors:
            self.row_delete_requested.emit(self._source_id, sensors)

    def _delete_selected_columns(self) -> None:
        # Only act on columns selected via header (stored in _header_selected_cols),
        # not on all columns implicitly selected because a row is selected.
        cols = getattr(self, "_header_selected_cols", set())
        self._emit_column_delete(cols)
        self._header_selected_cols = set()

    def _delete_column_by_index(self, col_idx: int) -> None:
        self._header_selected_cols = set()
        self._emit_column_delete({col_idx})

    def _emit_column_delete(self, col_indices: set) -> None:
        load_steps = []
        for col in sorted(col_indices):
            header = self._model.headerData(col, Qt.Orientation.Horizontal)
            try:
                load_steps.append(float(header))
            except (TypeError, ValueError):
                pass
        if load_steps:
            self.column_delete_requested.emit(self._source_id, load_steps)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def update_dataframe(self, df: pd.DataFrame) -> None:
        self._model.update_dataframe(df)

    def add_derived_row(self, sensor_name: str, formula: str = "",
                        position: int = None) -> None:
        self._model.add_derived_row(sensor_name, formula, position)

    def update_derived_row(self, sensor_name: str, values: pd.Series) -> None:
        self._model.update_derived_row(sensor_name, values)

    def set_mapped_names(self, mapped: dict[str, str]) -> None:
        """Set per-sensor mapped names (canonical / aliases) for the extra column."""
        self._model.set_mapped_names(mapped)

    def set_sensor_filter(self, text: str, regex: bool = False) -> None:
        """Filter rows by text across sensor name and mapped-names column."""
        self._model.set_filter(text, regex)

    def get_visible_sensor_names(self) -> list[str]:
        """Return sensor names currently visible (after text filter)."""
        return [self._model.sensor_name(r) for r in range(self._model.rowCount())]

    def get_model(self) -> SensorTableModel:
        return self._model

    def source_id(self) -> str:
        return self._source_id

    # ------------------------------------------------------------------ #
    # Drag initiation from row selection                                   #
    # ------------------------------------------------------------------ #

    def start_row_drag(self, row: int) -> None:
        sensor = self._model.sensor_name(row)
        mime = QMimeData()
        payload = json.dumps([{
            "sensor_name": sensor,
            "source_id": self._source_id,
            "is_derived": self._model.is_derived(row),
            "formula": self._model._formulas.get(sensor, ""),
        }])
        mime.setData(_MIME_ROW, QByteArray(payload.encode()))
        drag = QDrag(self._table)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
