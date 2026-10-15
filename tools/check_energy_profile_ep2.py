"""Native Qt/WebEngine acceptance for EP2 two-dimensional chart readability."""
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

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.ui.main_window import MainWindow
from check_s7 import js, rendered, settle, wait


def main():
    output = ROOT / "artifacts" / "ui-glass" / "ep2" / uuid4().hex
    output.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    controller = ProjectController(output / "recovery", output / "preferences.ini")
    window = MainWindow(controller)
    errors, checks, screenshots = [], {}, []
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))

    def capture(name):
        QTest.qWait(220)
        assert window.grab().save(str(output / name))
        screenshots.append(name)

    def capture_chart(name):
        QTest.qWait(220)
        assert panel.webview.grab().save(str(output / name))
        screenshots.append(name)

    try:
        window.resize(1440, 1000)
        window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        files = []
        for name, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
            path = output / f"{name}.log"
            path.write_text("SYNTHETIC EP2 QA\nEntering Gaussian System\n"
                            f" SCF Done: E(RB3LYP) = {value-.03:.12f} A.U.\n"
                            f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                            " Normal termination of Gaussian 16\n", encoding="utf-8")
            files.append(path)
        controller.import_files(files); settle(controller)
        controller.reference_node(controller.project.nodes[0].id); settle(controller)
        controller.rename_node(controller.project.nodes[1].id, "TS1 <script>", "transition_state"); settle(controller)
        window.navigation.setCurrentRow(2)
        panel = window.profile
        rendered(panel)
        path = controller.selected_path
        expected = [0., 15.0602273775, -5.0200757925, -15.6877368516]
        actual = [point["value"] for point in panel.last_payload["paths"][0]["points"]]
        assert all(abs(a-b) < 1e-9 for a, b in zip(actual, expected)), actual
        checks["four_point_oracle_unchanged"] = True

        hover = js(panel.page, "document.getElementById('plot').data.find(t=>t.customdata).customdata[1][3]")
        assert "TS1" in hover and "&lt;script&gt;" in hover, repr(hover)
        assert "SHA:" not in hover and "Expression" not in hover and "<script>" not in hover
        checks["hover_is_compact_provenance_safe_and_escaped"] = True

        ts_entry = path.entries[1].id
        panel.set_table_selection([(path.id, ts_entry)])
        settle(controller); rendered(panel)
        assert js(panel.page, "window.grpr.shown.paths[0].points[1].selected")
        details = js(panel.page, "JSON.stringify({shapes:document.getElementById('plot').layout.shapes,"+
                     "ring:document.getElementById('plot').data.find(t=>t.meta&&t.meta.kind==='selected-ring').marker.line.color})")
        details = json.loads(details)
        assert details["shapes"] and details["ring"] == panel.last_payload["visual_style"]["focus"]
        checks["selected_point_has_sunset_ring_and_projection"] = True
        capture("wide-cn-selected-hover.png")
        js(panel.page, "const p=document.getElementById('plot'),i=p.data.findIndex(t=>t.customdata);"+
           "Plotly.Fx.hover(p,[{curveNumber:i,pointNumber:1}]);true")
        wait(lambda: js(panel.page, "!!document.querySelector('.hoverlayer .hovertext')"), "Plotly hover card")
        hover_card = js(panel.page, "document.querySelector('.hoverlayer .hovertext').textContent")
        assert "TS1" in hover_card
        checks["hover_card_visible_in_real_webengine"] = True
        capture_chart("cn-hover-card.png")

        panel.set_table_selection([(path.id, path.entries[0].id), (path.id, path.entries[1].id)])
        QTest.mouseClick(panel.barrier_button, Qt.MouseButton.LeftButton)
        settle(controller); rendered(panel)
        assert panel.last_payload["barrier_label"] == "ΔG‡"
        annotations = js(panel.page, "JSON.stringify(document.getElementById('plot').layout.annotations.map(a=>a.text||''))")
        assert "ΔG‡ =" in " ".join(json.loads(annotations))
        checks["barrier_notation_matches_gibbs_energy"] = True
        capture("cn-explicit-barrier.png")
        capture_chart("cn-barrier-callout.png")

        panel.set_language("en")
        settle(controller); rendered(panel)
        assert panel.last_payload["text"]["guide"] == "Curves and ribbons are visual guides; values are at nodes"
        assert panel.last_payload["barrier_label"] == "ΔG‡"
        capture("en-2d-profile.png")
        checks["english_guide_and_units"] = True
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
        window.close()
        app.processEvents()
        (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
