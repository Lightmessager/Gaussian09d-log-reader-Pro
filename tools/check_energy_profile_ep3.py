"""Native Qt/WebEngine acceptance for EP3 layered 3D chart controls."""
import json
from pathlib import Path
import sys
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]
from diagnose_static_runtime import windows_affinity
modes, _, select_affinity = windows_affinity()
process_affinity = modes["default"] & 0xFFFFFF3F
if process_affinity:
    select_affinity(process_affinity)

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.storage import ProjectRepository
from gaussianreadpro.ui.main_window import MainWindow
from check_s7 import js, rendered, settle, wait


def main():
    output = ROOT / "artifacts" / "ui-glass" / "ep3" / uuid4().hex
    output.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    controller = ProjectController(output / "recovery", output / "preferences.ini")
    window = MainWindow(controller)
    errors, checks, screenshots = [], {}, []
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))
    reopened_controller = reopened_window = None

    def capture(name, widget=None):
        QTest.qWait(180)
        assert (widget or window).grab().save(str(output / name))
        screenshots.append(name)

    try:
        window.resize(1440, 1000)
        window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        files = []
        for name, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
            path = output / f"{name}.log"
            path.write_text("SYNTHETIC EP3 QA\nEntering Gaussian System\n"
                            f" SCF Done: E(RB3LYP) = {value-.03:.12f} A.U.\n"
                            f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                            " Normal termination of Gaussian 16\n", encoding="utf-8")
            files.append(path)
        controller.import_files(files); settle(controller)
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        controller.rename_node(controller.project.nodes[1].id, "TS1", "transition_state"); settle(controller)
        window.navigation.setCurrentRow(2)
        panel = window.profile
        rendered(panel)
        path_a = controller.selected_path

        panel.view_combo.setCurrentIndex(1)
        settle(controller); rendered(panel)
        assert panel.last_payload["view"] == "3d"
        assert panel.summary["canvas_count"] > 0, panel.warning.text()
        assert any(panel.last_payload["text"]["category"] in warning for warning in panel.last_payload["warnings"])
        one = js(panel.page, "JSON.stringify({types:document.getElementById('plot').data.map(t=>t.type),"+
                    "drag:document.getElementById('plot').layout.scene.dragmode})")
        one = json.loads(one)
        assert one["types"].count("mesh3d") == 3
        assert one["types"].count("scatter3d") == 9
        checks["single_path_webgl_and_category_depth_notice"] = True
        capture("single-path-3d.png")
        panel.expand()
        QTest.qWait(300); rendered(panel)
        capture("single-path-3d-expanded.png", panel._expanded)
        panel._expanded.close(); QTest.qWait(250)

        controller.edit_path("copy", "Path B"); settle(controller)
        path_b = controller.selected_path
        controller.reference_node(controller.project.nodes[2].id); settle(controller)
        controller.edit_path("color", "#F4A06A"); settle(controller)
        panel.set_language("en")
        panel.compare_box.setChecked(True)
        settle(controller); rendered(panel)
        assert len(panel.last_payload["paths"]) == 2
        assert any("References differ" in warning for warning in panel.last_payload["warnings"])
        two = js(panel.page, "JSON.stringify(document.getElementById('plot').layout.scene.yaxis.ticktext)")
        assert json.loads(two) == [path["label"] for path in panel.last_payload["paths"]]
        checks["two_path_names_and_reference_warning"] = True
        capture("two-path-reference-warning.png")

        controller.edit_path("copy", "Path C"); settle(controller)
        path_c = controller.selected_path
        controller.edit_path("color", "#A88BDF"); settle(controller)
        panel.set_language("en"); settle(controller); rendered(panel)
        assert len(panel.last_payload["paths"]) == 3
        scene = json.loads(js(panel.page, "JSON.stringify((()=>{const p=document.getElementById('plot');"+
            "return {types:p.data.map(t=>t.type),ticks:p.layout.scene.yaxis.ticktext,"+
            "plane:p.data.filter(t=>t.type==='mesh3d'&&t.legendgroup==='zero-plane').map(t=>({hover:t.hoverinfo,opacity:t.opacity})),"+
            "projections:p.data.filter(t=>t.type==='scatter3d'&&t.type==='scatter3d'&&t.line&&t.line.dash==='dot').map(t=>t.hoverinfo),"+
            "markers:p.data.filter(t=>t.customdata).length,drag:p.layout.scene.dragmode}})())"))
        assert scene["types"].count("mesh3d") == 7
        assert scene["types"].count("scatter3d") == 27
        assert scene["ticks"] == [path["label"] for path in panel.last_payload["paths"]]
        assert scene["plane"] == [{"hover": "skip", "opacity": 0.09}]
        assert len(scene["projections"]) == 6 and all(value == "skip" for value in scene["projections"])
        assert scene["markers"] == 3
        assert panel.summary["canvas_count"] > 0
        checks["three_paths_layered_with_constant_auxiliary_traces"] = True
        capture("three-paths-en-3d.png")

        # Camera interaction runs in the live WebEngine scene and its relayout event is persisted.
        panel.dragmode_combo.setCurrentIndex(1)
        assert js(panel.page, "document.getElementById('plot').layout.scene.dragmode") == "pan"
        panel.dragmode_combo.setCurrentIndex(0)
        assert js(panel.page, "document.getElementById('plot').layout.scene.dragmode") == "orbit"
        camera_before = json.loads(js(panel.page, "JSON.stringify(document.getElementById('plot')._fullLayout.scene.camera)"))
        panel.camera_combo.activated.emit(2)
        wait(lambda: json.loads(js(panel.page, "JSON.stringify(document.getElementById('plot')._fullLayout.scene.camera)")) != camera_before,
             "path-aligned camera preset", 8)
        settle(controller)
        checks["camera_presets_rotate_live_webgl_scene"] = True
        panel.camera_combo.activated.emit(1)
        wait(lambda: abs(controller.plot_state.get("viewports", {}).get(panel.last_payload["context"]+"/3d",{}).get("camera",{}).get("eye",{}).get("x",0)+1.1)<1e-6,
             "isometric camera persistence")
        panel.camera_combo.activated.emit(3)
        wait(lambda: abs(controller.plot_state.get("viewports", {}).get(panel.last_payload["context"]+"/3d",{}).get("camera",{}).get("eye",{}).get("z",0)-3.0)<1e-6,
             "top-down camera persistence")
        panel.camera_combo.activated.emit(4)
        settle(controller); rendered(panel)
        assert abs(panel.last_payload["viewport"]["camera"]["eye"]["z"] - 3.0) < 1e-6
        checks["camera_presets_pan_orbit_and_saved_camera_restore"] = True
        capture("camera-presets-en-3d.png")

        # The existing plotly_click bridge is exercised with a rendered WebGL marker identity.
        marker = js(panel.page, "JSON.stringify(document.getElementById('plot').data.find(t=>t.customdata).customdata[1])")
        marker = json.loads(marker)
        js(panel.page, "const p=document.getElementById('plot'),t=p.data.find(x=>x.customdata);"+
           "p.emit('plotly_click',{points:[{customdata:t.customdata[1]}],event:{ctrlKey:false,shiftKey:false}});true")
        wait(lambda: window._selected_node == marker[2], "3D marker selection round trip")
        settle(controller); rendered(panel)
        checks["webgl_marker_selection_bridge"] = True

        # Several updates must reuse the same path-bounded trace set and one listener set.
        trace_count = panel.summary["trace_count"]
        for index in range(12):
            entry = path_a.entries[index % len(path_a.entries)]
            panel.set_table_selection([(path_a.id, entry.id)])
            rendered(panel)
        assert panel.summary["trace_count"] == trace_count == 34
        assert panel.summary["listeners_bound"] == 1
        checks["repeated_updates_do_not_accumulate_traces_or_listeners"] = True

        # Export both supported 3D artifacts from the same live Plotly figure.
        assert panel.export_to(output / "export-3d-png", "png", language="en")
        wait(lambda: not panel._capture and (output / "export-3d-png" / "profile.png").is_file(), "3D PNG export", 45)
        settle(controller)
        screenshots.append("export-3d-png/profile.png")
        assert panel.export_to(output / "export-3d-html", "html", language="en")
        settle(controller)
        assert (output / "export-3d-html" / "profile.html").is_file()
        checks["3d_png_and_offline_html_exports"] = True

        # Keep the selected path aligned with the camera context before saving the project.
        controller.set_workspace(path_id=path_c.id)
        panel.refresh(); settle(controller); rendered(panel)
        assert panel.last_payload["context"].split("/")[1] == path_c.id
        project_file = output / "EP3-study.grproj"
        controller.save(project_file); settle(controller)
        with ProjectRepository(project_file, read_only=True) as repository:
            restored = repository.load()
        # Each path has its own camera; dictionary order is unrelated to the active context.
        camera_key = panel.last_payload["context"] + "/3d"
        saved_camera = restored.plot_state["viewports"][camera_key]["camera"]
        assert abs(saved_camera["eye"]["z"] - 3.0) < 1e-6
        controller.close(); wait(lambda: controller._closed, "close EP3 source project")
        reopened_controller = ProjectController(output / "recovery-reopen", output / "preferences-reopen.ini")
        reopened_window = MainWindow(reopened_controller)
        reopened_window.resize(1440, 1000); reopened_window.show()
        reopened_controller.open_project(project_file); settle(reopened_controller)
        rendered(reopened_window.profile)
        reopened_window.profile.view_combo.setCurrentIndex(1)
        settle(reopened_controller); rendered(reopened_window.profile)
        reopened_camera_key = reopened_window.profile.last_payload["context"] + "/3d"
        restored_camera = reopened_window.profile.last_payload["viewport"].get("camera")
        assert restored_camera == saved_camera, {
            "saved_key": camera_key,
            "reopened_key": reopened_camera_key,
            "stored_keys": list(reopened_controller.plot_state["viewports"]),
            "saved_paths": [(path.id, path.label) for path in restored.paths],
            "reopened_paths": [(path.id, path.label) for path in reopened_controller.project.paths],
            "saved_workspace": dict(restored.workspace_state),
            "reopened_workspace": dict(reopened_controller.workspace),
            "reopened_camera": restored_camera,
            "saved_camera": saved_camera,
        }
        live_camera = json.loads(js(reopened_window.profile.page,
                                    "JSON.stringify(document.getElementById('plot')._fullLayout.scene.camera)"))
        assert live_camera["eye"] == dict(saved_camera["eye"])
        checks["camera_restored_after_project_reopen"] = True
        capture("reopened-saved-camera-3d.png", reopened_window)

        # Exercise the WebGL-unavailable fallback without changing global machine settings.
        reopened_panel = reopened_window.profile
        js(reopened_panel.page, "window.GRPR_FORCE_NO_WEBGL=true;true")
        reopened_panel.view_combo.setCurrentIndex(0); settle(reopened_controller); rendered(reopened_panel)
        reopened_panel.view_combo.setCurrentIndex(1)
        wait(lambda: reopened_controller.plot_state.get("mode") == "2d", "forced WebGL fallback")
        settle(reopened_controller); rendered(reopened_panel)
        assert "WebGL" in reopened_panel.warning.text()
        checks["webgl_fallback_to_2d"] = True
        js(reopened_panel.page, "window.GRPR_FORCE_NO_WEBGL=false;true")

        assert not errors and not panel.blocked_requests and not panel.javascript_errors
        report = {"passed": True, "platform": app.platformName(), "checks": checks,
                  "process_affinity": hex(process_affinity), "screenshots": screenshots,
                  "run": str(output), "errors": errors,
                  "javascript_errors": panel.javascript_errors,
                  "blocked_remote_requests": panel.blocked_requests,
                  "final_trace_count": trace_count}
    except BaseException as error:
        panel = window.profile
        report = {"passed": False, "platform": app.platformName(), "checks": checks,
                  "process_affinity": hex(process_affinity), "screenshots": screenshots,
                  "run": str(output), "error": str(error), "traceback": traceback.format_exc(),
                  "errors": errors,
                  "load_events": list(getattr(panel, "load_events", [])),
                  "javascript_errors": list(getattr(panel, "javascript_errors", []))}
        window.grab().save(str(output / "failure.png"))
    finally:
        for instance in (controller, reopened_controller):
            if instance and not instance._closed:
                if instance.busy:
                    wait(lambda i=instance: not i.busy, "finish EP3 worker", 120)
                instance.close(); wait(lambda i=instance: i._closed, "close EP3 project")
        if reopened_window:
            reopened_window.close()
        window.close(); app.processEvents()
        (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
