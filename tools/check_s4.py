"""Actual Qt workbench workflow, screenshots and core-backed numerical oracle."""
import json
import os
from pathlib import Path
import sys
from time import monotonic, perf_counter
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("GRPR_NATIVE_PLOT", "1")  # This historical check targets the S4 native overview.

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gaussianreadpro.core.models import snapshot_to_dict
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.storage import ProjectRepository
from gaussianreadpro.ui.main_window import MainWindow
from gaussianreadpro.ui.theme import apply_theme


def settle(app, controller, timeout=25):
    deadline = monotonic() + timeout
    while controller.busy:
        QTest.qWait(10)
        if monotonic() >= deadline:
            raise TimeoutError(controller.operation)
    app.processEvents()


def main():
    start = perf_counter()
    out = ROOT / "artifacts/s4"
    run = out / "runs" / uuid4().hex
    logs = run / "logs"
    logs.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setOrganizationName("GaussianReadPro")
    app.setApplicationName("GaussianReadPro")
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    controller = ProjectController(run / "recovery", run / "preferences.ini")
    window = MainWindow(controller)
    window.resize(1500, 950)
    errors, ticks = [], []
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(perf_counter()))
    timer.start()
    checks = {}
    try:
        window.show()
        controller.bootstrap()
        settle(app, controller)
        QTest.qWait(180)
        assert window.grab().save(str(out / "home.png"))
        paths = []
        values = {"R": -150., "TS1": -149.976, "I1": -150.008, "P": -150.025}
        for name, value in values.items():
            path = logs / (name + ".log")
            path.write_text("SYNTHETIC S4 DEMO - not real Gaussian output\nEntering Gaussian System\n"
                            " #p B3LYP/def2-SVP opt freq\n --------------------\n"
                            f" SCF Done: E(RB3LYP) = {value - .03:.12f} A.U.\n"
                            " Temperature 298.150 Kelvin. Pressure 1.00000 Atm.\n"
                            " Thermal correction to Gibbs Free Energy= 0.030000000\n"
                            f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                            " Normal termination of Gaussian 16\n", encoding="utf-8")
            paths.append(path)
        # Exercise the same window import action used by file chooser and drop.
        window.import_paths(paths)
        settle(app, controller)
        QTest.qWait(25)  # the first import chains from new-project completion
        settle(app, controller)
        assert len(controller.project.nodes) == 4
        window.navigation.setCurrentRow(2)
        window.select_node(controller.project.nodes[0].id)
        QTest.mouseClick(window.reference_button, Qt.MouseButton.LeftButton)
        settle(app, controller)
        result = controller.results[0]
        expected = [0., .024, -.008, -.025]
        assert result.valid and all(abs(value.relative_hartree - wanted) < 1e-12 for value, wanted in zip(result.nodes, expected))
        checks["actual_reference_button_and_core_values"] = True
        window.select_node(controller.project.nodes[1].id)
        window.role_combo.setCurrentIndex(window.role_combo.findData("transition_state"))
        QTest.mouseClick(window.apply_node, Qt.MouseButton.LeftButton)
        settle(app, controller)
        window.preview.repaint()
        app.processEvents()
        point, node, _ = window.preview.positions[2]
        QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton, pos=point.toPoint())
        assert window.node_name.text() == node.label
        checks["actual_preview_click_selects_table"] = True
        window.select_node(controller.project.nodes[1].id)
        window.horizontal.setSizes([860, 300])
        window.vertical.setSizes([300, 350])
        window.splitters_changed()
        project_path = run / "Energy study.grproj"
        controller.save(project_path)
        settle(app, controller)
        QTest.qWait(150)
        assert window.saved.text() == "已保存"
        checks["project_committed"] = True
        assert window.grab().save(str(out / "workbench-wide.png"))
        window.resize(960, 750)
        QTest.qWait(150)
        assert window.sidebar.width() == 64 and not window.inspector.isVisible()
        assert window.grab().save(str(out / "workbench-compact.png"))
        checks["compact_layout"] = True
        window.resize(1500, 950)
        window.navigation.setCurrentRow(1)
        window.source_table.selectRow(1)
        QTest.qWait(100)
        assert window.grab().save(str(out / "sources.png"))
        window.navigation.setCurrentRow(2)
        window.select_node(controller.project.nodes[1].id)
        window.search.setText("TS1")
        controller.save()
        settle(app, controller)
        saved = controller.project
        controller.close()
        settle(app, controller)
        assert controller._closed and not window.isVisible()
        checks["graceful_async_close"] = True
        # Create a genuinely new window/controller and reopen the committed project.
        controller = ProjectController(run / "recovery", run / "preferences.ini")
        window = MainWindow(controller)
        window.show()
        controller.open_project(project_path, ignore_recovery=True)
        settle(app, controller)
        assert controller.project == saved
        assert window.node_name.text() == "TS1" and window.search.text() == "TS1"
        assert window.node_proxy.rowCount() == 1 and controller.results[0].valid
        checks["new_window_restores_filter_selection_and_results"] = True
        with ProjectRepository(project_path, read_only=True) as repository:
            assert repository.load() == controller.project
        controller.new_project()
        settle(app, controller)
        references = [ROOT / "tests/fixtures/reference" / name for name in ("dvb_ir.out", "dvb_sp.out", "dvb_gopt.out")]
        controller.import_files(references)
        settle(app, controller)
        assert len(controller.project.source_files) == len(controller.project.nodes) == 3
        controller.path_options(kind="scf")
        settle(app, controller)
        controller.reference_node(controller.project.nodes[0].id)
        settle(app, controller)
        assert controller.results[0].valid
        checks["three_real_g16_logs_import_and_scf_calculation"] = True
        real_result = snapshot_to_dict(controller.results[0])
        controller.close()
        settle(app, controller)
        assert not errors, errors
        report = {"stage": "S4", "passed": True, "checks": checks, "errors": errors,
                  "desktop_platform": app.platformName(), "project": str(project_path),
                  "synthetic_golden_relative_hartree": [v.relative_hartree for v in result.nodes],
                  "real_scf_path": real_result,
                  "heartbeat_ticks": len(ticks), "elapsed_ms": (perf_counter() - start) * 1000,
                  "screenshots": [str(out / name) for name in ("home.png", "workbench-wide.png", "workbench-compact.png", "sources.png")]}
        (out / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "real_scf_path"}, indent=2, ensure_ascii=False))
        return 0
    finally:
        timer.stop()
        settle(app, controller)
        if not controller._closed:
            controller.close(allow_recovery=True)
            settle(app, controller)


if __name__ == "__main__":
    raise SystemExit(main())
