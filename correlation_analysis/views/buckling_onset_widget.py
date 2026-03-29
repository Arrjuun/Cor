"""Widget displaying SUP, INF, membrane, and bending strain history for a buckling onset element."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
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
    """Content widget for a buckling onset tab: SUP, INF, membrane, and bending strain
    history with onset markers.

    This widget does NOT wrap itself in a QScrollArea — the parent tab content
    (BucklingTabContent) owns the scroll area.

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
        # Store arrays for to_config() / export
        self._time = np.asarray(time, dtype=float)
        self._sup = {k: np.asarray(v, dtype=float) for k, v in sup.items()}
        self._inf = {k: np.asarray(v, dtype=float) for k, v in inf.items()}
        self._onset_timesteps = list(onset_timesteps)
        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI                                                                   #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        """Four plots arranged in a grid (no scroll area — owned by parent tab)."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(16)

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
            layout.addWidget(banner)

        # Grid container for the four plots
        self._plots_container = QWidget()
        self._plots_grid = QGridLayout(self._plots_container)
        self._plots_grid.setSpacing(8)
        layout.addWidget(self._plots_container)

        # Build the four plot widgets: SUP → INF → Membrane → Bending
        self._plot_widgets: list[pg.PlotWidget] = []
        for plot_key, y_label, _ in _PLOT_SPECS:
            pw = self._make_plot(plot_key, y_label, self._time, self._sup, self._inf, self._onset_timesteps)
            self._plot_widgets.append(pw)

        self._num_columns = 1
        self._relayout_plots()

    def _relayout_plots(self) -> None:
        """Re-place all onset plots in the grid according to current column count."""
        for pw in self._plot_widgets:
            self._plots_grid.removeWidget(pw)
        for i, pw in enumerate(self._plot_widgets):
            row = i // self._num_columns
            col = i % self._num_columns
            self._plots_grid.addWidget(pw, row, col)

    def set_columns(self, n: int) -> None:
        """Rearrange the four onset plots into *n* columns."""
        self._num_columns = max(1, min(4, n))
        self._relayout_plots()

    def _make_plot(
        self,
        plot_key: str,
        y_label: str,
        time: np.ndarray,
        sup: dict[str, np.ndarray],
        inf: dict[str, np.ndarray],
        onset_timesteps: list[float],
    ) -> pg.PlotWidget:
        """Build one pyqtgraph PlotWidget for *plot_key*
        (``"SUP"``, ``"INF"``, ``"Membrane"``, or ``"Bending"``)."""
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

    # ------------------------------------------------------------------ #
    # Serialisation                                                        #
    # ------------------------------------------------------------------ #

    def to_config(self) -> dict:
        """Return a JSON-serialisable dict representing this widget's data."""
        return {
            "type": "buckling_onset",
            "element_id": self._element_id,
            "source_label": self._source_label,
            "onset_timesteps": list(self._onset_timesteps),
            "time": self._time.tolist(),
            "sup": {k: v.tolist() for k, v in self._sup.items()},
            "inf": {k: v.tolist() for k, v in self._inf.items()},
        }

    @staticmethod
    def from_config(cfg: dict) -> "BucklingOnsetWidget":
        """Reconstruct a widget from a previously saved config dict."""
        return BucklingOnsetWidget(
            element_id=cfg["element_id"],
            time=np.array(cfg["time"], dtype=float),
            sup={k: np.array(v, dtype=float) for k, v in cfg.get("sup", {}).items()},
            inf={k: np.array(v, dtype=float) for k, v in cfg.get("inf", {}).items()},
            onset_timesteps=cfg.get("onset_timesteps", []),
            source_label=cfg.get("source_label", ""),
        )
