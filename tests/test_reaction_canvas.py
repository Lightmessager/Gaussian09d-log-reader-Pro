from copy import deepcopy

import pytest

from gaussianreadpro.core import Project, ReactionPath
from gaussianreadpro.core.models import new_id
from gaussianreadpro.core.reaction_network import empty_network
from gaussianreadpro.ui.reaction_builder_state import BuilderDraft


def _stage(stage_id, species_id, label, parents=(), *, role="intermediate"):
    parents = list(parents)
    return {
        "id": stage_id,
        "role": role,
        "label": label,
        "predecessor_stage_id": parents[0] if parents else None,
        "predecessor_stage_ids": parents,
        "species": [{"species_id": species_id, "coefficient": 1.0}],
        "terms": [],
        "confirm_additional_terms": False,
        "node_id": None,
        "entry_id": None,
        "historical": False,
        "missing": False,
        "normalization_confirmed": True,
        "normalization_note": "已核对",
    }


def _draft_with_path():
    path = ReactionPath(new_id(), "画布测试", ())
    project = Project(new_id(), paths=(path,))
    draft = BuilderDraft.from_project(project, path.id)
    ids = {name: new_id() for name in ("species_a", "species_b", "species_c", "stage_a", "stage_b", "stage_c")}
    network = empty_network()
    network["species"] = [
        {"id": ids[f"species_{name}"], "name": name.upper(), "formula": "", "starred": False,
         "bindings": []}
        for name in ("a", "b", "c")
    ]
    stages = [
        _stage(ids["stage_a"], ids["species_a"], "A", role="reactant"),
        _stage(ids["stage_b"], ids["species_b"], "B", (ids["stage_a"],), role="transition_state"),
        _stage(ids["stage_c"], ids["species_c"], "C", role="product"),
    ]
    connection = {
        "id": new_id(), "source_stage_id": ids["stage_a"], "target_stage_id": ids["stage_b"],
        "confirmed": True, "note": "已核对", "reactants": deepcopy(stages[0]["species"]),
        "products": deepcopy(stages[1]["species"]), "terms": [],
    }
    network["path_reactions"].append({
        "path_id": path.id, "stages": stages, "connections": [connection],
        "zero_point": {"kind": "reactant", "stage_id": ""}, "preset": "relative_energy",
        "energy_kind": "gibbs_total", "energy_mode": "absolute", "historical": False,
    })
    draft.network = network
    return draft, ids


def _recipe(draft):
    return next(item for item in draft.network["path_reactions"] if item["path_id"] == draft.path_id)


def test_move_stage_changes_layout_only_and_undo_redo_are_local():
    draft, ids = _draft_with_path()
    before_network = deepcopy(draft.network)
    before = draft.snapshot()

    generation = draft.execute({"type": "move_stage", "stage_id": ids["stage_b"], "x": 260, "y": 140})

    assert generation == before["generation"] + 1
    assert draft.network == before_network
    assert draft.layout["stages"][ids["stage_b"]] == {"x": 260.0, "y": 140.0}
    assert draft.undo()
    assert draft.network == before_network
    assert draft.layout == before["layout"]
    assert draft.redo()
    assert draft.network == before_network
    assert draft.layout["stages"][ids["stage_b"]] == {"x": 260.0, "y": 140.0}


def test_saved_layout_ignores_unknown_and_invalid_coordinates():
    known = new_id()

    layout = BuilderDraft._sanitize_layout({"stages": {
        known: {"x": "80", "y": 24},
        new_id(): {"x": 10, "y": 20},
        "not-a-uuid": {"x": 20, "y": 30},
        known: {"x": float("inf"), "y": 24},
    }}, {known})

    assert layout == {}
    assert BuilderDraft._sanitize_layout({"stages": {
        known: {"x": 80, "y": 24},
        new_id(): {"x": 10, "y": 20},
    }}, {known}) == {"stages": {known: {"x": 80.0, "y": 24.0}}}


def test_connect_rejects_cycle_without_changing_draft_or_history():
    draft, ids = _draft_with_path()
    before = draft.snapshot()

    with pytest.raises(ValueError, match="cycle"):
        draft.execute({
            "type": "add_connection",
            "connection": {
                "id": new_id(), "source_stage_id": ids["stage_b"], "target_stage_id": ids["stage_a"],
                "confirmed": False, "note": "", "reactants": [], "products": [], "terms": [],
            },
        })

    assert draft.snapshot() == before
    assert not draft.undo()


