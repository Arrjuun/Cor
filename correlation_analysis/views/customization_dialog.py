"""Series styling / customization dialog."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


LINE_STYLES = ["Solid", "Dashed", "Dotted", "DashDot"]
MARKERS = ["None", "Circle", "Square", "Triangle", "Diamond", "Cross"]

# Map line style names to Qt pen styles
LINE_STYLE_MAP = {
    "Solid": Qt.PenStyle.SolidLine,
    "Dashed": Qt.PenStyle.DashLine,
    "Dotted": Qt.PenStyle.DotLine,
    "DashDot": Qt.PenStyle.DashDotLine,
}


@dataclass
class SeriesStyle:
    """Complete styling definition for a graph series."""
    color: str = "#1565C0"          # hex color
    line_style: str = "Solid"       # one of LINE_STYLES
    marker: str = "Circle"          # one of MARKERS
    thickness: int = 1              # 1-10
    visible: bool = True
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "color": self.color,
            "line_style": self.line_style,
            "marker": self.marker,
            "thickness": self.thickness,
            "visible": self.visible,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeriesStyle":
        return cls(
            color=data.get("color", "#1565C0"),
            line_style=data.get("line_style", "Solid"),
            marker=data.get("marker", "Circle"),
            thickness=data.get("thickness", 2),
            visible=data.get("visible", True),
            label=data.get("label", ""),
        )

    def pen_color(self) -> QColor:
        return QColor(self.color)


class ColorButton(QPushButton):
    """A push button that shows the current color and opens a color picker."""

    color_changed = Signal(str)

    def __init__(self, color: str = "#1565C0", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = color
        self.setFixedWidth(80)
        self.setCheckable(False)
        self._update_style()
        self.clicked.connect(self._pick_color)

    def set_color(self, color: str) -> None:
        self._color = color
        self._update_style()

    def get_color(self) -> str:
        return self._color

    def _update_style(self) -> None:
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; "
            f"color: {'black' if QColor(self._color).lightness() > 128 else 'white'}; "
            f"border: 1px solid #999; border-radius: 3px; }}"
        )
        self.setText(self._color)

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, "Select Color")
        if color.isValid():
            self._color = color.name()
            self._update_style()
            self.color_changed.emit(self._color)


class CustomizationDialog(QDialog):
    """Dialog for editing a SeriesStyle."""

    def __init__(
        self,
        style: Optional[SeriesStyle] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Customize Series")
        self.setMinimumWidth(320)
        self._style = SeriesStyle() if style is None else SeriesStyle(**style.__dict__)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Color
        self._color_btn = ColorButton(self._style.color)
        form.addRow("Color:", self._color_btn)

        # Line style
        self._line_combo = QComboBox()
        self._line_combo.addItems(LINE_STYLES)
        self._line_combo.setCurrentText(self._style.line_style)
        form.addRow("Line Style:", self._line_combo)

        # Marker
        self._marker_combo = QComboBox()
        self._marker_combo.addItems(MARKERS)
        self._marker_combo.setCurrentText(self._style.marker)
        form.addRow("Marker:", self._marker_combo)

        # Thickness
        self._thickness_spin = QSpinBox()
        self._thickness_spin.setRange(1, 10)
        self._thickness_spin.setValue(self._style.thickness)
        form.addRow("Thickness:", self._thickness_spin)

        # Visible
        self._visible_cb = QCheckBox()
        self._visible_cb.setChecked(self._style.visible)
        form.addRow("Visible:", self._visible_cb)

        # Label
        self._label_edit = QLineEdit(self._style.label)
        form.addRow("Label:", self._label_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_style(self) -> SeriesStyle:
        """Return the edited SeriesStyle."""
        return SeriesStyle(
            color=self._color_btn.get_color(),
            line_style=self._line_combo.currentText(),
            marker=self._marker_combo.currentText(),
            thickness=self._thickness_spin.value(),
            visible=self._visible_cb.isChecked(),
            label=self._label_edit.text(),
        )
