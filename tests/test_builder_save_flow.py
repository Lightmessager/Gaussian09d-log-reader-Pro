from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path
from time import monotonic

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gaussianreadpro.core import EnergyKind, Project, ReactionPath, parse_log
from gaussianreadpro.core.models import new_id
from gaussianreadpro.core.reaction_network import apply_path_recipe, empty_network
from gaussianreadpro.core.units import from_hartree
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.storage import ProjectRepository
from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog


def _reaction_fixture(tmp_path, *, zero_at="reactant", missing_stage=None):
    sources = []
    for label, gibbs in zip(("R", "TS", "P"), (-10.0, -9.98, -10.02)):
        path = tmp_path / f"{label}.log"
        path.write_text(
            "Entering Gaussian System\n"
            f" SCF Done: E(RB3LYP) = {gibbs - 0.03:.12f} A.U.\n"
            " Thermal correction to Gibbs Free Energy= 0.030000000000\n"
            f" Sum of electronic and thermal Free Energies= {gibbs:.12f}\n"
            " Normal termination of Gaussian 16\n",
            encoding="utf-8",
        )
        sources.append(parse_log(path).source)

    path = ReactionPath(new_id(), "R → TS → P", ())
    project = Project(new_id(), source_files=tuple(sources), paths=(path,))
    network = empty_network()
    stages = []
    roles = ("reactant", "transition_state", "product")
    labels = ("R", "TS", "P")
    for index, (label, role, source) in enumerate(zip(labels, roles, sources)):
        species = {"id": new_id(), "name": label, "starred": False, "bindings": [
            {"source_file_id": source.id, "job_id": source.jobs[0].id, "historical": False}
        ]}
        network["species"].append(species)
        is_missing = index == missing_stage
        stage = {
            "id": new_id(), "role": role, "label": label,
            "predecessor_stage_id": stages[-1]["id"] if stages else None,
            "predecessor_stage_ids": [stages[-1]["id"]] if stages else [],
            "species": [{"species_id": species["id"], "coefficient": 1.0}],
            "terms": [] if is_missing else [{
                "species_id": species["id"], "source_file_id": source.id,
                "job_id": source.jobs[0].id, "energy_kind": EnergyKind.GIBBS_TOTAL.value,
                "coefficient": 1.0, "system_mode": "complete_system",
                "reason": "U5 controlled same-job SCF plus thermal correction",
                "historical": False,
            }],
            "confirm_additional_terms": False, "node_id": None, "entry_id": None,
            "historical": False, "missing": is_missing,
            "normalization_confirmed": True,
            "normalization_note": "Controlled fixture: composition and shared reference reviewed",
        }
        stages.append(stage)

    connections = []
    for parent, child in zip(stages, stages[1:]):
        connections.append({
            "id": new_id(), "source_stage_id": parent["id"], "target_stage_id": child["id"],
            "confirmed": True, "note": "Controlled fixture: reviewed reaction edge",
            "reactants": parent["species"], "products": child["species"], "terms": [],
        })

    zero_stage = stages[0] if zero_at == "reactant" else stages[2]
    network["path_reactions"] = [{
        "path_id": path.id, "stages": stages, "connections": connections,
        "zero_point": {"kind": "reactant" if zero_at == "reactant" else "stage",
                       "stage_id": zero_stage["id"]},
        "preset": "relative_energy", "energy_kind": EnergyKind.GIBBS_TOTAL.value,
        "energy_mode": "absolute", "historical": False,
    }]
    return project, network, path.id, tuple(sources)


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def _settle(app, controller, timeout=12):
    from PySide6.QtTest import QTest
    deadline = monotonic() + timeout
    while controller.busy:
        app.processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, controller.operation
    app.processEvents()
    assert controller.pool.waitForDone(5000), "controller worker did not leave the pool after completion"


