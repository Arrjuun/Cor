"""LoadStep vs Strain graph widget using pyqtgraph."""
from __future__ import annotations

import json
from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .customization_dialog import CustomizationDialog, SeriesStyle, LINE_STYLE_MAP, MARKERS

_MIME_ROW = "application/x-sensor-row"

_COLORS = [
    "#1565C0", "#C62828", "#2E7D32", "#F57F17",
    "#6A1B9A", "#00838F", "#4E342E", "#37474F",
    "#AD1457", "#00695C",
]


def _make_pen(style: SeriesStyle):
    """Create a cosmetic pyqtgraph pen from a SeriesStyle."""
    qt_style = LINE_STYLE_MAP.get(style.line_style, Qt.PenStyle.SolidLine)
    return pg.mkPen(color=style.color, width=style.thickness,
                    style=qt_style, cosmetic=True)


def _make_symbol_pen(color: str):
    return pg.mkPen(color=color, width=1, cosmetic=True)


def _make_symbol_brush(color: str):
    return pg.mkBrush(color)


def _make_symbol(marker: str) -> Optional[str]:
    return {
        "None": None, "Circle": "o", "Square": "s",
        "Triangle": "t", "Diamond": "d", "Cross": "+",
    }.get(marker)


class LoadStepGraphWidget(QWidget):
    """
    pyqtgraph-based LoadStep vs Strain graph.
    - Drag-and-drop rows from DataTableWidget to add series.
    - Right-click context menu for series customization.
    - Crosshair + tooltip on mouse hover.
    """

    series_dropped = Signal(dict)
    series_removed = Signal(str, str)
    remove_requested = Signal()

    def __init__(self, title: str = "LoadStep vs Strain",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._title = title
        self._series: dict[str, dict] = {}
        self._bands: dict[str, dict] = {}   # band_id → {key, pct, upper_item, lower_item, fill_item}
        self._color_idx = 0
        self._build_ui(title)

    def get_title(self) -> str:
        return self._title

    # ------------------------------------------------------------------ #
    # Build UI                                                             #
    # ------------------------------------------------------------------ #

    def _build_ui(self, title: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Close button header
        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 0)
        header.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setToolTip("Remove this graph")
        close_btn.setCheckable(False)
        close_btn.setStyleSheet(
            "QPushButton { border: none; color: #9E9E9E; font-size: 16px; padding: 0; }"
            "QPushButton:hover { color: #F44336; }"
        )
        close_btn.clicked.connect(self.remove_requested.emit)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self._plot = pg.PlotWidget(title=title)
        self._plot.setBackground("w")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("bottom", "Load Step")
        self._plot.setLabel("left", "Strain")
        self._plot.addLegend(offset=(10, 10))
        self._plot.getPlotItem().getViewBox().setMenuEnabled(False)

        # Event filter: context menu on plot, intercept drag-and-drop events
        self._plot.installEventFilter(self)
        self._plot.viewport().installEventFilter(self)

        # Crosshair
        crosshair_pen = pg.mkPen(color="#BDBDBD", width=1,
                                 style=Qt.PenStyle.DashLine, cosmetic=True)
        self._vline = pg.InfiniteLine(angle=90, movable=False, pen=crosshair_pen)
        self._plot.addItem(self._vline, ignoreBounds=True)
        self._vline.setVisible(False)

        # Hover tooltip label (TextItem stays in the plot)
        self._hover_label = pg.TextItem(
            text="", anchor=(0, 1),
            fill=pg.mkBrush(255, 255, 255, 220),
            border=pg.mkPen(color="#BDBDBD", width=1, cosmetic=True),
        )
        self._hover_label.setZValue(200)
        self._plot.addItem(self._hover_label, ignoreBounds=True)
        self._hover_label.setVisible(False)

        # SignalProxy throttles mouse-move events to 30 fps
        self._mouse_proxy = pg.SignalProxy(
            self._plot.scene().sigMouseMoved,
            rateLimit=30,
            slot=self._on_mouse_moved,
        )

        layout.addWidget(self._plot)

    # ------------------------------------------------------------------ #
    # Hover                                                                #
    # ------------------------------------------------------------------ #

    _SNAP_PX = 20   # pixel radius within which the tooltip snaps to a data point

    def _on_mouse_moved(self, event) -> None:
        pos = event[0]
        if not self._series or not self._plot.sceneBoundingRect().contains(pos):
            self._vline.setVisible(False)
            self._hover_label.setVisible(False)
            return

        vb = self._plot.getPlotItem().getViewBox()
        mp = vb.mapSceneToView(pos)
        x = mp.x()

        # Find the single closest data point across all series (pixel distance)
        best_info = None
        best_px_dist = np.inf
        best_xi = None
        for info in self._series.values():
            xdata, ydata = info["x"], info["y"]
            if len(xdata) == 0:
                continue
            idx = int(np.argmin(np.abs(xdata - x)))
            scene_pt = vb.mapViewToScene(QPointF(xdata[idx], ydata[idx]))
            dx = pos.x() - scene_pt.x()
            dy = pos.y() - scene_pt.y()
            dist = (dx * dx + dy * dy) ** 0.5
            if dist < best_px_dist:
                best_px_dist = dist
                best_info = info
                best_xi = idx

        if best_info is None or best_px_dist > self._SNAP_PX:
            self._vline.setVisible(False)
            self._hover_label.setVisible(False)
            return

        best_x = best_info["x"][best_xi]
        self._vline.setPos(best_x)
        self._vline.setVisible(True)

        label = best_info["style"].label or best_info["sensor_name"]
        lines = [
            f"<b>Load Step: {best_x:.4g}</b>",
            f"{label}: {best_info['y'][best_xi]:.6g}",
        ]

        self._hover_label.setHtml("<br>".join(lines))
        self._hover_label.setPos(best_x, mp.y())
        self._hover_label.setVisible(True)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def add_series(
        self,
        sensor_name: str,
        source_id: str,
        x: np.ndarray,
        y: np.ndarray,
        style: Optional[SeriesStyle] = None,
    ) -> str:
        key = f"{source_id}::{sensor_name}"

        if style is None:
            style = SeriesStyle(
                color=_COLORS[self._color_idx % len(_COLORS)],
                label=sensor_name,
            )
            self._color_idx += 1

        pen = _make_pen(style)
        symbol = _make_symbol(style.marker)
        sym_pen = _make_symbol_pen(style.color)
        sym_brush = _make_symbol_brush(style.color)

        sym_size = 5 + style.thickness * 2

        display_label = style.label or sensor_name
        legend_name = f"{display_label} [{style.formula}]" if style.formula else display_label

        if key in self._series:
            item = self._series[key]["item"]
            # Use setData with all style kwargs for reliable update
            item.setData(
                x=x, y=y,
                pen=pen,
                symbol=symbol,
                symbolPen=sym_pen,
                symbolBrush=sym_brush,
                symbolSize=sym_size,
            )
            item.setVisible(style.visible)
            # Update legend label (formula may have changed)
            legend = self._plot.getPlotItem().legend
            if legend is not None:
                legend.removeItem(item)
                legend.addItem(item, legend_name)
            # Refresh band positions if data changed
            self._refresh_bands_for_key(key, x, y)
        else:
            item = self._plot.plot(
                x=x, y=y,
                pen=pen,
                symbol=symbol,
                symbolPen=sym_pen,
                symbolBrush=sym_brush,
                symbolSize=sym_size,
                name=legend_name,
            )

        self._series[key] = {
            "item": item, "style": style,
            "sensor_name": sensor_name, "source_id": source_id,
            "x": x, "y": y,
        }
        return key

    def remove_series(self, key: str) -> None:
        if key in self._series:
            self._plot.removeItem(self._series[key]["item"])
            del self._series[key]
        # Remove any bands tied to this series
        for band_id in [bid for bid, b in self._bands.items() if b["key"] == key]:
            self.remove_error_band(band_id)
        if not self._series:
            self._vline.setVisible(False)
            self._hover_label.setVisible(False)

    def customize_series(self, key: str) -> None:
        if key not in self._series:
            return
        dlg = CustomizationDialog(self._series[key]["style"], self)
        if dlg.exec():
            s = self._series[key]
            self.add_series(s["sensor_name"], s["source_id"], s["x"], s["y"], dlg.get_style())

    def _show_series_context_menu(self, global_pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        if self._series:
            for key, info in self._series.items():
                label = info["style"].label or info["sensor_name"]
                sm = menu.addMenu(f"  {label}")
                sm.addAction("Customize…").triggered.connect(
                    lambda _=False, k=key: self.customize_series(k))
                sm.addAction("Hide" if info["style"].visible else "Show").triggered.connect(
                    lambda _=False, k=key: self._toggle_visibility(k))
                sm.addAction("Add Error Band…").triggered.connect(
                    lambda _=False, k=key: self._prompt_add_error_band(k))
                # List existing bands for this series
                for band_id, binfo in self._bands.items():
                    if binfo["key"] == key:
                        sm.addAction(f"Remove Band ±{binfo['pct']:.4g}%").triggered.connect(
                            lambda _=False, bid=band_id: self.remove_error_band(bid))
                sm.addAction("Remove").triggered.connect(
                    lambda _=False, k=key: self.remove_series(k))
            menu.addSeparator()
        menu.addAction("Clear All Series").triggered.connect(self.clear)
        menu.exec(global_pos)

    def _toggle_visibility(self, key: str) -> None:
        if key not in self._series:
            return
        s = self._series[key]
        new_style = SeriesStyle(**{**s["style"].__dict__, "visible": not s["style"].visible})
        self.add_series(s["sensor_name"], s["source_id"], s["x"], s["y"], new_style)

    def consume_next_color(self) -> str:
        """Return the next auto-color and advance the internal counter."""
        color = _COLORS[self._color_idx % len(_COLORS)]
        self._color_idx += 1
        return color

    def series_keys(self) -> list[str]:
        return list(self._series.keys())

    def get_series_info(self, key: str) -> Optional[dict]:
        return dict(self._series[key]) if key in self._series else None

    def clear(self) -> None:
        self._plot.clear()
        self._series.clear()
        self._bands.clear()
        self._vline.setVisible(False)
        self._hover_label.setVisible(False)
        self._color_idx = 0
        # Re-add overlay items lost by clear()
        self._plot.addItem(self._vline, ignoreBounds=True)
        self._plot.addItem(self._hover_label, ignoreBounds=True)

    def to_config(self) -> dict:
        return {
            "title": self._title,
            "series": [
                {"sensor_name": s["sensor_name"],
                 "source_id": s["source_id"],
                 "style": s["style"].to_dict()}
                for s in self._series.values()
            ],
            "bands": [
                {"key": b["key"], "pct": b["pct"]}
                for b in self._bands.values()
            ],
        }

    def get_bands(self) -> dict[str, dict]:
        """Return a copy of the current error bands dict."""
        return dict(self._bands)

    # ------------------------------------------------------------------ #
    # Error bands                                                         #
    # ------------------------------------------------------------------ #

    def add_error_band(self, key: str, pct: float) -> Optional[str]:
        """Add a ±pct% translucent fill band around the named series.

        Returns the band_id string, or None if *key* is not a known series.
        """
        if key not in self._series:
            return None

        band_id = f"{key}::band::{pct:.4g}"
        # Replace any existing band at the same percentage
        if band_id in self._bands:
            self.remove_error_band(band_id)

        info = self._series[key]
        x = info["x"]
        y = info["y"]
        color = info["style"].color

        upper_y = y * (1 + pct / 100)
        lower_y = y * (1 - pct / 100)

        upper_item = pg.PlotDataItem(x, upper_y, pen=pg.mkPen(None))
        lower_item = pg.PlotDataItem(x, lower_y, pen=pg.mkPen(None))

        # Items must be in the plot before FillBetweenItem connects to their signals
        self._plot.addItem(upper_item)
        self._plot.addItem(lower_item)

        c = QColor(color)
        c.setAlpha(50)
        fill_item = pg.FillBetweenItem(upper_item.curve, lower_item.curve, brush=pg.mkBrush(c))
        self._plot.addItem(fill_item)

        self._bands[band_id] = {
            "key": key,
            "pct": pct,
            "upper_item": upper_item,
            "lower_item": lower_item,
            "fill_item": fill_item,
        }
        return band_id

    def remove_error_band(self, band_id: str) -> None:
        """Remove an error band by its ID."""
        if band_id not in self._bands:
            return
        b = self._bands.pop(band_id)
        self._plot.removeItem(b["fill_item"])
        self._plot.removeItem(b["upper_item"])
        self._plot.removeItem(b["lower_item"])

    def _refresh_bands_for_key(self, key: str, x: np.ndarray, y: np.ndarray) -> None:
        """Recompute band curves when the underlying series data changes."""
        for b in self._bands.values():
            if b["key"] != key:
                continue
            pct = b["pct"]
            b["upper_item"].setData(x, y * (1 + pct / 100))
            b["lower_item"].setData(x, y * (1 - pct / 100))

    def _prompt_add_error_band(self, key: str) -> None:
        """Ask the user for a percentage and add an error band."""
        from PySide6.QtWidgets import QInputDialog
        pct, ok = QInputDialog.getDouble(
            self, "Add Error Band", "Error band percentage (%):",
            10.0, 0.1, 100.0, 1,
        )
        if ok:
            self.add_error_band(key, pct)

    # ------------------------------------------------------------------ #
    # Drag-and-drop + context menu                                        #
    # ------------------------------------------------------------------ #

    def _vb(self):
        return self._plot.getPlotItem().getViewBox()

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        et = event.type()

        # Intercept drag-and-drop before pyqtgraph's scene sees them.
        # Handling here (returning True) prevents the ViewBox from entering a
        # stale drag state that causes edge-panning after the drop.
        if et == QEvent.Type.DragEnter:
            if event.mimeData().hasFormat(_MIME_ROW):
                event.acceptProposedAction()
                return True
        elif et == QEvent.Type.DragMove:
            if event.mimeData().hasFormat(_MIME_ROW):
                event.acceptProposedAction()
                return True
        elif et == QEvent.Type.Drop:
            if event.mimeData().hasFormat(_MIME_ROW):
                raw = bytes(event.mimeData().data(_MIME_ROW)).decode()
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        data = [data]
                    for payload in data:
                        self.series_dropped.emit(payload)
                except json.JSONDecodeError:
                    pass
                event.acceptProposedAction()
                return True

        # Right-click context menu on plot
        if obj is self._plot and et == QEvent.Type.ContextMenu:
            self._show_series_context_menu(event.globalPos())
            return True

        return super().eventFilter(obj, event)
