"""Native Qt/WebEngine acceptance for EP1 chart controls and responsive layout."""
import json
from pathlib import Path
import sys
import traceback
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

# Use only the previously documented process-local compatibility mask on this host.
from diagnose_static_runtime import windows_affinity
modes, _, select_affinity = windows_affinity()
process_affinity = modes["default"] & 0xFFFFFF3F
if process_affinity:
    select_affinity(process_affinity)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.ui.main_window import MainWindow
from check_s7 import rendered, settle, wait


def main():
    output = ROOT / "artifacts" / "ui-glass" / "ep1" / uuid4().hex
    output.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    controller = ProjectController(output / "recovery", output / "preferences.ini")
    window = MainWindow(controller)
    errors, checks, screenshots = [], {}, []
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))

    def capture(filename, widget=None):
        QTest.qWait(180)
        assert (widget or window).grab().save(str(output / filename))
        screenshots.append(filename)

    try:
        window.resize(1440, 1000)
        window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        log_paths = []
        for name, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
            path = output / f"{name}.log"
            path.write_text("SYNTHETIC EP1 QA\nEntering Gaussian System\n"
                            f" SCF Done: E(RB3LYP) = {value-.03:.12f} A.U.\n"
                            f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                            " Normal termination of Gaussian 16\n", encoding="utf-8")
            log_paths.append(path)
        controller.import_files(log_paths); settle(controller)
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        controller.edit_path("copy", "Path B"); settle(controller)
        controller.edit_path("color", "#EEA06F"); settle(controller)
        window.navigation.setCurrentRow(2)
        panel = window.profile
        rendered(panel)
        assert len(panel.paths_menu.actions()) == 2
        assert panel.paths_button.isEnabled()
        checks["path_visibility_menu_has_color_coded_paths"] = True

        # Keyboard activation must open the same menu as the pointer.
        panel.paths_button.setFocus()
        QTest.keyClick(panel.paths_button, Qt.Key.Key_Space)
        QTest.qWait(120)
        if not panel.paths_menu.isVisible():
            QTest.keyClick(panel.paths_button, Qt.Key.Key_Return)
            QTest.qWait(120)
        assert panel.paths_menu.isVisible(), "Path menu did not open from keyboard activation"
        capture("paths-menu-cn-light.png", panel.paths_menu)
        panel.paths_menu.hide()
        checks["path_menu_keyboard_access"] = True

        for language, theme, size, name in (
            ("zh_CN", "light", (1440, 1000), "wide-cn-light.png"),
            ("en", "dark", (1100, 820), "compact-en-dark.png"),
            ("zh_CN", "light", (860, 680), "narrow-cn-light.png"),
            ("en", "light", (860, 680), "narrow-en-light.png"),
        ):
            window.resize(*size)
            window.language_combo.setCurrentIndex(window.language_combo.findData(language))
            window.theme_combo.setCurrentIndex(window.theme_combo.findData(theme))
            settle(controller); rendered(panel); app.processEvents()
            expected_compact = panel.width() < 900
            assert bool(panel.toolbar_panel.property("compact")) == expected_compact
            assert not panel.paths_button.isHidden()
            assert panel.paths_button.accessibleName()
            capture(name)
        checks["responsive_bilingual_light_dark_matrix"] = True

        nodes_before = controller.project.nodes
        paths_before = controller.project.paths
        values_before = [value.display_value for result in controller.results for value in result.nodes]
        selected_id = controller.project.paths[-1].id
        panel._path_actions[selected_id].trigger()
        settle(controller); rendered(panel)
        assert controller.project.nodes == nodes_before and controller.project.paths == paths_before
        assert [value.display_value for result in controller.results for value in result.nodes] == values_before
        assert controller.plot_state["compare"]
        assert selected_id in controller.plot_state["hidden_paths"]
        checks["visibility_is_plot_state_only"] = True
        assert not errors, errors
        report = {"passed": True, "checks": checks, "screenshots": screenshots,
                  "run": str(output), "process_affinity": hex(process_affinity),
                  "platform": app.platformName(), "errors": errors}
    except BaseException as error:
        report = {"passed": False, "checks": checks, "screenshots": screenshots,
                  "run": str(output), "process_affinity": hex(process_affinity),
                  "platform": app.platformName(), "error": str(error), "errors": errors,
                  "traceback": traceback.format_exc(),
                  "load_events": list(getattr(getattr(window, "profile", None), "load_events", [])),
                  "javascript_errors": list(getattr(getattr(window, "profile", None), "javascript_errors", []))}
    finally:
        if not controller._closed:
            settle(controller)
            controller.close()
            wait(lambda: controller._closed, "Close EP1 QA project")
        window.close()
        app.processEvents()
        (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
