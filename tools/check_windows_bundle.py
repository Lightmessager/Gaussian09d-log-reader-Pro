"""Smoke-test the built Windows onedir folder and its bundled render paths."""
import ctypes
from ctypes import wintypes
import argparse
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist" / "GaussianReaderPro"
EXE = BUNDLE / "GaussianReaderPro.exe"
MASK = 0xFFFFFF3F


def set_affinity():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetProcessAffinityMask.restype = ctypes.c_int
    if not kernel.SetProcessAffinityMask(kernel.GetCurrentProcess(), MASK):
        raise ctypes.WinError(ctypes.get_last_error())


def main():
    if os.name != "nt":
        raise SystemExit("Run this smoke test on Windows.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "windows-smoke")
    args = parser.parse_args()
    set_affinity()
    internal = BUNDLE / "_internal"
    required = [EXE, BUNDLE / "README-Windows.txt", BUNDLE / "Launch-GaussianReaderPro-compat.cmd",
                BUNDLE / "build-manifest.json", internal / "PySide6" / "QtWebEngineProcess.exe",
                internal / "gaussianreadpro" / "resources" / "plot" / "profile.html",
                internal / "gaussianreadpro" / "resources" / "plot" / "profile.js",
                internal / "gaussianreadpro" / "resources" / "plot" / "scene3d.js",
                internal / "gaussianreadpro" / "resources" / "plot" / "vendor" / "three.module.min.js",
                internal / "gaussianreadpro" / "resources" / "plot" / "vendor" / "THREE-LICENSE.txt",
                internal / "gaussianreadpro" / "resources" / "icons" / "app-icon.png",
                internal / "gaussianreadpro" / "resources" / "locales" / "zh_CN.json",
                internal / "matplotlib" / "mpl-data" / "fonts" / "ttf" / "DejaVuSans.ttf"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise AssertionError(f"Missing bundled files: {missing}")
    if (internal / "PySide6" / "icuuc.dll").exists():
        raise AssertionError("Incompatible external ICU DLL was bundled")

    scratch = args.out.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    payload = {
        "paths": [{"visible": True, "points": [{"x": 0, "value": 0.0, "valid": True, "selected": False,
            "role": "reactant", "label_offset": [0, 20], "label_short": "R", "value_label": "0.000"}],
            "curve_runs": [[[0, 0], [1, 1]]], "color": "#9174D0", "label": "Smoke", "reference": "@{R}", "id": "p"}],
        "mode": "relative", "text": {"reference": "Reference", "guide": "Bundle smoke", "step": "Step"},
        "energy_label": "Relative energy", "unit_label": "kcal/mol", "ticks": [0], "tick_labels": ["R"],
        "viewport": {}, "default_y_range": [-1, 2], "warnings": []}
    request = scratch / "render-request.json"
    image = scratch / "render-smoke.png"
    request.write_text(json.dumps(payload), encoding="utf-8")
    process = subprocess.run([str(EXE), "--render-static", str(request), str(image)],
                             cwd=BUNDLE, capture_output=True, timeout=120)
    result_file = Path(str(request) + ".result.json")
    if process.returncode or not image.is_file() or not result_file.is_file():
        raise RuntimeError(f"Frozen Agg renderer failed: {process.returncode}: {process.stderr[-1500:]!r}")
    renderer = json.loads(result_file.read_text(encoding="utf-8"))
    if renderer.get("backend") != "Agg" or not renderer.get("python_isolated"):
        raise AssertionError(f"Unexpected frozen renderer metadata: {renderer}")

    vector_results = {}
    for format in ("svg", "pdf"):
        vector = scratch / ("render-smoke." + format)
        attempt = subprocess.run([str(EXE), "--render-static", str(request), str(vector)],
                                 cwd=BUNDLE, capture_output=True, timeout=120)
        metadata = json.loads(result_file.read_text(encoding="utf-8"))
        if attempt.returncode or not vector.is_file() or vector.stat().st_size == 0:
            raise RuntimeError(f"Frozen {format} renderer failed: {attempt.returncode}; {metadata}")
        vector_results[format] = {**metadata, "bytes": vector.stat().st_size}

    help_result = subprocess.run([str(EXE), "--help"], cwd=BUNDLE, capture_output=True, timeout=30)
    if help_result.returncode:
        raise RuntimeError(f"Frozen Qt/CLI bootstrap failed: {help_result.returncode}")
    version_result = subprocess.run([str(EXE), "--version"], cwd=BUNDLE, capture_output=True, timeout=30)
    version_text = (version_result.stdout + version_result.stderr).decode(errors="replace").strip()
    if version_result.returncode or version_text != "GaussianReaderPro 2.0.0":
        raise RuntimeError(f"Frozen version command mismatch: {version_result.returncode}: {version_text!r}")

    webengine_report = scratch / "webengine-smoke.json"
    webengine = subprocess.run([str(EXE), "--webengine-smoke-report", str(webengine_report)],
                               cwd=BUNDLE, capture_output=True, timeout=60)
    if webengine.returncode or not webengine_report.is_file():
        raise RuntimeError(f"Frozen Qt WebEngine smoke failed: {webengine.returncode}: {webengine.stderr[-1500:]!r}")
    page = json.loads(webengine_report.read_text(encoding="utf-8"))
    if not page.get("passed") or page.get("protocol") != 2 or not page.get("plotly"):
        raise AssertionError(f"Bundled chart page did not complete its bridge handshake: {page}")
    result = {"passed": True, "bundle": str(BUNDLE), "version": version_text, "webengine": page,
                      "renderer": renderer, "vectors": vector_results, "affinity": hex(MASK),
                      "static_render_bytes": image.stat().st_size,
                      "artifacts": {"png": str(image), "svg": str(scratch / "render-smoke.svg"),
                                    "pdf": str(scratch / "render-smoke.pdf"),
                                    "webengine": str(webengine_report)}}
    (scratch / "bundle-smoke.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
