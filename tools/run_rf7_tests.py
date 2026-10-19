"""RF7 full regression runner with the documented host affinity and a log."""
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"src"),str(ROOT/"tools")]
from diagnose_static_runtime import windows_affinity
m,_,select=windows_affinity();select(m["default"]&0xFFFFFF3F)
import pytest
if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr,"reconfigure"):sys.stderr.reconfigure(encoding="utf-8")
temporary=(ROOT/"artifacts/rf7"/("pytest-"+uuid4().hex[:10])).resolve()
assert temporary.is_relative_to((ROOT/"artifacts/rf7").resolve()) and not temporary.exists()
raise SystemExit(pytest.main([*(sys.argv[1:] or ["-q"]),"--basetemp",str(temporary)]))
