"""One concentrated native run: create custom-colour paths and reopen five paths."""
import hashlib
import json
import os
from pathlib import Path
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
    modes, _, select = windows_affinity(); select(modes["default"] & 0xFFFFFF3F)
    from PySide6.QtCore import QTimer, Qt, QUrl, QPoint
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialogButtonBox, QColorDialog
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.storage import ProjectRepository
    from gaussianreadpro.storage.preferences import LocalPreferences
    from gaussianreadpro.ui.main_window import MainWindow
    from gaussianreadpro.ui.path_editor import NewPathDialog
    from gaussianreadpro.ui.theme import apply_theme

    out.mkdir(parents=True, exist_ok=True)
    project_file = out / "five-paths.grproj"
    prefs = out / "preferences.ini"
    if name == "write":
        from build_profile_rf4_fixture import main as fixture
        with ProjectRepository(fixture(), read_only=True) as repo:
            project = repo.load()
        with ProjectRepository(project_file, create=True) as repo:
            repo.save(project)
        LocalPreferences(prefs).save(language="en", theme="dark", window_geometry=None, recent_projects=[], reduce_motion=True)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    app = QApplication([]); app.setQuitOnLastWindowClosed(False); apply_theme(app, "dark", reduce_motion=True)
    controller = ProjectController(out / ("recovery-" + name), prefs)
    window = MainWindow(controller); window.show(); panel = window.profile
    report = {"phase": name, "passed": False, "pid": os.getpid(), "affinity": "0xffffff3f", "checks": {}}
    views = []

    def wait(predicate, timeout=45):
        deadline = monotonic() + timeout
        while not predicate():
            QTest.qWait(40)
            if monotonic() > deadline:
                raise TimeoutError(f"multi-path timeout: {controller.operation}; JS={panel.javascript_errors[:4]}; failure={panel.failure}")
        QTest.qWait(100)

    def js(code, page=None):
        values = []; (page or panel.page).runJavaScript("JSON.stringify(" + code + ")", values.append)
        wait(lambda: bool(values), 15)
        return json.loads(values[0]) if values[0] else None

    def stable():
        QTest.qWait(550)
        wait(lambda: not controller.busy and not controller._workspace_timer.isActive() and not controller._pending_structure and panel.ready and panel.last_payload is not None)
        wait(lambda: panel.summary.get("render_id") == panel.last_payload["render_id"])

    def create(label, color, node_ids):
        callback_errors = []
        def fill():
            try:
                dialog = QApplication.activeModalWidget()
                assert isinstance(dialog, NewPathDialog), type(dialog)
                dialog.name_edit.setText(label); dialog.color_edit.setText(color)
                for i in range(dialog.nodes.count()):
                    item = dialog.nodes.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) in node_ids:
                        dialog.nodes.scrollToItem(item); QTest.qWait(30)
                        rect = dialog.nodes.visualItemRect(item)
                        QTest.mouseClick(dialog.nodes.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.left()+9, rect.center().y()))
                assert set(dialog.values()["node_ids"]) == set(node_ids)
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
            except Exception:
                callback_errors.append(traceback.format_exc())
                dialog = QApplication.activeModalWidget()
                if dialog: dialog.reject()
        QTimer.singleShot(350, fill)
        js("document.getElementById('new-path-control').click()")
        wait(lambda: not QApplication.activeModalWidget())
        assert not callback_errors, callback_errors
        wait(lambda: any(p.label == label for p in controller.project.paths)); stable()
        return next(p for p in controller.project.paths if p.label == label)

    try:
        controller.bootstrap(); wait(lambda: not controller.busy)
        controller.open_project(project_file, ignore_recovery=True); wait(lambda: not controller.busy and controller.project is not None)
        window.navigation.setCurrentRow(2); window.compact_tabs.setCurrentIndex(1); window.setGeometry(60, 60, 1672, 941); stable()
        if name == "write":
            controller.set_plot_state(mode="3d", compare=True, hidden_paths=[]); stable()
            a, b = controller.project.paths
            before_nodes = controller.project.nodes
            c = create("Path C", "#52cdb8", [e.node_id for e in b.entries])
            report["checks"]["native_add_dialog_creates_custom_color"] = c.color == "#52cdb8" and len(c.entries) == 4
            report["checks"]["explicit_nodes_and_reference_preserved"] = controller.project.nodes == before_nodes and c.reference_expression == b.reference_expression
            report["checks"]["three_paths_draw_three_shadows"] = js("window.grpr.diagnostics().curtains") == 3
            report["checks"]["same_shadow_shader_uses_custom_color"] = js("(()=>{const c=window.grpr.renderer3d.group.children.filter(o=>o.userData.decoration==='curtain');return c.some(o=>o.material.uniforms.tint.value.getHexString()==='52cdb8')&&c.every(o=>o.material.fragmentShader.includes('.14*a*a'))})()")
            js("document.getElementById('path-list-control').click()")
            report["checks"]["all_three_paths_accessible"] = js("document.querySelectorAll('.path-picker-row').length") == 3
            js("document.querySelector('[data-path-id=\"" + b.id + "\"] .path-visibility').click()")
            stable()
            report["checks"]["hide_updates_scene_and_table"] = js("window.grpr.diagnostics().curtains") == 2 and len(panel.last_payload["inspector"]["table_paths"]) == 2
            js("document.querySelector('[data-path-id=\"" + b.id + "\"] .path-visibility').click()")
            stable()
            def fill_color():
                dialog = QApplication.activeModalWidget()
                if isinstance(dialog, QColorDialog):
                    dialog.setCurrentColor(QColor("#f27da9"))
                    box = dialog.findChild(QDialogButtonBox)
                    QTest.mouseClick(box.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton)
                elif dialog:
                    dialog.reject()
            QTimer.singleShot(350, fill_color)
            js("document.querySelector('[data-path-id=\"" + b.id + "\"] .path-color').click()")
            wait(lambda: not QApplication.activeModalWidget()); stable()
            report["checks"]["nonactive_color_edit_targets_uuid"] = controller.selected_path.id == c.id and next(p for p in controller.project.paths if p.id == b.id).color == "#f27da9"
            create("Path D", "#68acff", [e.node_id for e in a.entries])
            create("Path E", "#dbc564", [e.node_id for e in b.entries])
            report["checks"]["five_paths_and_twenty_points_render"] = js("window.grpr.diagnostics().curtains") == 5 and js("window.grpr.diagnostics().pick_objects") == 20
            report["checks"]["five_legends_and_table_columns"] = js("document.querySelectorAll('#overview-legend span').length") == 5 and len(panel.last_payload["inspector"]["table_paths"]) == 5
            report["checks"]["table_scroll_width_is_readable"] = js("document.getElementById('key-energy-table').scrollWidth>document.querySelector('.energy-table-scroll').clientWidth")
            js("window.grpr.workbenchAction({action:'mode',mode:'2d'})"); stable()
            report["checks"]["two_d_five_computed_paths"] = js("document.querySelector('.plotly-host').data.filter(t=>t.meta?.kind==='computed-nodes').length") == 5
            js("window.grpr.workbenchAction({action:'mode',mode:'3d'})"); stable()
            js("window.grpr.cameraTool('fit')"); stable()
            js("document.getElementById('path-list-control').click()")
            QTest.qWait(250)
            image = window.grab(); image.save(str(out / "five-paths.png"))
            report["screenshot"] = {"file": str(out / "five-paths.png"), "pixels": [image.width(), image.height()], "capture": "unmodified QWidget.grab"}
            expected = {p.id: p.color for p in controller.project.paths}
            (out / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
            controller.save(project_file); wait(lambda: not controller.busy)
            with ProjectRepository(project_file, read_only=True) as repo:
                saved = repo.load()
            report["checks"]["five_paths_saved_with_colors"] = {p.id:p.color for p in saved.paths} == expected
        else:
            expected = json.loads((out / "expected.json").read_text())
            report["checks"]["fresh_process_five_paths_and_colors"] = {p.id:p.color for p in controller.project.paths} == expected
            report["checks"]["fresh_process_shadows_restored"] = js("window.grpr.diagnostics().curtains") == 5
            assert panel.export_to(out / "offline", "html", language="en")
            wait(lambda: (out / "offline/manifest.json").is_file() and not controller.busy)
            payload = json.loads((out / "offline/plot.json").read_text(encoding="utf-8"))
            report["checks"]["offline_payload_five_custom_colors"] = {p["id"]:p["color"] for p in payload["paths"]} == expected
            errors, blocked = [], []
            class Offline(QWebEngineUrlRequestInterceptor):
                def interceptRequest(self, info):
                    if info.requestUrl().scheme() not in ("file", "data", "blob", "about"):
                        blocked.append(info.requestUrl().toString()); info.block(True)
            class Page(QWebEnginePage):
                def javaScriptConsoleMessage(self, level, message, line, source):
                    if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: errors.append(message[:500])
            view = QWebEngineView(); profile = QWebEngineProfile(view); interceptor = Offline(profile); profile.setUrlRequestInterceptor(interceptor)
            page = Page(profile, view); view.setPage(page); views.append((view,page,profile,interceptor))
            view.resize(1476,891); view.show(); view.load(QUrl.fromLocalFile(str(out / "offline/profile.html")))
            wait(lambda: js("window.grpr?.diagnostics()?.curtains===5", page), 60)
            report["checks"]["offline_five_shadows_run"] = True
            js("document.getElementById('compare-control').click()", page)
            wait(lambda: js("window.grpr.shown.compare===false&&window.grpr.diagnostics().curtains===1", page))
            js("document.getElementById('compare-control').click()", page)
            wait(lambda: js("window.grpr.shown.compare===true&&window.grpr.diagnostics().curtains===5", page))
            report["checks"]["offline_comparison_restores_five"] = True
            path_id = next(iter(expected))
            js("window.grpr.workbenchAction({action:'active_path',path_id:'" + path_id + "'})", page)
            wait(lambda: js("window.grpr.shown.active_path_id==='" + path_id + "'", page))
            report["checks"]["offline_active_path_switch_works"] = True
            report["checks"]["offline_creation_and_color_disabled"] = js("document.getElementById('new-path-control').disabled&&[...document.querySelectorAll('.path-color')].every(b=>b.disabled)", page)
            report["checks"]["offline_no_js_or_network_errors"] = not errors and not blocked
            report["offline_errors"] = errors; report["blocked_requests"] = blocked
        report["checks"]["no_live_javascript_errors"] = not panel.javascript_errors
        report["passed"] = all(report["checks"].values())
    except Exception as error:
        report["error"] = str(error); report["traceback"] = traceback.format_exc()
    finally:
        (out / (name + "-validation.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        for view,page,profile,interceptor in views: view.close();view.setPage(None);page.deleteLater()
        window.close();controller.close();app.quit()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--phase": return phase(sys.argv[2], Path(sys.argv[3]))
    out = ROOT / "artifacts/multi-paths" / ("run-" + uuid4().hex[:10]);out.mkdir(parents=True)
    for name in ("write", "restore"):
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--phase", name, str(out)], capture_output=True)
        (out / (name + "-stdout.txt")).write_bytes(process.stdout);(out / (name + "-stderr.txt")).write_bytes(process.stderr)
        if process.returncode: print(str(out));print(process.stdout.decode("utf-8",errors="replace"));return process.returncode
    reports=[json.loads((out/(name+"-validation.json")).read_text(encoding="utf-8")) for name in ("write","restore")]
    summary={"passed":all(r["passed"] for r in reports),"checks":sum(len(r["checks"]) for r in reports),"run":str(out),"pids":[r["pid"] for r in reports]}
    (ROOT/"artifacts/multi-paths/validation.json").write_text(json.dumps(summary,indent=2),encoding="utf-8");print(json.dumps(summary,indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":raise SystemExit(main())
