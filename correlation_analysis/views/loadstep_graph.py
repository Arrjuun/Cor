"""LoadStep vs Strain graph widget using pyqtgraph."""
from __future__ import annotations

import json
from typing import Any, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QByteArray, QMimeData, Qt, Signal
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
        self._color_idx = 0
        self._dragging = False
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

        # Event filter: context menu on plot, block mouse during drag on viewport
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
        self._plot.addItem(self._hover_label)
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

    def _on_mouse_moved(self, event) -> None:
        pos = event[0]
        if not self._series or not self._plot.sceneBoundingRect().contains(pos):
            self._vline.setVisible(False)
            self._hover_label.setVisible(False)
            return

        vb = self._plot.getPlotItem().getViewBox()
        mp = vb.mapSceneToView(pos)
        x = mp.x()

        self._vline.setPos(x)
        self._vline.setVisible(True)

        lines = [f"<b>Load Step: {x:.4g}</b>"]
        for info in self._series.values():
            xdata, ydata = info["x"], info["y"]
            if len(xdata) == 0:
                continue
            idx = int(np.argmin(np.abs(xdata - x)))
            label = info["style"].label or info["sensor_name"]
            lines.append(f"{label}: {ydata[idx]:.6g}")

        self._hover_label.setHtml("<br>".join(lines))
        # Clamp label to stay within view
        vr = vb.viewRange()
        lx = x if x < (vr[0][0] + vr[0][1]) / 2 else x
        self._hover_label.setPos(lx, mp.y())
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

        if key in self._series:
            item = self._series[key]["item"]
            # Use setData with all style kwargs for reliable update
            item.setData(
                x=x, y=y,
                pen=pen,
                symbol=symbol,
                symbolPen=sym_pen,
                symbolBrush=sym_brush,
                symbolSize=7,
            )
            item.setVisible(style.visible)
        else:
            item = self._plot.plot(
                x=x, y=y,
                pen=pen,
                symbol=symbol,
                symbolPen=sym_pen,
                symbolBrush=sym_brush,
                symbolSize=7,
                name=style.label or sensor_name,
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

    def series_keys(self) -> list[str]:
        return list(self._series.keys())

    def get_series_info(self, key: str) -> Optional[dict]:
        return dict(self._series[key]) if key in self._series else None

    def clear(self) -> None:
        self._plot.clear()
        self._series.clear()
        self._vline.setVisible(False)
        self._hover_label.setVisible(False)
        self._color_idx = 0
        # Re-add overlay items lost by clear()
        self._plot.addItem(self._vline, ignoreBounds=True)
        self._plot.addItem(self._hover_label)

    def to_config(self) -> dict:
        return {
            "title": self._title,
            "series": [
                {"sensor_name": s["sensor_name"],
                 "source_id": s["source_id"],
                 "style": s["style"].to_dict()}
                for s in self._series.values()
            ],
        }

    # ------------------------------------------------------------------ #
    # Drag-and-drop + context menu                                        #
    # ------------------------------------------------------------------ #

    def _vb(self):
        return self._plot.getPlotItem().getViewBox()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_ROW):
            self._dragging = True
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_ROW):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._dragging = False
        self._release_plot_mouse()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._dragging = False
        if event.mimeData().hasFormat(_MIME_ROW):
            raw = bytes(event.mimeData().data(_MIME_ROW)).decode()
            try:
                data = json.loads(raw)
                # Payload is always a list; support legacy single-dict for safety
                if isinstance(data, dict):
                    data = [data]
                for payload in data:
                    self.series_dropped.emit(payload)
            except json.JSONDecodeError:
                pass
            event.acceptProposedAction()
        else:
            event.ignore()
        # Defer to the next event-loop tick so all DnD bookkeeping and any
        # modal-dialog events raised by series_dropped are fully processed first.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._release_plot_mouse)

    def _release_plot_mouse(self) -> None:
        """Clear stuck mouse-drag state in pyqtgraph after a DnD drop.

        When a modal dialog is shown synchronously inside series_dropped (e.g.
        "add mapped sensors?"), its event loop can leave pyqtgraph's GraphicsScene
        with stale entries in dragButtons, causing the ViewBox to pan/zoom on
        plain mouse-move. Clear that state directly.
        """
        from PySide6.QtWidgets import QApplication
        scene = self._plot.scene()
        if hasattr(scene, "dragButtons"):
            scene.dragButtons.clear()
        if hasattr(scene, "clickEvents"):
            scene.clickEvents.clear()
        while QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        et = event.type()
        # Right-click context menu on plot
        if obj is self._plot and et == QEvent.Type.ContextMenu:
            self._show_series_context_menu(event.globalPos())
            return True
        # Block all mouse interaction on the viewport while a drag is in progress.
        # This prevents pyqtgraph's scene from interpreting drag motion as pan/zoom.
        if obj is self._plot.viewport() and self._dragging:
            if et in (
                QEvent.Type.MouseButtonPress,
                QEvent.Type.MouseButtonDblClick,
                QEvent.Type.MouseMove,
            ):
                return True
        return super().eventFilter(obj, event)
