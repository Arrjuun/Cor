"""Main application window."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QWidget,
)

from .import_view import ImportView
from .analysis_view import AnalysisView
from .vsg_extraction_dialog import VsgExtractionDialog

VIEW_IMPORT = 0
VIEW_ANALYSIS = 1


class MainWindow(QMainWindow):
    """
    Application shell. Switches between ImportView and AnalysisView.

    Signals:
        save_session_requested(filepath)
        load_session_requested(filepath)
        export_html_requested(filepath)
    """

    save_session_requested = Signal(str)
    load_session_requested = Signal(str)
    export_html_requested = Signal(str)
    export_csv_requested = Signal(str)
    new_session_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Correlation Analysis")
        self.resize(1400, 900)
        self._build_ui()
        self._build_menu()

    def _build_ui(self) -> None:
        self._stack = QStackedWidget()
        self._import_view = ImportView()
        self._analysis_view = AnalysisView()
        self._stack.addWidget(self._import_view)   # index 0
        self._stack.addWidget(self._analysis_view) # index 1
        self.setCentralWidget(self._stack)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        self._build_toolbar()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Analysis Tools")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._buckling_action = QAction("Buckling Analysis", self)
        self._buckling_action.setToolTip(
            "Open buckling analysis dialog (requires sensor mapping with Sensor Pair column)"
        )
        self._buckling_action.setVisible(False)   # shown only in Analysis view
        self._buckling_action.triggered.connect(
            self._analysis_view.buckling_requested.emit
        )
        toolbar.addAction(self._buckling_action)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("File")

        new_act = QAction("New Session", self)
        new_act.setShortcut(QKeySequence.StandardKey.New)
        new_act.triggered.connect(self.new_session_requested)
        file_menu.addAction(new_act)

        file_menu.addSeparator()

        open_act = QAction("Open Session…", self)
        open_act.setShortcut(QKeySequence.StandardKey.Open)
        open_act.triggered.connect(self._on_load_session)
        file_menu.addAction(open_act)

        save_act = QAction("Save Session…", self)
        save_act.setShortcut(QKeySequence.StandardKey.Save)
        save_act.triggered.connect(self._on_save_session)
        file_menu.addAction(save_act)

        file_menu.addSeparator()

        export_act = QAction("Export to HTML…", self)
        export_act.triggered.connect(self._on_export_html)
        file_menu.addAction(export_act)

        export_csv_act = QAction("Export to CSV…", self)
        export_csv_act.triggered.connect(self._on_export_csv)
        file_menu.addAction(export_csv_act)

        file_menu.addSeparator()

        vsg_act = QAction("VSG Extraction…", self)
        vsg_act.triggered.connect(self._on_vsg_extraction)
        file_menu.addAction(vsg_act)

        file_menu.addSeparator()

        quit_act = QAction("Exit", self)
        quit_act.setShortcut(QKeySequence.StandardKey.Quit)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        # View menu
        view_menu = menubar.addMenu("View")
        self._import_act = QAction("Switch to Import View", self)
        analysis_act = QAction("Switch to Analysis View", self)
        self._import_act.triggered.connect(lambda: self.show_view(VIEW_IMPORT))
        analysis_act.triggered.connect(lambda: self.show_view(VIEW_ANALYSIS))
        view_menu.addAction(self._import_act)
        view_menu.addAction(analysis_act)

        # Help menu
        help_menu = menubar.addMenu("Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._on_about)
        help_menu.addAction(about_act)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def import_view(self) -> ImportView:
        return self._import_view

    @property
    def analysis_view(self) -> AnalysisView:
        return self._analysis_view

    def show_view(self, index: int) -> None:
        if index == VIEW_IMPORT and getattr(self, "_import_locked", False):
            return
        self._stack.setCurrentIndex(index)
        self._buckling_action.setVisible(index == VIEW_ANALYSIS)

    def lock_import_view(self) -> None:
        """Prevent navigation back to the import view (called after proceeding)."""
        self._import_locked = True
        self._import_act.setEnabled(False)

    def unlock_import_view(self) -> None:
        """Re-enable navigation to the import view (called on new session)."""
        self._import_locked = False
        self._import_act.setEnabled(True)

    def show_status(self, message: str, timeout: int = 3000) -> None:
        self._status_bar.showMessage(message, timeout)

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message: str) -> None:
        QMessageBox.information(self, "Information", message)

    # ------------------------------------------------------------------ #
    # Menu handlers                                                        #
    # ------------------------------------------------------------------ #

    def _on_save_session(self) -> None:
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Session",
            filter="JSON Files (*.json)"
        )
        if filepath:
            if not filepath.endswith(".json"):
                filepath += ".json"
            self.save_session_requested.emit(filepath)

    def _on_load_session(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Open Session",
            filter="JSON Files (*.json)"
        )
        if filepath:
            self.load_session_requested.emit(filepath)

    def _on_export_html(self) -> None:
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export to HTML",
            filter="HTML Files (*.html)"
        )
        if filepath:
            if not filepath.endswith(".html"):
                filepath += ".html"
            self.export_html_requested.emit(filepath)

    def _on_export_csv(self) -> None:
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export to CSV",
            filter="CSV Files (*.csv)"
        )
        if filepath:
            if not filepath.endswith(".csv"):
                filepath += ".csv"
            self.export_csv_requested.emit(filepath)

    def _on_vsg_extraction(self) -> None:
        dlg = VsgExtractionDialog(self)
        dlg.exec()

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Correlation Analysis",
            "<b>Correlation Analysis v1.0</b><br><br>"
            "Sensor strain correlation tool.<br>"
            "Built with PySide6, pyqtgraph, and Bokeh.",
        )
