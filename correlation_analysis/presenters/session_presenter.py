"""Session save/load presenter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox

from ..models.data_model import DataModel
from ..models.sensor_mapping import SensorMapping
from ..models.session_model import SessionModel

if TYPE_CHECKING:
    from ..views.main_window import MainWindow
    from .analysis_presenter import AnalysisPresenter


class SessionPresenter:
    """Coordinates session save and load operations."""

    def __init__(
        self,
        window: "MainWindow",
        session_model: SessionModel,
        data_model: DataModel,
        mapping: SensorMapping,
        analysis_presenter: "AnalysisPresenter",
    ) -> None:
        self._window = window
        self._session = session_model
        self._data = data_model
        self._mapping = mapping
        self._analysis = analysis_presenter
        self._connect_signals()

    def _connect_signals(self) -> None:
        self._window.save_session_requested.connect(self.save_session)
        self._window.load_session_requested.connect(self.load_session)
        self._window.new_session_requested.connect(self.new_session)

    # ------------------------------------------------------------------ #
    # New session                                                          #
    # ------------------------------------------------------------------ #

    def new_session(self) -> None:
        reply = QMessageBox.question(
            self._window,
            "New Session",
            "Start a new session? All unsaved data will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Clear models
        self._data.clear()
        self._mapping.clear()

        # Reset views
        self._window.analysis_view.clear_tables()
        tab_view = self._window.analysis_view.get_tab_view()
        tab_view.clear_all_tabs()
        tab_view.add_tab("Analysis 1")   # restore default tab
        self._window.import_view.reset()

        # Unlock import navigation and switch back
        self._window.unlock_import_view()
        self._window.show_view(0)  # VIEW_IMPORT

    # ------------------------------------------------------------------ #
    # Save                                                                 #
    # ------------------------------------------------------------------ #

    def save_session(self, filepath: str) -> None:
        try:
            tab_view = self._window.analysis_view.get_tab_view()
            state = {
                "sources": self._data.to_dict(),
                "mapping": self._mapping.to_dict(),
                "tabs": tab_view.to_config(),
            }
            self._session.save(filepath, state)
            self._window.show_status(f"Session saved: {Path(filepath).name}")
        except Exception as exc:
            self._window.show_error(f"Failed to save session:\n{exc}")

    # ------------------------------------------------------------------ #
    # Load                                                                 #
    # ------------------------------------------------------------------ #

    def load_session(self, filepath: str) -> None:
        try:
            state = self._session.load(filepath)
        except FileNotFoundError:
            self._window.show_error(f"File not found: {filepath}")
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self._window.show_error(f"Invalid session file:\n{exc}")
            return

        try:
            # Clear any previously loaded state before populating from the new session
            self._window.analysis_view.clear_tables()
            self._data.from_dict(state.get("sources", {}))
            self._mapping.load_from_dict(state.get("mapping", {}))
            self._analysis.initialize_from_model()
            # Restore graph tabs — must come after initialize_from_model so that
            # GraphDataModel can look up series data for each saved sensor.
            self._analysis.graph_presenter.restore_graphs_from_config(
                state.get("tabs", [])
            )
            self._window.show_view(1)  # switch to analysis view
            self._window.show_status(
                f"Session loaded: {Path(filepath).name}"
            )
        except Exception as exc:
            import traceback
            self._window.show_error(
                f"Error restoring session:\n{exc}\n\n{traceback.format_exc()}"
            )
