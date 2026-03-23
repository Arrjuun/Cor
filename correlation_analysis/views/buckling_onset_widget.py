"""Widget displaying membrane and bending strain history for a buckling onset element."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

_SERIES_COLORS = {
    "e11": "#1565C0",
    "e22": "#C62828",
    "e12": "#2E7D32",
}
_ONSET_COLOR = "#FF6F00"


class BucklingOnsetWidget(QWidget):
    """Tab content widget: membrane + bending strain history with onset markers.

    Parameters
    ----------
    element_id:
        The element / rosette identifier string shown in the tab title.
    time:
        1-D array of time / load-step values (x-axis).
    sup:
        Dict mapping ``"e11"``, ``"e22"``, ``"e12"`` to SUP (superior) strain arrays.
    inf:
        Dict mapping ``"e11"``, ``"e22"``, ``"e12"`` to INF (inferior) strain arrays.
    onset_timesteps:
        List of timestep values where buckling onset was detected; a vertical dashed
        line is drawn at each one on both plots.
    """

    def __init__(
        self,
        element_id: str,
        time: np.ndarray,
        sup: dict[str, np.ndarray],
        inf: dict[str, np.ndarray],
        onset_timesteps: list[float],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._element_id = element_id
        self._build_ui(time, sup, inf, onset_timesteps)

    # ------------------------------------------------------------------ #
    # UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(
        self,
        time: np.ndarray,
        sup: dict[str, np.ndarray],
        inf: dict[str, np.ndarray],
        onset_timesteps: list[float],
    ) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(4, 4, 4, 4)
        root_layout.setSpacing(4)

        # Scrollable container for both plots
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        inner = QVBoxLayout(container)
        inner.setSpacing(16)
        inner.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(container)
        root_layout.addWidget(scroll)

        # Build membrane plot, then bending plot
        for plot_type in ("Membrane", "Bending"):
            plot_widget = self._make_plot(plot_type, time, sup, inf, onset_timesteps)
            inner.addWidget(plot_widget)

        inner.addStretch()

    def _make_plot(
        self,
        plot_type: str,
        time: np.ndarray,
        sup: dict[str, np.ndarray],
        inf: dict[str, np.ndarray],
        onset_timesteps: list[float],
    ) -> pg.PlotWidget:
        """Create and return one pyqtgraph PlotWidget for *plot_type* (Membrane or Bending)."""
        title = f"{plot_type} Strain History - Element {self._element_id}"
        plot = pg.PlotWidget(title=title)
        plot.setBackground("w")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setLabel("bottom", "Step Time")
        plot.setLabel("left", f"{plot_type} Strain")
        plot.setMinimumHeight(380)
        plot.addLegend(offset=(10, 10))

        # Plot each strain component
        for comp in ("e11", "e22", "e12"):
            sup_arr = sup.get(comp)
            inf_arr = inf.get(comp)
            if sup_arr is None or inf_arr is None:
                continue
            if len(sup_arr) != len(time) or len(inf_arr) != len(time):
                continue

            y = (sup_arr + inf_arr) / 2.0 if plot_type == "Membrane" else (sup_arr - inf_arr) / 2.0
            color = _SERIES_COLORS.get(comp, "#000000")
            pen = pg.mkPen(color=color, width=2, cosmetic=True)
            plot.plot(
                time, y,
                pen=pen,
                name=comp,
                symbol="o",
                symbolSize=6,
                symbolBrush=pg.mkBrush(color),
                symbolPen=pg.mkPen(color, width=1),
            )

        # Onset vertical lines
        onset_pen = pg.mkPen(
            color=_ONSET_COLOR, width=2,
            style=Qt.PenStyle.DashLine, cosmetic=True,
        )
        for ts in onset_timesteps:
            label_text = f"Buckling Onset\nStep Time = {ts:.6f}"
            vline = pg.InfiniteLine(
                pos=ts,
                angle=90,
                movable=False,
                pen=onset_pen,
                label=label_text,
                labelOpts={
                    "position": 0.90,
                    "color": _ONSET_COLOR,
                    "fill": pg.mkBrush(255, 255, 255, 200),
                    "border": pg.mkPen(_ONSET_COLOR, width=1),
                },
            )
            plot.addItem(vline)

        return plot
