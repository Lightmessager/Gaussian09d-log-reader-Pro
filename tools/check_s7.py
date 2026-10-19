"""Native offline Plotly/exports check; no renderer sandbox bypasses."""
import json
from pathlib import Path
import sys
import shutil
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.ui.main_window import MainWindow
from gaussianreadpro.ui.theme import apply_theme
from gaussianreadpro.storage import ProjectRepository
from gaussianreadpro.validation_rf7 import memory_snapshot


def wait(test, description, timeout=30):
    deadline = monotonic() + timeout
    while not test():
        QTest.qWait(10)
        if monotonic() > deadline:
            raise TimeoutError(description)


def settle(controller):
    wait(lambda: not controller.busy and not controller._workspace_dirty and not controller._plot_dirty, controller.operation,
         180 if controller.operation == "export" else 30)


def rendered(panel):
    wait(lambda: panel.failure or panel.ready and panel.last_payload and panel.summary.get("render_id") == panel.last_payload["render_id"], "render handshake")
    if panel.failure:
        raise RuntimeError(panel.failure + " / " + str(panel.javascript_errors))


def js(page, code):
    result = []
    page.runJavaScript(code, lambda data: result.append(data))
    wait(lambda: bool(result), "JavaScript callback")
    return result[0]


def main():
    output = ROOT / "artifacts/s7"
    run = output / "runs" / uuid4().hex
    run.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    controller = ProjectController(run / "recovery", run / "preferences.ini")
    window = MainWindow(controller)
    errors, checks, performance = [], {}, {}
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))
    extra_view = None
    try:
        window.resize(1540, 1080)
        window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        paths = []
        for name, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
            file = run / (name + ".log")
            file.write_text("SYNTHETIC S7 VALIDATION\nEntering Gaussian System\n"
                            f" SCF Done: E(RB3LYP) = {value-.03:.12f} A.U.\n"
                            " Thermal correction to Gibbs Free Energy= 0.030000000000\n"
                            f" Sum of electronic and thermal Free Energies= {value:.12f}\n Normal termination of Gaussian 16\n", encoding="utf-8")
            paths.append(file)
        window.import_paths(paths); settle(controller)
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        controller.rename_node(controller.project.nodes[0].id, "反应物 R · α", "reactant"); settle(controller)
        controller.rename_node(controller.project.nodes[1].id, "TS1 · ΔG‡", "transition_state"); settle(controller)
        panel = window.profile
        rendered(panel)
        expected = [n.display_value for n in controller.results[0].nodes]
        actual = [p["value"] for p in panel.summary["points"]]
        assert actual == expected
        checks["current_core_values"] = True
        path = controller.selected_path
        key = (path.id, path.entries[1].id)
        QTest.qWait(500)  # The newly shown page finishes Plotly's responsive resize.
        position = json.loads(js(panel.page, "JSON.stringify(window.grpr.pointPosition("+json.dumps(key[0])+","+json.dumps(key[1])+"))"))
        panel.webview.setFocus()
        js(panel.page, "window.probeClicks=[]; document.addEventListener('mousedown',e=>window.probeClicks.push({x:e.clientX,y:e.clientY,target:e.target.tagName,cls:String(e.target.className.baseVal||e.target.className)})); true")
        QTest.mouseMove(panel.webview.focusProxy() or panel.webview, QPoint(round(position["x"]), round(position["y"])))
        QTest.qWait(200)
        QTest.mouseClick(panel.webview.focusProxy() or panel.webview, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(position["x"]), round(position["y"])))
        wait(lambda: window._selected_node == path.entries[1].node_id, "actual chart mouse click")
        settle(controller); rendered(panel)
        checks["actual_mouse_roundtrip"] = True
        window.select_node(path.entries[2].node_id)
        settle(controller); rendered(panel)
        assert js(panel.page, "window.grpr.shown.paths[0].points[2].selected")
        checks["table_to_plot_selection"] = True
        panel.set_table_selection([(path.id,path.entries[0].id),(path.id,path.entries[1].id)])
        QTest.mouseClick(panel.barrier_button,Qt.MouseButton.LeftButton)
        settle(controller); rendered(panel)
        assert panel.last_payload["barrier"] and panel.last_payload["barrier"]["value"]==expected[1]
        checks["explicit_local_barrier"] = True
        panel.reset_options({"barrier":None})
        settle(controller); rendered(panel)
        # Plotly.react can still be settling after the Qt payload handshake.
        QTest.qWait(250)
        js(panel.page, "Plotly.relayout(document.querySelector('#plot .plotly-host'), {'xaxis.range':[-0.7,3.7], 'yaxis.range':[-22,23]}); true")
        wait(lambda: bool(controller.plot_state.get("viewports")), "viewport event")
        settle(controller); rendered(panel)
        context = panel.last_payload["context"] + "/2d"
        assert list(controller.project.plot_state["viewports"][context]["x_range"]) == [-.7,3.7]
        js(panel.page, "Plotly.relayout(document.querySelector('#plot .plotly-host'), {'annotations[0].ax':22, 'annotations[0].ay':-48}); true")
        settle(controller); rendered(panel)
        assert controller.plot_state.get("label_offsets")
        assert [p["value"] for p in panel.summary["points"]] == expected
        checks["viewport_and_label_offsets_preserve_values"] = True
        controller.edit_path("copy", "路径 β / comparison"); settle(controller)
        controller.edit_path("color", "#d59139"); settle(controller)
        if not panel.compare_box.isChecked():
            QTest.mouseClick(panel.compare_box, Qt.MouseButton.LeftButton)
        settle(controller); rendered(panel)
        assert len(panel.last_payload["paths"]) == 2
        checks["multi_path_comparison"] = True
        js(panel.page,"Plotly.Fx.unhover(document.querySelector('#plot .plotly-host')); true")
        QTest.mouseMove(window, QPoint(25,25))
        QTest.qWait(150)
        assert window.grab().save(str(output / "profile-2d.png"))
        export_started = monotonic()
        for format in ("png", "svg", "pdf", "html"):
            assert panel.export_to(run / ("export-2d-" + format), format, language="zh_CN")
            settle(controller)
            assert (run / ("export-2d-"+format) / ("profile."+format)).is_file()
            if format != "html":
                shutil.copyfile(run/("export-2d-"+format)/("profile."+format),output/("export-2d."+format))
        checks["two_dimensional_exports"] = True
        performance["2d_four_exports_ms"] = round((monotonic() - export_started) * 1000, 3)
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
        from gaussianreadpro.prototype import OfflineRequests
        extra_view = QWebEngineView()
        exported_profile = QWebEngineProfile(extra_view)
        exported_requests = OfflineRequests(exported_profile)
        exported_profile.setUrlRequestInterceptor(exported_requests)
        exported_page = QWebEnginePage(exported_profile, extra_view)
        extra_view.setPage(exported_page)
        extra_view.resize(1100, 760)
        extra_view.show()
        extra_view.load(QUrl.fromLocalFile(str(run / "export-2d-html/profile.html")))
        wait(lambda: bool(js(exported_page, "Boolean(window.grpr && window.grpr.shown)")), "portable offline HTML")
        assert js(exported_page,"window.grpr.shown.paths[0].points[1].value") == expected[1]
        js(exported_page,"Plotly.relayout(document.querySelector('#plot .plotly-host'), {'xaxis.range':[-1,5]}); true")
        wait(lambda:js(exported_page,"window.grpr.shown.viewport.x_range && window.grpr.shown.viewport.x_range[1]===5"),"standalone viewport")
        count=js(exported_page,"window.grpr.renderCount")
        js(exported_page,"document.querySelector('#plot .plotly-host').emit('plotly_legendclick',{curveNumber:2}); true")
        wait(lambda:js(exported_page,"window.grpr.renderCount")>count,"standalone legend redraw")
        assert js(exported_page,"document.querySelector('#plot .plotly-host').layout.xaxis.range[1]")==5
        js(exported_page,"document.querySelector('[data-mode=\"3d\"]').click(); true")
        try:
            wait(lambda:js(exported_page,"window.grpr.shown.view==='3d'"),"standalone 3D toggle")
        except TimeoutError:
            print("standalone_3d_notice=", js(exported_page, "document.getElementById('notice').textContent"), flush=True)
            raise
        assert js(exported_page,"Boolean(window.grpr.renderer3d && window.grpr.renderer3d.nodes.length)")
        assert not exported_requests.blocked
        checks["portable_html_without_qt_bridge"] = True
        extra_view.setPage(None)
        exported_page.deleteLater()
        extra_view.close()
        app.processEvents()
        panel.view_combo.setCurrentIndex(1)
        settle(controller); rendered(panel)
        assert panel.summary["view"] == "3d" and panel.summary["renderer"] == "Three.js" and panel.summary["labels"] > 0, panel.warning.text()
        js(panel.page,"window.grpr.renderer3d.orbit(15,-8); window.grpr.renderer3d.commit(); true")
        settle(controller); rendered(panel)
        assert controller.plot_state["viewports"][panel.last_payload["context"]+"/3d"]["three_v1"]["projection"]=="orthographic"
        QTest.qWait(300)
        assert window.grab().save(str(output / "profile-3d.png"))
        export_3d_started = monotonic()
        assert panel.export_to(run / "export-3d-png", "png", language="en")
        wait(lambda: not panel._capture and (run / "export-3d-png/profile.png").is_file(), "3D PNG capture", 40)
        settle(controller)
        shutil.copyfile(run/"export-3d-png/profile.png",output/"export-3d.png")
        assert panel.export_to(run / "export-3d-html", "html", language="en")
        settle(controller)
        performance["3d_png_html_exports_ms"] = round((monotonic() - export_3d_started) * 1000, 3)
        checks["real_three_scene_and_png"] = True
        window.language_combo.setCurrentIndex(window.language_combo.findData("en")); settle(controller)
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark")); settle(controller); rendered(panel)
        QTest.qWait(150)
        window.grab().save(str(output/"profile-en-dark.png"))
        QTest.mouseClick(panel.expand_button,Qt.MouseButton.LeftButton)
        QTest.qWait(350)
        assert panel._expanded and panel._expanded.grab().save(str(output/"profile-expanded.png"))
        panel._expanded.close()
        QTest.qWait(250)
        window.resize(1000,820)
        QTest.qWait(250)
        window.grab().save(str(output/"profile-compact.png"))
        window.resize(1540,1080)
        QTest.qWait(250)
        checks["bilingual_themes_expand_and_compact"] = True
        panel.view_combo.setCurrentIndex(0)
        settle(controller); rendered(panel)
        original_count = panel.summary["trace_count"]
        original_svg_count = panel.summary["svg_count"]
        performance["memory_before_100_updates"] = memory_snapshot()
        updates_started = monotonic()
        for index in range(100):
            panel.set_table_selection([(controller.selected_path.id, controller.selected_path.entries[index % 4].id)])
            rendered(panel)
        performance["hundred_updates_ms"] = round((monotonic() - updates_started) * 1000, 3)
        QTest.qWait(300)
        performance["memory_after_100_updates"] = memory_snapshot()
        assert panel.summary["trace_count"] == original_count
        assert panel.summary["listeners_bound"] == 1
        assert panel.summary["svg_count"] == original_svg_count
        checks["hundred_updates_stable_structure"] = True
        stale = {"type":"select", "project_id":controller.project.id, "revision":-1,
                 "render_id":panel.last_payload["render_id"], "points":[{"path_id":path.id,"entry_id":path.entries[0].id,"node_id":path.entries[0].node_id}]}
        selected = window._selected_node
        panel.handle_event(json.dumps(stale))
        assert window._selected_node == selected
        checks["stale_events_ignored"] = True
        js(panel.page, "window.GRPR_FORCE_NO_WEBGL=true; true")
        panel.view_combo.setCurrentIndex(1)
        wait(lambda: controller.plot_state.get("mode") == "2d", "WebGL fallback")
        settle(controller); rendered(panel)
        assert "WebGL" in panel.warning.text()
        checks["webgl_fallback"] = True
        project_file = run / "S7-study.grproj"
        settle(controller)
        assert controller.save(project_file), "Save was not submitted"
        settle(controller)
        assert project_file.is_file(), f"Save did not create project: {errors}"
        with ProjectRepository(project_file, read_only=True) as repository:
            restored = repository.load()
        assert restored.plot_state == controller.project.plot_state
        checks["saved_plot_state"] = True
        assert not errors and not panel.blocked_requests
        report = {"passed": True, "platform": app.platformName(), "checks": checks, "errors": errors,
                  "performance": performance,
                  "javascript_errors": panel.javascript_errors, "blocked_remote_requests": panel.blocked_requests,
                  "project": str(project_file), "run": str(run), "values": expected,
                  "final_summary": panel.summary}
        controller.close(); wait(lambda:controller._closed,"close for reopen")
        new_controller=ProjectController(run/"recovery-2",run/"preferences-2.ini")
        new_window=MainWindow(new_controller)
        new_window.resize(1460,1000)
        new_window.show()
        new_controller.open_project(project_file); settle(new_controller); rendered(new_window.profile)
        assert new_controller.project.plot_state==restored.plot_state
        assert new_window.profile.last_payload["viewport"]==panel.last_payload["viewport"]
        checks["fresh_window_restores_viewport_and_camera"] = True
        new_controller.close(); wait(lambda:new_controller._closed,"close reopened window")
        (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "failure.json").unlink(missing_ok=True)
        (output / "failure.png").unlink(missing_ok=True)
        print(json.dumps({"passed":True,"checks":checks,"run":str(run)}, ensure_ascii=True, indent=2))
    except BaseException as error:
        panel = window.profile
        window.grab().save(str(output / "failure.png"))
        (output / "failure.json").write_text(json.dumps({"error":str(error),"failure":panel.failure,"summary":panel.summary,
            "js":panel.javascript_errors,"events":errors,"loads":panel.load_events,
            "controller":{"operation":controller.operation,"busy":controller.busy,"revision":controller.project.revision,
                          "workspace_dirty":controller._workspace_dirty,"plot_dirty":controller._plot_dirty},
            "clicks":js(panel.page,"JSON.stringify(window.probeClicks)") if panel.ready else None},ensure_ascii=False,indent=2),encoding="utf-8")
        raise
    finally:
        if controller.busy:
            wait(lambda:not controller.busy, "finish worker", 180)
        if not controller._closed:
            controller.close(); wait(lambda:controller._closed, "close")
        app.processEvents()


if __name__ == "__main__":
    main()
