"""Real Qt/WebGL matrix and bounded renderer-process measurements for EP6."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import statistics
import sys
from time import perf_counter, process_time
import traceback
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]
from diagnose_static_runtime import windows_affinity
modes, _, select_affinity = windows_affinity()
process_affinity = modes["default"] & 0xFFFFFF3F
select_affinity(process_affinity)

from PySide6 import __version__ as qt_version
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.presentation.palette import get_palette
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.ui.main_window import MainWindow
from check_s7 import js, rendered, settle, wait


def memory_snapshot():
    """Read this UI process and its own WebEngine descendants using Win32 APIs."""
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("image", wintypes.WCHAR * 260)]

    class Memory(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD),
                    ("peak_ws", ctypes.c_size_t), ("ws", ctypes.c_size_t),
                    ("peak_paged", ctypes.c_size_t), ("paged", ctypes.c_size_t),
                    ("peak_nonpaged", ctypes.c_size_t), ("nonpaged", ctypes.c_size_t),
                    ("pagefile", ctypes.c_size_t), ("peak_pagefile", ctypes.c_size_t),
                    ("private", ctypes.c_size_t)]

    kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(Entry))
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD)
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise OSError("Could not enumerate the QA process tree")
    processes = {}
    try:
        entry = Entry(); entry.size = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            processes[entry.pid] = (entry.parent, entry.image)
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    descendants = {os.getpid()}
    while True:
        expanded = descendants | {pid for pid, (parent, _) in processes.items() if parent in descendants}
        if expanded == descendants:
            break
        descendants = expanded
    rows, unavailable = [], []
    for pid in sorted(descendants):
        image = processes.get(pid, (None, "python"))[1]
        if pid != os.getpid() and "qtwebengine" not in image.lower():
            continue
        handle = kernel.OpenProcess(0x1010, False, pid)
        memory = Memory(); memory.size = ctypes.sizeof(memory)
        try:
            if not handle or not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.size):
                unavailable.append(pid)
                continue
            rows.append({"pid": pid, "image": image, "ui": pid == os.getpid(),
                         "working_set_bytes": memory.ws, "private_bytes": memory.private})
        finally:
            if handle:
                kernel.CloseHandle(handle)
    return {"processes": rows, "unavailable_pids": unavailable,
            "ui_private_bytes": sum(r["private_bytes"] for r in rows if r["ui"]),
            "webengine_private_bytes": sum(r["private_bytes"] for r in rows if not r["ui"])}


def listener_counts(page):
    return json.loads(js(page, "JSON.stringify((()=>{const p=document.getElementById('plot');"
        "return Object.fromEntries(['plotly_click','plotly_selected','plotly_relayout','plotly_legendclick',"
        "'plotly_webglcontextlost'].map(k=>{const e=p._ev&&p._ev._events&&p._ev._events[k];"
        "return [k,Array.isArray(e)?e.length:e?1:0]}))})())"))


def main(args):
    os.environ["QT_SCALE_FACTOR"] = str(args.scale_factor)
    run = ROOT / "artifacts/ui-glass/ep6" / uuid4().hex
    run.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    controller = ProjectController(run / "recovery", run / "preferences.ini")
    window = MainWindow(controller)
    report = {"passed": False, "run": str(run), "checks": {}, "screenshots": [], "metrics": {},
              "environment": {"python": sys.version, "qt": qt_version, "os": platform.platform(),
                              "process_affinity": hex(process_affinity), "qt_scale_factor": args.scale_factor,
                              "expected_dpr": args.expected_dpr, "actual_dpr": app.primaryScreen().devicePixelRatio()},
              "limits": ["Windows source checkout with process-local CPU compatibility mask",
                         "Synthetic four-point logs; real-log corpus and distribution packages are outside this EP stage",
                         "DPR values are process-level Qt scale simulations on this Windows desktop",
                         "Private bytes are measured for the UI and its WebEngine descendants; GPU/driver allocations are excluded",
                         "Bounded warmed 100-update samples have no pre-redesign baseline and do not prove absence of leaks"]}
    errors = []
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))

    def capture(name, widget=window):
        QTest.qWait(150)
        assert widget.grab().save(str(run / name))
        report["screenshots"].append(name)

    try:
        assert abs(app.primaryScreen().devicePixelRatio() - args.expected_dpr) < .05
        window.resize(1440, 1000); window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        files = []
        for name, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
            path = run / f"{name}.log"
            path.write_text("SYNTHETIC EP6 VALIDATION\nEntering Gaussian System\n"
                            f" SCF Done: E(RB3LYP) = {value-.03:.12f} A.U.\n"
                            f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                            " Normal termination of Gaussian 16\n", encoding="utf-8")
            files.append(path)
        controller.import_files(files); settle(controller)
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        controller.rename_node(controller.project.nodes[1].id, "TS1", "transition_state"); settle(controller)
        palette = get_palette("light")["colors"]
        controller.edit_path("color", palette["lavender"]); settle(controller)
        path_a = controller.selected_path
        controller.edit_path("copy", "Path B"); settle(controller)
        controller.edit_path("color", palette["sunset"]); settle(controller)
        controller.edit_path("copy", "Path C"); settle(controller)
        controller.edit_path("color", palette["lavender"]); settle(controller)
        controller.reference_node(controller.project.nodes[2].id); settle(controller)
        controller.set_workspace(path_id=path_a.id); window.refresh(); settle(controller)
        window.navigation.setCurrentRow(2)
        panel = window.profile
        rendered(panel)
        panel.compare_box.setChecked(True); settle(controller); rendered(panel)
        window.select_node(controller.project.nodes[1].id); settle(controller); rendered(panel)
        assert all(abs(a-b) < 1e-8 for a, b in zip(
            [p["value"] for p in panel.last_payload["paths"][0]["points"]],
            [0, 15.0602273775, -5.0200757925, -15.6877368516]))
        assert len(panel.last_payload["paths"]) == 3 and panel.last_payload["warnings"]
        report["checks"]["scientific_oracle_and_three_path_reference_warning"] = True
        original_science = (controller.project.nodes, controller.project.paths)

        # Full language/theme/size/dimension matrix; each screenshot is an actual Qt window grab.
        for language in (() if args.skip_matrix else ("zh_CN", "en")):
            window.language_combo.setCurrentIndex(window.language_combo.findData(language)); settle(controller)
            for theme in ("light", "dark"):
                window.theme_combo.setCurrentIndex(window.theme_combo.findData(theme)); settle(controller)
                for width, height in ((1440, 1000), (860, 680)):
                    window.resize(width, height); QTest.qWait(180)
                    if width < 1024:
                        window.compact_tabs.setCurrentIndex(1)
                    for dimension in (0, 1):
                        panel.view_combo.setCurrentIndex(dimension); settle(controller); rendered(panel)
                        assert panel.last_payload["dark"] == (theme == "dark")
                        assert panel.last_payload["language"] == language
                        assert panel.last_payload["view"] == ("3d" if dimension else "2d")
                        assert panel.export_button.isVisible() and panel.expand_button.isVisible()
                        assert panel.stack.width() >= 250 and panel.stack.height() >= 145
                        if not dimension and width < 1024:
                            assert js(panel.page, "document.getElementById('plot').layout.annotations.filter(a=>a.xref!=='paper').length") <= 4
                            assert js(panel.page, "document.getElementById('plot').layout.showlegend") is False
                        if dimension:
                            assert panel.summary["canvas_count"] > 0
                            if width < 1024:
                                assert js(panel.page, "document.getElementById('plot').layout.scene.zaxis.title.text") == "ΔG / kcal/mol"
                                assert js(panel.page, "document.getElementById('plot').layout.showlegend") is False
                            assert js(panel.page, "document.getElementById('plot').data.filter(t=>t.meta&&t.meta.kind==='visual-ribbon'&&t.hoverinfo==='skip').length") == len(panel.last_payload["paths"])
                        assert js(panel.page, "document.getElementById('plot').data.filter(t=>t.meta&&t.meta.kind==='computed-nodes').every(t=>t.marker.symbol==='circle')")
                        assert js(panel.page, "document.getElementById('plot').data.filter(t=>t.meta&&t.meta.kind==='visual-curve'&&t.hoverinfo==='skip').length") == len(panel.last_payload["paths"])
                        capture(f"{language}-{theme}-{width}-{2+dimension}d.png")
        if not args.skip_matrix:
            report["checks"]["cn_en_light_dark_wide_narrow_2d_3d_matrix"] = True
            report["checks"]["demo_smooth_glow_circle_nodes_and_3d_decorative_ribbons"] = True
        else:
            report["skipped_checks"] = ["language/theme/size/dimension matrix"]

        # Expanded plot shares the exact inspector; wide collapse and narrow hiding are session-only.
        window.resize(1440, 1000); QTest.qWait(200)
        window.language_combo.setCurrentIndex(window.language_combo.findData("en")); settle(controller)
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark")); settle(controller)
        panel.compare_box.setChecked(False)
        panel.view_combo.setCurrentIndex(0); settle(controller); rendered(panel)
        for index in (2, 1):
            entry = path_a.entries[index]
            position = json.loads(js(panel.page, "JSON.stringify(window.grpr.pointPosition("+
                json.dumps(path_a.id)+","+json.dumps(entry.id)+"))"))
            target = panel.webview.focusProxy() or panel.webview
            location = target.mapTo(window, QPoint(round(position["x"]), round(position["y"])))
            QTest.mouseMove(window.windowHandle(), location)
            QTest.qWait(150)  # Let Plotly's hover hit-test consume the pointer move before clicking.
            QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=location)
            wait(lambda: window._selected_node == entry.node_id, "actual glowing 2D marker selection", 6)
            settle(controller); rendered(panel)
        report["checks"]["actual_mouse_selects_real_nodes_through_glow_layers"] = True
        capture("demo-aligned-2d-workbench.png")
        panel.compare_box.setChecked(True)
        panel.reset_options({"hidden_paths": [controller.project.paths[-1].id]})
        panel.view_combo.setCurrentIndex(1); settle(controller); rendered(panel)
        capture("demo-aligned-3d-workbench.png")
        browser, details = panel.webview, window.plot_inspector
        old_parent = details.parentWidget()
        snapshot = details.snapshot
        panel.expand(); QTest.qWait(250); rendered(panel)
        dialog = panel._expanded
        dialog.showNormal(); dialog.resize(1440, 900); QTest.qWait(250)
        assert dialog.details_scroll.widget() is details and details.snapshot == snapshot
        assert panel.webview is browser and dialog.details_scroll.isVisible()
        assert "Transition state" in details.summary.text()
        capture("expanded-3d-details.png", dialog)
        dialog.details_toggle.click(); assert not dialog.details_scroll.isVisible()
        dialog.details_toggle.click(); assert dialog.details_scroll.isVisible()
        dialog.resize(880, 680); QTest.qWait(150)
        assert not dialog.details_scroll.isVisible() and not dialog.details_toggle.isVisible()
        capture("expanded-3d-narrow.png", dialog)
        dialog.resize(1440, 900); QTest.qWait(200)
        report["checks"]["expanded_shared_inspector_collapse_and_narrow_layout"] = True

        # Real mouse input is delivered through the WebEngine focus proxy to the live WebGL canvas.
        panel.camera_combo.activated.emit(1); QTest.qWait(200)
        camera_events = []
        def record_camera_event(raw):
            camera_events.append(json.loads(raw))
        panel.bridge.eventSignal.connect(record_camera_event)
        camera_before = json.loads(js(panel.page, "JSON.stringify(document.getElementById('plot')._fullLayout.scene._scene.getCamera())"))
        target = panel.webview.focusProxy() or panel.webview
        panel.webview.setFocus()
        js(panel.page, "window.ep6Mouse=[];['pointerdown','pointermove','pointerup','mousedown','mousemove','mouseup'].forEach(k=>document.addEventListener(k,e=>window.ep6Mouse.push({type:k,buttons:e.buttons,trusted:e.isTrusted,x:e.clientX,y:e.clientY,target:e.target.tagName,cls:String(e.target.className.baseVal||e.target.className)})));true")
        center = QPoint(round(target.width()*.52), round(target.height()*.50))
        native_window = dialog.windowHandle()
        center = target.mapTo(dialog, center)
        QTest.mouseMove(native_window, center)
        QTest.qWait(100)
        QTest.mousePress(native_window, Qt.MouseButton.LeftButton, pos=center)
        for step in range(1, 9):
            QTest.mouseMove(native_window, center + QPoint(step*12, step*5), 30)
        QTest.mouseRelease(native_window, Qt.MouseButton.LeftButton, pos=center + QPoint(96, 40))
        QTest.qWait(1000)
        settle(controller)
        def camera_synced():
            actual = json.loads(js(panel.page, "JSON.stringify(document.getElementById('plot')._fullLayout.scene._scene.getCamera())"))
            saved = controller.plot_state.get("viewports", {}).get(panel.last_payload["context"] + "/3d", {}).get("camera", {})
            return all(abs(saved.get("eye", {}).get(axis, 999)-actual["eye"][axis]) < 1e-6 for axis in ("x", "y", "z"))
        wait(camera_synced, "live drag camera persistence", 12)
        camera_after = json.loads(js(panel.page, "JSON.stringify(document.getElementById('plot')._fullLayout.scene._scene.getCamera())"))
        report["mouse_drag_events"] = json.loads(js(panel.page, "JSON.stringify(window.ep6Mouse)"))
        report["camera_after_mouse_drag"] = camera_after
        assert camera_after != camera_before, "Real mouse drag did not change the WebGL camera"
        settle(controller)
        saved = controller.plot_state["viewports"][panel.last_payload["context"] + "/3d"]["camera"]
        report["saved_camera_after_mouse_drag"] = {k: dict(v) for k, v in saved.items()}
        report["camera_bridge_events"] = camera_events
        report["camera_queue_state"] = js(panel.page, "JSON.stringify(window.grpr.queueState)")
        assert all(abs(saved["eye"][axis]-camera_after["eye"][axis]) < 1e-6 for axis in ("x", "y", "z"))
        panel.bridge.eventSignal.disconnect(record_camera_event)
        report["checks"]["real_mouse_webgl_rotation_and_camera_event_persistence"] = True
        dialog.close(); QTest.qWait(150)
        assert details.parentWidget() is old_parent and panel.webview is browser
        panel.reset_options({"hidden_paths": []}); settle(controller); rendered(panel)

        if not args.skip_performance:
            # Warm each mode before sampling private bytes; collect every 20 selections.
            window.resize(980, 820); QTest.qWait(150)
            window.compact_tabs.setCurrentIndex(1)
            for dimension in (0, 1):
                panel.view_combo.setCurrentIndex(dimension); settle(controller); rendered(panel)
                for index in range(10):
                    panel.set_table_selection([(path_a.id, path_a.entries[index % 4].id)]); rendered(panel)
                first_structure = (panel.summary["trace_count"], listener_counts(panel.page))
                assert all(count >= 1 for count in first_structure[1].values()), first_structure
                memory = [{"updates": 0, **memory_snapshot()}]
                render_before = js(panel.page, "window.grpr.renderCount")
                started, cpu_started, durations = perf_counter(), process_time(), []
                for index in range(100):
                    tick = perf_counter()
                    panel.set_table_selection([(path_a.id, path_a.entries[index % 4].id)]); rendered(panel)
                    durations.append(perf_counter() - tick)
                    assert panel.summary["trace_count"] == first_structure[0]
                    if (index+1) % 20 == 0:
                        memory.append({"updates": index+1, **memory_snapshot()})
                after_listeners = listener_counts(panel.page)
                assert after_listeners == first_structure[1]
                assert all(not sample["unavailable_pids"] and any(not p["ui"] for p in sample["processes"]) for sample in memory)
                report["metrics"][f"{2+dimension}d"] = {
                    "updates": 100, "wall_seconds": perf_counter()-started,
                    "ui_cpu_seconds": process_time()-cpu_started,
                    "median_update_seconds": statistics.median(durations),
                    "p95_update_seconds": sorted(durations)[94],
                    "render_count_before": render_before, "render_count_after": js(panel.page, "window.grpr.renderCount"),
                    "trace_count": first_structure[0], "listener_counts_before": first_structure[1],
                    "listener_counts_after": after_listeners, "memory_samples": memory}
                print(f"Completed {2+dimension}D: 100 updates, {first_structure[0]} traces", flush=True)
            report["checks"]["hundred_updates_per_mode_keep_trace_and_real_listener_counts"] = True
            report["checks"]["ui_and_webengine_private_memory_samples_recorded"] = True
        assert (controller.project.nodes, controller.project.paths) == original_science
        assert not errors and not panel.javascript_errors and not panel.blocked_requests
        report["checks"]["view_interactions_preserve_science_and_have_no_js_errors_or_remote_requests"] = True
        report.update(passed=True, errors=errors, javascript_errors=panel.javascript_errors,
                      blocked_remote_requests=panel.blocked_requests)
    except BaseException as error:
        report.update(error=str(error), traceback=traceback.format_exc(), errors=errors,
                      load_events=list(getattr(window.profile, "load_events", [])),
                      javascript_errors=list(getattr(window.profile, "javascript_errors", [])))
        capture("failure.png")
    finally:
        if getattr(window.profile, "_expanded", None):
            window.profile._expanded.close()
        if not controller._closed:
            settle(controller); controller.close(); wait(lambda: controller._closed, "close EP6 project")
        window.close(); app.processEvents()
        (run / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "run": str(run), "checks": report["checks"],
                          "error": report.get("error"), "skipped_checks": report.get("skipped_checks", []),
                          "metrics": {key: {"seconds": value["wall_seconds"], "updates": value["updates"],
                                             "traces": value["trace_count"]} for key, value in report["metrics"].items()}},
                         ensure_ascii=False, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale-factor", type=float, default=.8)
    parser.add_argument("--expected-dpr", type=float, default=1.)
    parser.add_argument("--skip-performance", action="store_true")
    parser.add_argument("--skip-matrix", action="store_true")
    raise SystemExit(main(parser.parse_args()))
