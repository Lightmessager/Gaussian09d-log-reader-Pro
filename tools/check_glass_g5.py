"""Desktop G5 checks with independent local preferences and synthetic data."""
import json
import os
from dataclasses import replace
from pathlib import Path
import sys
from time import perf_counter, process_time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.storage.preferences import LocalPreferences
from gaussianreadpro.ui.glass_widgets import GlassButton, GlassPanel
from gaussianreadpro.ui.main_window import MainWindow
from check_s7 import js, rendered, settle, wait


def current_process_memory():
    """Current Python UI process only; WebEngine child processes are excluded."""
    if os.name != "nt":
        return None
    from ctypes import POINTER, Structure, byref, c_size_t, sizeof, windll
    from ctypes import wintypes

    class ProcessMemoryCounters(Structure):
        _fields_ = [("cb", wintypes.DWORD), ("page_fault_count", wintypes.DWORD),
                    ("peak_working_set", c_size_t), ("working_set", c_size_t),
                    ("quota_peak_paged_pool", c_size_t), ("quota_paged_pool", c_size_t),
                    ("quota_peak_nonpaged_pool", c_size_t), ("quota_nonpaged_pool", c_size_t),
                    ("pagefile", c_size_t), ("peak_pagefile", c_size_t)]

    counters = ProcessMemoryCounters()
    counters.cb = sizeof(counters)
    kernel = windll.kernel32
    psapi = windll.psapi
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (wintypes.HANDLE, POINTER(ProcessMemoryCounters), wintypes.DWORD)
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), byref(counters), counters.cb):
        return None
    return {"working_set_bytes": counters.working_set, "private_bytes": counters.pagefile}


