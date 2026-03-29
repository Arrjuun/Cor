"""Widget displaying SUP, INF, membrane, and bending strain history for a buckling onset element."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
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

# Plot-type descriptors: (key, y-axis label, derivation note)
_PLOT_SPECS = [
    ("SUP",      "SUP Strain",      "Raw superior-surface strain from the data source"),
    ("INF",      "INF Strain",      "Raw inferior-surface strain from the data source"),
    ("Membrane", "Membrane Strain", "(SUP + INF) / 2"),
    ("Bending",  "Bending Strain",  "(SUP − INF) / 2"),
]


class BucklingOnsetWidget(QWidget):
    """Tab content widget: SUP, INF, membrane, and bending strain history with onset markers.

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
        line is drawn at each one on all plots.
    source_label:
        Display name of the data source this element's strains came from
        (e.g. ``"source_a.csv"``).  Shown in the widget header and plot titles.
    """

    def __init__(
        self,
        element_id: str,
        time: np.ndarray,
        sup: dict[str, np.ndarray],
        inf: dict[str, np.ndarray],
        onset_timesteps: list[float],
        source_label: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._element_id = element_id
        self._source_label = source_label
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

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        inner = QVBoxLayout(container)
        inner.setSpacing(16)
        inner.setContentsMargins(8, 8, 8, 8)
        scroll.setWidget(container)
        root_layout.addWidget(scroll)

        # Source header banner
        if self._source_label:
            banner = QLabel(f"Data Source:  {self._source_label}")
            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            banner.setFont(font)
            banner.setStyleSheet(
                "color: #1565C0; background: #E3F2FD; "
                "border-radius: 4px; padding: 6px 10px;"
            )
            inner.addWidget(banner)

        # Four plots: SUP → INF → Membrane → Bending
        for plot_key, y_label, _ in _PLOT_SPECS:
            inner.addWidget(self._make_plot(plot_key, y_label, time, sup, inf, onset_timesteps))

        inner.addStretch()

    def _make_plot(
        self,
        plot_key: str,
        y_label: str,
        time: np.ndarray,
        sup: dict[str, np.ndarray],
        inf: dict[str, np.ndarray],
        onset_timesteps: list[float],
    ) -> pg.PlotWidget:
        """Build one pyqtgraph PlotWidget for *plot_key* (``"SUP"``, ``"INF"``,
        ``"Membrane"``, or ``"Bending"``)."""
        src_tag = f"  [{self._source_label}]" if self._source_label else ""
        title = f"{plot_key} Strain — Element {self._element_id}{src_tag}"

        plot = pg.PlotWidget(title=title)
        plot.setBackground("w")
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setLabel("bottom", "Step Time")
        plot.setLabel("left", y_label)
        plot.setMinimumHeight(360)
        plot.addLegend(offset=(10, 10))

        for comp in ("e11", "e22", "e12"):
            sup_arr = sup.get(comp)
            inf_arr = inf.get(comp)

            # Determine the y-values for this plot type
            if plot_key == "SUP":
                if sup_arr is None or len(sup_arr) != len(time):
                    continue
                y = sup_arr
            elif plot_key == "INF":
                if inf_arr is None or len(inf_arr) != len(time):
                    continue
                y = inf_arr
            elif plot_key == "Membrane":
                if sup_arr is None or inf_arr is None:
                    continue
                if len(sup_arr) != len(time) or len(inf_arr) != len(time):
                    continue
                y = (sup_arr + inf_arr) / 2.0
            else:  # Bending
                if sup_arr is None or inf_arr is None:
                    continue
                if len(sup_arr) != len(time) or len(inf_arr) != len(time):
                    continue
                y = (sup_arr - inf_arr) / 2.0

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
            vline = pg.InfiniteLine(
                pos=ts,
                angle=90,
                movable=False,
                pen=onset_pen,
                label=f"Buckling Onset\nStep Time = {ts:.6f}",
                labelOpts={
                    "position": 0.90,
                    "color": _ONSET_COLOR,
                    "fill": pg.mkBrush(255, 255, 255, 200),
                    "border": pg.mkPen(_ONSET_COLOR, width=1),
                },
            )
            plot.addItem(vline)

        return plot