def _builder_for_fixture(controller, network, path_id):
    dialog = ReactionBuilderDialog(controller, path_id=path_id)
    # U6 routes direct closes through the dirty-draft guard. These U5 flow
    # tests do not exercise that guard; discard any leftover view-local draft
    # during fixture teardown instead of opening a modal choice dialog.
    dialog._ask_draft_exit = lambda _reason: "discard"
    dialog.network = network
    dialog._base_network = deepcopy(network)
    if dialog.builder_draft is not None:
        dialog.builder_draft.network = network
    dialog._load_recipe()
    return dialog


@pytest.fixture
def loaded_reaction(qt_app, tmp_path):
    project, network, path_id, sources = _reaction_fixture(tmp_path)
    project_path = tmp_path / "study.grproj"
    with ProjectRepository(project_path, create=True) as repository:
        repository.save(apply_path_recipe(project, deepcopy(network), path_id))
    controller = ProjectController(tmp_path / "recovery", tmp_path / "preferences.ini")
    controller.bootstrap()
    _settle(qt_app, controller)
    assert controller.open_project(project_path)
    _settle(qt_app, controller)
    yield controller, project, network, path_id, sources
    controller._workspace_timer.stop()
    if not controller._closed:
        controller.close()
        _settle(qt_app, controller)
    assert controller.pool.waitForDone(5000), "controller worker did not stop during fixture teardown"


@pytest.mark.parametrize(("source_state", "expected_code"),
                         (("changed", "source_changed"), ("missing", "source_missing")))
def test_changed_source_invalidates_preview(loaded_reaction, qt_app, source_state, expected_code):
    controller, _project, network, path_id, sources = loaded_reaction
    previews = []
    controller.reactionPreviewReady.connect(lambda token, preview: previews.append((token, preview)))

    source_path = Path(sources[0].original_path)
    if source_state == "changed":
        source_path.write_text(source_path.read_text(encoding="utf-8") + "source changed\n", encoding="utf-8")
    else:
        source_path.unlink()
    assert controller.preview_reaction_recipe(
        network, path_id, draft_generation=0, base_revision=controller.project.revision,
    )
    _settle(qt_app, controller)

    assert previews
    preview = previews[-1][1]
    assert preview.blocking
    assert any(item.code == expected_code for item in preview.diagnostics)
    assert all(not node.valid for node in preview.path_result.nodes)


def test_preview_uses_same_job_scftotal_and_both_zero_points(loaded_reaction, qt_app):
    controller, _project, network, path_id, sources = loaded_reaction
    received = []
    controller.reactionPreviewReady.connect(lambda token, preview: received.append((token, preview)))

    assert controller.preview_reaction_recipe(
        network, path_id, draft_generation=7, base_revision=controller.project.revision,
    )
    _settle(qt_app, controller)
    reactant_zero = received[-1][1]
    assert not reactant_zero.blocking
    assert [node.absolute_hartree for node in reactant_zero.path_result.nodes] == pytest.approx(
        (-10.0, -9.98, -10.02), abs=1e-11,
    )
    assert [node.relative_hartree for node in reactant_zero.path_result.nodes] == pytest.approx(
        (0.0, 0.02, -0.02), abs=1e-11,
    )
    assert reactant_zero.path_result.nodes[0].relative_hartree is not None
    assert reactant_zero.path_result.unit.value == "kcal_mol"
    assert from_hartree(0.02, reactant_zero.path_result.unit) == pytest.approx(12.550, abs=0.01)
    assert from_hartree(-0.04, reactant_zero.path_result.unit) == pytest.approx(-25.100, abs=0.01)
    first_sources = reactant_zero.path_result.nodes[0].dependencies
    assert {(item.kind, item.source_line) for item in first_sources} == {
        (EnergyKind.SCF, sources[0].jobs[0].energies[EnergyKind.SCF].source_line),
        (EnergyKind.GIBBS_CORRECTION,
         sources[0].jobs[0].energies[EnergyKind.GIBBS_CORRECTION].source_line),
    }
    assert {item.job_id for item in first_sources} == {sources[0].jobs[0].id}
    for node, source in zip(reactant_zero.path_result.nodes, sources):
        assert {item.kind for item in node.dependencies} == {
            EnergyKind.SCF, EnergyKind.GIBBS_CORRECTION,
        }
        assert {item.job_id for item in node.dependencies} == {source.jobs[0].id}
        assert {item.source_line for item in node.dependencies} == {
            source.jobs[0].energies[EnergyKind.SCF].source_line,
            source.jobs[0].energies[EnergyKind.GIBBS_CORRECTION].source_line,
        }

    product_network = {**network, "path_reactions": [dict(network["path_reactions"][0])]}
    recipe = product_network["path_reactions"][0]
    recipe["zero_point"] = {"kind": "stage", "stage_id": recipe["stages"][-1]["id"]}
    assert controller.preview_reaction_recipe(
        product_network, path_id, draft_generation=8, base_revision=controller.project.revision,
    )
    _settle(qt_app, controller)
    product_zero = received[-1][1]
    assert not product_zero.blocking
    assert [node.absolute_hartree for node in product_zero.path_result.nodes] == pytest.approx(
        (-10.0, -9.98, -10.02), abs=1e-11,
    )
    assert [node.relative_hartree for node in product_zero.path_result.nodes] == pytest.approx(
        (0.02, 0.04, 0.0), abs=1e-11,
    )
    assert product_zero.path_result.nodes[-1].relative_hartree is not None