def test_one_command_is_one_undo_and_new_command_clears_redo():
    draft, ids = _draft_with_path()
    before = draft.snapshot()
    new_connection = {
        "id": new_id(), "source_stage_id": ids["stage_a"], "target_stage_id": ids["stage_c"],
        "confirmed": False, "note": "", "reactants": [], "products": [], "terms": [],
    }

    draft.execute({"type": "add_connection", "connection": new_connection})
    assert draft.undo()
    restored = draft.snapshot()
    assert {key: value for key, value in restored.items() if key != "generation"} == {
        key: value for key, value in before.items() if key != "generation"}
    assert restored["generation"] == before["generation"] + 2
    assert draft.redo()
    assert any(edge["id"] == new_connection["id"] for edge in _recipe(draft)["connections"])
    assert draft.undo()
    draft.execute({"type": "move_stage", "stage_id": ids["stage_c"], "x": 120, "y": 80})
    assert not draft.redo()


def test_add_delete_connection_and_coefficient_change_each_have_one_undo():
    draft, ids = _draft_with_path()
    recipe = _recipe(draft)
    original_edge = deepcopy(recipe["connections"][0])
    new_connection = {
        "id": new_id(), "source_stage_id": ids["stage_a"], "target_stage_id": ids["stage_c"],
        "confirmed": False, "note": "", "reactants": [], "products": [], "terms": [],
    }

    generation = draft.generation
    draft.execute({"type": "add_connection", "connection": new_connection})
    assert draft.generation == generation + 1
    draft.execute({"type": "remove_connection", "connection_id": new_connection["id"]})
    assert draft.generation == generation + 2
    assert draft.undo()
    assert any(edge["id"] == new_connection["id"] for edge in _recipe(draft)["connections"])
    assert draft.undo()
    assert len(_recipe(draft)["connections"]) == 1

    generation = draft.generation
    draft.execute({"type": "update_connection", "connection_id": original_edge["id"],
        "fields": {"reactants": [{"species_id": ids["species_a"], "coefficient": 2.0}]}})
    assert draft.generation == generation + 1
    assert not _recipe(draft)["connections"][0]["confirmed"]
    assert draft.undo()
    assert _recipe(draft)["connections"][0] == original_edge


def test_science_edits_clear_confirmation_but_layout_and_label_do_not():
    draft, ids = _draft_with_path()
    recipe = _recipe(draft)
    edge_id = recipe["connections"][0]["id"]
    stage = next(item for item in recipe["stages"] if item["id"] == ids["stage_b"])

    draft.execute({"type": "update_stage", "stage_id": stage["id"], "fields": {"label": "过渡态 B"}})
    draft.execute({"type": "move_stage", "stage_id": stage["id"], "x": 80, "y": 60})
    recipe = _recipe(draft)
    stage = next(item for item in recipe["stages"] if item["id"] == ids["stage_b"])
    assert stage["normalization_confirmed"]
    assert next(edge for edge in recipe["connections"] if edge["id"] == edge_id)["confirmed"]

    composition = deepcopy(stage["species"])
    composition.append({"species_id": ids["species_c"], "coefficient": 2.0})
    draft.execute({"type": "set_composition", "stage_id": stage["id"], "species": composition})
    recipe = _recipe(draft)
    stage = next(item for item in recipe["stages"] if item["id"] == ids["stage_b"])
    assert not stage["normalization_confirmed"]
    assert stage["normalization_note"] == ""
    assert not next(edge for edge in recipe["connections"] if edge["id"] == edge_id)["confirmed"]
    assert draft.undo()
    restored = next(item for item in _recipe(draft)["stages"] if item["id"] == ids["stage_b"])
    assert restored["normalization_confirmed"]
    assert restored["normalization_note"] == "已核对"


def test_path_energy_options_are_one_scientific_command_and_undo_together():
    draft, _ = _draft_with_path()
    before = draft.snapshot()

    draft.execute({"type": "set_path_options", "path_options": {
        "energy_mode": "edge_recursive", "energy_kind": "scf", "label": "新路径名"}})

    recipe = _recipe(draft)
    assert recipe["energy_mode"] == "edge_recursive"
    assert recipe["energy_kind"] == "scf"
    assert draft.path_options["label"] == "新路径名"
    assert not recipe["connections"][0]["confirmed"]
    assert draft.undo()
    assert {key: value for key, value in draft.snapshot().items() if key != "generation"} == {
        key: value for key, value in before.items() if key != "generation"}


