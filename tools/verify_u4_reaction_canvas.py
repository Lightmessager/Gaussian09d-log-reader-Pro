"""Capture and check the U4 reaction builder at the 840x680 target size."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gaussianreadpro.core import Project, ReactionPath
from gaussianreadpro.core.models import new_id
from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog
from gaussianreadpro.ui.theme import apply_theme


class PreviewController(QObject):
    """QObject-compatible stub with the signals expected by the dialog."""

    busyChanged = Signal(bool, str)
    failed = Signal(str, str)

    def __init__(self, project):
        super().__init__()
        self.project = project
        self.read_only = False
        self.busy = False


def main():
    app = QApplication.instance() or QApplication([])
    apply_theme(app, "light")
    path = ReactionPath(new_id(), "U4 branching and merge", ())
    controller = PreviewController(Project(new_id(), paths=(path,)))
    dialog = ReactionBuilderDialog(controller, path_id=path.id)

    species_ids = []
    for name in ("Reactant", "Branch A", "Branch B", "Product"):
        species = {"id": new_id(), "name": name, "formula": "", "starred": False, "bindings": []}
        assert dialog._execute_draft_command({"type": "add_species", "species": species})
        species_ids.append(species["id"])

    stages = []
    for name, role, species_id, parents in (
        ("Reactant", "reactant", species_ids[0], []),
        ("Branch A", "intermediate", species_ids[1], []),
        ("Branch B", "intermediate", species_ids[2], []),
        ("Product", "product", species_ids[3], []),
    ):
        stage = {"id": new_id(), "role": role, "label": name,
            "predecessor_stage_id": parents[0] if parents else None,
            "predecessor_stage_ids": parents,
            "species": [{"species_id": species_id, "coefficient": 1.0}], "terms": [],
            "confirm_additional_terms": False, "node_id": None, "entry_id": None,
            "historical": False, "missing": False,
            "normalization_confirmed": False, "normalization_note": ""}
        stages.append(stage)

    for stage in stages:
        if stage["label"] == "Branch A" or stage["label"] == "Branch B":
            stage["predecessor_stage_ids"] = [stages[0]["id"]]
            stage["predecessor_stage_id"] = stages[0]["id"]
        elif stage["label"] == "Product":
            stage["predecessor_stage_ids"] = [stages[1]["id"], stages[2]["id"]]
            stage["predecessor_stage_id"] = stages[1]["id"]
        assert dialog._execute_draft_command({"type": "add_stage", "stage": stage})

    dialog.resize(840, 680)
    dialog.show()
    app.processEvents()
    QTest.qWait(150)

    assert dialog.size().width() == 840 and dialog.size().height() == 680, dialog.size()
    assert dialog.stage_canvas.stage_count() == 4
    assert len(dialog.stage_canvas.rendered_connection_pairs()) == 4
    assert dialog.stage_views.indexOf(dialog.stage_list.parentWidget()) == 1
    assert dialog.stage_canvas.isVisible() and dialog.stage_inspector.isVisible()
    visible_scene = dialog.stage_canvas.mapToScene(dialog.stage_canvas.viewport().rect()).boundingRect()
    selected_card = dialog.stage_canvas.stage_item(stages[-1]["id"])
    assert visible_scene.intersects(selected_card.sceneBoundingRect()), (
        visible_scene, selected_card.sceneBoundingRect(), dialog.stage_canvas.viewport().size(),
        dialog.stage_canvas.horizontalScrollBar().minimum(), dialog.stage_canvas.horizontalScrollBar().maximum(),
        dialog.stage_canvas.horizontalScrollBar().value(), dialog.stage_canvas.sceneRect(),
        dialog.stage_canvas._selected_stage_id, dialog._selected_stage_id)

    list_tab = dialog.stage_views.indexOf(dialog.stage_list.parentWidget())
    dialog.stage_views.setCurrentIndex(list_tab)
    app.processEvents()
    assert dialog.stage_list.isVisible(), "keyboard alternative list is unreachable"
    dialog.stage_views.setCurrentIndex(0)
    right_scroll = dialog.right_panel_scroll
    right_scroll.horizontalScrollBar().setValue(right_scroll.horizontalScrollBar().maximum())
    app.processEvents()
    role_field = dialog.stage_inspector.stage_role
    role_position = role_field.mapTo(right_scroll.viewport(), QPoint(0, 0))
    role_rect = role_field.rect().translated(role_position)
    assert role_rect.intersects(right_scroll.viewport().rect()), "stage detail control cannot be scrolled into view"
    right_scroll.horizontalScrollBar().setValue(0)
    app.processEvents()

    def within_dialog(widget):
        top_left = widget.mapTo(dialog, QPoint(0, 0))
        return (top_left.x() >= 0 and top_left.y() >= 0 and
                top_left.x() + widget.width() <= dialog.width() and
                top_left.y() + widget.height() <= dialog.height())

    primary_actions = (dialog.undo_button, dialog.redo_button, dialog.apply_button,
                       dialog.save_network_button, dialog.save_file_button, dialog.cancel_button)
    assert all(button.isVisible() and within_dialog(button) for button in primary_actions), [
        (button.text(), button.isVisible(), button.geometry().getRect()) for button in primary_actions]

    output = ROOT / "artifacts" / "ux-v2" / "u4" / "reaction_canvas_840x680.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    app.processEvents()
    image = app.primaryScreen().grabWindow(dialog.winId())
    assert not image.isNull(), "Qt returned an empty window capture"
    assert image.save(str(output)), output
    print(json.dumps({"window_size": [dialog.width(), dialog.height()],
        "stage_count": dialog.stage_canvas.stage_count(),
        "connection_count": len(dialog.stage_canvas.rendered_connection_pairs()),
        "primary_actions_within_window": True, "screenshot": str(output)}, ensure_ascii=False))
    dialog.close()
    app.processEvents()


if __name__ == "__main__":
    main()
