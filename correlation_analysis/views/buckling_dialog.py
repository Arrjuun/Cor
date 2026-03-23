"""Buckling Analysis Dialog.

Shows sensor pairs grouped by their Sensor Pair mapping value, with
collapsible groups, per-sensor correlation-type dropdowns, and small
non-interactive trend sparklines.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ------------------------------------------------------------------ #
# Data classes (built by the presenter, consumed by the dialog)       #
# ------------------------------------------------------------------ #

@dataclass
class SourceInfo:
    """Sensor occurrence in one imported source."""
    source_id: str
    display_name: str        # filename / user label
    sensor_name: str         # actual name in that source's DataFrame ("—" if absent)
    data: Optional[pd.Series] = None   # index=load_step, values=strain (None if absent)


@dataclass
class SensorEntry:
    """One sensor row inside a BucklingGroup (one rosette element or one individual sensor)."""
    canonical: str
    default_cor: str                        # "e11" / "e12" / "e22"
    sources: list[SourceInfo] = field(default_factory=list)


@dataclass
class BucklingGroup:
    """One collapsible card in the dialog — represents one Sensor Pair value.

    For rosette groups the card is split per source, so ``source_label`` carries
    the source display name (e.g. ``"source_a.csv"``).  For individual-sensor
    groups it is left empty and all sources are shown as side-by-side columns.
    """
    pair_id: str
    is_rosette: bool
    rosette_id: str                         # own rosette ID; "" when is_rosette is False
    source_label: str = ""                  # non-empty for per-source rosette groups
    sensors: list[SensorEntry] = field(default_factory=list)
    # Ordered list mirrors the order of SourceInfo entries inside each SensorEntry.
    # For rosette groups: [("left", own_rosette_id), ("right", paired_rosette_id)]
    # For individual groups: [(source_id, display_name), ...]
    source_headers: list[tuple[str, str]] = field(default_factory=list)


# ------------------------------------------------------------------ #
# Mini sparkline (non-interactive)                                     #
# ------------------------------------------------------------------ #

def _make_sparkline(data: Optional[pd.Series]) -> pg.PlotWidget:
    """Return a tiny, read-only pyqtgraph plot with a single line series."""
    pw = pg.PlotWidget()
    pw.setFixedSize(150, 52)
    pw.setMouseEnabled(x=False, y=False)
    pw.hideAxis("left")
    pw.hideAxis("bottom")
    pw.setBackground("w")
    pw.getPlotItem().hideButtons()
    pw.setMenuEnabled(False)
    pw.setToolTip("")

    if data is not None and not data.dropna().empty:
        clean = data.dropna()
        try:
            x = [float(v) for v in clean.index]
            y = clean.values.tolist()
            pw.plot(x, y, pen=pg.mkPen("#1565C0", width=1.5))
        except (ValueError, TypeError):
            pass

    # Block all mouse events so the widget is truly inert
    pw.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return pw


# ------------------------------------------------------------------ #
# Group card widget                                                    #
# ------------------------------------------------------------------ #

class BucklingGroupWidget(QFrame):
    """Collapsible card representing one Sensor Pair group."""

    def __init__(self, group: BucklingGroup, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._group = group
        self._expanded = True
        self._cor_combos: list[QComboBox] = []
        self._build_ui()

    # ---- Construction -----------------------------------------------

    def _build_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        self.setLineWidth(1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Header bar ----
        header = QWidget()
        header.setObjectName("BucklingHeader")
        header.setStyleSheet(
            "#BucklingHeader { background: #E3F2FD; border-bottom: 1px solid #BBDEFB; }"
        )
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(8, 6, 8, 6)
        hdr_layout.setSpacing(8)

        self._checkbox = QCheckBox()
        self._checkbox.setChecked(True)
        self._checkbox.setToolTip("Include in analysis")
        hdr_layout.addWidget(self._checkbox)

        title_lbl = QLabel(self._make_title())
        title_lbl.setFont(QFont("", -1, QFont.Weight.Bold))
        hdr_layout.addWidget(title_lbl)
        hdr_layout.addStretch()

        # Type badge
        badge_text = "Rosette" if self._group.is_rosette else "Individual"
        badge_color = "#7B1FA2" if self._group.is_rosette else "#1565C0"
        badge = QLabel(badge_text)
        badge.setStyleSheet(
            f"color: white; background: {badge_color}; "
            "border-radius: 4px; padding: 2px 8px; font-weight: bold;"
        )
        hdr_layout.addWidget(badge)

        self._toggle_btn = QPushButton("∧")
        self._toggle_btn.setFixedSize(26, 26)
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.clicked.connect(self._toggle_body)
        hdr_layout.addWidget(self._toggle_btn)

        outer.addWidget(header)

        # ---- Body ----
        self._body = QWidget()
        self._build_body()
        outer.addWidget(self._body)

    def _make_title(self) -> str:
        g = self._group
        if g.is_rosette:
            # e.g. "Rosette_1 → Rosette_2   [source_a.csv]"
            title = g.pair_id
            if g.source_label:
                title += f"   [{g.source_label}]"
            return title
        # Individual: "SensorA_name  Mapping: SensorB_name"
        if g.sensors:
            names = [
                si.sensor_name
                for si in g.sensors[0].sources
                if si.sensor_name and si.sensor_name != "—"
            ]
            if len(names) >= 2:
                return f"{names[0]}   Mapping: {names[1]}"
            if names:
                return names[0]
        return g.pair_id

    def _build_body(self) -> None:
        grid = QGridLayout(self._body)
        grid.setContentsMargins(12, 8, 12, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        n_src = len(self._group.source_headers)

        # ---- Column headers ----
        header_font = QFont("", -1, QFont.Weight.Bold)
        cor_hdr = QLabel("Cor")
        cor_hdr.setFont(header_font)
        grid.addWidget(cor_hdr, 0, 0, Qt.AlignmentFlag.AlignCenter)

        for i, (_, disp) in enumerate(self._group.source_headers):
            col_base = 1 + i * 2
            sensor_hdr = QLabel(f"Sensor\n({disp})")
            sensor_hdr.setFont(header_font)
            sensor_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(sensor_hdr, 0, col_base)

            trend_hdr = QLabel("Trend")
            trend_hdr.setFont(header_font)
            trend_hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(trend_hdr, 0, col_base + 1)

        # ---- Sensor rows ----
        self._cor_combos.clear()
        for row_idx, entry in enumerate(self._group.sensors):
            r = row_idx + 1

            combo = QComboBox()
            combo.addItems(["e11", "e12", "e22"])
            combo.setCurrentText(entry.default_cor)
            combo.setFixedWidth(68)
            self._cor_combos.append(combo)
            grid.addWidget(combo, r, 0, Qt.AlignmentFlag.AlignCenter)

            for i, src_info in enumerate(entry.sources):
                col_base = 1 + i * 2

                name_lbl = QLabel(src_info.sensor_name)
                name_lbl.setToolTip(f"Canonical: {entry.canonical}")
                name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                if src_info.sensor_name == "—":
                    name_lbl.setStyleSheet("color: #BDBDBD;")
                grid.addWidget(name_lbl, r, col_base)

                sparkline = _make_sparkline(src_info.data)
                grid.addWidget(sparkline, r, col_base + 1, Qt.AlignmentFlag.AlignCenter)

        # Column stretch: Cor fixed, sensor+trend pairs share remaining space
        grid.setColumnStretch(0, 0)
        for i in range(n_src):
            grid.setColumnStretch(1 + i * 2, 1)   # sensor name
            grid.setColumnStretch(2 + i * 2, 2)   # trend plot

    # ---- Toggle ---------------------------------------------------------

    def _toggle_body(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._toggle_btn.setText("∧" if self._expanded else "∨")

    # ---- Public API ------------------------------------------------------

    def is_checked(self) -> bool:
        return self._checkbox.isChecked()

    def set_checked(self, checked: bool) -> None:
        self._checkbox.setChecked(checked)

    def get_selection(self) -> dict:
        """Return a serialisable dict describing this group's current selection."""
        rows = []
        for i, entry in enumerate(self._group.sensors):
            cor = self._cor_combos[i].currentText() if i < len(self._cor_combos) else entry.default_cor
            rows.append({
                "canonical": entry.canonical,
                "cor": cor,
                "sources": {
                    si.source_id: si.sensor_name for si in entry.sources
                },
            })
        return {
            "pair_id": self._group.pair_id,
            "is_rosette": self._group.is_rosette,
            "rosette_id": self._group.rosette_id,
            "sensors": rows,
        }