def test_connection_composition_rejects_unknown_nested_fields_atomically():
    draft, ids = _draft_with_path()
    edge_id = _recipe(draft)["connections"][0]["id"]
    before = draft.snapshot()

    with pytest.raises(ValueError, match="connection reactants"):
        draft.execute({"type": "update_connection", "connection_id": edge_id,
            "fields": {"reactants": [{"species_id": ids["species_a"], "coefficient": 1, "guess": True}]}})

    assert draft.snapshot() == before
    assert not draft.undo()


@pytest.mark.parametrize("command", [
    {"type": "move_stage", "stage_id": "stage_id", "x": float("nan"), "y": 0},
    {"type": "move_stage", "stage_id": "stage_id", "x": 100001, "y": 0},
    {"type": "move_stage", "stage_id": "stage_id", "x": 0, "y": 0, "extra": True},
])
def test_invalid_command_is_atomic(command):
    draft, ids = _draft_with_path()
    command = {**command, "stage_id": ids["stage_a"]}
    before = draft.snapshot()

    with pytest.raises(ValueError):
        draft.execute(command)

    assert draft.snapshot() == before
    assert not draft.undo()


def test_canvas_renders_roles_zero_point_missing_ts_and_branch_merge_edges():
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.reaction_canvas import ReactionCanvas

    app = QApplication.instance() or QApplication([])
    draft, ids = _draft_with_path()
    draft.execute({"type": "add_connection", "connection": {
        "id": new_id(), "source_stage_id": ids["stage_a"], "target_stage_id": ids["stage_c"],
        "confirmed": False, "note": "", "reactants": [], "products": [], "terms": [],
    }})
    draft.execute({"type": "add_connection", "connection": {
        "id": new_id(), "source_stage_id": ids["stage_b"], "target_stage_id": ids["stage_c"],
        "confirmed": False, "note": "", "reactants": [], "products": [], "terms": [],
    }})
    draft.execute({"type": "set_zero", "zero_point": {"kind": "reactant", "stage_id": ids["stage_a"]}})
    draft.execute({"type": "update_stage", "stage_id": ids["stage_b"], "fields": {"missing": True}})
    canvas = ReactionCanvas()
    canvas.set_draft(draft.snapshot())

    assert set(canvas.rendered_connection_pairs()) == {
        (ids["stage_a"], ids["stage_b"]),
        (ids["stage_a"], ids["stage_c"]),
        (ids["stage_b"], ids["stage_c"]),
    }
    assert canvas.stage_count() == 3
    assert "零点" in canvas.stage_item(ids["stage_a"]).toolTip()
    assert "NOT FOUND" in canvas.stage_item(ids["stage_b"]).toolTip()
    canvas.close()
    app.processEvents()


def test_canvas_selection_emits_kind_and_stage_uuid():
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.reaction_canvas import ReactionCanvas

    app = QApplication.instance() or QApplication([])
    draft, ids = _draft_with_path()
    canvas = ReactionCanvas()
    canvas.set_draft(draft.snapshot())
    selected = []
    canvas.selectionRequested.connect(lambda kind, identifier: selected.append((kind, identifier)))

    canvas.select_stage(ids["stage_b"])

    assert selected == [("stage", ids["stage_b"])]
    canvas.close()
    app.processEvents()


def test_canvas_movement_emits_one_layout_command_on_release():
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.reaction_canvas import ReactionCanvas

    app = QApplication.instance() or QApplication([])
    draft, ids = _draft_with_path()
    canvas = ReactionCanvas()
    canvas.set_draft(draft.snapshot())
    canvas.resize(760, 560)
    canvas.show()
    QTest.qWait(50)
    item = canvas.stage_item(ids["stage_a"])
    start = canvas.mapFromScene(item.mapToScene(item.boundingRect().center()))
    commands = []
    canvas.commandRequested.connect(commands.append)

    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(canvas.viewport(), start + QPoint(70, 42), delay=50)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(70, 42))
    app.processEvents()

    assert [item["type"] for item in commands] == ["move_stage"]
    assert commands[0]["stage_id"] == ids["stage_a"]
    assert commands[0]["x"] != commands[0]["y"]
    canvas.close()


