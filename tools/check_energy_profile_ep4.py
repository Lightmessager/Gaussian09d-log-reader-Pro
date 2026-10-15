"""Qt acceptance for the read-only energy-profile inspector and responsive mini overview."""
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

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.ui.main_window import MainWindow
from check_s7 import rendered, settle, wait


def main():
    output = ROOT / "artifacts" / "ui-glass" / "ep4" / uuid4().hex
    output.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    controller = ProjectController(output / "recovery", output / "preferences.ini")
    window = MainWindow(controller)
    checks, screenshots, errors = {}, [], []
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))

    def capture(name, widget=None):
        QTest.qWait(200)
        assert (widget or window).grab().save(str(output / name))
        screenshots.append(name)

    try:
        window.resize(1440, 1000)
        window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        files = []
        for name, energy in (("R", -150.0), ("TS1", -149.976), ("P", -150.025)):
            path = output / f"{name}.log"
            path.write_text(
                "SYNTHETIC EP4 QA\nEntering Gaussian System\n"
                f" SCF Done: E(RB3LYP) = {energy-.03:.12f} A.U.\n"
                f" Sum of electronic and thermal Free Energies= {energy:.12f}\n"
                " Normal termination of Gaussian 16\n", encoding="utf-8")
            files.append(path)
        controller.import_files(files); settle(controller)
        path = controller.selected_path
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        path = controller.selected_path
        window.navigation.setCurrentRow(2)
        rendered(window.profile)

        selected = controller.project.nodes[1]
        entry = next(item for item in path.entries if item.node_id == selected.id)
        window.select_node(selected.id)
        settle(controller)
        snapshot = window.plot_inspector.snapshot
        expected = next(item for item in next(r for r in controller.results if r.path_id == path.id).nodes
                        if item.entry_id == entry.id and item.node_id == selected.id)
        assert snapshot["node_id"] == selected.id and snapshot["entry_id"] == entry.id
        assert snapshot["value"] == expected.display_value
        assert snapshot["status"] == "valid"
        assert any(item["source_path"].endswith("TS1.log") and item["job_ordinal"] == 1 and item["line"] > 0
                   for item in snapshot["sources"])
        checks["selected_value_and_file_job_line_evidence"] = True

        controller.rename_node(selected.id, controller.project.nodes[0].label, "transition_state")
        settle(controller)
        window.select_node(selected.id)
        snapshot = window.plot_inspector.snapshot
        assert snapshot["node_label"] == controller.project.nodes[0].label
        assert snapshot["node_id"] == selected.id and snapshot["value"] == expected.display_value
        checks["duplicate_label_keeps_identity_and_value_separate"] = True
        capture("wide-selected-node-inspector.png")

        positions = [position for position, node, value in window.plot_inspector.preview.positions
                     if node.id == selected.id]
        assert positions
        window.plot_inspector.preview.setFocus()
        point = positions[0]
        QTest.mouseClick(window.plot_inspector.preview, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(point.x()), round(point.y())))
        settle(controller)
        assert window.plot_inspector.snapshot["node_id"] == selected.id
        checks["mini_overview_selects_by_node_id"] = True

        window.profile.expand(); QTest.qWait(350)
        capture("expanded-energy-profile.png", window.profile._expanded)
        window.profile._expanded.close(); QTest.qWait(250)
        checks["expanded_profile_preserved"] = True

        window.resize(980, 820); QTest.qWait(350)
        assert window.compact_tabs.isVisible()
        window.compact_tabs.setCurrentIndex(2); QTest.qWait(250)
        assert window.inspector.isVisible() and not window.vertical.isVisible()
        assert window.plot_inspector.preview.isVisible()
        capture("compact-node-details.png")
        checks["compact_details_tab_and_mini_overview"] = True

        window.language = "en"
        window.retranslate(); QTest.qWait(150)
        assert window.plot_inspector.title.text() == "Selected node"
        assert window.compact_tabs.tabText(2) == "Node details"
        checks["inspector_bilingual_labels"] = True

        assert not errors
        report = {"passed": True, "platform": app.platformName(), "checks": checks,
                  "process_affinity": hex(process_affinity), "screenshots": screenshots,
                  "run": str(output), "errors": errors}
    except BaseException as error:
        report = {"passed": False, "platform": app.platformName(), "checks": checks,
                  "process_affinity": hex(process_affinity), "screenshots": screenshots,
                  "run": str(output), "error": str(error), "traceback": traceback.format_exc(),
                  "errors": errors}
        window.grab().save(str(output / "failure.png"))
    finally:
        if controller.busy:
            wait(lambda: not controller.busy, "finish EP4 worker", 120)
        if not controller._closed:
            controller.close(); wait(lambda: controller._closed, "close EP4 project")
        window.close(); app.processEvents()
        (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
