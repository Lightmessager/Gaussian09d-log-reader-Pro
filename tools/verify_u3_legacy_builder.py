"""Open a synthetic legacy path in the real Qt builder and capture its first view."""
import os
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from gaussianreadpro.core import EnergyKind, Project, ReactionPath, compile_expression, parse_log
from gaussianreadpro.core.models import (CalculationMode, EnergyRef, KindPolicy, PathEntry,
                                         ProfileNode, new_id)
from gaussianreadpro.core.reaction_network import read_reaction_network
from gaussianreadpro.core import calculate_path
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.storage.sources import SourceConnection
from gaussianreadpro.ui.main_window import MainWindow
from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog
from gaussianreadpro.ui.import_summary import ImportSummaryDialog, JobCandidateDialog
from gaussianreadpro.ui.theme import apply_theme


class PreviewController(QObject):
    busyChanged = Signal(bool, str)
    failed = Signal(str, str)

    def __init__(self, project):
        super().__init__()
        self.project = project
        self.read_only = False
        self.busy = False
        self.results = ()


def main():
    app = QApplication.instance() or QApplication([])
    apply_theme(app, "light")
    with TemporaryDirectory(prefix="gaussianreadpro-u3-") as temporary:
        log = Path(temporary) / "legacy-single-reference.log"
        log.write_text("Entering Gaussian System\n SCF Done: E(RB3LYP) = -1.020000000000 A.U.\n"
            " Thermal correction to Gibbs Free Energy= 0.020000000000\n"
            " Sum of electronic and thermal Free Energies= -1.000000000000\n"
            " Normal termination of Gaussian 16\n", encoding="utf-8")
        source = parse_log(log).source
        ref = EnergyRef(source.id, source.jobs[0].id, KindPolicy.FOLLOW_PATH)
        expression = compile_expression("@{legacy}", {"legacy": ref}).expression
        node = ProfileNode(new_id(), "Legacy A", expression, display={"x": 30.0, "y": 20.0})
        entry = PathEntry(new_id(), node.id, 0, {"highlighted": True})
        path = ReactionPath(new_id(), "Legacy relative path", (entry,), EnergyKind.GIBBS_TOTAL,
                            expression, "relative")
        project = Project(new_id(), (source,), (node,), (path,), alias_bindings={"legacy": ref})
        controller = PreviewController(project)

        summary = ImportSummaryDialog(project, added_source_ids={source.id})
        summary.show()
        app.processEvents()
        summary_text = "\n".join(item.text() for item in summary.findChildren(QLabel))
        assert "本次新增来源文件：1 个" in summary_text
        assert "Gaussian 作业：1 个" in summary_text
        assert "SCF 可用：项目 1 / 1；本次新增 1 / 1 个作业" in summary_text
        assert summary.candidates_button.isVisible()
        candidates = JobCandidateDialog(project)
        candidates.show()
        app.processEvents()
        assert candidates.table.rowCount() == 1
        assert source.id in candidates.table.item(0, 1).text()
        assert source.original_path in candidates.table.item(0, 1).text()
        assert source.jobs[0].id in candidates.table.item(0, 2).text()
        candidates.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        candidates.name_edits[0].setText("Legacy source job")
        candidates._accept_selection()
        assert candidates.result() == QDialog.DialogCode.Accepted
        assert candidates.selected_candidates[0]["job_id"] == source.jobs[0].id
        candidates.close()
        summary.close()

        dialog = ReactionBuilderDialog(controller, path.id)
        dialog.resize(1180, 760)
        dialog.show()
        app.processEvents()

        assert dialog.builder_draft.legacy_mode == "legacy_supported"
        assert dialog.legacy_panel.isVisible()
        assert dialog.legacy_convert_button.isVisible()
        assert node.label in dialog.legacy_nodes.toPlainText()
        screenshot = Path("artifacts/u3_legacy_builder_first_open.png")
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        if not dialog.grab().toImage().save(str(screenshot)):
            raise RuntimeError("Could not save the builder screenshot")
        before = read_reaction_network(project)
        dialog.reject()
        app.processEvents()
        assert controller.project is project
        assert read_reaction_network(controller.project) == before
        dialog.deleteLater()
        app.processEvents()

        absolute_path = replace(path, calculation_mode=CalculationMode.ABSOLUTE,
                                reference_expression=None)
        absolute_project = replace(project, paths=(absolute_path,))
        absolute_controller = PreviewController(absolute_project)
        absolute_dialog = ReactionBuilderDialog(absolute_controller, absolute_path.id)
        absolute_dialog.show()
        app.processEvents()
        assert absolute_dialog.builder_draft.legacy_mode == "legacy_expert"
        assert not absolute_dialog.legacy_convert_button.isVisible()
        assert absolute_dialog.legacy_jobs_new_path_button.isVisible()
        assert "绝对能量" in absolute_dialog.legacy_notice.text()
        absolute_dialog.reject()
        app.processEvents()
        assert absolute_controller.project is absolute_project
        absolute_dialog.deleteLater()
        app.processEvents()

        project_controller = ProjectController(Path(temporary) / "recovery",
                                               Path(temporary) / "preferences.ini")
        project_controller.project = project
        project_controller.results = (calculate_path(project, path.id),)
        project_controller.connections = (SourceConnection(source.id, "changed", None),)
        project_controller.workspace = {"path_id": path.id, "page": 0}
        project_controller.set_workspace = lambda **_values: True
        main_window = MainWindow(project_controller)
        main_window.show()
        app.processEvents()
        assert main_window.workflow_summary.next_action == "reconnect_source"
        main_window.workflow_next_button.click()
        app.processEvents()
        assert main_window.navigation.currentRow() == 1
        assert main_window._selected_source == source.id
        assert main_window.reconnect_button.isEnabled()
        main_window._allow_close = True
        main_window.close()
        main_window.profile.dispose()
        main_window.deleteLater()
        project_controller._status_timer.stop()
        project_controller._workspace_timer.stop()
        project_controller.deleteLater()
        app.processEvents()
        print("Windows-native Qt checks passed: import candidates, legacy conversion boundaries, "
              f"unmodified exit, reconnect routing, and selected source. Screenshot: {screenshot.resolve()}")


if __name__ == "__main__":
    main()
