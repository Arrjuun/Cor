"""Tab-based graph view containing LoadStep and Ratio graphs."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTabBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .loadstep_graph import LoadStepGraphWidget
from .ratio_graph import RatioGraphWidget


class GraphTabContent(QWidget):
    """
    Content of a single tab: one or more LoadStep graphs and an optional Ratio graph.
    """

    loadstep_graph_added = Signal(object)   # LoadStepGraphWidget
    ratio_graph_added = Signal(object)      # RatioGraphWidget

    def __init__(self, tab_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.tab_id = tab_id
        self._loadstep_graphs: list[LoadStepGraphWidget] = []
        self._ratio_graphs: list[RatioGraphWidget] = []
        self._all_graphs: list[QWidget] = []
        self._num_columns: int = 1
        self._build_ui()

    def _build_ui(self) -> None:
        self._layout = QVBoxLayout(self)
        self._layout.setSpacing(4)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._inner_layout = QVBoxLayout(container)
        self._inner_layout.setSpacing(8)
        scroll.setWidget(container)
        self._layout.addWidget(scroll)

        # Toolbar: add buttons + columns spinbox
        btn_layout = QHBoxLayout()
        add_ls = QPushButton("+ LoadStep Graph")
        add_ratio = QPushButton("+ Ratio Graph")
        add_ls.setCheckable(False)
        add_ratio.setCheckable(False)
        add_ls.clicked.connect(self.add_loadstep_graph)
        add_ratio.clicked.connect(self.add_ratio_graph)
        btn_layout.addWidget(add_ls)
        btn_layout.addWidget(add_ratio)
        btn_layout.addStretch()
        btn_layout.addWidget(QLabel("Columns:"))
        self._col_spin = QSpinBox()
        self._col_spin.setRange(1, 6)
        self._col_spin.setValue(1)
        self._col_spin.setFixedWidth(55)
        self._col_spin.setToolTip("Number of graph columns in this tab")
        self._col_spin.valueChanged.connect(self._on_columns_changed)
        btn_layout.addWidget(self._col_spin)
        self._inner_layout.addLayout(btn_layout)

        # Grid container for graphs
        self._graphs_container = QWidget()
        self._graph_layout = QGridLayout(self._graphs_container)
        self._graph_layout.setSpacing(8)
        self._inner_layout.addWidget(self._graphs_container)
        self._inner_layout.addStretch()

        # Default graphs
        self.add_loadstep_graph()
        self.add_ratio_graph()

    def add_loadstep_graph(self, title: str = "") -> LoadStepGraphWidget:
        idx = len(self._loadstep_graphs) + 1
        graph = LoadStepGraphWidget(title or f"LoadStep vs Strain {idx}", self)
        graph.setMinimumHeight(350)
        self._loadstep_graphs.append(graph)
        self._all_graphs.append(graph)
        graph.remove_requested.connect(lambda g=graph: self._remove_graph(g))
        self._relayout_graphs()
        self.loadstep_graph_added.emit(graph)
        return graph

    def add_ratio_graph(self, title: str = "") -> RatioGraphWidget:
        idx = len(self._ratio_graphs) + 1
        graph = RatioGraphWidget(title or f"Ratio Graph {idx}", self)
        graph.setMinimumHeight(350)
        self._ratio_graphs.append(graph)
        self._all_graphs.append(graph)
        graph.remove_requested.connect(lambda g=graph: self._remove_graph(g))
        self._relayout_graphs()
        self.ratio_graph_added.emit(graph)
        return graph

    def _remove_graph(self, graph: QWidget) -> None:
        """Remove a single graph widget from this tab."""
        if graph not in self._all_graphs:
            return
        self._graph_layout.removeWidget(graph)
        self._all_graphs.remove(graph)
        if graph in self._loadstep_graphs:
            self._loadstep_graphs.remove(graph)
        elif graph in self._ratio_graphs:
            self._ratio_graphs.remove(graph)
        graph.hide()
        graph.deleteLater()
        self._relayout_graphs()

    def _relayout_graphs(self) -> None:
        """Re-place all graphs in the grid according to current column count."""
        for g in self._all_graphs:
            self._graph_layout.removeWidget(g)
        for i, g in enumerate(self._all_graphs):
            row = i // self._num_columns
            col = i % self._num_columns
            self._graph_layout.addWidget(g, row, col)

    def _on_columns_changed(self, value: int) -> None:
        self._num_columns = value
        self._relayout_graphs()

    def set_columns(self, n: int) -> None:
        """Set number of columns programmatically (e.g. on session restore)."""
        self._num_columns = max(1, min(6, n))
        self._col_spin.setValue(self._num_columns)
        self._relayout_graphs()

    def get_loadstep_graphs(self) -> list[LoadStepGraphWidget]:
        return list(self._loadstep_graphs)

    def get_ratio_graphs(self) -> list[RatioGraphWidget]:
        return list(self._ratio_graphs)

    def clear_graphs(self) -> None:
        """Remove all graph widgets from this tab (used before restoring from config)."""
        for g in list(self._all_graphs):
            self._graph_layout.removeWidget(g)
            g.deleteLater()
        self._loadstep_graphs.clear()
        self._ratio_graphs.clear()
        self._all_graphs.clear()

    def to_config(self) -> dict:
        return {
            "tab_id": self.tab_id,
            "num_columns": self._num_columns,
            "loadstep_graphs": [g.to_config() for g in self._loadstep_graphs],
            "ratio_graphs": [g.to_config() for g in self._ratio_graphs],
        }


class TabGraphView(QWidget):
    """
    QTabWidget-based container for graph tabs.
    Includes a '+' button to add new tabs.
    """

    tab_added = Signal(str)     # tab_id
    tab_removed = Signal(str)   # tab_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._tab_counter = 0
        self._tabs: dict[str, GraphTabContent] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        self._tab_widget.tabBarDoubleClicked.connect(self._rename_tab)

        # Corner '+' button
        add_btn = QToolButton()
        add_btn.setText("+")
        add_btn.setToolTip("Add new tab")
        add_btn.setCheckable(False)
        add_btn.clicked.connect(self.add_tab)
        self._tab_widget.setCornerWidget(add_btn, Qt.Corner.TopRightCorner)

        layout.addWidget(self._tab_widget)

        # Create first default tab
        self.add_tab("Analysis 1")

    def add_tab(self, name: str = "") -> GraphTabContent:
        self._tab_counter += 1
        tab_id = f"tab_{self._tab_counter}"
        if not name:
            name = f"Analysis {self._tab_counter}"

        content = GraphTabContent(tab_id)
        self._tabs[tab_id] = content

        idx = self._tab_widget.addTab(content, name)
        self._tab_widget.setCurrentIndex(idx)
        self.tab_added.emit(tab_id)
        return content

    def _close_tab(self, index: int) -> None:
        if self._tab_widget.count() <= 1:
            # Don't close the last tab — just clear it or ignore
            return
        widget = self._tab_widget.widget(index)
        tab_id = None
        for tid, content in self._tabs.items():
            if content is widget:
                tab_id = tid
                break
        self._tab_widget.removeTab(index)
        if tab_id:
            del self._tabs[tab_id]
            self.tab_removed.emit(tab_id)

    def _rename_tab(self, index: int) -> None:
        current = self._tab_widget.tabText(index)
        name, ok = QInputDialog.getText(
            self, "Rename Tab", "Tab name:", QLineEdit.EchoMode.Normal, current
        )
        if ok and name.strip():
            self._tab_widget.setTabText(index, name.strip())

    def current_tab(self) -> Optional[GraphTabContent]:
        idx = self._tab_widget.currentIndex()
        widget = self._tab_widget.widget(idx)
        if isinstance(widget, GraphTabContent):
            return widget
        return None

    def get_tab(self, tab_id: str) -> Optional[GraphTabContent]:
        return self._tabs.get(tab_id)

    def all_tabs(self) -> list[GraphTabContent]:
        return list(self._tabs.values())

    def get_tab_name(self, tab_id: str) -> str:
        """Return the display name of a tab by its ID."""
        content = self._tabs.get(tab_id)
        if content is None:
            return tab_id
        for i in range(self._tab_widget.count()):
            if self._tab_widget.widget(i) is content:
                return self._tab_widget.tabText(i)
        return tab_id

    def get_all_loadstep_graphs(self) -> list[LoadStepGraphWidget]:
        graphs = []
        for tab in self._tabs.values():
            graphs.extend(tab.get_loadstep_graphs())
        return graphs

    def clear_all_tabs(self) -> None:
        """Remove every tab (used before restoring a session)."""
        while self._tab_widget.count():
            self._tab_widget.removeTab(0)
        self._tabs.clear()
        self._tab_counter = 0

    def to_config(self) -> list[dict]:
        result = []
        for tab_id, tab in self._tabs.items():
            cfg = tab.to_config()
            cfg["tab_name"] = self.get_tab_name(tab_id)
            result.append(cfg)
        return result
