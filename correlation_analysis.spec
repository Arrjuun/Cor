# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Correlation Analysis — Linux target.

Build
-----
    pyinstaller correlation_analysis.spec --clean

Output: dist/CorrelationAnalysis/

Deployment layout
-----------------
The app locates the fembuckling Python environment and library via paths
relative to the executable (get_app_root() = sys.executable.parent).
Assemble the final bundle like this:

    <DeploymentRoot>/
      CorrelationAnalysis/          ← dist/CorrelationAnalysis/ (this build)
          CorrelationAnalysis       ← Linux executable
          correlation_analysis/    ← bundled data (QSS, vsg script, …)
          …
      Envs/
          env/                     ← ../Envs/env  relative to exe  ✓
      Buckling/
          fembuckling/             ← ../Buckling/fembuckling       ✓

The Envs/ and Buckling/ folders are NOT bundled here — copy them manually.
If your layout differs, update _PYTHON_ENV_REL / _FEMBUCKLING_REL in
    correlation_analysis/views/buckling_export_dialog.py
before building.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ---------------------------------------------------------------------------
# Collect data files from packages that ship non-Python assets
# ---------------------------------------------------------------------------
qt_material_datas = collect_data_files("qt_material")
bokeh_datas       = collect_data_files("bokeh")
pyqtgraph_datas   = collect_data_files("pyqtgraph")

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        # ── App resources ──────────────────────────────────────────────────
        # QSS stylesheet and icons
        (
            "correlation_analysis/resources",
            "correlation_analysis/resources",
        ),
        # VSG extraction script is passed to `abaqus python <path>` as a
        # subprocess argument — it must exist as a real file on disk.
        # --onedir keeps data files next to the exe, so the path is stable.
        (
            "correlation_analysis/vsg_extraction/vsg_extraction.py",
            "correlation_analysis/vsg_extraction",
        ),
        # ── Third-party data assets ────────────────────────────────────────
        *qt_material_datas,   # theme XML files, icons
        *bokeh_datas,         # templates, static JS/CSS
        *pyqtgraph_datas,     # example data, UI resources
    ],
    hiddenimports=[
        # PySide6 — collect_submodules covers most, but list critical ones
        # explicitly so they are never missed if hooks change
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtPrintSupport",
        "PySide6.QtSvg",
        "PySide6.QtOpenGL",
        # pyqtgraph pulls in many sub-packages dynamically
        *collect_submodules("pyqtgraph"),
        # bokeh uses dynamic imports for renderers, models, etc.
        *collect_submodules("bokeh"),
        # qt_material
        "qt_material",
        # stdlib / data stack (usually auto-detected but listed for safety)
        "pandas",
        "pandas._libs.tslibs.np_datetime",
        "pandas._libs.tslibs.nattype",
        "pandas._libs.tslibs.timedeltas",
        "numpy",
        "numpy.core._multiarray_umath",
        # graphlib is used by the formula engine
        "graphlib",
    ],
    hookspath=[],
    hooksconfig={
        "gi": {"module-versions": {}},  # suppress GObject warnings if present
    },
    runtime_hooks=[],
    excludes=[
        # Exclude heavy packages not used by this app
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# Executable
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # binaries go into COLLECT, not the exe itself
    name="CorrelationAnalysis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX is unreliable with PySide6 on Linux
    console=False,           # no terminal window (pure GUI)
    # Set console=True temporarily if you need to see startup errors
)

# ---------------------------------------------------------------------------
# Collection (--onedir layout)
# ---------------------------------------------------------------------------
# --onedir is required: it places vsg_extraction.py as a real file next to
# the exe so that `abaqus python <path>` receives a valid filesystem path.
# --onefile would extract it to a temp sys._MEIPASS directory instead.
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CorrelationAnalysis",   # → dist/CorrelationAnalysis/
)
