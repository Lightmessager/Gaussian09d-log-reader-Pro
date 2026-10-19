"""Launch the frozen 2.0.0 app and click its default-home rename/editor actions."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "dist" / "GaussianReaderPro" / "GaussianReaderPro.exe"
MASK = 0xFFFFFF3F


def _set_affinity():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetProcessAffinityMask.restype = ctypes.c_int
    if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), MASK):
        raise ctypes.WinError(ctypes.get_last_error())


def main():
    if os.name != "nt":
        raise SystemExit("Run frozen desktop acceptance on Windows.")
    _set_affinity()
    if not EXE.is_file():
        raise SystemExit(f"Build the 2.0.0 Windows package first: {EXE}")

    run = ROOT / "artifacts" / "ux-v2" / "u8" / uuid4().hex
    run.mkdir(parents=True, exist_ok=False)
    config = run / "config.json"
    report_path = run / "frozen-ui-validation.json"
    config.write_text(json.dumps({"out": str(run)}, indent=2), encoding="utf-8")
    env = os.environ.copy()
    env["QT_SCALE_FACTOR"] = "0.8"
    env.pop("QT_QPA_PLATFORM", None)
    result = subprocess.run([str(EXE), "--validate-ux-v2-u8", str(config)],
                            cwd=ROOT, env=env, capture_output=True, timeout=180)
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    report["exit_code"] = result.returncode
    report["stdout"] = result.stdout.decode(errors="replace")[-2000:]
    report["stderr"] = result.stderr.decode(errors="replace")[-3000:]
    report["passed"] = bool(result.returncode == 0 and report.get("passed"))
    (run / "frozen-ui-validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "exit_code": result.returncode,
                      "run": str(run), "report": str(run / "frozen-ui-validation.json"),
                      "checks": report.get("checks", {}), "error": report.get("error")},
                     ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
