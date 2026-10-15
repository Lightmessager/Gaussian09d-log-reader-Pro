"""Native S6 workflow with synthetic oracle, actual editor events and screenshots."""
import json
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.ui.main_window import MainWindow
from gaussianreadpro.ui.expression_editor import ExpressionDialog
from gaussianreadpro.ui.theme import apply_theme
from gaussianreadpro.storage import ProjectRepository


def settle(app, controller, editor=None):
    deadline = monotonic() + 30
    while controller.busy or editor is not None and editor.isVisible():
        QTest.qWait(10)
        if monotonic() > deadline:
            raise TimeoutError(controller.operation)
    app.processEvents()


def main():
    out = ROOT / "artifacts/s6"
    run = out / "runs" / uuid4().hex
    run.mkdir(parents=True)
    app = QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    controller = ProjectController(run / "recovery", run / "preferences.ini")
    window = MainWindow(controller)
    errors, checks = [], {}
    controller.failed.connect(lambda code, detail: errors.append((code, detail)))
    try:
        window.show()
        window.resize(1520, 1000)
        controller.bootstrap()
        settle(app, controller)
        controller.new_project()
        settle(app, controller)
        values = {"R": -100., "A": -50., "TS1": -149.976, "I1": -140., "B": -10.008, "P": -150.025}
        paths = []
        for name, energy in values.items():
            path = run / (name + ".log")
            path.write_text("SYNTHETIC S6 VALIDATION\nEntering Gaussian System\n"
                            f" SCF Done: E(RB3LYP) = {energy - .03:.12f} A.U.\n"
                            f" Sum of electronic and thermal Free Energies= {energy:.12f}\n"
                            " Normal termination of Gaussian 16\n", encoding="utf-8")
            paths.append(path)
        window.import_paths(paths)
        settle(app, controller)
        ids = {n.label: n.id for n in controller.project.nodes}
        controller.remove_nodes([ids["A"], ids["B"]])
        settle(app, controller)
        for name, extra in (("R", "A"), ("I1", "B")):
            editor = ExpressionDialog(controller, node_id=ids[name], language=window.language, parent=window)
            editor.show()
            QTest.qWait(80)
            QTest.mouseClick(editor.add_button, Qt.MouseButton.LeftButton)
            row = editor.rows[-1]
            source = next(s for s in controller.project.source_files if s.display_name == extra)
            row["source"].setCurrentIndex(row["source"].findData(source.id))
            editor.flush()
            settle(app, controller)
            if name == "I1":
                QTest.qWait(120)
                assert editor.grab().save(str(out / "builder.png"))
            QTest.mouseClick(editor.close_button, Qt.MouseButton.LeftButton)
            settle(app, controller, editor)
            editor.deleteLater()
            if name == "R":
                window.select_node(ids["R"])
                QTest.mouseClick(window.reference_button, Qt.MouseButton.LeftButton)
                settle(app, controller)
        window.select_node(ids["R"])
        QTest.mouseClick(window.reference_button, Qt.MouseButton.LeftButton)
        settle(app, controller)
        actual = [n.relative_hartree for n in controller.results[0].nodes]
        assert all(abs(a - b) < 1e-10 for a, b in zip(actual, [0., .024, -.008, -.025])) and len(actual) == 4
        checks["four_node_oracle"] = True
        window.select_node(ids["TS1"])
        editor = ExpressionDialog(controller, node_id=ids["TS1"], language=window.language, parent=window)
        editor.show()
        editor.tabs.setCurrentIndex(1)
        editor.text.setPlainText("@{TS1} + (")
        QTest.qWait(450)
        settle(app, controller)
        QTest.qWait(80)
        assert editor.grab().save(str(out / "invalid-draft.png"))
        QTest.mouseClick(editor.close_button, Qt.MouseButton.LeftButton)
        settle(app, controller, editor)
        editor.deleteLater()
        assert next(n for n in controller.project.nodes if n.id == ids["TS1"]).expression.draft_error
        checks["invalid_draft_autosave"] = True
        revision = controller.project.revision
        controller.undo()
        settle(app, controller)
        assert controller.project.revision > revision and controller.results[0].valid
        checks["undo_monotonic"] = True
        controller.edit_path("copy", "Shared comparison")
        settle(app, controller)
        assert controller.project.paths[0].entries[0].node_id == controller.project.paths[1].entries[0].node_id
        checks["shared_path_copy"] = True
        window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
        settle(app, controller)
        window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark"))
        settle(app, controller)
        QTest.qWait(150)
        assert window.grab().save(str(out / "workbench-en-dark.png"))
        window.resize(1000, 800)
        QTest.qWait(150)
        assert window.grab().save(str(out / "workbench-compact.png"))
        destination = run / "S6-study.grproj"
        controller.save(destination)
        settle(app, controller)
        with ProjectRepository(destination, read_only=True) as repository:
            restored = repository.load()
        assert restored.nodes == controller.project.nodes and restored.paths == controller.project.paths
        checks["saved_expression_identity"] = True
        assert not errors
        result = {"passed": True, "platform": app.platformName(), "checks": checks,
                  "project": str(destination), "relative_hartree": actual, "errors": errors}
        (out / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        if controller.busy:
            settle(app, controller)
        controller.close()
        settle(app, controller)
        window.deleteLater()
        app.processEvents()


if __name__ == "__main__":
    main()
