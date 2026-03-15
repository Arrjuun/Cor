"""Ratio graph widget with box selection, using pyqtgraph."""
from __future__ import annotations

import json
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QByteArray, QMimeData, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QRubberBand,
    QVBoxLayout,
    QWidget,
)

from .customization_dialog import CustomizationDialog, SeriesStyle, LINE_STYLE_MAP

_MIME_COL = "application/x-loadstep-column"


class RatioGraphWidget(QWidget):
    """
    Ratio graph: X=Strain A, Y=Strain B, one point per sensor.
    Accepts drag-and-drop of load-step columns.
    Supports toolbar-toggled box selection of points.
    """

    loadstep_dropped = Signal(dict)               # MIME payload
    points_selected_for_plot = Signal(list, str)  # [sensor_names], target_graph_id
    points_deleted = Signal(list)                 # [sensor_names]
    remove_requested = Signal()

    def __init__(self, title: str = "Ratio Graph",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._title = title
        self._scatter: Optional[pg.ScatterPlotItem] = None
        self._sensors: list[str] = []
        self._values_a: list[float] = []
        self._values_b: list[float] = []
        self._ratios: list[float] = []
        self._label_a: str = "Source A"
        self._label_b: str = "Source B"
        self._load_step: float = 0.0
        self._selected_indices: set[int] = set()
        self._ref_lines: list = []
        self._box_selecting = False
        self._rb_origin: Optional[QPoint] = None
        self._build_ui(title)

    # ------------------------------------------------------------------ #
    # Build UI                                                             #
    # ------------------------------------------------------------------ #

    def _build_ui(self, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Toolbar
        toolbar = QHBoxLayout()
        self._select_btn = QPushButton("☐ Box Select")
        self._select_btn.setCheckable(True)
        self._select_btn.setToolTip(
            "Toggle box selection mode.\n"
            "When active, left-click and drag to select points."
        )
        self._select_btn.toggled.connect(self._on_select_mode_toggled)
        toolbar.addWidget(self._select_btn)

        self._slope_btn = QPushButton("+ Reference Band")
        self._slope_btn.setCheckable(False)
        self._slope_btn.setToolTip("Add a ±N% corridor around the 1:1 reference line")
        self._slope_btn.clicked.connect(self._ask_reference_band)
        toolbar.addWidget(self._slope_btn)

        self._clear_ref_btn = QPushButton("Clear Refs")
        self._clear_ref_btn.setCheckable(False)
        self._clear_ref_btn.clicked.connect(self.clear_reference_lines)
        toolbar.addWidget(self._clear_ref_btn)

        toolbar.addStretch()

        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setToolTip("Remove this graph")
        close_btn.setCheckable(False)
        close_btn.setStyleSheet(
            "QPushButton { border: none; color: #9E9E9E; font-size: 16px; padding: 0; }"
            "QPushButton:hover { color: #F44336; }"
        )
        close_btn.clicked.connect(self.remove_requested.emit)
        toolbar.addWidget(close_btn)
        layout.addLayout(toolbar)

        # Plot widget
        self._plot = pg.PlotWidget(title=title)
        self._plot.setBackground("w")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("bottom", "Strain A")
        self._plot.setLabel("left", "Strain B")

        # Install event filter on PlotWidget and its viewport for drops + box select
        self._plot.setAcceptDrops(True)
        self._plot.installEventFilter(self)
        self._plot.viewport().installEventFilter(self)

        # Rubber band drawn on the viewport
        self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self._plot.viewport())

        # Hover tooltip: in-plot TextItem (avoids QToolTip fighting pyqtgraph)
        self._hover_label = pg.TextItem(
            text="", anchor=(0, 1),
            fill=pg.mkBrush(255, 255, 255, 220),
            border=pg.mkPen(color="#BDBDBD", width=1, cosmetic=True),
        )
        self._hover_label.setZValue(200)
        self._hover_label.setVisible(False)

        # SignalProxy throttles mouse-move events to 30 fps
        self._mouse_proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved,
            rateLimit=30,
            slot=self._on_mouse_moved,
        )

        layout.addWidget(self._plot)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def plot_ratio(
        self,
        sensors: list[str],
        values_a: list[float],
        values_b: list[float],
        ratios: list[float],
        load_step: float = 0.0,
        label_a: str = "Source A",
        label_b: str = "Source B",
    ) -> None:
        """
        Plot Strain A (X) vs Strain B (Y), one point per sensor.
        Includes a 1:1 reference line.
        """
        self._sensors = list(sensors)
        self._values_a = list(values_a)
        self._values_b = list(values_b)
        self._ratios = list(ratios)
        self._selected_indices.clear()
        self._label_a = label_a
        self._label_b = label_b
        self._load_step = load_step

        # Filter valid (non-NaN) entries
        valid_idx = [
            i for i, (a, b) in enumerate(zip(values_a, values_b))
            if not (np.isnan(float(a)) or np.isnan(float(b)))
        ]

        if not valid_idx:
            return

        x_vals = np.array([values_a[i] for i in valid_idx], dtype=float)
        y_vals = np.array([values_b[i] for i in valid_idx], dtype=float)

        # Per-point data for hover tooltips
        spot_data = [
            {
                "sensor": sensors[i],
                "strain_a": values_a[i],
                "strain_b": values_b[i],
                "ratio": ratios[i] if not np.isnan(float(ratios[i])) else float("nan"),
                "orig_idx": i,
            }
            for i in valid_idx
        ]

        if self._scatter is not None:
            self._plot.removeItem(self._scatter)
            self._scatter = None
        # Remove old reference lines and hover label
        self.clear_reference_lines()
        if self._hover_label.scene() is not None:
            self._plot.removeItem(self._hover_label)

        brushes = [pg.mkBrush("#1565C0")] * len(valid_idx)
        pens = [pg.mkPen(color="#1565C0", width=1, cosmetic=True)] * len(valid_idx)

        self._scatter = pg.ScatterPlotItem(
            x=x_vals, y=y_vals,
            size=10,
            pen=pens,
            brush=brushes,
            data=spot_data,
            hoverable=False,  # we handle hover ourselves
        )
        self._plot.addItem(self._scatter)

        # Re-add hover label on top
        self._plot.addItem(self._hover_label)
        self._hover_label.setVisible(False)

        # Axes labels
        self._plot.setLabel("bottom", f"Strain — {label_a}")
        self._plot.setLabel("left", f"Strain — {label_b}")
        self._plot.setTitle(f"Strain Correlation @ Load Step {load_step}")

        # 1:1 reference line (Y = X)
        all_vals = np.concatenate([x_vals, y_vals])
        lo, hi = float(np.nanmin(all_vals)), float(np.nanmax(all_vals))
        margin = (hi - lo) * 0.05
        ref_x = np.array([lo - margin, hi + margin])
        ref_line = self._plot.plot(
            ref_x, ref_x,
            pen=pg.mkPen(color="#9E9E9E", width=1, style=Qt.PenStyle.DashLine, cosmetic=True),
            name="1:1 line",
        )
        self._ref_lines.append(ref_line)

        self._plot.enableAutoRange()

    def add_slope_band(self, pct: float) -> None:
        """Add ±pct% corridor lines around the 1:1 reference."""
        if not self._sensors:
            return
        # Compute data range from current scatter
        if self._scatter is None:
            return
        pts = self._scatter.getData()
        if pts[0] is None or len(pts[0]) == 0:
            return
        all_vals = np.concatenate([pts[0], pts[1]])
        lo, hi = float(np.nanmin(all_vals)), float(np.nanmax(all_vals))
        margin = (hi - lo) * 0.05
        ref_x = np.array([lo - margin, hi + margin])

        factor_pos = 1.0 + pct / 100.0
        factor_neg = 1.0 - pct / 100.0

        band_pen = pg.mkPen(color="#F57F17", width=1,
                            style=Qt.PenStyle.DashLine, cosmetic=True)
        line_pos = self._plot.plot(ref_x, ref_x * factor_pos, pen=band_pen,
                                   name=f"+{pct:.0f}%")
        line_neg = self._plot.plot(ref_x, ref_x * factor_neg, pen=band_pen,
                                   name=f"-{pct:.0f}%")
        self._ref_lines.extend([line_pos, line_neg])

    def clear_reference_lines(self) -> None:
        for line in self._ref_lines:
            self._plot.removeItem(line)
        self._ref_lines.clear()

    def get_selected_sensors(self) -> list[str]:
        return [self._sensors[i] for i in sorted(self._selected_indices)
                if i < len(self._sensors)]

    def is_select_mode(self) -> bool:
        return self._select_btn.isChecked()

    # ------------------------------------------------------------------ #
    # Reference band dialog                                                #
    # ------------------------------------------------------------------ #

    def _ask_reference_band(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Add Reference Band")
        dlg.setMinimumWidth(280)
        form = QFormLayout(dlg)

        spin = QDoubleSpinBox()
        spin.setRange(0.1, 100.0)
        spin.setDecimals(1)
        spin.setSuffix(" %")
        spin.setValue(10.0)
        form.addRow("Corridor (±%):", spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.add_slope_band(spin.value())

    # ------------------------------------------------------------------ #
    # Box select mode toggle                                               #
    # ------------------------------------------------------------------ #

    def _on_select_mode_toggled(self, checked: bool) -> None:
        vb = self._plot.getPlotItem().getViewBox()
        if checked:
            # Disable pyqtgraph pan/zoom so our rubber band can use left-drag
            vb.setMouseEnabled(x=False, y=False)
            self._select_btn.setText("✓ Box Select (ON)")
            self._select_btn.setStyleSheet("background-color: #1565C0; color: white;")
        else:
            vb.setMouseEnabled(x=True, y=True)
            self._selected_indices.clear()
            if self._scatter:
                self._update_scatter_colors()
            self._select_btn.setText("☐ Box Select")
            self._select_btn.setStyleSheet("")

    # ------------------------------------------------------------------ #
    # Hover                                                                #
    # ------------------------------------------------------------------ #

    def _on_mouse_moved(self, event) -> None:
        pos = event[0]
        if self._scatter is None or not self._plot.sceneBoundingRect().contains(pos):
            self._hover_label.setVisible(False)
            return

        vb = self._plot.getPlotItem().getViewBox()
        mp = vb.mapSceneToView(pos)
        mx, my = mp.x(), mp.y()

        # Find nearest point
        pts = self._scatter.getData()
        if pts[0] is None or len(pts[0]) == 0:
            self._hover_label.setVisible(False)
            return

        xs, ys = pts[0], pts[1]
        # Normalize by view range for better distance calc
        vr = vb.viewRange()
        x_range = vr[0][1] - vr[0][0] or 1.0
        y_range = vr[1][1] - vr[1][0] or 1.0
        dists = ((xs - mx) / x_range) ** 2 + ((ys - my) / y_range) ** 2
        nearest = int(np.argmin(dists))

        # Only show tooltip if close enough (within 2% of view range)
        if np.sqrt(dists[nearest]) > 0.05:
            self._hover_label.setVisible(False)
            return

        # Get spot data — scatter stores per-point data in the spots list
        spots = self._scatter.points()
        if nearest >= len(spots):
            self._hover_label.setVisible(False)
            return

        d = spots[nearest].data()
        if not isinstance(d, dict):
            self._hover_label.setVisible(False)
            return

        ratio_str = f"{d['ratio']:.4f}" if not np.isnan(float(d['ratio'])) else "N/A"
        html = (
            f"<b>{d['sensor']}</b><br>"
            f"Strain A: {d['strain_a']:.6g}<br>"
            f"Strain B: {d['strain_b']:.6g}<br>"
            f"Ratio (A/B): {ratio_str}"
        )
        self._hover_label.setHtml(html)
        self._hover_label.setPos(mx, my)
        self._hover_label.setVisible(True)

    # ------------------------------------------------------------------ #
    # Event filter: drop + box select                                      #
    # ------------------------------------------------------------------ #

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent

        et = event.type()

        # --- Drag-and-drop (on PlotWidget or its viewport) ---
        if et == QEvent.Type.DragEnter:
            if event.mimeData().hasFormat(_MIME_COL):
                event.acceptProposedAction()
                return True
        elif et == QEvent.Type.DragMove:
            if event.mimeData().hasFormat(_MIME_COL):
                event.acceptProposedAction()
                return True
        elif et == QEvent.Type.Drop:
            if event.mimeData().hasFormat(_MIME_COL):
                raw = bytes(event.mimeData().data(_MIME_COL)).decode()
                try:
                    payload = json.loads(raw)
                    self.loadstep_dropped.emit(payload)
                except json.JSONDecodeError:
                    pass
                event.acceptProposedAction()
                return True

        # --- Box selection (only on viewport, only when select mode active) ---
        if obj is self._plot.viewport() and self._select_btn.isChecked():
            if et == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._rb_origin = event.pos()
                    self._rubber_band.setGeometry(QRect(self._rb_origin, self._rb_origin))
                    self._rubber_band.show()
                    self._box_selecting = True
                    return True

            elif et == QEvent.Type.MouseMove and self._box_selecting:
                self._rubber_band.setGeometry(
                    QRect(self._rb_origin, event.pos()).normalized()
                )
                return True

            elif et == QEvent.Type.MouseButtonRelease and self._box_selecting:
                self._rubber_band.hide()
                self._box_selecting = False
                rect = QRect(self._rb_origin, event.pos()).normalized()
                self._select_points_in_rect(rect)
                if self._selected_indices:
                    self._show_selection_menu(
                        self._plot.viewport().mapToGlobal(event.pos())
                    )
                return True

        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ #
    # Point selection helpers                                              #
    # ------------------------------------------------------------------ #

    def _select_points_in_rect(self, rect: QRect) -> None:
        if self._scatter is None or not self._sensors:
            return

        vb = self._plot.getPlotItem().getViewBox()
        tl_scene = self._plot.mapToScene(rect.topLeft())
        br_scene = self._plot.mapToScene(rect.bottomRight())
        tl_plot = vb.mapSceneToView(tl_scene)
        br_plot = vb.mapSceneToView(br_scene)

        x_min = min(tl_plot.x(), br_plot.x())
        x_max = max(tl_plot.x(), br_plot.x())
        y_min = min(tl_plot.y(), br_plot.y())
        y_max = max(tl_plot.y(), br_plot.y())

        self._selected_indices.clear()
        for i, (va, vb_val) in enumerate(zip(self._values_a, self._values_b)):
            try:
                fa, fb = float(va), float(vb_val)
            except (TypeError, ValueError):
                continue
            if np.isnan(fa) or np.isnan(fb):
                continue
            if x_min <= fa <= x_max and y_min <= fb <= y_max:
                self._selected_indices.add(i)

        self._update_scatter_colors()

    def _update_scatter_colors(self) -> None:
        if self._scatter is None:
            return
        brushes = []
        for i, (va, vb_val) in enumerate(zip(self._values_a, self._values_b)):
            try:
                fa, fb = float(va), float(vb_val)
                if np.isnan(fa) or np.isnan(fb):
                    continue
            except (TypeError, ValueError):
                continue
            brushes.append(
                pg.mkBrush("#F44336") if i in self._selected_indices
                else pg.mkBrush("#1565C0")
            )
        if brushes:
            self._scatter.setBrush(brushes)

    def _show_selection_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        count = len(self._selected_indices)
        plot_act = menu.addAction(f"Plot {count} Selected Sensor(s) to LoadStep Graph…")
        delete_act = menu.addAction(f"Remove {count} Selected Point(s)")
        menu.addSeparator()
        cancel = menu.addAction("Cancel Selection")

        action = menu.exec(global_pos)
        if action == plot_act:
            sensors = self.get_selected_sensors()
            self.points_selected_for_plot.emit(sensors, "pick")
        elif action == delete_act:
            sensors = self.get_selected_sensors()
            self.points_deleted.emit(sensors)
            self._remove_selected_points()
        elif action == cancel:
            self._selected_indices.clear()
            self._update_scatter_colors()

    def to_config(self) -> Optional[dict]:
        """Return serialisable config, or None if nothing has been plotted."""
        if not self._sensors:
            return None
        return {
            "title": self._title,
            "sensors": list(self._sensors),
            "values_a": list(self._values_a),
            "values_b": list(self._values_b),
            "ratios": list(self._ratios),
            "label_a": self._label_a,
            "label_b": self._label_b,
            "load_step": self._load_step,
        }

    def get_export_data(self) -> Optional[dict]:
        """Return current plot data for export, or None if nothing plotted."""
        if not self._sensors:
            return None
        return {
            "sensors": list(self._sensors),
            "values_a": list(self._values_a),
            "values_b": list(self._values_b),
            "ratios": list(self._ratios),
            "label_a": getattr(self, "_label_a", "Source A"),
            "label_b": getattr(self, "_label_b", "Source B"),
        }

    def _remove_selected_points(self) -> None:
        keep = [i for i in range(len(self._sensors)) if i not in self._selected_indices]
        sensors = [self._sensors[i] for i in keep]
        values_a = [self._values_a[i] for i in keep]
        values_b = [self._values_b[i] for i in keep]
        ratios = [self._ratios[i] for i in keep]
        self._selected_indices.clear()
        if sensors:
            self.plot_ratio(sensors, values_a, values_b, ratios)

    # ------------------------------------------------------------------ #
    # Outer widget drop fallback                                           #
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_COL):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_COL):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_COL):
            raw = bytes(event.mimeData().data(_MIME_COL)).decode()
            try:
                payload = json.loads(raw)
                self.loadstep_dropped.emit(payload)
            except json.JSONDecodeError:
                pass
            event.acceptProposedAction()
        else:
            event.ignore()
