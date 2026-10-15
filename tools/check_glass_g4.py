"""Isolated desktop Qt/WebEngine checks for the G4 chart theme contract.

Run with normal desktop permissions; Chromium's sandbox stays enabled.
All projects, preferences, captures and exports live under the unique QA run.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.ui.main_window import MainWindow
from check_s7 import js, rendered, settle, wait


def main(*, include_static=True, static_rounds=1):
    if static_rounds < 1:
        raise ValueError("static_rounds must be positive")
    output = ROOT / "artifacts/ui-glass/g4"
    run = output / "runs" / uuid4().hex
    run.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    controller = ProjectController(run / "recovery", run / "preferences.ini")
    window = MainWindow(controller)
    panel = window.profile
    errors, checks = [], {}
    controller.failed.connect(lambda code, detail: errors.append([code, detail]))
    extra_view = None
    report = {"passed": False, "run": str(run), "platform": app.platformName(), "checks": checks,
              "python": sys.version, "executable": sys.executable,
              "static_exports": "included" if include_static else "not_run",
              "static_rounds": static_rounds if include_static else 0, "static_runs": []}
    if os.name == "nt":
        from diagnose_static_runtime import windows_affinity
        masks, _, _ = windows_affinity()
        report["process_affinity"] = hex(masks["default"])

    def capture(name, widget=window):
        QTest.qWait(250)
        assert widget.grab().save(str(run / name))

    def chart():
        return json.loads(js(panel.page, "JSON.stringify({bg:document.getElementById('plot').layout.paper_bgcolor,"
            "markers:document.getElementById('plot')._fullData.filter(t=>t.customdata).map(t=>"
            "({color:t.marker.color,line:t.marker.line,legend:t.showlegend})),"
            "validation:Plotly.validate(document.getElementById('plot').data,document.getElementById('plot').layout)||[]})"))

    def fitted(page):
        return js(page, "Boolean(document.getElementById('plot')._fullLayout && "
            "Math.abs(document.getElementById('plot')._fullLayout.width-document.getElementById('plot').clientWidth)<2 && "
            "Math.abs(document.getElementById('plot')._fullLayout.height-document.getElementById('plot').clientHeight)<2)")

    try:
        assert app.platformName() not in ("offscreen", "minimal"), "Desktop Qt platform required"
        window.resize(1440, 1000)
        window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        files = []
        for name, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
            file = run / (name + ".log")
            file.write_text("SYNTHETIC G4 QA\nEntering Gaussian System\n"
                f" SCF Done: E(RB3LYP) = {value-.03:.12f} A.U.\n"
                f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                " Normal termination of Gaussian 16\n", encoding="utf-8")
            files.append(file)
        window.import_paths(files); settle(controller)
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        controller.rename_node(controller.project.nodes[0].id, "反应物 R · α", "reactant"); settle(controller)
        controller.rename_node(controller.project.nodes[1].id, "TS1 · ΔG‡", "transition_state"); settle(controller)
        controller.edit_path("color", "#8D6AC8"); settle(controller)
        controller.edit_path("copy", "路径 β / comparison"); settle(controller)
        controller.edit_path("color", "#CF733D"); settle(controller)
        window.navigation.setCurrentRow(2)
        rendered(panel)
        panel.compare_box.setChecked(True); settle(controller); rendered(panel)
        selected_path = controller.selected_path
        panel.set_table_selection([(selected_path.id, selected_path.entries[0].id)])
        rendered(panel)
        expected = [n.display_value for result in controller.results for n in result.nodes]
        assert [p["value"] for p in panel.summary["points"]] == expected
        colors = [path.color for path in controller.project.paths]
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("light")); settle(controller); rendered(panel)
        light = chart()
        report["light_chart"] = light
        capture("profile-web-2d-cn-light.png")
        for path, marker in zip(panel.last_payload["paths"], light["markers"]):
            assert all(color.lower() == path["color"].lower() for color in marker["color"])
        checks["selection_preserves_path_and_legend_color"] = True

        window.language_combo.setCurrentIndex(window.language_combo.findData("en")); settle(controller)
        panel.theme_combo.setCurrentIndex(panel.theme_combo.findData("dark")); settle(controller); rendered(panel)
        assert not window._glass_theme == "dark", "Independent chart theme must leave app appearance alone"
        dark = chart()
        assert dark["bg"] == panel.last_payload["visual_style"]["background"] != light["bg"]
        assert panel.native.dark, "Native fallback must follow the independent chart theme"
        assert panel.page.backgroundColor().name().lower() == dark["bg"].lower()
        capture("profile-web-2d-en-dark.png")
        capture("profile-native-en-dark.png", panel.native)
        checks["independent_theme"] = True
        panel.view_combo.setCurrentIndex(1); settle(controller); rendered(panel)
        assert panel.summary["view"] == "3d" and panel.summary["canvas_count"] > 0
        report["dark_3d_chart"] = chart()
        invalid = [item for item in report["dark_3d_chart"]["validation"] if item.get("code") == "value"]
        assert not invalid, invalid
        capture("profile-web-3d-en-dark.png")
        camera = {"eye": {"x": 1.9, "y": 1.6, "z": 1.3}, "center": {"x": 0, "y": 0, "z": 0}, "up": {"x": 0, "y": 0, "z": 1}}
        js(panel.page, "Plotly.relayout(document.getElementById('plot'), {'scene.camera':" + json.dumps(camera) + "}); true")
        settle(controller); rendered(panel)
        browser = panel.webview
        panel.expand(); QTest.qWait(300); rendered(panel)
        wait(lambda: fitted(panel.page), "Expanded plot fills the viewport")
        assert panel.webview is browser
        assert js(panel.page, "document.getElementById('plot').layout.scene.camera.eye.x") == 1.9
        capture("profile-web-3d-expanded.png", panel._expanded)
        panel._expanded.close(); QTest.qWait(200); rendered(panel)
        wait(lambda: fitted(panel.page), "Restored plot fills the viewport")
        assert js(panel.page, "document.getElementById('plot').layout.scene.camera.eye.x") == 1.9
        assert panel.webview is browser
        checks["scatter3d_and_expand_reuse_browser"] = True
        checks["responsive_geometry_preserves_camera"] = True

        js(panel.page, "window.captureTitles=[]; const originalToImage=Plotly.toImage; "
            "Plotly.toImage=function(target,options){window.captureTitles.push({"
            "step:target.layout.scene.xaxis.title.text,category:target.layout.scene.yaxis.title.text,"
            "energy:target.layout.scene.zaxis.title.text}); return originalToImage(target,options);}; true")
        assert panel.export_to(run / "export-3d-png", "png", language="en")
        wait(lambda: panel._capture is None and (run / "export-3d-png/profile.png").is_file(), "3D PNG", 45)
        settle(controller)
        titles = json.loads(js(panel.page, "JSON.stringify(window.captureTitles[window.captureTitles.length-1])"))
        assert titles["step"] == "Reaction step" and titles["category"] == "Path category"
        assert "kcal/mol" in titles["energy"], titles
        assert not panel.last_payload.get("image_capture"), "Capture must restore the live compact view"
        assert js(panel.page, "document.getElementById('plot').layout.scene.camera.eye.x") == 1.9
        checks["actual_three_dimensional_png"] = True
        checks["png_axis_titles_and_view_restore"] = True
        panel.view_combo.setCurrentIndex(0); settle(controller); rendered(panel)
        def verify_bundle(folder):
            assert (folder / "manifest.json").is_file(), errors
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            for name, info in manifest["files"].items():
                assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == info["sha256"]
            saved = json.loads((folder / "plot.json").read_text(encoding="utf-8"))
            assert saved["paths"] == panel.last_payload["paths"]
            return manifest

        if include_static:
            from PIL import Image
            from xml.etree import ElementTree
            for round_index in range(static_rounds):
                language = "zh_CN" if round_index % 2 == 0 else "en"
                for format in ("png", "svg", "pdf"):
                    name = "export-2d-" + format if round_index == 0 else f"static-{round_index+1:02d}-{format}"
                    folder = run / name
                    assert panel.export_to(folder, format, language=language)
                    settle(controller)
                    manifest = verify_bundle(folder)
                    assert manifest["python_isolated"] and manifest["backend"].lower() == "agg"
                    assert not any("Glyph" in warning and "missing" in warning for warning in manifest.get("warnings", []))
                    primary = folder / ("profile." + format)
                    if format == "png":
                        with Image.open(primary) as image:
                            assert image.width >= 1600 and image.convert("RGB").getpixel((0, 0)) == (255, 255, 255)
                    elif format == "svg":
                        assert ElementTree.parse(primary).getroot().tag.endswith("svg")
                    else:
                        data = primary.read_bytes()
                        assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF")
                    report["static_runs"].append({"round": round_index+1, "format": format,
                        "language": language, "bundle": name, "python": manifest["python"],
                        "seconds": manifest["render_seconds"], "cjk_font": manifest["cjk_font"]})
                    (run / "validation-in-progress.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps({"static_round": round_index+1, "completed": len(report["static_runs"])}), flush=True)
            assert len(report["static_runs"]) == static_rounds*3
            checks["paper_exports_and_manifests"] = True
            if static_rounds > 1:
                checks["consecutive_static_exports"] = True
        html_folder = run / "export-2d-html"
        assert panel.export_to(html_folder, "html", language="zh_CN")
        settle(controller)
        verify_bundle(html_folder)
        checks["html_manifest"] = True

        from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from gaussianreadpro.prototype import OfflineRequests
        extra_view = QWebEngineView()
        extra_profile = QWebEngineProfile(extra_view)
        extra_requests = OfflineRequests(extra_profile)
        extra_profile.setUrlRequestInterceptor(extra_requests)
        extra_page = QWebEnginePage(extra_profile, extra_view)
        extra_view.setPage(extra_page)
        extra_view.resize(1100, 820); extra_view.show()
        extra_view.load(QUrl.fromLocalFile(str(run / "export-2d-html/profile.html")))
        wait(lambda: js(extra_page, "Boolean(window.grpr && window.grpr.shown)"), "Offline HTML")
        foreground = js(extra_page, "getComputedStyle(document.body).color")
        assert foreground == "rgb(244, 239, 250)", foreground
        capture("profile-html-dark.png", extra_view)
        extra_view.resize(900, 680)
        wait(lambda: fitted(extra_page), "Standalone HTML resize")
        js(extra_page, "document.getElementById('view-toggle').click(); true")
        wait(lambda: js(extra_page, "window.grpr.shown.view==='3d'"), "Offline HTML 3D")
        assert not extra_requests.blocked
        checks["offline_html_theme_and_3d"] = True

        assert colors == [path.color for path in controller.project.paths]
        assert not errors and not panel.javascript_errors and not panel.blocked_requests
        report.update(passed=True, errors=errors, loads=panel.load_events, javascript_errors=panel.javascript_errors,
                      blocked_remote_requests=panel.blocked_requests, final_summary=panel.summary)
    except BaseException as error:
        report.update(error=str(error), failure=panel.failure, errors=errors, loads=panel.load_events,
                      javascript_errors=panel.javascript_errors, summary=panel.summary)
        capture("failure.png")
        raise
    finally:
        (run / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in ("passed", "run", "checks", "error", "failure") if key in report},
                         ensure_ascii=True, indent=2), flush=True)
        if extra_view is not None:
            extra_view.setPage(None)
            extra_view.close()
        if getattr(panel, "_expanded", None):
            panel._expanded.close()
        if controller.busy:
            wait(lambda: not controller.busy, "Finish worker", 180)
        if not controller._closed:
            controller.close(); wait(lambda: controller._closed, "Close isolated QA project")
        app.processEvents()
        if report["passed"]:
            (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-static", action="store_true", help="Run WebEngine checks only; mark Agg exports as not_run")
    parser.add_argument("--static-rounds", type=int, default=1, help="Fresh PNG/SVG/PDF exports per round, with no retries")
    args = parser.parse_args()
    main(include_static=not args.skip_static, static_rounds=args.static_rounds)
