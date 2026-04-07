"""Application-wide logging configuration."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(log_dir: Path | None = None, level: int = logging.DEBUG) -> Path:
    """
    Configure rotating file logging for the application.

    Args:
        log_dir: Directory to write log file. Defaults to the project root.
        level: Root log level (DEBUG by default so all detail is captured).

    Returns:
        Path to the log file (useful to show the user where logs are stored).
    """
    if log_dir is None:
        # Place log in the user's current working directory so it follows
        # wherever the app is invoked from (matches the Buckling_Exports dir).
        log_dir = Path.cwd()

    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "correlation_analysis.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid adding duplicate handlers if called more than once
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root_logger.handlers):
        return log_file

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file: 5 MB per file, keep 3 backups
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Also show WARNING+ in the console for immediate visibility during development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    return log_file