# ------------------------------------------------------------------ #
# Main dialog                                                          #
# ------------------------------------------------------------------ #

class BucklingDialog(QDialog):
    """
    Dialog listing all sensor pairs from the loaded mapping, grouped by
    their Sensor Pair value, for selection before running buckling analysis.

    Signals
    -------
    analyze_requested : list[dict]
        Emitted when "Analyze Checked Elements" is clicked with the list
        of checked group selection dicts (from :meth:`BucklingGroupWidget.get_selection`).
    """

    analyze_requested = Signal(list)

    def __init__(
        self,
        groups: list[BucklingGroup],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._groups = groups
        self._group_widgets: list[BucklingGroupWidget] = []
        self.setWindowTitle("Buckling Analysis — Sensor Pair Selection")
        self.setMinimumSize(960, 620)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ---- Top toolbar ----
        top_bar = QHBoxLayout()
        check_all_btn = QPushButton("Check All")
        uncheck_all_btn = QPushButton("Uncheck All")
        check_all_btn.setCheckable(False)
        uncheck_all_btn.setCheckable(False)
        check_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        uncheck_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        top_bar.addWidget(check_all_btn)
        top_bar.addWidget(uncheck_all_btn)
        top_bar.addStretch()
        n_rosette = sum(1 for g in self._groups if g.is_rosette)
        n_individual = len(self._groups) - n_rosette
        summary = QLabel(
            f"<span style='color:#7B1FA2;'><b>{n_rosette}</b> Rosette</span>"
            f"  |  "
            f"<span style='color:#1565C0;'><b>{n_individual}</b> Individual</span>"
            f"  groups"
        )
        top_bar.addWidget(summary)
        layout.addLayout(top_bar)

        # ---- Scrollable group list ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(4, 4, 4, 4)
        container_layout.setSpacing(10)

        for group in self._groups:
            w = BucklingGroupWidget(group, container)
            self._group_widgets.append(w)
            container_layout.addWidget(w)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        # ---- Bottom bar ----
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        analyze_btn = QPushButton("Analyze Checked Elements")
        analyze_btn.setCheckable(False)
        analyze_btn.setMinimumWidth(220)
        analyze_btn.clicked.connect(self._on_analyze)
        bottom_bar.addWidget(analyze_btn)
        layout.addLayout(bottom_bar)

    # ---- Helpers --------------------------------------------------------

    def _set_all_checked(self, checked: bool) -> None:
        for w in self._group_widgets:
            w.set_checked(checked)

    def _on_analyze(self) -> None:
        selections = [w.get_selection() for w in self._group_widgets if w.is_checked()]
        if not selections:
            QMessageBox.warning(
                self,
                "No Selection",
                "Please check at least one element before analyzing.",
            )
            return
        self.analyze_requested.emit(selections)
        self.accept()
