"""User-created paths: explicit node identities, colours and persistence."""
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox

from gaussianreadpro.core.models import Unit, snapshot_to_dict
from gaussianreadpro.storage import ProjectRepository
from gaussianreadpro.ui.path_editor import NewPathDialog
from test_plot_spec_export import example
from test_workbench import app, workbench, settle, write_logs


def test_create_colored_path_inherits_reference_and_survives_save(workbench, app, tmp_path):
    _, controller = workbench
    controller.import_files(write_logs(tmp_path / "logs")); settle(app, controller)
    controller.reference_node(controller.project.nodes[0].id); settle(app, controller)
    template = controller.selected_path
    nodes = controller.project.nodes
    assert controller.edit_path("new", " Green path ", color="#52CDB8", node_ids=[nodes[0].id, nodes[2].id])
    settle(app, controller)
    created = controller.selected_path
    assert created.label == "Green path" and created.color == "#52cdb8"
    assert created.reference_expression == template.reference_expression
    assert created.energy_kind == template.energy_kind and created.unit == template.unit
    assert [e.node_id for e in created.entries] == [nodes[0].id, nodes[2].id]
    assert not {e.id for e in created.entries} & {e.id for e in template.entries}
    assert controller.project.nodes == nodes and controller.plot_state["compare"] is True
    destination = tmp_path / "colored.grproj"
    assert controller.save(destination); settle(app, controller)
    with ProjectRepository(destination, read_only=True) as repo:
        restored = repo.load()
    assert restored.paths[-1] == created
    assert restored.workspace_state["path_id"] == created.id and restored.plot_state["compare"] is True
    assert controller.undo(); settle(app, controller)
    assert len(controller.project.paths) == 1 and controller.project.nodes == nodes
    assert controller.redo(); settle(app, controller)
    assert controller.project.paths[-1] == created


def test_targeted_color_change_and_invalid_creation_do_not_change_selection(workbench, app):
    _, controller = workbench
    assert controller.edit_path("new", "First", color="#ad83ff"); settle(app, controller)
    first = controller.selected_path
    assert controller.edit_path("new", "Second", color="#68ACFF"); settle(app, controller)
    active = controller.selected_path.id
    assert controller.edit_path("color", "#F27DA9", path_id=first.id); settle(app, controller)
    assert controller.selected_path.id == active
    assert controller.project.paths[0].color == "#f27da9"
    snapshot = controller.project
    workspace = controller.workspace.copy()
    for kwargs in ({"label": ""}, {"label": "Invalid", "color": "red"},
                   {"label": "Invalid", "node_ids": ["unknown"]}, {"label": "Invalid", "color": "#12345678"}):
        assert not controller.edit_path("new", **kwargs)
        assert controller.project is snapshot and controller.workspace == workspace
    assert not controller.edit_path("color", None)
    controller.read_only = True
    assert not controller.edit_path("new", "Readonly", color="#123456")


def test_creation_dialog_validates_color_and_keeps_explicit_node_order(app, tmp_path):
    project, _, _ = example(tmp_path)
    dialog = NewPathDialog(project, project.paths[0], language="en")
    dialog.name_edit.setText("Custom path")
    dialog.color_edit.setText("notcolor")
    assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.color_edit.setText("#68AcFF")
    item = dialog.nodes.takeItem(2)
    dialog.nodes.insertItem(0, item)
    dialog.nodes.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.nodes.item(2).setCheckState(Qt.CheckState.Checked)
    values = dialog.values()
    assert values["color"] == "#68acff"
    assert values["node_ids"] == [project.nodes[2].id, project.nodes[1].id]
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.close()
