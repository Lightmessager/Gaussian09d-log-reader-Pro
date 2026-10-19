"""Exercise the U5 apply/save flow in a visible 840x680 Windows Qt window."""
import json
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gaussianreadpro.core import EnergyKind, Project, ReactionPath, parse_log
from gaussianreadpro.core.models import new_id
from gaussianreadpro.core.reaction_network import empty_network
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.storage import ProjectRepository
from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog
from gaussianreadpro.ui.theme import apply_theme


def _wait(controller, app, timeout=20):
    deadline = monotonic() + timeout
    while controller.busy:
        app.processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, controller.operation
    app.processEvents()
    assert controller.pool.waitForDone(5000), "controller worker did not leave the pool"


def _fixture(root):
    sources = []
    for label, gibbs in zip(("R", "TS", "P"), (-10.0, -9.98, -10.02)):
        path = root / f"{label}.log"
        path.write_text(
            "Entering Gaussian System\n"
            f" SCF Done: E(RB3LYP) = {gibbs - 0.03:.12f} A.U.\n"
            " Thermal correction to Gibbs Free Energy= 0.030000000000\n"
            f" Sum of electronic and thermal Free Energies= {gibbs:.12f}\n"
            " Normal termination of Gaussian 16\n", encoding="utf-8")
        sources.append(parse_log(path).source)

    path = ReactionPath(new_id(), "U5 controlled save flow", ())
    project = Project(new_id(), source_files=tuple(sources), paths=(path,))
    network = empty_network()
    stages = []
    for index, (label, role, source) in enumerate(zip(
            ("R", "TS", "P"), ("reactant", "transition_state", "product"), sources)):
        species = {"id": new_id(), "name": label, "starred": False, "bindings": [
            {"source_file_id": source.id, "job_id": source.jobs[0].id, "historical": False}]}
        network["species"].append(species)
        stages.append({
            "id": new_id(), "role": role, "label": label,
            "predecessor_stage_id": stages[-1]["id"] if stages else None,
            "predecessor_stage_ids": [stages[-1]["id"]] if stages else [],
            "species": [{"species_id": species["id"], "coefficient": 1.0}],
            "terms": [{"species_id": species["id"], "source_file_id": source.id,
                       "job_id": source.jobs[0].id, "energy_kind": EnergyKind.GIBBS_TOTAL.value,
                       "coefficient": 1.0, "system_mode": "complete_system",
                       "reason": "U5 controlled same-job SCF plus thermal correction",
                       "historical": False}],
            "confirm_additional_terms": False, "node_id": None, "entry_id": None,
            "historical": False, "missing": False, "normalization_confirmed": True,
            "normalization_note": "Controlled fixture: composition and shared reference reviewed",
        })
    connections = []
    for parent, child in zip(stages, stages[1:]):
        connections.append({
            "id": new_id(), "source_stage_id": parent["id"], "target_stage_id": child["id"],
            "confirmed": True, "note": "Controlled fixture: reviewed reaction edge",
            "reactants": parent["species"], "products": child["species"], "terms": [],
        })
    network["path_reactions"] = [{
        "path_id": path.id, "stages": stages, "connections": connections,
        "zero_point": {"kind": "reactant", "stage_id": stages[0]["id"]},
        "preset": "relative_energy", "energy_kind": EnergyKind.GIBBS_TOTAL.value,
        "energy_mode": "absolute", "historical": False,
    }]
    return project, network, path.id


def _inside(dialog, widget):
    point = widget.mapTo(dialog, QPoint(0, 0))
    return (point.x() >= 0 and point.y() >= 0 and
            point.x() + widget.width() <= dialog.width() and
            point.y() + widget.height() <= dialog.height())


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app, "light")

    with tempfile.TemporaryDirectory(prefix="gaussianreadpro-u5-") as work:
        root = Path(work)
        project, network, path_id = _fixture(root)
        project_path = root / "u5-control.grproj"
        with ProjectRepository(project_path, create=True) as repository:
            repository.save(project)

        controller = ProjectController(root / "recovery", root / "preferences.ini")
        controller.bootstrap()
        _wait(controller, app)
        assert controller.open_project(project_path)
        _wait(controller, app)
        dialog = ReactionBuilderDialog(controller, path_id=path_id)
        dialog.network = network
        dialog._base_network = deepcopy(network)
        dialog.builder_draft.network = network
        dialog._load_recipe()
        dialog.resize(840, 680)
        dialog.show()
        app.processEvents()
        QTest.qWait(180)
        assert dialog.size().width() == 840 and dialog.size().height() == 680
        actions = (dialog.apply_button, dialog.apply_menu_button, dialog.preview_button,
                   dialog.save_network_button, dialog.save_file_button, dialog.cancel_button)
        assert all(button.isVisible() and _inside(dialog, button) for button in actions), [
            (button.text(), button.geometry().getRect()) for button in actions]

        output = ROOT / "artifacts" / "ux-v2" / "u5" / "apply_save_840x680.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        image = app.primaryScreen().grabWindow(dialog.winId())
        assert not image.isNull() and image.save(str(output)), output

        original_save = controller.backend.save
        save_attempts = []

        def fail_once(current_project, destination=None):
            save_attempts.append(current_project.revision)
            if len(save_attempts) == 1:
                raise OSError("controlled U5 save failure")
            return original_save(current_project, destination)

        controller.backend.save = fail_once
        assert dialog._apply_and_save()
        _wait(controller, app)
        assert dialog._flow_state == "applied_unsaved", dialog.flow_status.text()
        assert len(controller.project.nodes) == 3
        assert len(next(item for item in controller.project.paths if item.id == path_id).entries) == 3
        applied_revision = controller.project.revision
        applied_node_ids = tuple(item.id for item in controller.project.nodes)

        assert dialog._apply_and_save()
        _wait(controller, app)
        assert dialog._flow_state == "saved", dialog.flow_status.text()
        assert len(save_attempts) == 2
        assert controller.project.revision == applied_revision
        assert tuple(item.id for item in controller.project.nodes) == applied_node_ids
        dialog.close()
        controller._workspace_timer.stop()
        assert controller.close()
        _wait(controller, app)
        assert controller.pool.waitForDone(5000)

        print(json.dumps({
            "window_size": [840, 680], "actions_within_window": True,
            "applied_nodes": len(applied_node_ids), "controlled_save_attempts": len(save_attempts),
            "retry_reused_applied_revision": True, "final_flow_state": dialog._flow_state,
            "screenshot": str(output),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
