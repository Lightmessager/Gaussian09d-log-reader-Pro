"""Capture a visible U6 builder matrix at one Qt scale factor per process."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--dpr", type=float, required=True, choices=(1.0, 1.5, 2.0))
args = parser.parse_args()
try:
    _scale_percent = ctypes.windll.shcore.GetScaleFactorForDevice(0)
    _native_scale = _scale_percent / 100.0
    _native_dpi = round(96 * _native_scale)
except (AttributeError, OSError):
    try:
        _native_dpi = ctypes.windll.user32.GetDpiForSystem()
        _native_scale = _native_dpi / 96.0
    except (AttributeError, OSError):
        _native_dpi = 96
        _native_scale = 1.0
_qt_scale_factor = args.dpr / _native_scale
os.environ["QT_SCALE_FACTOR"] = str(_qt_scale_factor)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gaussianreadpro.core import Project, ReactionPath
from gaussianreadpro.core.models import new_id
from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog
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
        self.connections = ()


def _fixture():
    path = ReactionPath(new_id(), "U6 desktop matrix", ())
    project = Project(new_id(), paths=(path,))
    return project, path.id


def _add_stage(dialog, name, role, species_id, predecessors=()):
    stage_id = new_id()
    stage = {
        "id": stage_id, "role": role, "label": name,
        "predecessor_stage_id": predecessors[0] if predecessors else None,
        "predecessor_stage_ids": list(predecessors),
        "species": [{"species_id": species_id, "coefficient": 1.0}], "terms": [],
        "confirm_additional_terms": False, "node_id": None, "entry_id": None,
        "historical": False, "missing": False,
        "normalization_confirmed": False, "normalization_note": "",
    }
    assert dialog._execute_draft_command({"type": "add_stage", "stage": stage})
    return stage_id


def _populate(dialog):
    species_ids = []
    for name in ("反应物 R", "过渡态 TS", "产物 P"):
        identifier = new_id()
        assert dialog._execute_draft_command({"type": "add_species", "species": {
            "id": identifier, "name": name, "formula": "", "starred": False, "bindings": []}})
        species_ids.append(identifier)
    first = _add_stage(dialog, "反应物 R", "reactant", species_ids[0])
    second = _add_stage(dialog, "过渡态 TS", "transition_state", species_ids[1], (first,))
    _add_stage(dialog, "产物 P", "product", species_ids[2], (second,))
    dialog.stage_list.setCurrentRow(1)
    return second


def _rect_inside(dialog, widget):
    top_left = widget.mapTo(dialog, QPoint(0, 0))
    return (top_left.x() >= 0 and top_left.y() >= 0 and
            top_left.x() + widget.width() <= dialog.width() and
            top_left.y() + widget.height() <= dialog.height())


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    project, path_id = _fixture()
    controller = PreviewController(project)
    dialog = ReactionBuilderDialog(controller, path_id=path_id)
    selected_stage = _populate(dialog)
    draft = dialog.builder_draft
    generation = draft.generation
    output_dir = ROOT / "artifacts" / "ux-v2" / "u6" / f"dpr-{args.dpr:g}"
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("*.png"):
        if "-actual" not in stale.name:
            stale.unlink()
    records = []
    available = app.primaryScreen().availableGeometry()

    try:
        dialog.show()
        app.processEvents()
        QTest.qWait(120)
        for width, height in ((840, 680), (1100, 820), (1440, 900)):
            screen_limit = (max(840, available.width() - 16),
                            max(560, available.height() - 12))
            actual_target = (min(width, screen_limit[0]), min(height, screen_limit[1]))
            constrained_by_screen = actual_target != (width, height)
            dialog.resize(*actual_target)
            for language in ("zh_CN", "en"):
                dialog.set_language(language)
                for theme in ("light", "dark"):
                    reduced = (language == "en") == (theme == "dark")
                    apply_theme(app, theme, reduced=reduced, reduce_motion=reduced)
                    app.processEvents()
                    QTest.qWait(80)
                    assert (dialog.width(), dialog.height()) == actual_target, (
                        dialog.size(), actual_target, available.getRect(), dialog.minimumSizeHint(),
                        [(type(widget).__name__, widget.objectName(), widget.minimumSizeHint().width(),
                          widget.minimumSizeHint().height()) for widget in dialog.findChildren(QObject)
                         if hasattr(widget, "minimumSizeHint") and
                         (widget.minimumSizeHint().width() > 200 or widget.minimumSizeHint().height() > 100)])
                    assert dialog.builder_draft is draft
                    assert draft.generation == generation
                    assert dialog.stage_list.currentItem().data(Qt.ItemDataRole.UserRole) == selected_stage
                    assert dialog.stage_inspector._selected_id == selected_stage

                    actions = (dialog.restore_draft_button, dialog.undo_button, dialog.redo_button,
                               dialog.apply_button, dialog.apply_menu_button,
                               dialog.preview_button, dialog.cancel_button)
                    action_records = []
                    for button in actions:
                        assert button.isVisibleTo(dialog) and _rect_inside(dialog, button), (
                            width, height, language, theme, button.text(), button.geometry().getRect())
                        assert button.accessibleName(), (button.text(), button.accessibleName())
                        measured = button.fontMetrics().horizontalAdvance(button.text())
                        action_records.append({
                            "text": button.text(), "accessible_name": button.accessibleName(),
                            "width": button.width(), "text_advance": measured,
                            "fits_single_line": measured <= button.contentsRect().width(),
                        })
                    assert all(item["fits_single_line"] for item in action_records), action_records

                    dialog.species_list.setFocus()
                    QTest.keyClick(dialog.species_list, Qt.Key.Key_Tab)
                    assert app.focusWidget() is dialog.stage_list
                    QTest.keyClick(dialog.stage_list, Qt.Key.Key_Tab)
                    assert app.focusWidget() is dialog.stage_inspector.stage_name
                    dialog.restore_draft_button.setFocus()
                    app.processEvents()

                    file_name = (f"{width}x{height}-actual{dialog.width()}x{dialog.height()}-"
                                 f"{language}-{theme}-r{int(reduced)}.png")
                    output = output_dir / file_name
                    image = app.primaryScreen().grabWindow(dialog.winId())
                    assert not image.isNull() and image.save(str(output)), output
                    records.append({
                        "window_size": [width, height], "requested_scale_factor": args.dpr,
                        "actual_window_size": [dialog.width(), dialog.height()],
                        "screen_available_size": [available.width(), available.height()],
                        "constrained_by_screen": constrained_by_screen,
                        "native_system_dpi": _native_dpi, "qt_scale_factor": _qt_scale_factor,
                        "actual_dpr": dialog.devicePixelRatioF(), "language": language,
                        "theme": theme, "reduced_effects_and_motion": reduced,
                        "focused_tab_chain": ["species_list", "stage_list", "stage_inspector.stage_name"],
                        "draft_generation_preserved": draft.generation == generation,
                        "selected_stage_preserved": selected_stage,
                        "actions": action_records, "screenshot": str(output.resolve()),
                    })
        dialog._allow_close = True
        dialog.close()
    finally:
        dialog._allow_close = True
        if dialog.isVisible():
            dialog.close()

    report = {
        "matrix": "U6 draft protection",
        "requested_scale_factor": args.dpr,
        "native_system_dpi": _native_dpi, "qt_scale_factor": _qt_scale_factor,
        "screenshots": len(records),
        "records": records,
    }
    report_path = output_dir / "validation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path.resolve()), "screenshots": len(records),
                      "requested_scale_factor": args.dpr,
                      "native_system_dpi": _native_dpi, "qt_scale_factor": _qt_scale_factor,
                      "actual_dprs": sorted({item["actual_dpr"] for item in records})},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
