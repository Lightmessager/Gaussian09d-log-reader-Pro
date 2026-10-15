"""Collect successful source/frozen smoke evidence and reproducible package metrics."""
import hashlib
import json
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "s0"


def main():
    source = json.loads((OUT / "source-smoke.json").read_text(encoding="utf-8"))
    frozen = json.loads((OUT / "frozen-smoke.json").read_text(encoding="utf-8"))
    baseline = json.loads((OUT / "baseline.json").read_text(encoding="utf-8"))
    assert source["passed"] and frozen["passed"], "Both smoke runs must pass"
    assert not source["frozen"] and frozen["frozen"]
    assert source["plotly_sha256"] == frozen["plotly_sha256"]
    assert source["render_summary"]["values"] == frozen["render_summary"]["values"]
    original_hash = hashlib.sha256((ROOT / "Gaussian_LogReaderPro.py").read_bytes()).hexdigest()
    assert original_hash == baseline["original_sha256"], "Original reference was changed"
    package = ROOT / "dist" / "GaussianReadPro-S0"
    files = [p for p in package.rglob("*") if p.is_file()]
    required = {
        "executable": package / "GaussianReadPro-S0.exe",
        "qt_webengine_process": package / "_internal" / "PySide6" / "QtWebEngineProcess.exe",
        "local_plotly": package / "_internal" / "gaussianreadpro" / "resources" / "plot" / "vendor" / "plotly.min.js",
        "local_page": package / "_internal" / "gaussianreadpro" / "resources" / "plot" / "index.html",
    }
    assert all(p.is_file() for p in required.values()), required
    assert not (package / "_internal" / "icuuc.dll").exists(), "Foreign ICU must not shadow Windows ICU"
    summary = {"stage": "S0", "windows_feasibility": "passed", "host": platform.platform(),
               "original_sha256": original_hash, "synthetic_fixture_count": len(baseline["cases"]),
               "source_checks": source["checks"], "frozen_checks": frozen["checks"],
               "package_file_count": len(files), "package_bytes": sum(p.stat().st_size for p in files),
               "required_assets": {k: str(v.relative_to(ROOT)) for k, v in required.items()},
               "windows_icu_source": "OS library; unrelated host ICU excluded",
               "pending": ["Real Gaussian logs and Link1 boundary calibration in S1",
                           "macOS and Linux native build/smoke tests",
                           "Windows clean-machine and installed-product tests in S9",
                           "Final application UI, 3D profiles and project storage in later stages"]}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
