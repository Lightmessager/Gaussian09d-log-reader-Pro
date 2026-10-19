"""Build the Windows onedir package with this machine's process-local workaround."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile


if os.name != "nt":
    raise SystemExit("Build the Windows package on Windows.")

# The host has a known default-scheduler native crash. Match the repository's
# Windows validation mask for this build process only; no OS setting is changed.
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
kernel.GetCurrentProcess.restype = ctypes.c_void_p
kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
kernel.SetProcessAffinityMask.restype = ctypes.c_int
if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), 0xFFFFFF3F):
    raise ctypes.WinError(ctypes.get_last_error())

from PyInstaller.__main__ import run  # noqa: E402
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from gaussianreadpro import APP_NAME, VERSION_LABEL, __version__

if sys.argv[1:] != ["--package-only"]:
    sys.argv = [sys.argv[0], "--noconfirm", "--clean", "packaging/windows.spec"]
    run()

# PyInstaller 6 keeps runtime data under _internal. Put the human-facing guide
# and optional host workaround alongside the EXE so users can find them.
bundle = root / "dist" / APP_NAME
for name in ("README-Windows.txt", "Launch-GaussianReaderPro-compat.cmd"):
    shutil.copy2(root / "packaging" / name, bundle / name)

exe = bundle / (APP_NAME + ".exe")
manifest = {
    "application": APP_NAME,
    "version": __version__,
    "version_label": VERSION_LABEL,
    "platform": "Windows x64",
    "format": "PyInstaller onedir portable",
    "python": sys.version.split()[0],
    "sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
    "executable_bytes": exe.stat().st_size,
    "resources": {p.relative_to(bundle / "_internal/gaussianreadpro/resources").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (bundle / "_internal/gaussianreadpro/resources").rglob("*") if p.is_file()},
}
(bundle / "build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

release = root / "artifacts" / "releases"
release.mkdir(parents=True, exist_ok=True)
archive = release / (APP_NAME + "-" + VERSION_LABEL + "-Windows-x64-portable.zip")
if archive.exists():
    archive.unlink()
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as output:
    for path in bundle.rglob("*"):
        if path.is_file():
            output.write(path, path.relative_to(bundle.parent))
print(f"Portable archive: {archive} ({archive.stat().st_size:,} bytes)")
