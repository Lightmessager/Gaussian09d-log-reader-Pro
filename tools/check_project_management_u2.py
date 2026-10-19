#!/usr/bin/env python3
"""Run U2 project naming/save scenarios in a fresh local Qt window."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))


def set_compatibility_affinity():
    if os.name != "nt":
        return None
    from diagnose_static_runtime import windows_affinity
    modes, _, select_affinity = windows_affinity()
    mask = modes["default"] & 0xFFFFFF3F
    select_affinity(mask)
    return mask


def wait_idle(app, controller, timeout=20):
    from PySide6.QtTest import QTest
    deadline = monotonic() + timeout
    while controller.busy:
        app.processEvents()
        QTest.qWait(5)
        if monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for {controller.operation}")
    app.processEvents()


def main():
    affinity = set_compatibility_affinity()
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.storage import ProjectRepository, StorageError
    from gaussianreadpro.storage.preferences import LocalPreferences
    from gaussianreadpro.ui.main_window import MainWindow
    from gaussianreadpro.ui.tables import ID_ROLE
    from gaussianreadpro.ui.theme import apply_theme

    run_dir = ROOT / "artifacts" / "ux-v2" / "u2" / "desktop-runs" / uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    controller = ProjectController(run_dir / "recovery", run_dir / "preferences.ini")
    window = MainWindow(controller)
    window.resize(840, 680)
    window.show()
    controller.bootstrap()
    wait_idle(app, controller)
    controller.new_project()
    wait_idle(app, controller)
    window.navigation.setCurrentRow(0)
    app.processEvents()

    name_answers = iter(("Desktop draft", "Desktop saved renamed", "Recent copy renamed"))
    QInputDialog.getText = staticmethod(lambda *_args, **_kwargs: (next(name_answers), True))
    QMessageBox.question = staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)

    # The real visible header button edits the unsaved name into workspace state.
    QTest.mouseClick(window.project_name, Qt.MouseButton.LeftButton)
    app.processEvents()
    if controller.workspace.get("ux_v2", {}).get("pending_project_name") != "Desktop draft":
        raise AssertionError("The header rename did not update the pending project name")

    target = run_dir / "Desktop draft.grproj"
    QFileDialog.getSaveFileName = staticmethod(lambda *_args, **_kwargs: ("", ""))
    window.save_project()
    canceled = controller.path is None and window.saved.text() == "尚未保存"

    original_save = controller.backend.save
    def fail_save(*_args, **_kwargs):
        raise StorageError("storage_io_failed", "synthetic U2 desktop failure")
    controller.backend.save = fail_save
    QFileDialog.getSaveFileName = staticmethod(lambda *_args, **_kwargs: (str(target), ""))
    window.save_project()
    wait_idle(app, controller)
    failed = (controller.path is None
              and controller.workspace.get("ux_v2", {}).get("pending_project_name") == "Desktop draft"
              and window.project_name.text() == "Desktop draft"
              and window.saved.text() == "保存失败")
    window.grab().save(str(run_dir / "first-save-failed-840x680.png"))

    controller.backend.save = original_save
    window.save_project()
    wait_idle(app, controller)
    first_save = {
        "canceled_name_kept": canceled,
        "failed_name_kept": failed,
        "retry_saved": controller.path == target.resolve() and window.saved.text() == "已保存",
        "pending_name_removed_from_active_project": "pending_project_name" not in controller.project.workspace_state.get("ux_v2", {}),
    }
    if not all(first_save.values()):
        raise AssertionError(f"First-save lifecycle failed: {first_save}")

    project_id = controller.project.id
    QTest.mouseClick(window.project_name, Qt.MouseButton.LeftButton)
    wait_idle(app, controller)
    renamed = run_dir / "Desktop saved renamed.grproj"
    current_rename = {
        "old_file_removed": not target.exists(),
        "new_file_exists": renamed.exists(),
        "path_updated": controller.path == renamed.resolve(),
        "project_id_preserved": controller.project.id == project_id,
    }
    if not all(current_rename.values()):
        raise AssertionError(f"Current-project rename failed: {current_rename}")

    copied_recent = run_dir / "recent-copy.grproj"
    with ProjectRepository(copied_recent, create=True) as repository:
        repository.save(controller.project)
    LocalPreferences(run_dir / "preferences.ini").remember_project(copied_recent)
    controller.preferences["recent_projects"] = LocalPreferences(run_dir / "preferences.ini").load()["recent_projects"]
    controller.recentChanged.emit()
    app.processEvents()
    for row in range(window.recent.count()):
        item = window.recent.item(row)
        data = item.data(ID_ROLE)
        if data and data[0] == "project" and Path(data[1]) == copied_recent.resolve():
            window.recent.setCurrentItem(item)
            break
    window.recent_rename_button.click()
    wait_idle(app, controller)
    recent_renamed = run_dir / "Recent copy renamed.grproj"
    recent_rename = {
        "old_recent_removed": not copied_recent.exists(),
        "new_recent_exists": recent_renamed.exists(),
        "current_project_unchanged": controller.path == renamed.resolve() and controller.project.id == project_id,
    }
    if not all(recent_rename.values()):
        raise AssertionError(f"Noncurrent recent rename failed: {recent_rename}")

    window.navigation.setCurrentRow(0)
    app.processEvents()
    for row in range(window.recent.count()):
        item = window.recent.item(row)
        data = item.data(ID_ROLE)
        if data and data[0] == "project" and Path(data[1]) == recent_renamed.resolve():
            window.recent.setCurrentItem(item)
            break
    action_widgets = {
        "open": window.recent_open_button,
        "rename": window.recent_rename_button,
        "remove_from_recent": window.recent_remove_button,
        "delete_file": window.recent_delete_button,
        "continue": window.continue_button,
    }
    visible_actions = {}
    for key, widget in action_widgets.items():
        center = widget.mapTo(window, widget.rect().center())
        visible_actions[key] = {
            "visible": widget.isVisible(),
            "enabled": widget.isEnabled(),
            "focusable": widget.focusPolicy().value != 0,
            "rect_inside_window": window.rect().contains(center),
            "text": widget.text(),
            "rect": [widget.x(), widget.y(), widget.width(), widget.height()],
        }
    if any(not item["visible"] or not item["rect_inside_window"] or not item["focusable"]
           for item in visible_actions.values()):
        raise AssertionError(f"Recent project actions are clipped or unreachable: {visible_actions}")
    window.grab().save(str(run_dir / "recent-project-actions-840x680.png"))

    window.language = "en"
    window.retranslate()
    english_actions = [widget.text() for widget in action_widgets.values()]
    if english_actions != ["Open", "Rename", "Remove from recent", "Delete project file", "Continue last session"]:
        raise AssertionError(f"Unexpected English action labels: {english_actions}")
    english_actions_enabled = [widget.isEnabled() for widget in action_widgets.values()]
    if not all(english_actions_enabled):
        raise AssertionError(f"Recent project actions should be enabled for the selected item: {english_actions_enabled}")
    window.grab().save(str(run_dir / "recent-project-actions-en-840x680.png"))

    report = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": app.platformName(),
        "process_affinity": hex(affinity) if affinity is not None else None,
        "window_size": [window.width(), window.height()],
        "first_save": first_save,
        "current_project_rename": current_rename,
        "noncurrent_recent_rename": recent_rename,
        "recent_actions_840x680": visible_actions,
        "english_recent_actions": english_actions,
        "english_recent_actions_enabled": english_actions_enabled,
        "synthetic_projects_only": True,
        "screenshots": ["first-save-failed-840x680.png", "recent-project-actions-840x680.png",
                        "recent-project-actions-en-840x680.png"],
    }
    (run_dir / "u2-desktop-evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), **report}, ensure_ascii=False, indent=2), flush=True)

    controller._workspace_timer.stop()
    if not controller.close():
        raise RuntimeError("The synthetic controller did not accept close")
    wait_idle(app, controller)
    window.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