def test_not_found_transition_state_preview_never_has_a_numeric_energy(qt_app, tmp_path):
    project, network, path_id, _sources = _reaction_fixture(tmp_path, missing_stage=1)
    # The energy-free TS remains explicit and the adjacent connections were confirmed in the fixture.
    controller = ProjectController(tmp_path / "recovery", tmp_path / "preferences.ini")
    project_path = tmp_path / "missing-ts.grproj"
    with ProjectRepository(project_path, create=True) as repository:
        repository.save(project)
    controller.bootstrap()
    _settle(qt_app, controller)
    controller.open_project(project_path)
    _settle(qt_app, controller)
    previews = []
    controller.reactionPreviewReady.connect(lambda token, preview: previews.append(preview))
    assert controller.preview_reaction_recipe(
        network, path_id, draft_generation=1, base_revision=controller.project.revision,
    )
    _settle(qt_app, controller)
    result = previews[-1]
    missing_node = result.path_result.nodes[1]
    assert missing_node.absolute_hartree is None
    assert missing_node.relative_hartree is None
    assert any(item.code == "missing_transition_state" and item.severity == "warning"
               for item in result.diagnostics)
    controller.close()
    _settle(qt_app, controller)


def test_wrong_base_revision_cannot_start_a_preview(loaded_reaction):
    controller, _project, network, path_id, _sources = loaded_reaction
    assert not controller.preview_reaction_recipe(
        network, path_id, draft_generation=2, base_revision=controller.project.revision - 1,
    )


def test_project_revision_change_invalidates_cached_preview_before_apply(loaded_reaction, qt_app):
    controller, _project, network, path_id, _sources = loaded_reaction
    token_holder = []
    controller.reactionPreviewReady.connect(lambda token, _preview: token_holder.append(token))
    assert controller.preview_reaction_recipe(
        network, path_id, draft_generation=3, base_revision=controller.project.revision,
    )
    _settle(qt_app, controller)
    assert token_holder
    prior_ids = tuple(node.id for node in controller.project.nodes)

    changed = replace(controller.project, revision=controller.project.revision + 1)
    assert controller._edit(changed)
    _settle(qt_app, controller)
    assert not controller.apply_reaction_recipe(
        network, path_id, preview_token=token_holder[-1], draft_generation=3,
    )
    assert tuple(node.id for node in controller.project.nodes) == prior_ids


