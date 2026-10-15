# Build from repository root: python -m PyInstaller --noconfirm packaging/s0.spec
from pathlib import Path
import sys

root = Path(SPECPATH).parent
assets = root / "src" / "gaussianreadpro" / "resources" / "plot"
a = Analysis(
    [str(root / "tools" / "run_s0.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(assets), "gaussianreadpro/resources/plot")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "plotly"],
    noarchive=False,
)
# Windows Qt uses the OS ICU API. The host's Poppler runtime adds a different
# ICU to PATH; automatic discovery bundled its versioned exports instead.
# Let the Windows loader resolve the OS ICU rather than ship unrelated DLLs.
if sys.platform == "win32":
    a.binaries = [entry for entry in a.binaries
                  if Path(entry[0]).name.lower() not in {"icuuc.dll", "icudt78.dll"}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GaussianReadPro-S0",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="GaussianReadPro-S0")
