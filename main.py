"""Application entry point."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

try:
    from qt_material import apply_stylesheet
    _HAS_QT_MATERIAL = True
except ImportError:
    _HAS_QT_MATERIAL = False

from correlation_analysis.utils.logging_config import setup_logging
from correlation_analysis.models.data_model import DataModel
from correlation_analysis.models.sensor_mapping import SensorMapping
from correlation_analysis.models.formula_engine import FormulaEngine
from correlation_analysis.models.session_model import SessionModel
from correlation_analysis.models.graph_data_model import GraphDataModel
from correlation_analysis.views.main_window import MainWindow, VIEW_ANALYSIS
from correlation_analysis.presenters.import_presenter import ImportPresenter
from correlation_analysis.presenters.analysis_presenter import AnalysisPresenter
from correlation_analysis.presenters.session_presenter import SessionPresenter
from correlation_analysis.presenters.export_presenter import ExportPresenter


def main() -> None:
    log_file = setup_logging()

    log = logging.getLogger(__name__)
    log.info("=" * 60)
    log.info("Correlation Analysis starting. Log file: %s", log_file)

    app = QApplication(sys.argv)
    app.setApplicationName("Correlation Analysis")
    app.setOrganizationName("Airbus")

    # Apply qt-material theme (must be before window creation)
    if _HAS_QT_MATERIAL:
        extra = {
            "button_color": "#ffffff",
            "button_text_color": "#ffffff",
        }
        apply_stylesheet(app, theme="light_blue.xml", extra=extra)

    # Load additional QSS overrides
    qss_path = Path(__file__).parent / "correlation_analysis" / "resources" / "styles" / "default.qss"
    if qss_path.exists():
        current_style = app.styleSheet()
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(current_style + "\n" + f.read())

    # ------------------------------------------------------------------ #
    # Construct models                                                     #
    # ------------------------------------------------------------------ #
    data_model = DataModel()
    mapping = SensorMapping()
    formula_engine = FormulaEngine()
    graph_data_model = GraphDataModel(data_model, mapping)
    session_model = SessionModel()

    # ------------------------------------------------------------------ #
    # Construct views via MainWindow                                       #
    # ------------------------------------------------------------------ #
    window = MainWindow()

    # ------------------------------------------------------------------ #
    # Wire presenters                                                      #
    # ------------------------------------------------------------------ #
    analysis_presenter = AnalysisPresenter(
        window.analysis_view,
        data_model,
        mapping,
        formula_engine,
        graph_data_model,
    )

    import_presenter = ImportPresenter(
        window.import_view,
        data_model,
        mapping,
    )

    # Navigate to analysis view on proceed (one-way: import view locked afterwards)
    window.import_view.proceed_requested.connect(
        lambda: (
            analysis_presenter.initialize_from_model(),
            window.lock_import_view(),
            window.show_view(VIEW_ANALYSIS),
        )
    )

    session_presenter = SessionPresenter(
        window,
        session_model,
        data_model,
        mapping,
        analysis_presenter,
    )

    export_presenter = ExportPresenter(window, analysis_presenter)

    # ------------------------------------------------------------------ #
    # Show                                                                 #
    # ------------------------------------------------------------------ #
    window.show()
    log.info("Application window shown. Entering event loop.")
    exit_code = app.exec()
    log.info("Application exited with code %d.", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