def main(stage="g5", expected_dpr=None):
    if stage not in ("g5", "g6"):
        raise ValueError("stage must be g5 or g6")
    qa_start = perf_counter()
    run = ROOT / "artifacts/ui-glass" / stage / uuid4().hex
    run.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    controller = ProjectController(run / "recovery", run / "preferences.ini")
    window = MainWindow(controller)
    report = {"passed": False, "run": str(run), "checks": {}, "python": sys.version,
            "platform": app.platformName(), "screenshots": [], "stage": stage,
            "screen_dpr": app.primaryScreen().devicePixelRatio(),
            "qt_scale_factor": os.environ.get("QT_SCALE_FACTOR"), "expected_dpr": expected_dpr}
    if os.name == "nt":
        from diagnose_static_runtime import windows_affinity
        masks, _, _ = windows_affinity()
        report["process_affinity"] = hex(masks["default"])
    checks = report["checks"]
    errors = []
    controller.failed.connect(lambda code, detail: errors.append([code, detail]))

    def capture(name, widget=None):
        QTest.qWait(200)
        assert (widget or window).grab().save(str(run / name))
        report["screenshots"].append(name)

    def shutdown():
        if not controller._closed:
            settle(controller)
            controller.close()
            wait(lambda: controller._closed, "Close QA project")
        window.close()
        app.processEvents()

    try:
        assert app.platformName() not in ("offscreen", "minimal")
        if expected_dpr is not None:
            assert abs(report["screen_dpr"] - expected_dpr) < .05, report["screen_dpr"]
        window.resize(1440, 920); window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        logs = []
        for name, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
            log = run / (name + ".log")
            log.write_text("SYNTHETIC G5 QA\nEntering Gaussian System\n"
                           f" SCF Done: E(RB3LYP) = {value-.03:.12f} A.U.\n"
                           f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                           " Normal termination of Gaussian 16\n", encoding="utf-8")
            logs.append(log)
        controller.import_files(logs); settle(controller)
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        window.navigation.setCurrentRow(2)
        panel = window.profile
        rendered(window.profile)
        first_chart_ready_seconds = perf_counter() - qa_start
        QTest.qWait(600); settle(controller)
        before = controller.project
        values = controller.results

        for language, theme, reduced, motion, size, filename in (
            ("zh_CN", "light", False, False, (1440, 1000), "standard-cn-light.png"),
            ("en", "dark", False, False, (1440, 1000), "standard-en-dark.png"),
            ("en", "dark", True, True, (1100, 820), "reduced-en-dark.png"),
            ("en", "dark", True, True, (860, 680), "reduced-en-dark-compact.png"),
            ("zh_CN", "light", True, True, (860, 680), "reduced-cn-compact.png"),
        ):
            window.language_combo.setCurrentIndex(window.language_combo.findData(language))
            window.theme_combo.setCurrentIndex(window.theme_combo.findData(theme))
            window.visual_effects_action.setChecked(reduced)
            window.motion_action.setChecked(motion)
            window.resize(*size)
            settle(controller); rendered(window.profile)
            QTest.qWait(220)
            assert window.backdrop.reduced == reduced
            assert all(panel.reduced == reduced for panel in window.findChildren(GlassPanel))
            assert app.property("glassReduceMotion") == motion
            if filename == "standard-en-dark":
                assert window.navigation.item(2).text() == "Paths"
                assert window.node_table.model().headerData(3, Qt.Orientation.Horizontal) == "ΔG / kcal/mol"
            if filename == "reduced-en-dark-compact":
                assert window.kind_combo.currentText() == "Gibbs"
                assert window.mode_combo.currentText() == "ΔG"
                assert window.unit_combo.currentText() == "kcal/mol"
            toolbar = window.appearance_button.parentWidget()
            for widget in (window.search, window.language_combo, window.theme_combo, window.appearance_button):
                assert widget.isVisible() and toolbar.rect().contains(widget.geometry()), (filename, widget.objectName())
            capture(filename)
        if stage == "g6":
            assert window.compact_tabs.isVisible() and window.compact_tabs.tabText(1) == "能量图"
            assert window.unit_combo.currentText() == "kcal/mol"
            assert panel.last_payload["kind"] == "gibbs_total" and panel.last_payload["mode"] == "relative"
            assert js(panel.page, "document.querySelector('.ytitle')?.textContent") == "ΔG / kcal/mol"
            checks["compact_energy_axis_matches_selected_gibbs_kind"] = True
            window.compact_tabs.setCurrentIndex(0); app.processEvents()
            assert window.node_table.viewport().height() >= 180
            capture("compact-nodes-cn.png")
            window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
            settle(controller); app.processEvents()
            assert window.compact_tabs.tabText(0) == "Path nodes" and window.compact_tabs.tabText(1) == "Energy chart"
            assert window.unit_combo.currentText() == "kcal/mol"
            window.compact_tabs.setCurrentIndex(1); app.processEvents()
            assert window.profile.height() >= 220 and window.chart_card.isVisible()
            assert js(panel.page, "document.querySelector('.ytitle')?.textContent") == "ΔG / kcal/mol"
            capture("compact-chart-en.png")
            checks["compact_focus_tabs_and_bilingual_labels"] = True

            # Check structural/listener stability while driving real chart selections.
            initial = dict(panel.summary)
            initial_render_count = js(panel.page, "window.grpr.renderCount")
            selected = controller.selected_path
            memory_before = current_process_memory()
            started, cpu_started = perf_counter(), process_time()
            for index in range(100):
                panel.set_table_selection([(selected.id, selected.entries[index % len(selected.entries)].id)])
                rendered(panel)
            memory_after = current_process_memory()
            report["metrics"] = {"qa_setup_to_first_chart_seconds": first_chart_ready_seconds,
                                  "hundred_chart_update_seconds": perf_counter()-started,
                                  "hundred_chart_update_cpu_seconds": process_time()-cpu_started,
                                  "python_ui_memory_before": memory_before,
                                  "python_ui_memory_after": memory_after,
                                  "memory_scope": "Python UI process; WebEngine child processes excluded",
                                  "chart_render_count_before": initial_render_count,
                                  "chart_render_count_after": js(panel.page, "window.grpr.renderCount"),
                                  "chart_listeners_bound": panel.summary.get("listeners_bound"),
                                  "chart_trace_count_before": initial.get("trace_count"),
                                  "chart_trace_count_after": panel.summary.get("trace_count"),
                                  "idle_cpu_sample": None}
            assert panel.summary.get("listeners_bound") == 1
            assert panel.summary.get("trace_count") == initial.get("trace_count")
            checks["one_hundred_chart_updates_keep_structure"] = True

            panel.view_combo.setCurrentIndex(1); settle(controller); rendered(panel)
            assert panel.summary.get("view") == "3d"
            capture("compact-chart-3d-en.png")
            QTest.mouseClick(panel.expand_button, Qt.MouseButton.LeftButton)
            QTest.qWait(250)
            assert getattr(panel, "_expanded", None) is not None
            capture("expanded-chart-3d-en.png", panel._expanded)
            panel._expanded.close(); QTest.qWait(200)
            checks["compact_real_3d_and_expanded_chart"] = True

            # A bounded idle sample; report the observed process CPU rather than FPS.
            idle_cpu, idle_wall = process_time(), perf_counter()
            QTest.qWait(1200); app.processEvents()
            report["metrics"]["idle_cpu_sample"] = {
                "cpu_seconds": process_time()-idle_cpu,
                "wall_seconds": perf_counter()-idle_wall}
            checks["idle_cpu_sample_recorded"] = True
        # Resizing can change the saved workspace; preferences must not alter science.
        assert controller.project.nodes == before.nodes and controller.project.paths == before.paths
        # Window/splitter workspace saves advance revision; compare every other
        # result field, including energies, references, dependencies and diagnostics.
        def scientific(results):
            return tuple(replace(result, revision=0,
                                 nodes=tuple(replace(node, revision=0) for node in result.nodes))
                         for result in results)
        assert scientific(controller.results) == scientific(values)
        checks["material_language_theme_and_compact_toolbar"] = True

        if stage == "g6":
            from gaussianreadpro.core.models import ImportState
            failed_source = run / "NoEnergy.log"
            failed_source.write_text("Entering Gaussian System\nNormal termination of Gaussian 16\n", encoding="utf-8")
            controller.import_files([failed_source]); settle(controller)
            assert controller.project.source_files[-1].import_state == ImportState.FAILED
            window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
            window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark"))
            window.resize(1100, 820)
            window.navigation.setCurrentRow(1)
            settle(controller); app.processEvents()
            model = window.source_table.model()
            failed_row = next(row for row in range(model.rowCount())
                              if model.index(row, 0).data(Qt.ItemDataRole.UserRole) == controller.project.source_files[-1].id)
            window.source_table.selectRow(failed_row)
            app.processEvents()
            assert "No energy fields were found" in window.source_detail.toPlainText()
            capture("source-failed-en-dark.png")
            checks["failed_source_row_visible"] = True
            window.theme_combo.setCurrentIndex(window.theme_combo.findData("light"))
            window.navigation.setCurrentRow(2)
            settle(controller)

        before = controller.project
        assert controller.update_preferences(language="zh_CN") and controller.busy
        window.motion_action.setChecked(False)
        window.motion_action.setChecked(True)
        settle(controller)
        assert controller.project == before
        stored = LocalPreferences(run / "preferences.ini").load()
        assert stored["visual_effects"] == "reduced" and stored["reduce_motion"] is True
        checks["queued_preferences_preserve_project"] = True

        window.appearance_menu.popup(window.appearance_button.mapToGlobal(QPoint(0, window.appearance_button.height())))
        QTest.qWait(150)
        capture("appearance-menu-cn.png", window.appearance_menu)
        window.appearance_menu.hide()
        button = window.import_button
        app.sendEvent(button, QEvent(QEvent.Type.Enter))
        assert button._edge == button._target()
        QTest.qWait(220)
        assert all(b._transition.state() == QAbstractAnimation.State.Stopped for b in window.findChildren(GlassButton))
        checks["reduced_motion_immediate_and_animations_idle"] = True

        # Close and bootstrap a new controller/window from the same INI file.
        controller.save(run / "project.grproj"); settle(controller)
        shutdown()
        controller = ProjectController(run / "recovery-reopened", run / "preferences.ini")
        controller.failed.connect(lambda code, detail: errors.append([code, detail]))
        window = MainWindow(controller)
        window.show(); controller.bootstrap(); settle(controller)
        assert window.visual_effects_action.isChecked() and window.motion_action.isChecked()
        assert window.backdrop.reduced and window.reduce_motion and window.language == "zh_CN"
        from gaussianreadpro.ui.batch_editor import BatchDialog
        controller.open_project(run / "project.grproj"); settle(controller)
        dialog = BatchDialog(controller, [controller.project.nodes[0].id], parent=window)
        dialog.show(); QTest.qWait(150)
        assert all(p.reduced for p in dialog.findChildren(GlassPanel))
        capture("reopened-reduced-dialog-cn.png", dialog)
        dialog.reject(); dialog.deleteLater()
        checks["restart_restores_options_and_new_dialog_inherits"] = True
        assert not errors
        report.update(passed=True, errors=errors)
    except BaseException as error:
        report.update(error=str(error), errors=errors,
                      load_events=list(getattr(getattr(window, "profile", None), "load_events", [])),
                      javascript_errors=list(getattr(getattr(window, "profile", None), "javascript_errors", [])))
        capture("failure.png")
        raise
    finally:
        shutdown()
        (run / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("g5", "g6"), default="g5")
    parser.add_argument("--expected-dpr", type=float)
    args = parser.parse_args()
    main(args.stage, args.expected_dpr)