def test_apply_save_cancel_then_retry_does_not_duplicate_nodes(loaded_reaction, qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    controller, _project, network, path_id, _sources = loaded_reaction
    dialog = _builder_for_fixture(controller, network, path_id)
    original_update = controller.backend.update

    def update_as_unsaved(project):
        return replace(original_update(project), path=None)

    controller.backend.update = update_as_unsaved
    destination = tmp_path / "first-save.grproj"
    choices = iter(("", str(destination)))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (next(choices), ""))

    assert dialog._apply_and_save(), (dialog.preview.text(), dialog.flow_status.text())
    _settle(qt_app, controller)
    assert dialog._flow_state == "applied_unsaved"
    assert len(controller.project.nodes) == 3
    assert len(next(path for path in controller.project.paths if path.id == path_id).entries) == 3

    assert dialog._apply_and_save()  # Retry now saves the applied project; it does not apply again.
    _settle(qt_app, controller)
    assert destination.exists()
    assert dialog._flow_state == "saved"
    assert len(controller.project.nodes) == 3
    assert len(next(path for path in controller.project.paths if path.id == path_id).entries) == 3
    dialog.close()


def test_saved_path_can_create_next_path_without_exit_prompt(loaded_reaction, qt_app):
    controller, _project, network, path_id, _sources = loaded_reaction
    dialog = _builder_for_fixture(controller, network, path_id)
    prompts = []
    dialog._ask_draft_exit = lambda reason: prompts.append(reason) or "discard"

    assert dialog._apply_and_save(), (dialog.preview.text(), dialog.flow_status.text())
    _settle(qt_app, controller)
    assert dialog._flow_state == "saved"

    dialog._new_path("Second path")

    assert prompts == []
    assert dialog._draft_new_path is not None
    assert dialog._active_path_id == dialog._draft_new_path.id
    dialog.close()


def test_save_failure_retries_io_only(loaded_reaction, qt_app, monkeypatch):
    controller, _project, network, path_id, _sources = loaded_reaction
    dialog = _builder_for_fixture(controller, network, path_id)
    original_save = controller.backend.save
    original_update = controller.backend.update
    save_calls, update_calls = [], []

    def fail_first_save(project, destination=None):
        save_calls.append(project.revision)
        if len(save_calls) == 1:
            raise OSError("controlled save failure")
        return original_save(project, destination)

    def count_update(project):
        update_calls.append(project.revision)
        return original_update(project)

    monkeypatch.setattr(controller.backend, "save", fail_first_save)
    monkeypatch.setattr(controller.backend, "update", count_update)
    assert dialog._apply_and_save()
    _settle(qt_app, controller)
    assert dialog._flow_state == "applied_unsaved"
    assert len(save_calls) == 1
    assert len(update_calls) == 1
    applied_revision = controller.project.revision
    node_ids = tuple(node.id for node in controller.project.nodes)

    assert dialog._apply_and_save()
    _settle(qt_app, controller)
    assert dialog._flow_state == "saved"
    assert len(save_calls) == 2
    assert len(update_calls) == 1
    assert controller.project.revision == applied_revision
    assert tuple(node.id for node in controller.project.nodes) == node_ids
    dialog.close()


def test_apply_only_stops_before_project_file_save(loaded_reaction, qt_app, monkeypatch):
    controller, _project, network, path_id, _sources = loaded_reaction
    dialog = _builder_for_fixture(controller, network, path_id)
    save_calls = []
    original_save = controller.backend.save

    def count_save(project, destination=None):
        save_calls.append(project.revision)
        return original_save(project, destination)

    monkeypatch.setattr(controller.backend, "save", count_save)
    assert dialog._apply_only()
    _settle(qt_app, controller)
    assert dialog._flow_state == "applied_unsaved"
    assert len(controller.project.nodes) == 3
    assert not save_calls
    dialog.close()


def test_unrelated_completion_cannot_finish_a_save(loaded_reaction, qt_app, monkeypatch):
    from threading import Event

    controller, _project, _network, _path_id, _sources = loaded_reaction
    dialog = ReactionBuilderDialog(controller)
    original_save = controller.backend.save
    entered, release = Event(), Event()

    def gated_save(project, destination=None):
        entered.set()
        assert release.wait(5), "test did not release controlled save"
        return original_save(project, destination)

    monkeypatch.setattr(controller.backend, "save", gated_save)
    try:
        assert dialog._start_file_save()
        assert entered.wait(5)
        token = dialog._pending_token
        dialog._operation_finished(token, "calculate", True, controller.project.id,
                                   controller.project.revision, str(controller.path))
        assert dialog._pending_operation == "save"
        assert dialog._flow_state == "saving"
    finally:
        release.set()
    _settle(qt_app, controller)
    assert dialog._flow_state == "saved"
    dialog.close()


