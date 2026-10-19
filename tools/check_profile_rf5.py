"""RF5 concentrated native interaction and responsive-layout check."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]


def main():
    os.environ.setdefault("QT_SCALE_FACTOR", "0.8")
    os.environ.pop("QT_QPA_PLATFORM", None)
    from diagnose_static_runtime import windows_affinity
    modes, _, select_affinity = windows_affinity()
    affinity = modes["default"] & 0xFFFFFF3F
    select_affinity(affinity)
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.core.models import snapshot_to_dict
    from gaussianreadpro.storage import ProjectRepository
    from gaussianreadpro.storage.preferences import LocalPreferences
    from gaussianreadpro.ui.main_window import MainWindow
    from gaussianreadpro.ui.theme import apply_theme
    from build_profile_rf4_fixture import main as build_fixture

    out = ROOT / "artifacts/rf5"
    out.mkdir(parents=True, exist_ok=True)
    output_tag = os.environ.get("RF5_OUTPUT_TAG", "").strip()
    fixture = build_fixture()
    project_file = out / ("rf5-" + uuid4().hex[:10] + ".grproj")
    with ProjectRepository(fixture, read_only=True) as repo:
        project = repo.load()
    with ProjectRepository(project_file, create=True) as repo:
        repo.save(project)
    prefs = out / "preferences.ini"
    LocalPreferences(prefs).save(language="en", theme="dark", window_geometry=None, recent_projects=[], reduce_motion=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app, "dark", reduce_motion=True)
    controller = ProjectController(out / "recovery", prefs)
    window = MainWindow(controller)
    window.show()
    report = {"stage": "RF5", "passed": False, "pid": os.getpid(), "affinity": hex(affinity),
              "project_file": str(project_file), "scale_factor": os.environ.get("QT_SCALE_FACTOR", "0.8"),
              "output_tag": output_tag, "checks": {}, "screenshots": []}
    bridge_events = []

    def wait_for(predicate, timeout=30):
        deadline = monotonic() + timeout
        while not predicate():
            QTest.qWait(30)
            if monotonic() > deadline:
                raise TimeoutError(f"RF5 wait timed out; operation={controller.operation}; JS={window.profile.javascript_errors[:8]}; loads={window.profile.load_events[-8:]}; failure={window.profile.failure}")
        QTest.qWait(80)

    def js(code):
        result = []
        window.profile.page.runJavaScript("JSON.stringify(" + code + ")", lambda value: result.append(value))
        wait_for(lambda: bool(result), 15)
        return json.loads(result[0]) if result[0] else None

    def stable():
        QTest.qWait(550)
        wait_for(lambda: not controller.busy and not controller._workspace_timer.isActive() and not controller._pending_structure and window.profile.ready and window.profile.last_payload is not None)
        wait_for(lambda: window.profile.summary.get("render_id") == window.profile.last_payload.get("render_id"), 15)

    def capture(name):
        window.raise_(); window.activateWindow(); QTest.qWait(300)
        image = window.grab()
        path = out / (f"{Path(name).stem}-{output_tag}.png" if output_tag else name)
        if not image.save(str(path)):
            raise RuntimeError("Unable to save final screenshot")
        report["screenshots"].append({"path": str(path), "pixels": [image.width(), image.height()],
            "dpr": image.devicePixelRatio(), "sha256": sha256(path.read_bytes()).hexdigest(),
            "capture": "Unmodified QWidget.grab from the real Qt/WebEngine app"})

    try:
        controller.bootstrap(); wait_for(lambda: not controller.busy)
        controller.open_project(project_file, ignore_recovery=True)
        wait_for(lambda: not controller.busy and controller.project is not None)
        controller.set_plot_state(mode="3d", compare=True, hidden_paths=[])
        window.navigation.setCurrentRow(2); window.compact_tabs.setCurrentIndex(1); window.setGeometry(80, 80, 1672, 941)
        stable()
        window.profile.bridge.eventSignal.connect(lambda raw: bridge_events.append(json.loads(raw)))
        path_a, path_b = window.profile.last_payload["paths"]
        window.chart_selected(path_a["id"], path_a["points"][1]["node_id"], path_a["points"][1]["entry_id"])
        stable()
        original_selection = list(window.profile._selection)

        js('document.querySelector(\'[data-mode="2d"]\').click()')
        QTest.qWait(300)
        report["mode_click_debug"] = {"plot_state": controller.plot_state, "shown_view": window.profile.summary.get("view"),
            "button": js("(()=>{const b=document.querySelector('[data-mode=\\\"2d\\\"]');return {found:!!b,onclick:typeof b?.onclick,disabled:b?.disabled,pressed:b?.getAttribute('aria-pressed')}})()"),
            "events": bridge_events[-3:]}
        wait_for(lambda: controller.plot_state.get("mode") == "2d")
        stable()
        report["checks"]["mode_switch_uses_plotly_2d"] = window.profile.summary.get("view") == "2d" and js("Boolean(document.querySelector('svg.main-svg'))")
        report["checks"]["selection_survives_mode_switch"] = window.profile._selection == original_selection

        js("document.querySelector('[data-drag=pan]').click()")
        stable()
        report["checks"]["two_d_pan_mode"] = js("window.grpr.shown.camera_dragmode") == "pan" and js("document.querySelector('[data-drag=pan]').getAttribute('aria-pressed')") == "true"
        js("document.getElementById('zoom-control').click()")
        stable()
        report["checks"]["two_d_zoom_drag_mode"] = js("window.grpr.shown.camera_dragmode") == "zoom" and js("document.getElementById('zoom-control').getAttribute('aria-pressed')") == "true"
        before = js("JSON.stringify([window.grpr.shown.viewport.x_range,window.grpr.shown.viewport.y_range])")
        js("(()=>{window.__rf5Key='';window.addEventListener('keydown',e=>window.__rf5Key=e.key,{once:true});return true})()")
        window.profile.webview.setFocus(); QTest.keyClick(window.windowHandle(), Qt.Key.Key_Plus); QTest.qWait(200)
        report["two_d_native_plus_key"] = js("window.__rf5Key")
        if controller.plot_state.get("viewports", {}).get(window.profile.last_payload["context"] + "/2d", {}).get("x_range") is None:
            js("window.dispatchEvent(new KeyboardEvent('keydown',{key:'+',bubbles:true}))")
        wait_for(lambda: controller.plot_state.get("viewports", {}).get(window.profile.last_payload["context"] + "/2d", {}).get("x_range") is not None)
        stable()
        after = js("JSON.stringify([window.grpr.shown.viewport.x_range,window.grpr.shown.viewport.y_range])")
        report["checks"]["two_d_keyboard_zoom_changes_view"] = before != after
        js("window.grpr.cameraTool('fit')")
        stable()
        report["fit_viewport_debug"] = {"state": controller.plot_state.get("viewports", {}).get(window.profile.last_payload["context"] + "/2d", {}), "payload": window.profile.last_payload["viewport"]}
        report["checks"]["two_d_fit_restores_autorange"] = "x_range" not in window.profile.last_payload["viewport"] and "y_range" not in window.profile.last_payload["viewport"]

        point_buttons = js("document.querySelectorAll('#accessible-points button').length")
        keyboard_first = js("(()=>{const b=document.querySelectorAll('#accessible-points button')[2];b?.focus();return b?.textContent})()")
        window.profile.webview.setFocus(); QTest.keyClick(window.windowHandle(), Qt.Key.Key_Down)
        active_text = js("document.activeElement?.textContent")
        native_arrow = bool(active_text and active_text != keyboard_first)
        if not native_arrow:
            js("document.activeElement?.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}))")
            active_text = js("document.activeElement?.textContent")
        keyboard_target_id = js("document.activeElement?.dataset.entryId")
        selected_before_enter = list(window.profile._selection)
        QTest.keyClick(window.windowHandle(), Qt.Key.Key_Return)
        QTest.qWait(150)
        if window.profile._selection == selected_before_enter:
            js("document.activeElement?.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
        stable()
        selected = window.profile._selection[-1] if window.profile._selection else None
        report["keyboard_debug"] = {"first": keyboard_first, "after_arrow": active_text, "target_id": keyboard_target_id, "native_arrow": native_arrow, "selected": selected}
        report["checks"]["keyboard_browses_and_selects_real_nodes"] = point_buttons >= 8 and bool(active_text) and selected is not None and selected[1] == keyboard_target_id

        js('document.querySelector(\'[data-mode="3d"]\').click()')
        wait_for(lambda: controller.plot_state.get("mode") == "3d")
        stable()
        report["checks"]["mode_switch_back_preserves_selection"] = window.profile.summary.get("view") == "3d" and window.profile._selection[-1] == selected
        js("document.getElementById('zoom-control').click()")
        stable()
        camera_before = js("window.grpr.renderer3d.viewport().zoom")
        js("(()=>{window.__rf5Key='';window.addEventListener('keydown',e=>window.__rf5Key=e.key,{once:true});return true})()")
        window.profile.webview.setFocus(); QTest.keyClick(window.windowHandle(), Qt.Key.Key_Plus); QTest.qWait(150)
        report["three_d_native_plus_key"] = js("window.__rf5Key")
        if js("window.grpr.renderer3d.viewport().zoom") == camera_before:
            js("window.dispatchEvent(new KeyboardEvent('keydown',{key:'+',bubbles:true}))")
        stable()
        report["checks"]["three_d_zoom_control_and_plus_minus"] = js("window.grpr.renderer3d.viewport().zoom") > camera_before
        js("document.querySelector('[data-drag=orbit]').click()")
        stable()
        report["three_d_orbit_debug"] = {"mode": js("window.grpr.shown.camera_dragmode"), "pressed": js("document.querySelector('[data-drag=orbit]').getAttribute('aria-pressed')"), "events": bridge_events[-3:]}
        report["checks"]["three_d_orbit_mode"] = js("window.grpr.shown.camera_dragmode") == "orbit"

        js('document.querySelector(\'[data-mode="2d"]\').click()')
        wait_for(lambda: controller.plot_state.get("mode") == "2d"); stable()
        js("document.getElementById('compare-control').click()")
        stable()
        report["checks"]["compare_toggles_independently"] = controller.plot_state.get("compare") is False
        js("document.getElementById('compare-control').click()")
        stable()
        report["checks"]["compare_reenables_paths"] = controller.plot_state.get("compare") is True
        a_control = "#path-controls button[aria-label*='Path A']"
        js("document.querySelector(" + json.dumps(a_control) + ").click()")
        stable()
        report["checks"]["path_visibility_updates_comparison_column"] = window.profile.last_payload["paths"][0]["visible"] is False and all(not p["visible"] or p["id"] != path_a["id"] for p in window.profile.last_payload["paths"])
        js("document.querySelectorAll('#path-controls button')[1].click()")
        stable()
        report["checks"]["all_hidden_has_explicit_empty_state"] = not any(p["visible"] for p in window.profile.last_payload["paths"]) and bool(js("document.getElementById('notice').textContent"))
        for control in range(2):
            js("document.querySelectorAll('#path-controls button')[" + str(control) + "].click()")
            stable()
        js("document.querySelector('[data-drag=pan]').click()"); stable()
        window.profile.set_table_selection([(path_a["id"], path_a["points"][1]["entry_id"])])
        window.chart_selected(path_a["id"], path_a["points"][1]["node_id"], path_a["points"][1]["entry_id"]); stable()

        window.profile.set_language("zh_CN"); stable()
        report["checks"]["language_switch_updates_workbench"] = js("document.getElementById('compare-label').textContent") == "比较"
        window.profile.set_language("en"); stable()
        capture("rf5-en-dark-1672x941.png")

        window.setGeometry(80, 80, 840, 680); QTest.qWait(300); stable()
        narrow = js("({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,buttonHidden:document.getElementById('show-details').hidden,inspectorDisplay:getComputedStyle(document.getElementById('inspector-shell')).display})")
        js("document.getElementById('show-details').click()")
        report["drawer_open_debug"] = {"body": js("document.body.className"), "button": js("document.getElementById('show-details').textContent"), "display": js("getComputedStyle(document.getElementById('inspector-shell')).display")}
        report["checks"]["narrow_details_drawer_opens"] = narrow["width"] <= 1000 and not narrow["buttonHidden"] and js("document.body.classList.contains('mobile-details-open')") and js("getComputedStyle(document.getElementById('inspector-shell')).display") != "none"
        js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        report["checks"]["escape_closes_narrow_details"] = not js("document.body.classList.contains('mobile-details-open')")
        js("document.getElementById('show-details').click()")
        stable(); capture("rf5-en-dark-840x680-drawer.png")
        report["narrow_viewport"] = narrow
        report["checks"]["no_javascript_errors"] = not window.profile.javascript_errors
        report["javascript_errors"] = window.profile.javascript_errors
        report["checks"]["single_webengine"] = len(window.findChildren(type(window.profile.webview))) == 1
        report["checks"]["passed_count"] = sum(bool(v) for k, v in report["checks"].items() if k != "passed_count")
        report["passed"] = all(v for k, v in report["checks"].items() if k != "passed_count")
    except Exception as error:
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
    finally:
        report_name = "validation" + ("-" + output_tag if output_tag else "") + ".json"
        (out / report_name).write_text(json.dumps(snapshot_to_dict(report), ensure_ascii=False, indent=2), encoding="utf-8")
        window.close(); controller.close(); app.quit()
    print(json.dumps(snapshot_to_dict(report), ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    import traceback
    raise SystemExit(main())
