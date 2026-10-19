"""Native S8 flow using the repository's fixed real Gaussian16 reference logs."""

import json
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]

from diagnose_static_runtime import windows_affinity
masks, _, select_affinity = windows_affinity()
select_affinity(masks["default"] & 0xFFFFFF3F)

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.core import EnergyKind
from gaussianreadpro.core.expressions import expression_from_ast, ref_ast
from gaussianreadpro.core.models import EnergyRef, KindPolicy
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.ui.main_window import MainWindow
from gaussianreadpro.ui.theme import apply_theme


def wait(predicate, label, seconds=45):
    deadline = monotonic() + seconds
    while not predicate():
        QTest.qWait(10)
        if monotonic() > deadline:
            raise TimeoutError(label)


def settle(controller):
    wait(lambda: not controller.busy and not controller._workspace_dirty and not controller._plot_dirty,
         controller.operation, 120)


def main():
    fixtures = ROOT / "tests/fixtures/reference"
    expected = json.loads((fixtures / "expected.json").read_text(encoding="utf-8"))
    cases = expected["cases"]
    paths = [fixtures / case["path"] for case in cases]
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError("The licensed local Gaussian16 reference logs are required")
    run = ROOT / "artifacts/s8/real-native" / uuid4().hex
    run.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    controller = ProjectController(run / "recovery", run / "preferences.ini")
    window = MainWindow(controller)
    window.resize(1440, 900)
    errors = []
    controller.failed.connect(lambda code, detail: errors.append({"code": code, "detail": detail}))
    reopened = None
    try:
        window.show()
        controller.bootstrap(); settle(controller)
        controller.new_project(); settle(controller)
        window.import_paths(paths)
        settle(controller)
        assert len(controller.project.source_files) == len(cases)
        # The imported default expressions follow Gibbs, but these reference logs
        # do not all contain Gibbs corrections. Bind each imported node explicitly
        # to its own parsed SCF job before switching the path to SCF.
        sources_by_name = {source.original_name: source for source in controller.project.source_files}
        for case in cases:
            source = sources_by_name[case["path"]]
            node = next(node for node in controller.project.nodes if node.label == source.display_name)
            controller.set_expression(expression_from_ast(ref_ast(EnergyRef(
                source.id, source.jobs[0].id, KindPolicy.FIXED, EnergyKind.SCF))), node_id=node.id)
            settle(controller)
        assert len(controller.project.paths[0].entries) == len(cases)
        assert controller.path_options(kind="scf")
        settle(controller)
        assert controller.reference_node(controller.project.nodes[0].id)
        settle(controller)
        result = controller.results[0]
        assert len(result.nodes) == len(cases), result
        assert all(point.valid for point in result.nodes), [
            (point.valid, [item.code for item in point.diagnostics]) for point in result.nodes]
        values = [point.relative_hartree for point in result.nodes]
        assert all(abs(value) < 1e-10 for value in values), values
        by_name = {source.original_name: source for source in controller.project.source_files}
        for case in cases:
            source = by_name[case["path"]]
            job = source.jobs[0]
            actual = job.energies[EnergyKind.SCF]
            assert actual.source_line == case["energies"]["scf"]["line"]
            assert abs(actual.value_hartree - float(case["energies"]["scf"]["value"])) < 1e-10
            assert source.sha256 == case["sha256"]
        panel = window.profile
        wait(lambda: panel.ready and panel.summary.get("render_id") == panel.last_payload["render_id"]
             and panel.summary.get("revision") == controller.project.revision
             and panel.last_payload.get("revision") == controller.project.revision, "real plot revision")
        assert not panel.summary.get("warnings"), panel.summary.get("warnings")
        assert [point["value"] for point in panel.summary["points"]] == [node.display_value for node in result.nodes]
        dom = {}
        panel.page.runJavaScript("JSON.stringify({notice:document.getElementById('notice').textContent, traces:document.querySelector('.plotly-host')?._fullData?.map(t=>({kind:t.meta?.kind, customdata:t.customdata?.length||0, x:t.x?.length||0})), table:document.body.innerText.slice(-500)})",
                                 lambda value: dom.update(json.loads(value)))
        wait(lambda: bool(dom), "DOM render diagnostics")
        assert not dom.get("notice"), dom
        assert any(item["kind"] == "computed-nodes" and item["customdata"] == len(cases)
                   for item in dom.get("traces", [])), dom
        screenshot = run / "real-gaussian-scf.png"
        QTest.qWait(500)
        assert window.grab().save(str(screenshot))
        assert panel.export_to(run / "offline-html", "html", language="en")
        settle(controller)
        assert (run / "offline-html/profile.html").is_file()
        target = run / "real-study.grproj"
        settle(controller)
        assert controller.save(target)
        settle(controller)
        assert target.is_file(), errors
        original_id = controller.project.id
        controller.close(); wait(lambda: controller._closed, "close original")
        reopened = ProjectController(run / "recovery-2", run / "preferences-2.ini")
        second_window = MainWindow(reopened)
        second_window.resize(1440, 900)
        second_window.show()
        assert reopened.open_project(target, ignore_recovery=True)
        settle(reopened)
        assert reopened.project.id == original_id
        assert [point.relative_hartree for point in reopened.results[0].nodes] == values
        assert len(reopened.project.source_files) == len(cases)
        report = {"passed": True, "source": "cclib Gaussian16 fixed real logs",
                  "project": str(target), "screenshot": str(screenshot), "qt_dpr": second_window.devicePixelRatioF(),
                  "logical_size": [window.width(), window.height()], "relative_hartree": values,
                  "node_count": len(result.nodes), "node_values": [point.display_value for point in result.nodes],
                  "node_diagnostics": [[item.code for item in point.diagnostics] for point in result.nodes],
                  "path_diagnostics": [item.code for item in result.diagnostics],
                  "plot_points": panel.summary.get("points"),
                  "payload_path_points": [{"valid": point.get("valid"), "value": point.get("value"),
                                           "diagnostics": point.get("diagnostics")}
                                          for path in panel.last_payload["paths"] for point in path["points"]],
                  "plot_warning": panel.summary.get("warning"),
                  "dom": dom,
                  "source_sha256": {case["path"]: case["sha256"] for case in cases}, "errors": errors}
        (run / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if reopened and not reopened._closed:
            settle(reopened)
            reopened.close(); wait(lambda: reopened._closed, "close reopened")
        if not controller._closed:
            settle(controller)
            controller.close(); wait(lambda: controller._closed, "close original")


if __name__ == "__main__":
    main()