def test_stale_preview_is_ignored_after_draft_generation_changes(loaded_reaction, qt_app):
    controller, _project, network, path_id, _sources = loaded_reaction
    dialog = _builder_for_fixture(controller, network, path_id)
    generation = dialog.builder_draft.generation
    assert controller.preview_reaction_recipe(
        network, path_id, draft_generation=generation, base_revision=controller.project.revision,
    )
    token = controller.active_task_token
    dialog._pending_token = token
    dialog._pending_operation = "preview"
    dialog._pending_preview_mode = "preview"
    dialog.builder_draft.generation += 1
    _settle(qt_app, controller)

    assert dialog._accepted_preview is None
    assert dialog._flow_state == "draft"
    dialog.close()


def test_source_change_after_preview_is_rechecked_before_apply(loaded_reaction, qt_app):
    from PySide6.QtCore import Qt

    controller, _project, network, path_id, sources = loaded_reaction
    dialog = _builder_for_fixture(controller, network, path_id)
    assert dialog._request_reaction_preview("preview")
    _settle(qt_app, controller)
    assert dialog._accepted_preview is not None
    assert not dialog._accepted_preview[1].blocking
    before_revision = controller.project.revision
    before_nodes = tuple(node.id for node in controller.project.nodes)

    source_path = Path(sources[0].original_path)
    source_path.write_text(source_path.read_text(encoding="utf-8") + "changed after preview\n", encoding="utf-8")
    assert dialog._apply_and_save()
    assert "-10.000000000000" not in dialog.preview.text()
    _settle(qt_app, controller)

    assert dialog._flow_state == "draft"
    assert any(dialog.diagnostics_list.item(index).data(Qt.ItemDataRole.UserRole).get("code") == "source_changed"
               for index in range(dialog.diagnostics_list.count()))
    assert controller.project.revision == before_revision
    assert tuple(node.id for node in controller.project.nodes) == before_nodes
    dialog.close()


def test_preview_diagnostic_clicks_to_connection_and_source_evidence(loaded_reaction, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    controller, _project, network, path_id, sources = loaded_reaction
    unreviewed = deepcopy(network)
    edge = unreviewed["path_reactions"][0]["connections"][0]
    edge["confirmed"] = False
    edge["note"] = ""
    dialog = _builder_for_fixture(controller, unreviewed, path_id)
    generation = dialog.builder_draft.generation
    assert controller.preview_reaction_recipe(
        unreviewed, path_id, draft_generation=generation, base_revision=controller.project.revision,
    )
    token = controller.active_task_token
    dialog._pending_token = token
    dialog._pending_operation = "preview"
    dialog._pending_preview_mode = "preview"
    _settle(qt_app, controller)

    assert dialog.diagnostics_list.count() >= 1
    diagnostic = next(dialog.diagnostics_list.item(index)
                      for index in range(dialog.diagnostics_list.count())
                      if dialog.diagnostics_list.item(index).data(Qt.ItemDataRole.UserRole).get("connection_id"))
    dialog._focus_preview_diagnostic(diagnostic)
    assert dialog._selected_connection_id == edge["id"]

    stage_id = unreviewed["path_reactions"][0]["stages"][1]["id"]
    stage_item = QListWidgetItem("stage diagnostic")
    stage_item.setData(Qt.ItemDataRole.UserRole, {"path_id": path_id, "stage_id": stage_id})
    dialog._focus_preview_diagnostic(stage_item)
    assert dialog._selected_stage_id == stage_id

    source_item = QListWidgetItem("source evidence")
    source_item.setData(Qt.ItemDataRole.UserRole, {
        "path_id": path_id, "source_file_id": sources[0].id,
    })
    dialog._focus_preview_diagnostic(source_item)
    assert dialog.main_tabs.currentWidget() is dialog.evidence_page
    assert sources[0].display_name in dialog.evidence.text()
    dialog.close()
