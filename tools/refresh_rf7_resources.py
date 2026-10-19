"""Refresh data-only RF7 resources, then recreate the audited portable archive."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/"src/gaussianreadpro/resources"
destination=ROOT/"dist/GaussianReaderPro/_internal/gaussianreadpro/resources"
assert destination.is_dir() and source.is_dir()
shutil.copytree(source,destination,dirs_exist_ok=True)
raise SystemExit(subprocess.call([sys.executable,str(ROOT/"tools/build_windows.py"),"--package-only"],cwd=ROOT))
