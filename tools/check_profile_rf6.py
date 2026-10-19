"""Concentrated RF6 native export, fresh-process restore and offline file:// checks."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import monotonic
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]


def phase(name, out):
    os.environ.setdefault("QT_SCALE_FACTOR", "0.8")
    os.environ.pop("QT_QPA_PLATFORM", None)
    from diagnose_static_runtime import windows_affinity
    masks, _, select = windows_affinity()
    select(masks["default"] & 0xFFFFFF3F)
    from PySide6.QtCore import QUrl
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.storage import ProjectRepository
    from gaussianreadpro.storage.preferences import LocalPreferences
    from gaussianreadpro.ui.main_window import MainWindow
    from gaussianreadpro.ui.theme import apply_theme
    from gaussianreadpro.core.models import snapshot_to_dict

    out.mkdir(parents=True, exist_ok=True)
    project_file = out / "rf6.grproj"
    preferences = out / "preferences.ini"
    if name == "write":
        from build_profile_rf4_fixture import main as fixture
        with ProjectRepository(fixture(), read_only=True) as repo:
            project = repo.load()
        with ProjectRepository(project_file, create=True) as repo:
            repo.save(project)
        LocalPreferences(preferences).save(language="en", theme="dark", window_geometry=None,
            recent_projects=[], reduce_motion=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app, "dark", reduce_motion=True)
    controller = ProjectController(out / ("recovery-" + name), preferences)
    window = MainWindow(controller)
    window.show()
    panel = window.profile
    report = {"phase": name, "pid": os.getpid(), "passed": False, "checks": {}, "affinity": "0xffffff3f"}
    offline_views = []

    def wait(predicate, timeout=45):
        deadline = monotonic() + timeout
        while not predicate():
            QTest.qWait(40)
            if monotonic() > deadline:
                raise TimeoutError(f"RF6 timeout: {controller.operation}; busy={controller.busy}; JS={panel.javascript_errors[:3]}; failure={panel.failure}")
        QTest.qWait(100)

    def js(code, page=None):
        values = []
        (page or panel.page).runJavaScript("JSON.stringify(" + code + ")", values.append)
        wait(lambda: bool(values), 15)
        return json.loads(values[0]) if values[0] else None

    def stable():
        QTest.qWait(550)
        wait(lambda: not controller.busy and not controller._workspace_timer.isActive() and not controller._pending_structure and panel.ready and panel.last_payload is not None)
        wait(lambda: panel.summary.get("render_id") == panel.last_payload["render_id"])

    def export(target, format, language="en"):
        stable()
        assert panel.export_to(out / target, format, language=language)
        wait(lambda: (out / target / "manifest.json").is_file() and not controller.busy and not panel._capture)
        stable()
        return json.loads((out / target / "manifest.json").read_text())

    try:
        controller.bootstrap(); wait(lambda: not controller.busy)
        controller.open_project(project_file, ignore_recovery=True)
        wait(lambda: not controller.busy and controller.project is not None)
        window.navigation.setCurrentRow(2)
        window.compact_tabs.setCurrentIndex(1)
        window.setGeometry(60, 60, 1672, 941)
        stable()
        if name == "write":
            controller.set_plot_state(mode="3d", compare=True, hidden_paths=[])
            stable()
            path = panel.last_payload["paths"][0]
            point = path["points"][1]
            window.chart_selected(path["id"], point["node_id"], point["entry_id"])
            panel.set_table_selection([(path["id"], point["entry_id"])])
            stable()
            wait(lambda: panel.last_payload.get("inspector", {}).get("structure", {}).get("status") == "available")
            report["checks"]["verified_structure_selected"] = True
            js("window.grpr.workbenchAction({action:'mode',mode:'2d'})")
            stable()
            js("Plotly.relayout(document.querySelector('.plotly-host'),{'xaxis.range':[-.7,3.7],'yaxis.range':[-22,28]})&&true")
            stable()
            js("window.grpr.workbenchAction({action:'mode',mode:'3d'})")
            stable()
            camera = {"version": 1, "projection": "orthographic", "position": [7, -11, 8],
                      "target": [.2, 0, -.1], "up": [0, 0, 1], "zoom": 1.2}
            js("window.grpr.setViewport(" + json.dumps({"three_v1": camera}) + ")")
            stable()
            chart = export("chart-3d", "png", "zh_CN")
            report["checks"]["three_png_current_renderer_1600x1000"] = chart["raster_source"] == "Three.js ProfileRenderer.capture" and chart["size"] == [1600, 1000]
            chart_payload = json.loads((out / "chart-3d/plot.json").read_text(encoding="utf-8"))
            report["checks"]["chart_camera_and_language_match"] = chart_payload["viewport"]["three_v1"] == camera and chart_payload["language"] == "zh_CN"
            display = export("workbench", "workbench_png")
            report["checks"]["workbench_png_scope"] = display["export_scope"] == "workbench" and display["raster_source"] == "QtWebEngine QWidget.grab"
            html = export("offline-3d", "html")
            report["checks"]["offline_three_assets_and_license"] = html["renderer"] == "Three.js r170" and "assets/vendor/THREE-LICENSE.txt" in html["files"]
            exported = json.loads((out / "offline-3d/plot.json").read_text(encoding="utf-8"))
            report["checks"]["selected_coordinates_embedded"] = exported["inspector"]["structure"]["status"] == "available" and not any("cache" in key.lower() for key in exported["inspector"]["structure"])
            for bundle in ("chart-3d", "workbench", "offline-3d"):
                manifest = json.loads((out / bundle / "manifest.json").read_text())
                report["checks"][bundle + "_audit_checksums"] = all(hashlib.sha256((out / bundle / key).read_bytes()).hexdigest() == info["sha256"] for key, info in manifest["files"].items())
            # Expected failures use existing destinations and timeout recovery without publishing.
            errors = []
            controller.failed.connect(lambda code, detail: errors.append(code))
            assert panel.export_to(out / "offline-3d", "html")
            wait(lambda: not controller.busy)
            report["checks"]["existing_destination_failure_preserves_output"] = errors[-1:] == ["destination_exists"] and (out / "offline-3d/profile.html").is_file()
            # Let the real timeout release an outstanding capture and restore UI.
            panel._capture = {"id": "failure-check", "payload": exported}
            panel.capture_timer.start(100)
            wait(lambda: panel._capture is None)
            stable()
            report["checks"]["capture_failure_releases_controls"] = panel._capture is None and panel.export_button.isEnabled()
            js("window.grpr.workbenchAction({action:'details',visible:false,drawer:false})")
            stable()
            expected = snapshot_to_dict(controller.plot_state)
            (out / "expected-state.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8")
            assert controller.save(project_file)
            wait(lambda: not controller.busy)
            with ProjectRepository(project_file, read_only=True) as repo:
                report["checks"]["saved_state_on_disk"] = snapshot_to_dict(repo.load().plot_state) == expected
        else:
            expected = json.loads((out / "expected-state.json").read_text(encoding="utf-8"))
            report["checks"]["fresh_process_state_restored"] = snapshot_to_dict(controller.plot_state) == expected
            report["checks"]["fresh_three_camera_restored"] = js("window.grpr.renderer3d.viewport()") == expected["viewports"][panel.last_payload["context"] + "/3d"]["three_v1"]
            report["checks"]["fresh_selection_restored"] = [list(pair) for pair in panel._selection] == expected["selected_points"]
            report["checks"]["fresh_details_hidden"] = js("document.body.classList.contains('details-hidden')")
            js("window.grpr.workbenchAction({action:'mode',mode:'2d'})")
            stable()
            report["checks"]["independent_2d_range_restored"] = js("window.grpr.shown.viewport.x_range") == [-.7, 3.7] and js("window.grpr.shown.viewport.y_range") == [-22, 28]
            paper = export("paper-2d", "png")
            report["checks"]["paper_2d_white_background"] = paper["paper_background"] == "white"
            blocked, requests, console_errors = [], [], []
            class OfflineOnly(QWebEngineUrlRequestInterceptor):
                def interceptRequest(self, info):
                    scheme = info.requestUrl().scheme()
                    requests.append(scheme)
                    if scheme not in ("file", "data", "blob", "about"):
                        blocked.append(info.requestUrl().toString()); info.block(True)
            class Page(QWebEnginePage):
                def javaScriptConsoleMessage(self, level, message, line, source):
                    if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                        console_errors.append(message[:1000])
            view = QWebEngineView()
            profile = QWebEngineProfile(view)
            interceptor = OfflineOnly(profile); profile.setUrlRequestInterceptor(interceptor)
            page = Page(profile, view); view.setPage(page)
            offline_views.append((view, profile, page, interceptor))
            view.resize(1476, 891); view.show()
            relocated = out / "relocated/offline-3d"
            shutil.copytree(out / "offline-3d", relocated)
            view.load(QUrl.fromLocalFile(str(relocated / "profile.html")))
            wait(lambda: js("Boolean(window.grpr?.renderer3d?.nodes?.length)", page), 60)
            report["offline_diagnostics"] = js("window.grpr.diagnostics()", page)
            report["checks"]["file_offline_uses_three_r170"] = report["offline_diagnostics"]["three_version"] == "170"
            report["checks"]["relocated_bundle_runs_without_qt_bridge"] = not js("Boolean(window.qt)", page)
            wait(lambda: js("Boolean(window.profileInspector?.molecule?.diagnostics().objects)", page), 30)
            report["checks"]["offline_molecule_runs"] = True
            js("window.grpr.workbenchAction({action:'mode',mode:'2d'})", page)
            wait(lambda: js("window.grpr.shown.view==='2d'&&Boolean(document.querySelector('svg.main-svg'))", page))
            report["checks"]["offline_2d_switch_works"] = True
            js("window.grpr.workbenchAction({action:'mode',mode:'3d'})", page)
            wait(lambda: js("window.grpr.shown.view==='3d'", page))
            report["checks"]["offline_switch_retains_camera"] = js("window.grpr.renderer3d.viewport()", page) == report["offline_diagnostics"]["viewport"]
            js("document.getElementById('compare-control').click()", page)
            wait(lambda: js("window.grpr.shown.compare===false", page))
            report["checks"]["offline_compare_can_reenable"] = not js("document.getElementById('compare-control').disabled", page)
            js("document.getElementById('compare-control').click()", page)
            wait(lambda: js("window.grpr.shown.compare===true&&window.grpr.shown.paths.filter(p=>p.visible).length===2", page))
            report["checks"]["offline_compare_reenabled_both_paths"] = True
            js("(()=>{const p=window.grpr.shown.paths[0],n=p.points[2];window.grpr.selectPoint(p.id,n.entry_id,n.node_id);return true})()", page)
            wait(lambda: js("window.grpr.shown.inspector.structure.status==='not_exported'", page))
            report["checks"]["offline_other_selection_drops_old_molecule"] = True
            # Open an old camera snapshot in a new document, exercising the
            # actual legacy conversion in the vendored Three runtime.
            from gaussianreadpro.services.plot_export import export_plot_bundle
            legacy = json.loads((out / "offline-3d/plot.json").read_text(encoding="utf-8"))
            legacy["viewport"] = {"camera": legacy["default_camera"]}
            legacy["viewports"][legacy["context"] + "/3d"] = legacy["viewport"]
            export_plot_bundle(legacy, out / "offline-legacy", "html")
            view.load(QUrl.fromLocalFile(str(out / "offline-legacy/profile.html")))
            wait(lambda: js("window.grpr?.diagnostics()?.migration==='plotly-v1'", page), 60)
            report["checks"]["legacy_camera_migrates_in_real_three"] = True
            js("(()=>{window.GRPR_FORCE_NO_WEBGL=true;window.grpr.render({...window.grpr.shown,view:'3d'});return true})()", page)
            wait(lambda: js("window.grpr.shown.view==='2d'&&Boolean(document.querySelector('svg.main-svg'))", page))
            report["checks"]["offline_webgl_failure_has_2d_fallback"] = bool(js("document.getElementById('notice').textContent", page))
            report["checks"]["offline_no_remote_or_js_errors"] = not blocked and not console_errors
            report["offline_console_errors"] = console_errors
            report["network_schemes"] = sorted(set(requests))
            report["blocked_remote_requests"] = blocked
        report["checks"]["no_live_javascript_errors"] = not panel.javascript_errors
        report["passed"] = all(report["checks"].values())
    except Exception as error:
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
    finally:
        (out / (name + "-validation.json")).write_text(json.dumps(snapshot_to_dict(report), ensure_ascii=False, indent=2), encoding="utf-8")
        for view, profile, page, interceptor in offline_views:
            view.close(); view.setPage(None); page.deleteLater()
        window.close(); controller.close(); app.quit()
    print(json.dumps(snapshot_to_dict(report), ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--phase":
        return phase(sys.argv[2], Path(sys.argv[3]))
    out = ROOT / "artifacts/rf6" / ("run-" + uuid4().hex[:10])
    out.mkdir(parents=True, exist_ok=True)
    summary_file = ROOT / "artifacts/rf6/validation.json"
    summary_file.write_text(json.dumps({"stage": "RF6", "passed": False, "status": "running", "run": str(out)}), encoding="utf-8")
    for name in ("write", "restore"):
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--phase", name, str(out)], capture_output=True)
        (out / (name + "-stdout.txt")).write_bytes(process.stdout)
        (out / (name + "-stderr.txt")).write_bytes(process.stderr)
        if process.returncode:
            summary_file.write_text(json.dumps({"stage": "RF6", "passed": False, "status": "failed", "phase": name, "run": str(out)}, indent=2), encoding="utf-8")
            print(str(out)); print(process.stdout.decode("utf-8", errors="replace")); return process.returncode
    reports = [json.loads((out / (name + "-validation.json")).read_text(encoding="utf-8")) for name in ("write", "restore")]
    summary = {"stage": "RF6", "passed": all(r["passed"] for r in reports), "status": "complete", "run": str(out),
               "checks": sum(len(r["checks"]) for r in reports), "processes": [r["pid"] for r in reports]}
    files = ["services/plot_export.py", "ui/profile_view.py", "core/plot_spec.py"]
    files += ["resources/plot/" + f for f in ("profile.html", "profile.js", "replica_controls.js", "replica.css", "scene3d.js", "inspector_view.js", "molecule_view.js", "vendor/three.module.min.js", "vendor/THREE-LICENSE.txt", "vendor/plotly.min.js")]
    summary["source_sha256"] = {name: hashlib.sha256((ROOT / "src/gaussianreadpro" / name).read_bytes()).hexdigest() for name in files}
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
