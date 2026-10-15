# Build from the repository root with the locked Windows Python 3.12 environment:
# .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean packaging/windows.spec
from pathlib import Path
import sys

root = Path(SPECPATH).parent
resources = root / "src" / "gaussianreadpro" / "resources"

a = Analysis(
    [str(root / "tools" / "run_app.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(resources), "gaussianreadpro/resources"),
           (str(root / "packaging" / "README-Windows.txt"), "."),
           (str(root / "packaging" / "Launch-GaussianReadPro-compat.cmd"), ".")],
    hiddenimports=[
        "gaussianreadpro.services.static_plot_worker",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtSvg",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
    ],
    hookspath=[],
    # Static exports explicitly use FigureCanvasAgg; including QtAgg here would
    # drag unused QtQuick/QML and their plugins into the desktop bundle.
    hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
)

# A Poppler installation earlier on PATH can contribute an incompatible ICU DLL
# that prevents Qt6Core from loading. Let Windows resolve its own ICU APIs.
if sys.platform == "win32":
    a.binaries = [entry for entry in a.binaries
                  if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GaussianReadPro",
    icon=str(root / "packaging" / "GaussianReadPro.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GaussianReadPro",
)
