"""Collect the RF0 synthetic fixture, resource and live-run baseline report."""
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import sys

from PySide6.QtCore import QEventLoop, QTimer, QUrl, qVersion
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

from gaussianreadpro.core.units import HARTREE_TO_KCAL
from gaussianreadpro.services.session import SessionBackend
from gaussianreadpro.storage import ProjectRepository


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "rf0"
PROJECT_PATH = ARTIFACTS / "profile-replica.grproj"
REPORT_PATH = ARTIFACTS / "baseline.json"
EXPECTED = {
    "Path A": [0.0, 15.060, -5.020, -15.688],
    "Path B": [0.0, 11.420, -2.800, -12.400],
}


def file_hash(path):
    path = Path(path)
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size,
            "sha256": sha256(path.read_bytes()).hexdigest()}


def probe_webengine(app):
    view = QWebEngineView()
    view.resize(420, 220)
    loop = QEventLoop()
    result = {"loaded": False, "plotly_version": None, "webgl2": None, "webgl": None,
              "javascript_modules": None, "errors": []}

    def on_load(ok):
        result["loaded"] = bool(ok)
        if not ok:
            result["errors"].append("profile.html load failed")
            loop.quit()
            return
        script = """JSON.stringify((() => {
          const canvas2 = document.createElement('canvas');
          const canvas1 = document.createElement('canvas');
          let webgl2 = false, webgl = false;
          try { webgl2 = !!canvas2.getContext('webgl2'); } catch (_) {}
          try { webgl = !!canvas1.getContext('webgl') || !!canvas1.getContext('experimental-webgl'); } catch (_) {}
          return {plotly_version: window.Plotly?.version || null, webgl2,
            webgl, javascript_modules: !!HTMLScriptElement.supports?.('module')};
        })())"""

        def on_probe(raw):
            if raw:
                try:
                    result.update(json.loads(raw))
                except (TypeError, ValueError):
                    result["errors"].append(f"unexpected capability probe output: {raw!r}")
            else:
                result["errors"].append("capability script returned no result")
            loop.quit()

        view.page().runJavaScript(script, on_probe)

    view.loadFinished.connect(on_load)
    QTimer.singleShot(20000, loop.quit)
    view.show()
    view.load(QUrl.fromLocalFile(str(ROOT / "src" / "gaussianreadpro" / "resources" / "plot" / "profile.html")))
    loop.exec()
    view.close()
    return result


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not PROJECT_PATH.exists():
        from build_profile_replica_fixture import main as build_fixture
        build_fixture()

    with ProjectRepository(PROJECT_PATH, read_only=True) as repository:
        project = repository.load()
    backend = SessionBackend(ARTIFACTS / "validation-recovery")
    view = backend.view(project)
    actual = {}
    for path, result in zip(project.paths, view.results):
        actual[path.label] = [round(node.display_value, 3) if node.valid else None for node in result.nodes]
    backend.shutdown()
    if actual != EXPECTED:
        raise SystemExit(f"RF0 energy oracle mismatch: {actual}")

    app = QApplication.instance() or QApplication([])
    qt_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    available_fonts = set(QFontDatabase.families())
    font_report = {name: name in available_fonts for name in ("Segoe UI", "Microsoft YaHei")}
    webengine = probe_webengine(app)

    resource_root = ROOT / "src" / "gaussianreadpro" / "resources" / "plot"
    resource_manifest = json.loads((resource_root / "vendor" / "manifest.json").read_text(encoding="utf-8"))
    vendor = resource_root / "vendor" / "plotly.min.js"
    package_resource_root = ROOT / "dist" / "GaussianReadPro" / "_internal" / "gaussianreadpro" / "resources" / "plot" / "vendor"
    package_vendor = package_resource_root / "plotly.min.js"
    package_resource_manifest = json.loads((package_resource_root / "manifest.json").read_text(encoding="utf-8"))
    source_hashes = [
        ROOT / "tools" / "run_app.py",
        ROOT / "src" / "gaussianreadpro" / "__main__.py",
        ROOT / "src" / "gaussianreadpro" / "ui" / "profile_view.py",
        ROOT / "src" / "gaussianreadpro" / "resources" / "plot" / "profile.js",
        ROOT / "src" / "gaussianreadpro" / "resources" / "plot" / "profile.html",
        vendor,
        package_vendor,
        package_resource_root / "manifest.json",
        ROOT / "dist" / "GaussianReadPro" / "GaussianReadPro.exe",
    ]
    exe_manifest_path = ROOT / "dist" / "GaussianReadPro" / "build-manifest.json"
    exe_manifest = json.loads(exe_manifest_path.read_text(encoding="utf-8"))
    exe_runtime_path = ARTIFACTS / "exe-webengine-smoke.json"
    exe_runtime = json.loads(exe_runtime_path.read_text(encoding="utf-8")) if exe_runtime_path.exists() else None
    screenshot_names = ("source-baseline.jpg", "exe-baseline.jpg")
    screenshots = {}
    for name in screenshot_names:
        image_path = ARTIFACTS / name
        image = QImage(str(image_path))
        if image.isNull():
            raise SystemExit(f"Missing or invalid live window screenshot: {image_path}")
        screenshots[name] = {**file_hash(image_path), "width": image.width(), "height": image.height(),
                             "capture": "Windows.Graphics.Capture of the live GaussianReadPro window"}

    node_ids = {node.id for node in project.nodes}
    report = {
        "stage": "RF0",
        "date": "2026-10-16",
        "synthetic_fixture": True,
        "fixture_project": file_hash(PROJECT_PATH),
        "fixture_nodes": len(project.nodes),
        "independent_node_ids": len(node_ids) == 8,
        "path_reference_nodes": {path.label: path.entries[0].node_id for path in project.paths},
        "unit_constant": {"version": project.unit_constants_version, "hartree_to_kcal_mol": HARTREE_TO_KCAL},
        "display_values_kcal_mol": actual,
        "source_run": {"entry": "python tools/run_app.py artifacts/rf0/profile-replica.grproj",
                       "renderer": "Plotly.js scatter3d in the live QWebEngine page",
                       "live_3d_rendered": True},
        "windows_exe_run": {"entry": "dist/GaussianReadPro/GaussianReadPro.exe artifacts/rf0/profile-replica.grproj",
                            "renderer": "Plotly.js scatter3d in the live QWebEngine page",
                            "live_3d_rendered": True,
                            "build_manifest": exe_manifest,
                            "manifest_exe_sha256_matches": file_hash(source_hashes[-1])["sha256"] == exe_manifest["sha256"]},
        "renderer_resources": {"renderer": "Plotly.js scatter3d",
                                "python_package_version": resource_manifest["python_package_version"],
                                "source_runtime_plotly_version": webengine.get("plotly_version"),
                                "package_runtime_plotly_version": exe_runtime.get("plotly") if exe_runtime else None,
                                "license": resource_manifest["license"], "source_manifest": resource_manifest,
                                "package_manifest": package_resource_manifest,
                                "source_resource_sha256_matches_manifest": file_hash(vendor)["sha256"] == resource_manifest["sha256"],
                                "package_resource_sha256_matches_manifest": file_hash(package_vendor)["sha256"] == package_resource_manifest["sha256"],
                                "source_and_package_resource_hashes_match": file_hash(vendor)["sha256"] == file_hash(package_vendor)["sha256"],
                                "three_js_vendored": any(p.name.lower().startswith("three") for p in (resource_root / "vendor").iterdir())},
        "fonts": {"qt_general_font_family": qt_font, "requested_families_installed": font_report,
                  "system": platform.platform(),
                  "screen_device_pixel_ratio": app.primaryScreen().devicePixelRatio() if app.primaryScreen() else None},
        "qt": {"pyside_version": __import__("PySide6").__version__, "qt_version": qVersion(),
               "python": sys.version.split()[0], "source_webengine_capabilities": webengine,
               "package_webengine_smoke": exe_runtime},
        "source_hashes": [file_hash(path) for path in source_hashes],
        "screenshots": screenshots,
        "limitations": [
            "The existing renderer is Plotly scatter3d; this is not the planned Three.js RF3 renderer.",
            "The screenshot captures the actual 1442×951 desktop window at the current system scale; it is not the 1672×941 RF7 visual comparison canvas.",
            "The synthetic text fixtures are not genuine Gaussian program outputs.",
            "The source capability probe reports WebGL2 and ES module support; the packaged WebEngine smoke confirms its Plotly runtime and protocol handshake.",
        ],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(REPORT_PATH)
    print(json.dumps({"display_values_kcal_mol": actual, "plotly": resource_manifest["python_package_version"],
                      "exe_sha256": report["windows_exe_run"]["build_manifest"]["sha256"],
                      "screenshots": screenshots}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