def test_drop_targets_keep_composition_and_energy_edits_separate():
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.reaction_canvas import ReactionCanvas

    app = QApplication.instance() or QApplication([])
    draft, ids = _draft_with_path()
    canvas = ReactionCanvas()
    canvas.set_draft(draft.snapshot())
    commands, rejected = [], []
    canvas.commandRequested.connect(commands.append)
    canvas.dropRejected.connect(rejected.append)
    before = draft.snapshot()

    assert canvas.apply_species_drop([ids["species_c"]], ids["stage_b"], "composition")
    assert commands[-1]["type"] == "set_composition"
    assert commands[-1]["species"][-1]["species_id"] == ids["species_c"]
    assert canvas.apply_species_drop([ids["species_c"]], ids["stage_b"], "energy") is False
    assert commands[-1]["type"] == "set_composition"
    assert rejected
    assert draft.snapshot() == before
    canvas.close()
    app.processEvents()


def test_stage_inspector_shows_selected_details_and_emits_edit_commands():
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.reaction_stage_inspector import ReactionStageInspector

    app = QApplication.instance() or QApplication([])
    draft, ids = _draft_with_path()
    before_network = deepcopy(draft.network)
    inspector = ReactionStageInspector()
    inspector.set_draft(draft.snapshot(), ids["stage_b"])
    commands = []
    inspector.commandRequested.connect(commands.append)

    assert inspector.summary.toPlainText().find("B") >= 0
    assert "物质组成" in inspector.summary.toPlainText()
    inspector.stage_name.setText("TS-B")
    inspector.stage_name.editingFinished.emit()
    assert commands == [{"type": "update_stage", "stage_id": ids["stage_b"],
                         "fields": {"label": "TS-B"}}]
    assert draft.network == before_network
    inspector.close()
    app.processEvents()


def test_builder_dialog_routes_stage_commands_through_shared_draft_and_footer_is_present():
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    class Controller(QObject):
        busyChanged = Signal(bool, str)
        failed = Signal(str, str)

        def __init__(self, project):
            super().__init__()
            self.project = project
            self.read_only = False
            self.busy = False

    app = QApplication.instance() or QApplication([])
    path = ReactionPath(new_id(), "U4 dialog", ())
    dialog = ReactionBuilderDialog(Controller(Project(new_id(), paths=(path,))), path_id=path.id)
    dialog.resize(840, 680)
    dialog.show()
    app.processEvents()

    assert dialog.network is dialog.builder_draft.network
    assert dialog.stage_canvas.isVisible()
    assert dialog.stage_views.indexOf(dialog.stage_list.parentWidget()) == 1
    assert dialog.stage_inspector.isVisible()
    assert dialog.undo_button.isVisible() and dialog.redo_button.isVisible()
    for button in (dialog.apply_button, dialog.save_network_button, dialog.cancel_button):
        assert button.isVisible()

    dialog.species_name.setText("A")
    dialog._add_placeholder_species()
    species_id = dialog.network["species"][0]["id"]
    generation = dialog.builder_draft.generation
    dialog._add_stage([species_id])
    assert dialog.builder_draft.generation == generation + 1
    assert len(dialog._current_recipe()["stages"]) == 1
    dialog._undo_builder()
    assert dialog._current_recipe()["stages"] == []
    assert dialog.network is dialog.builder_draft.network
    dialog.close()
    app.processEvents()


def test_builder_dialog_explains_which_confirmations_a_science_edit_cleared():
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    class Controller(QObject):
        busyChanged = Signal(bool, str)
        failed = Signal(str, str)

        def __init__(self, project):
            super().__init__()
            self.project = project
            self.read_only = False
            self.busy = False

    app = QApplication.instance() or QApplication([])
    draft, ids = _draft_with_path()
    path = ReactionPath(draft.path_id, "确认失效测试", ())
    dialog = ReactionBuilderDialog(Controller(Project(draft.base_project_id, paths=(path,))),
                                   path_id=path.id)
    dialog.builder_draft = draft
    dialog.network = draft.network
    dialog._render_species()
    dialog._render_stages(ids["stage_b"])

    assert dialog._execute_draft_command({"type": "set_zero", "zero_point": {
        "kind": "reactant", "stage_id": ids["stage_a"]}})

    notice = dialog.stage_inspector.change_notice.text()
    assert "统一零点" in notice
    assert "A" in notice and "A → B" in notice
    dialog.close()
    app.processEvents()
