"""Local preference migration, queued UI changes and bounded motion behavior."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent
from PySide6.QtWidgets import QApplication

from gaussianreadpro.storage import StorageError
from gaussianreadpro.storage.codec import dumps
from gaussianreadpro.storage.preferences import DEFAULTS, LEGACY_V1_KEYS, LocalPreferences
from gaussianreadpro.ui.glass_widgets import GlassButton, GlassPanel
from gaussianreadpro.ui.theme import apply_theme
from test_workbench import app, workbench, settle, write_logs


def test_complete_legacy_preferences_migrate_without_writing_on_read(tmp_path):
    prefs = LocalPreferences(tmp_path / "old.ini")
    old = {key: deepcopy(DEFAULTS[key]) for key in LEGACY_V1_KEYS}
    old.update(language="en", theme="dark", recent_projects=["old.grproj"])
    raw = dumps(old)
    prefs.settings.setValue("preferences_v1", raw)
    prefs.settings.sync()
    migrated = prefs.load()
    assert migrated == dict(old, visual_effects="standard", reduce_motion=False)
    assert prefs.settings.value("preferences_v1") == raw
    prefs.save(visual_effects="reduced", reduce_motion=True)
    assert LocalPreferences(tmp_path / "old.ini").load() == dict(old, visual_effects="reduced", reduce_motion=True)


@pytest.mark.parametrize("change", [
    {"reduce_motion": 1}, {"reduce_motion": "false"}, {"reduce_motion": None},
    {"visual_effects": True}, {"visual_effects": "unknown"}, {"unknown": False},
])
def test_invalid_preferences_never_overwrite_existing_file(tmp_path, change):
    prefs = LocalPreferences(tmp_path / "prefs.ini")
    prefs.save(theme="dark")
    raw = prefs.settings.value("preferences_v1")
    with pytest.raises(StorageError, match="invalid_preferences"):
        prefs.save(**change)
    assert prefs.settings.value("preferences_v1") == raw


@pytest.mark.parametrize("missing", ["language", "reduce_motion", "visual_effects"])
def test_partial_or_unknown_preference_shapes_are_not_migrated(tmp_path, missing):
    prefs = LocalPreferences(tmp_path / "broken.ini")
    values = deepcopy(DEFAULTS)
    values.pop(missing)
    raw = dumps(values)
    prefs.settings.setValue("preferences_v1", raw)
    with pytest.raises(StorageError, match="invalid_preferences"):
        prefs.load()
    assert prefs.settings.value("preferences_v1") == raw


def test_visual_options_queue_save_and_leave_scientific_state_unchanged(workbench, app, tmp_path):
    window, controller = workbench
    controller.import_files(write_logs(tmp_path / "logs")); settle(app, controller)
    before = controller.project
    values = controller.results
    assert controller.update_preferences(theme="dark") and controller.busy
    window.visual_effects_action.setChecked(True)
    window.motion_action.setChecked(True)
    window.motion_action.setChecked(False)
    window.motion_action.setChecked(True)
    assert window.backdrop.reduced and app.property("glassReduceMotion")
    settle(app, controller)
    assert controller.project == before and controller.results == values
    saved = LocalPreferences(tmp_path / "prefs.ini").load()
    assert saved["visual_effects"] == "reduced" and saved["reduce_motion"] is True
    # A dialog created after the change must inherit the same material.
    panel = GlassPanel()
    assert panel.reduced
    panel.deleteLater()
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    settle(app, controller)
    assert window.visual_effects_action.text() == "Reduce visual effects"
    assert window.motion_action.text() == "Reduce motion"
    assert window.appearance_button.accessibleName() == "Appearance settings"


def test_button_transition_is_reused_stops_on_hide_and_reduced_motion_is_immediate(app):
    from PySide6.QtTest import QTest
    apply_theme(app, "light", reduce_motion=False)
    button = GlassButton("Feedback")
    button.show(); app.processEvents()
    button.clearFocus()
    for _ in range(8):
        QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    assert len(button.findChildren(QAbstractAnimation)) == 1
    QTest.qWait(200)
    assert button._transition.state() == QAbstractAnimation.State.Stopped
    QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
    button.hide()
    assert button._transition.state() == QAbstractAnimation.State.Stopped
    button.show(); app.processEvents()
    apply_theme(app, "dark", reduced=True, reduce_motion=True)
    QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
    assert button._edge == button._target()
    assert button._transition.state() == QAbstractAnimation.State.Stopped
    button.deleteLater()
    apply_theme(app, "light")
