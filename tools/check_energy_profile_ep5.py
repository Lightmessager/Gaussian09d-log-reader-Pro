"""Native Windows acceptance for EP5 view-state persistence and offline exports."""
import hashlib
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

from PySide6.QtCore import QUrl
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.storage import ProjectRepository, StorageError
from gaussianreadpro.ui.main_window import MainWindow
from check_s7 import js, rendered, settle, wait


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _inspect_offline_html(app, page_path):
    view = QWebEngineView()
    loaded = []
    view.loadFinished.connect(loaded.append)
    view.load(QUrl.fromLocalFile(str(page_path.resolve())))
    wait(lambda: bool(loaded), "standalone HTML load", 40)
    if not loaded[-1]:
        raise AssertionError(f"offline HTML failed to load: {page_path}")
    wait(lambda: js(view.page(), "!!(window.grpr && document.getElementById('plot')._fullLayout)"),
         "standalone Plotly render", 40)
    result = []
    view.page().runJavaScript("JSON.stringify({plotly:!!window.Plotly,rendered:!!document.getElementById('plot')._fullLayout,"
                              "traces:(document.getElementById('plot').data||[]).length})", result.append)
    wait(lambda: bool(result), "standalone render details")
    details = json.loads(result[0])
    assert details["plotly"] and details["rendered"] and details["traces"] > 0, details
    view.close()
    app.processEvents()
    return details


