"""Compact build/test status without depending on shell profile initialization."""
from datetime import datetime
from pathlib import Path
import sys
if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
root=Path(__file__).resolve().parents[1]
print(datetime.now().isoformat(timespec="seconds"))
for name in (sys.argv[1:] or ["build-final.log","pytest-final.log"]):
    path=root/"artifacts/rf7"/name
    print(name)
    if path.exists():
        print("\n".join(path.read_text(encoding="utf-8",errors="replace").splitlines()[-8:]))
    else:print("not created")
