#!/usr/bin/env python3
"""Exercise U1's visible editor entry in a fresh local Qt workspace."""
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
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.ui.main_window import MainWindow
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog
    from gaussianreadpro.ui.theme import apply_theme

    run_dir = ROOT / "artifacts" / "ux-v2" / "u1" / "desktop-runs" / uuid4().hex
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
    if not controller.edit_path("new", "U1 active path", color="#7450af"):
        raise RuntimeError("Could not create the synthetic active path")
    wait_idle(app, controller)
    active_path_id = controller.selected_path.id
    window.activate_route("energy")
    app.processEvents()

    topbar = window.findChild(type(window.builder_button.parentWidget()), "topbar")
    visible_controls = {}
    for name, widget in (("builder", window.builder_button), ("save", window.save_button),
                         ("project_name", window.project_name), ("saved_status", window.saved)):
        center = widget.mapTo(topbar, widget.rect().center())
        visible_controls[name] = {
            "visible": widget.isVisible(),
            "enabled": widget.isEnabled(),
            "rect_in_topbar": [widget.x(), widget.y(), widget.width(), widget.height()],
            "center_inside_topbar": topbar.rect().contains(center),
        }
    if not window.builder_button.isVisible() or not window.builder_button.isEnabled():
        raise AssertionError("The editor button is not visibly actionable")
    if any(not item["visible"] or not item["center_inside_topbar"] for item in visible_controls.values()):
        raise AssertionError(f"A persistent control is clipped: {visible_controls}")

    energy_screenshot = run_dir / "energy-entry-840x680.png"
    window.grab().save(str(energy_screenshot))
    dialog_evidence = {}

    def inspect_builder():
        dialog = next((item for item in QApplication.topLevelWidgets()
                       if isinstance(item, ReactionBuilderDialog)), None)
        if dialog is None:
            QTimer.singleShot(20, inspect_builder)
            return
        dialog_evidence.update({
            "visible": dialog.isVisible(),
            "active_path_id": dialog.path_combo.currentData(),
            "active_path_label": dialog.path_combo.currentText(),
        })
        dialog.grab().save(str(run_dir / "reaction-builder.png"))
        dialog.accept()

    QTimer.singleShot(0, inspect_builder)
    QTest.mouseClick(window.builder_button, Qt.MouseButton.LeftButton)
    if not dialog_evidence.get("visible"):
        raise AssertionError("Clicking the visible button did not show a real ReactionBuilderDialog")
    if dialog_evidence.get("active_path_id") != active_path_id:
        raise AssertionError(f"Active path mismatch: {dialog_evidence}")

    report = {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "platform": app.platformName(),
        "process_affinity": hex(affinity) if affinity is not None else None,
        "window_size": [window.width(), window.height()],
        "route": "energy",
        "active_path_id": active_path_id,
        "visible_controls": visible_controls,
        "button_click_opened_real_dialog": dialog_evidence,
        "screenshots": [energy_screenshot.name, "reaction-builder.png"],
        "synthetic_project_only": True,
    }
    (run_dir / "u1-desktop-evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"run_dir": str(run_dir), **report}, ensure_ascii=False, indent=2), flush=True)

    if not controller.close():
        raise RuntimeError("The synthetic controller did not accept close")
    wait_idle(app, controller)
    window.deleteLater()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