def main():
    output = ROOT / "artifacts" / "ui-glass" / "ep5" / uuid4().hex
    output.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    controller = ProjectController(output / "recovery", output / "preferences.ini")
    window = MainWindow(controller)
    errors, checks, artifacts = [], {}, []
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))
    readonly_controller = readonly_window = reopened_controller = reopened_window = None
    try:
        window.resize(1440, 1000)
        window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        files = []
        for name, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
            path = output / f"{name}.log"
            path.write_text("SYNTHETIC EP5 VALIDATION\nEntering Gaussian System\n"
                            f" SCF Done: E(RB3LYP) = {value-.03:.12f} A.U.\n"
                            f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                            " Normal termination of Gaussian 16\n", encoding="utf-8")
            files.append(path)
        controller.import_files(files); settle(controller)
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        controller.edit_path("copy", "Path B"); settle(controller)
        path_ids = [path.id for path in controller.project.paths]
        window.navigation.setCurrentRow(2)
        settle(controller)
        panel = window.profile
        rendered(panel)

        # 2D packages: every supported paper format is actually rendered by the Qt app's export path.
        QTest.qWait(200)
        assert window.grab().save(str(output / "energy-profile-2d.png"))
        artifacts.append("energy-profile-2d.png")
        for format in ("png", "svg", "pdf", "html"):
            destination = output / f"2d-{format}"
            assert panel.export_to(destination, format, language="zh_CN" if format == "pdf" else "en")
            settle(controller)
            primary = destination / f"profile.{format}"
            assert primary.is_file() and primary.stat().st_size > 500, (format, primary)
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["view"] == "2d" and manifest["primary"] == primary.name
            for name, item in manifest["files"].items():
                assert _sha(destination / name) == item["sha256"]
            artifacts.append(primary.relative_to(output).as_posix())
            if format == "svg":
                from PySide6.QtSvg import QSvgRenderer
                renderer = QSvgRenderer(str(primary))
                assert renderer.isValid()
                preview = QImage(QSize(1760, 1040), QImage.Format.Format_ARGB32)
                preview.fill(0xffffffff)
                painter = QPainter(preview); renderer.render(painter); painter.end()
                assert preview.save(str(destination / "rendered-svg.png"))
                artifacts.append("2d-svg/rendered-svg.png")
                checks["svg_opens_in_native_renderer"] = True
            if format == "pdf":
                from PySide6.QtPdf import QPdfDocument
                document = QPdfDocument(None)
                assert document.load(str(primary)) == QPdfDocument.Error.None_
                assert document.pageCount() == 1
                preview = document.render(0, QSize(1760, 1040))
                assert not preview.isNull() and preview.save(str(destination / "rendered-pdf.png"))
                document.close()
                artifacts.append("2d-pdf/rendered-pdf.png")
                checks["chinese_pdf_opens_in_native_renderer"] = True
            if format == "html":
                html_text = primary.read_text(encoding="utf-8")
                assert "src=\"assets/plotly.min.js\"" in html_text
                assert "connect-src 'none'" in html_text and "cdn.plot.ly" not in html_text
                rendered_html = _inspect_offline_html(app, primary)
                checks["2d_html_runs_offline_in_qt_webengine"] = rendered_html
        checks["2d_png_svg_pdf_html_bundles"] = True

        # 3D PNG uses the live Plotly WebGL figure, and its HTML bundle carries local assets.
        panel.view_combo.setCurrentIndex(1); settle(controller); rendered(panel)
        assert panel.last_payload["view"] == "3d" and panel.summary["canvas_count"] > 0
        QTest.qWait(200)
        assert window.grab().save(str(output / "energy-profile-3d.png"))
        artifacts.append("energy-profile-3d.png")
        for format in ("png", "html"):
            destination = output / f"3d-{format}"
            assert panel.export_to(destination, format, language="en")
            if format == "png":
                wait(lambda: not panel._capture and (destination / "profile.png").is_file(), "3D PNG bundle", 60)
            settle(controller)
            primary = destination / f"profile.{format}"
            assert primary.is_file() and primary.stat().st_size > 500
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            assert manifest["view"] == "3d" and manifest["primary"] == primary.name
            for name, item in manifest["files"].items():
                assert _sha(destination / name) == item["sha256"]
            artifacts.append(primary.relative_to(output).as_posix())
            if format == "html":
                html_text = primary.read_text(encoding="utf-8")
                assert "src=\"assets/plotly.min.js\"" in html_text
                assert "connect-src 'none'" in html_text and "cdn.plot.ly" not in html_text
                rendered_html = _inspect_offline_html(app, primary)
                checks["3d_html_runs_offline_in_qt_webengine"] = rendered_html
        checks["3d_png_and_html_bundles"] = True

        # Existing destinations remain intact and are rejected as a whole.
        existing = output / "existing-package"
        existing.mkdir(); (existing / "keep.txt").write_text("keep", encoding="utf-8")
        from gaussianreadpro.services.plot_export import export_plot_bundle
        try:
            export_plot_bundle(panel.last_payload, existing, "html")
            raise AssertionError("existing export destination was overwritten")
        except StorageError as error:
            assert error.code == "destination_exists"
        assert (existing / "keep.txt").read_text(encoding="utf-8") == "keep"
        checks["existing_destination_is_preserved"] = True

        # The source must still match when export begins, even if the visible chart is stale.
        original_source = files[1].read_bytes()
        files[1].write_text("source changed after chart render\n", encoding="utf-8")
        rejected = output / "changed-source-export"
        assert panel.export_to(rejected, "html")
        settle(controller)
        assert errors and errors[-1]["code"] == "plot_sources_changed" and not rejected.exists()
        errors.clear()
        files[1].write_bytes(original_source)
        controller.calculate(); settle(controller); rendered(panel)
        checks["changed_source_rejected_without_partial_package"] = True

        # View-only state is saved into the project and survives a fresh controller open.
        panel.camera_combo.activated.emit(1)
        wait(lambda: abs(controller.plot_state.get("viewports", {}).get(panel.last_payload["context"] + "/3d", {}).get("camera", {}).get("eye", {}).get("x", 0) + 1.1) < 1e-6,
             "real camera preset persistence")
        settle(controller)
        panel.save_state(mode="3d", compare=True, theme="dark", hidden_paths=[path_ids[-1]])
        panel.refresh(); rendered(panel)
        settle(controller)
        project_file = output / "EP5-study.grproj"
        controller.save(project_file); settle(controller)
        saved_state = dict(controller.project.plot_state)
        with ProjectRepository(project_file, read_only=True) as repository:
            assert repository.load().plot_state == saved_state
        controller.close(); wait(lambda: controller._closed, "close writable EP5 project")
        reopened_controller = ProjectController(output / "reopen-recovery", output / "reopen-preferences.ini")
        reopened_window = MainWindow(reopened_controller)
        reopened_window.resize(1440, 1000); reopened_window.show()
        reopened_controller.open_project(project_file); settle(reopened_controller)
        rendered(reopened_window.profile)
        restored_panel = reopened_window.profile
        assert reopened_controller.project.plot_state == saved_state
        assert restored_panel.last_payload["view"] == "3d"
        assert restored_panel.last_payload["viewport"]["camera"] == saved_state["viewports"][restored_panel.last_payload["context"] + "/3d"]["camera"]
        assert restored_panel.last_payload["paths"][-1]["visible"] is False
        assert restored_panel.compare_box.isChecked()
        assert restored_panel.theme_combo.currentData() == "dark"
        actual_camera = json.loads(js(restored_panel.page,
            "JSON.stringify(document.getElementById('plot')._fullLayout.scene.camera)"))
        assert actual_camera["eye"] == dict(restored_panel.last_payload["viewport"]["camera"]["eye"])
        checks["mode_visibility_theme_and_camera_survive_project_reopen"] = True
        reopened_controller.close(); wait(lambda: reopened_controller._closed, "close reopened EP5 project")
        reopened_window.close()

        # A second read-only open can explore chart controls in memory, without changing project bytes.
        with ProjectRepository(project_file) as writer:
            before_bytes = _sha(project_file)
            readonly_controller = ProjectController(output / "readonly-recovery", output / "readonly-preferences.ini")
            readonly_window = MainWindow(readonly_controller)
            readonly_window.resize(1440, 1000); readonly_window.show()
            readonly_controller.open_project(project_file); settle(readonly_controller)
            assert readonly_controller.read_only
            readonly_window.navigation.setCurrentRow(2)
            readonly_panel = readonly_window.profile
            rendered(readonly_panel)
            original_state = dict(readonly_controller.plot_state)
            readonly_panel.view_combo.setCurrentIndex(0)
            readonly_panel.compare_box.setChecked(False)
            readonly_panel.theme_combo.setCurrentIndex(readonly_panel.theme_combo.findData("light"))
            readonly_panel.reset_options({"hidden_paths": []})
            rendered(readonly_panel)
            assert readonly_panel.state != original_state
            assert readonly_controller.plot_state == original_state
            assert not readonly_controller._plot_dirty
            assert readonly_panel.last_payload["view"] == "2d" and not readonly_panel.last_payload["dark"]
            QTest.qWait(600)
            readonly_controller.close(); wait(lambda: readonly_controller._closed, "close read-only project")
            assert _sha(project_file) == before_bytes
            assert writer.load().plot_state == saved_state
        checks["read_only_chart_exploration_is_session_only"] = True

        assert not errors and not panel.javascript_errors and not panel.blocked_requests
        report = {"passed": True, "platform": "windows", "process_affinity": hex(process_affinity),
                  "checks": checks, "artifacts": artifacts, "run": str(output), "errors": errors}
    except BaseException as error:
        report = {"passed": False, "platform": "windows", "process_affinity": hex(process_affinity),
                  "checks": checks, "artifacts": artifacts, "run": str(output), "error": str(error),
                  "traceback": traceback.format_exc(), "errors": errors}
        window.grab().save(str(output / "failure.png"))
    finally:
        for instance in (controller, readonly_controller, reopened_controller):
            if instance and not instance._closed:
                if instance.busy:
                    wait(lambda i=instance: not i.busy, "finish EP5 worker", 120)
                instance.close(); wait(lambda i=instance: i._closed, "close EP5 project")
        if readonly_window:
            readonly_window.close()
        if reopened_window:
            reopened_window.close()
        window.close(); app.processEvents()
        (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
