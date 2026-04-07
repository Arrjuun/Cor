"""Application path utilities.

Provides ``get_app_root()`` — the single source of truth for locating bundled
resources (Python environment, fembuckling library, vsg extraction script).

Rule of thumb
-------------
* **Bundled resources** (static files shipped with the app): resolve via
  ``get_app_root()``.  Their locations are fixed relative to the app
  installation directory and do not depend on where the user runs the app from.
* **Output / temporary files** (logs, Buckling_Exports, results): use
  ``Path.cwd()`` so they always land in the user's current working directory.
"""
from __future__ import annotations

import sys
from pathlib import Path


def get_app_root() -> Path:
    """Return the application root directory.

    * **Frozen** (PyInstaller / similar): returns the directory that contains
      the executable (``sys.executable``).
    * **Source** mode (``python main.py``): returns the directory that contains
      ``main.py``, derived from this file's location
      (``<app_root>/correlation_analysis/utils/paths.py``).

    The returned path is always absolute and resolved, so it is independent of
    the current working directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Running from source: go up utils/ -> correlation_analysis/ -> app root
    return Path(__file__).resolve().parents[2]
