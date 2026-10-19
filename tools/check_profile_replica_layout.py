"""RF2: visible source application, real WebEngine, measured client/DOM boundaries.

Run on the interactive Windows desktop. Captures are unmodified Qt window grabs.
Only the current process uses the documented compatibility CPU affinity.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import monotonic
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--scale-factor", default="0.8", help="0.8 × this desktop's 125%% scale gives DPR 1")
    args = parser.parse_args()
    os.environ["QT_SCALE_FACTOR"] = args.scale_factor
    os.environ.pop("QT_QPA_PLATFORM", None)
    from diagnose_static_runtime import windows_affinity
    modes, _, select_affinity = windows_affinity()
    affinity = modes["default"] & 0xFFFFFF3F
    select_affinity(affinity)
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.storage import ProjectRepository
    from gaussianreadpro.storage.preferences import LocalPreferences
    from gaussianreadpro.ui.main_window import MainWindow
    import gaussianreadpro.ui.main_window as main_module
    from gaussianreadpro.ui.theme import apply_theme

    folder = ROOT / "artifacts/rf2"
    folder.mkdir(parents=True, exist_ok=True)
    prefs = folder / "preferences.ini"
    LocalPreferences(prefs).save(language="en", theme="dark", window_geometry=None, recent_projects=[], reduce_motion=True)
    fixture = ROOT / "artifacts/rf0/profile-replica.grproj"
    project_file = folder / "rf2-layout.grproj"
    if not project_file.exists():
        with ProjectRepository(fixture, read_only=True) as repo:
            project = repo.load()
        with ProjectRepository(project_file, create=True) as repo:
            repo.save(project)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app, "dark", reduce_motion=True)
    controller = ProjectController(folder / "recovery", prefs)

    class IdentifiedWindow(MainWindow):
        def setWindowTitle(self, text):
            super().setWindowTitle(str(text) + f" [RF2 source · PID {os.getpid()}]")

    window = IdentifiedWindow(controller)
    window.show()
    report = {"stage": "RF2", "passed": False, "pid": os.getpid(), "source_module": main_module.__file__,
              "affinity": hex(affinity), "screenshots": [], "checks": {}}

    def wait_for(predicate, timeout=30):
        deadline = monotonic() + timeout
        while not predicate():
            QTest.qWait(30)
            if monotonic() > deadline:
                raise TimeoutError(f"RF2 wait timed out; operation={controller.operation}; JS={window.profile.javascript_errors}; failure={window.profile.failure}")
        QTest.qWait(80)

    def js(code):
        result = []
        window.profile.page.runJavaScript(code, lambda value: result.append(value))
        wait_for(lambda: bool(result), 15)
        return result[0]

    def stable():
        QTest.qWait(550)  # Let the existing 400 ms workspace persistence finish first.
        wait_for(lambda: not controller.busy and window.profile.ready and window.profile.summary.get("render_id") == (window.profile.last_payload or {}).get("render_id"))
        wait_for(lambda: js("Boolean(window.grpr.shown && !window.grpr.queueState.running && !window.grpr.queueState.pending && !window.grpr.queueState.resizePending && window.grpr.shown.render_id === " + str(window.profile.last_payload["render_id"]) + ")"))

    def capture(name):
        window.raise_()
        window.activateWindow()
        QTest.qWait(250)
        window.repaint()
        QTest.qWait(250)
        image = window.grab()
        path = folder / name
        if not image.save(str(path)):
            raise RuntimeError("Screenshot could not be saved")
        report["screenshots"].append({"path": str(path), "pixels": [image.width(), image.height()], "dpr": image.devicePixelRatio(),
                                      "sha256": sha256(path.read_bytes()).hexdigest(), "capture": "Unmodified QWidget.grab of the real visible Qt/WebEngine application client"})

    try:
        controller.bootstrap()
        wait_for(lambda: not controller.busy)
        controller.open_project(project_file, ignore_recovery=True)
        wait_for(lambda: not controller.busy and controller.project is not None)
        controller.set_plot_state(mode="3d", compare=True, hidden_paths=[])
        window.navigation.setCurrentRow(2)
        window.compact_tabs.setCurrentIndex(1)
        window.setGeometry(80, 80, 1672, 941)
        stable()
        selected = window.profile.last_payload["paths"][0]["points"][1]
        window.chart_selected(window.profile.last_payload["paths"][0]["id"], selected["node_id"], selected["entry_id"])
        window.profile.set_table_selection([(window.profile.last_payload["paths"][0]["id"], selected["entry_id"])])
        stable()
        report["screen"] = {"geometry": list(window.screen().geometry().getRect()), "dpr": window.devicePixelRatioF(), "platform": app.platformName()}
        report["client_size"] = [window.width(), window.height()]
        origin = window.profile.webview.mapTo(window, QPoint(0, 0))
        dom = json.loads(js("JSON.stringify(Object.fromEntries(['main-column','profile-toolbar','inspector-shell','molecule-placeholder','details-fields','overview-placeholder','table-placeholder','bottom-tools','orientation-placeholder'].map(id=>{const e=document.getElementById(id),r=e.getBoundingClientRect();return [id,{x:r.x,y:r.y,w:r.width,h:r.height,scrollHeight:e.scrollHeight,clientHeight:e.clientHeight}]})))"))
        for row in dom.values():
            row["x"] += origin.x()
            row["y"] += origin.y()
        report["regions"] = dom
        expected = {"main-column": [208, 59, 1056, 871], "profile-toolbar": [216, 69, 1035, 49], "inspector-shell": [1272, 59, 387, 854],
                    "bottom-tools": [477, 854, 441, 56], "orientation-placeholder": [216, 747, 150, 155]}
        errors = {key: max(abs(actual[k] - target) for k, target in zip(("x", "y", "w", "h"), values)) for key, values in expected.items() for actual in [dom[key]]}
        report["boundary_errors_dip"] = errors
        topbar, sidebar = window.findChild(type(window.sidebar), "topbar"), window.sidebar
        report["qt_regions"] = {"topbar": list(topbar.geometry().getRect()), "sidebar": list(sidebar.geometry().getRect()), "webview_origin": [origin.x(), origin.y()]}
        report["checks"]["fixed_canvas"] = report["client_size"] == [1672, 941] and abs(window.devicePixelRatioF() - 1) < .01
        report["checks"]["macro_boundaries"] = max(errors.values()) <= 4 and topbar.height() == 50 and sidebar.width() == 196
        report["checks"]["single_webengine"] = len(window.findChildren(type(window.profile.webview))) == 1
        report["checks"]["no_old_toolbar_or_tabs"] = not window.profile.toolbar_panel.isVisible() and not window.compact_tabs.isVisible()
        report["checks"]["right_panel_no_scroll"] = dom["inspector-shell"]["scrollHeight"] <= dom["inspector-shell"]["clientHeight"] + 1
        capture("rf2-en-dark-1672x941.png")
        scientific_values = [[p["value"] for p in path["points"]] for path in window.profile.last_payload["paths"]]
        js("document.querySelector('[data-mode=\"2d\"]').click()")
        wait_for(lambda: (window.profile.last_payload or {}).get("view") == "2d")
        stable()
        report["checks"]["dimension_button"] = window.profile.last_payload["view"] == "2d"
        js("document.querySelector('[data-mode=\"3d\"]').click()")
        wait_for(lambda: (window.profile.last_payload or {}).get("view") == "3d")
        stable()
        js("document.querySelectorAll('#path-controls button')[1].click()")
        wait_for(lambda: bool(window.profile.state.get("hidden_paths")))
        stable()
        js("document.querySelectorAll('#path-controls button')[1].click()")
        wait_for(lambda: not window.profile.state.get("hidden_paths"))
        stable()
        report["checks"]["path_controls"] = all(p["visible"] for p in window.profile.last_payload["paths"])
        js("document.getElementById('compare-control').click()")
        wait_for(lambda: not window.profile.state.get("compare"))
        stable()
        js("document.getElementById('compare-control').click()")
        wait_for(lambda: window.profile.state.get("compare"))
        stable()
        report["checks"]["compare_control"] = len(window.profile.last_payload["paths"]) == 2
        report["checks"]["scientific_values_unchanged"] = [[p["value"] for p in path["points"]] for path in window.profile.last_payload["paths"]] == scientific_values
        for row in range(3, 11):
            window.navigation.setCurrentRow(row)
            app.processEvents()
            assert window.stack.currentIndex() == row
        report["checks"]["independent_analysis_routes"] = True
        window.navigation.setCurrentRow(2)
        window.language_combo.setCurrentIndex(window.language_combo.findData("zh_CN"))
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("light"))
        window.resize(1440, 900)
        stable()
        capture("rf2-cn-light-1440x900.png")
        report["checks"]["cn_light_smoke"] = window.profile.last_payload["language"] == "zh_CN" and not window.profile.last_payload["dark"]
        window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark"))
        window.resize(1672, 941)
        stable()
        report["javascript_errors"] = window.profile.javascript_errors
        report["renderer"] = {"name": "Plotly scatter3d (RF3 renderer not started)", "runtime_version": window.profile.summary.get("plotly_version"), "view": window.profile.summary.get("view")}
        report["checks"]["javascript_no_errors"] = not window.profile.javascript_errors
        report["source_hashes"] = {str(path.relative_to(ROOT)): sha256(path.read_bytes()).hexdigest() for path in [ROOT / "src/gaussianreadpro/ui/main_window.py", ROOT / "src/gaussianreadpro/ui/profile_view.py", ROOT / "src/gaussianreadpro/ui/theme.py", ROOT / "src/gaussianreadpro/ui/glass_widgets.py", ROOT / "src/gaussianreadpro/presentation/palette.py", ROOT / "src/gaussianreadpro/resources/themes/lavender_sunset.json", *[ROOT / "src/gaussianreadpro/resources/plot" / name for name in ("profile.html", "profile.js", "replica.css", "replica_controls.js")], *sorted((ROOT / "src/gaussianreadpro/resources/icons").glob("*.svg"))]}
        report["passed"] = all(report["checks"].values())
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        (folder / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if args.keep_open and report["passed"]:
        return app.exec()
    controller.close()
    wait_for(lambda: controller._closed)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
