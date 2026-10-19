"""Persistence contract for local, unapplied reaction-builder drafts."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from gaussianreadpro.services.builder_drafts import (
    MAX_BUILDER_DRAFT_BYTES,
    BuilderDraftStore,
)
from gaussianreadpro.services.controller import ProjectController
from gaussianreadpro.services.session import SessionBackend
from gaussianreadpro.storage import StorageError
from gaussianreadpro.core import Project, ReactionPath
from gaussianreadpro.core.models import new_id
from gaussianreadpro.core.reaction_network import read_reaction_network
from gaussianreadpro.core.reaction_network import empty_network
from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog
from time import monotonic


def _payload(*, project_id=None, path_id=None, generation=3, revision=12):
    return {
        "project_id": project_id or str(uuid4()),
        "base_revision": revision,
        "path_id": path_id or str(uuid4()),
        "generation": generation,
        "network": {"species": [{"id": str(uuid4()), "name": "A"}]},
        "layout": {"stage": {"x": 12.5, "y": 9}},
        "path_options": {"label": "Path", "unit": "kcal_mol", "color": "#336699"},
        "legacy_mode": "empty",
    }


def test_builder_draft_round_trip_uses_only_uuid_derived_path(tmp_path):
    payload = _payload()
    store = BuilderDraftStore(tmp_path)

    saved_path = store.save(payload)

    assert saved_path == tmp_path / "ux-drafts" / payload["project_id"] / f"{payload['path_id']}.json"
    assert store.load(payload["project_id"], payload["path_id"]) == payload
    stored = json.loads(saved_path.read_text(encoding="utf-8"))
    assert stored["format"] == "gaussianreadpro.builder-draft"
    assert stored["version"] == 1


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(project_id="../../outside"),
    lambda value: value.update(path_id="not-a-uuid"),
    lambda value: value.update(base_revision=True),
    lambda value: value.update(generation=-1),
    lambda value: value.update(extra="not allowed"),
    lambda value: value.update(layout={"x": float("nan")}),
    lambda value: value.update(legacy_mode={"unexpected": True}),
])
def test_invalid_builder_draft_is_rejected_before_path_or_file_changes(tmp_path, mutate):
    store = BuilderDraftStore(tmp_path)
    good = _payload()
    saved = store.save(good)
    before = saved.read_bytes()
    invalid = _payload(project_id=good["project_id"], path_id=good["path_id"])
    mutate(invalid)

    with pytest.raises(StorageError):
        store.save(invalid)

    assert saved.read_bytes() == before
    assert list(saved.parent.glob("*.tmp")) == []


def test_builder_draft_size_limit_is_checked_on_write_and_read(tmp_path):
    store = BuilderDraftStore(tmp_path)
    payload = _payload()
    payload["network"] = {"padding": "x" * MAX_BUILDER_DRAFT_BYTES}

    with pytest.raises(StorageError, match="builder_draft_too_large"):
        store.save(payload)

    payload = _payload()
    path = store.save(payload)
    path.write_bytes(b" " * (MAX_BUILDER_DRAFT_BYTES + 1))
    with pytest.raises(StorageError, match="builder_draft_too_large"):
        store.load(payload["project_id"], payload["path_id"])


def test_corrupt_or_wrong_identity_builder_draft_is_not_loaded(tmp_path):
    payload = _payload()
    store = BuilderDraftStore(tmp_path)
    path = store.save(payload)
    path.write_text('{"format":"gaussianreadpro.builder-draft","version":1,', encoding="utf-8")
    with pytest.raises(StorageError, match="builder_draft_corrupt"):
        store.load(payload["project_id"], payload["path_id"])

    store.save(payload)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["project_id"] = str(uuid4())
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(StorageError, match="builder_draft_identity_mismatch"):
        store.load(payload["project_id"], payload["path_id"])


def test_duplicate_json_keys_and_non_finite_constants_are_rejected(tmp_path):
    payload = _payload()
    store = BuilderDraftStore(tmp_path)
    path = store.save(payload)
    path.write_text('{"format":"gaussianreadpro.builder-draft","version":1,"version":1}',
                    encoding="utf-8")
    with pytest.raises(StorageError, match="builder_draft_corrupt"):
        store.load(payload["project_id"], payload["path_id"])

    store.save(payload)
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "version": 99}),
                    encoding="utf-8")
    with pytest.raises(StorageError, match="builder_draft_corrupt"):
        store.load(payload["project_id"], payload["path_id"])

    path.write_text('{"format":"gaussianreadpro.builder-draft","version":1,"base_revision":NaN}',
                    encoding="utf-8")
    with pytest.raises(StorageError, match="builder_draft_corrupt"):
        store.load(payload["project_id"], payload["path_id"])


def test_failed_atomic_replace_preserves_previous_valid_draft_and_cleans_temp(tmp_path, monkeypatch):
    import gaussianreadpro.services.builder_drafts as builder_drafts

    original = _payload()
    store = BuilderDraftStore(tmp_path)
    target = store.save(original)
    old_bytes = target.read_bytes()
    changed = {**original, "generation": original["generation"] + 1,
               "network": {"species": [{"id": str(uuid4()), "name": "B"}]}}

    def interrupted_replace(_source, _destination):
        raise OSError("simulated interrupted atomic replacement")

    monkeypatch.setattr(builder_drafts.os, "replace", interrupted_replace)
    with pytest.raises(StorageError, match="builder_draft_write_failed"):
        store.save(changed)

    assert target.read_bytes() == old_bytes
    assert store.load(original["project_id"], original["path_id"]) == original
    assert list(target.parent.glob("*.tmp")) == []


def test_unwritable_draft_directory_preserves_previous_valid_file(tmp_path, monkeypatch):
    original = _payload()
    store = BuilderDraftStore(tmp_path)
    target = store.save(original)
    old_bytes = target.read_bytes()
    changed = {**original, "generation": original["generation"] + 1}
    original_mkdir = Path.mkdir

    def denied_directory(self, *args, **kwargs):
        if self == target.parent:
            raise PermissionError("simulated unwritable draft directory")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", denied_directory)
    with pytest.raises(StorageError, match="builder_draft_write_failed"):
        store.save(changed)

    assert target.read_bytes() == old_bytes


def test_remove_only_deletes_the_requested_generation(tmp_path):
    payload = _payload()
    store = BuilderDraftStore(tmp_path)
    path = store.save(payload)

    assert store.remove(payload["project_id"], payload["path_id"], payload["generation"] + 1) is False
    assert path.exists()
    assert store.remove(payload["project_id"], payload["path_id"], payload["generation"]) is True
    assert not path.exists()


def test_session_backend_loads_saved_draft_from_a_fresh_instance(tmp_path):
    payload = _payload()
    first_process = SessionBackend(tmp_path / "recovery")
    second_process = SessionBackend(tmp_path / "recovery")

    first_process.save_builder_draft(payload)

    assert second_process.load_builder_draft(payload["project_id"], payload["path_id"]) == payload
    assert second_process.remove_builder_draft(
        payload["project_id"], payload["path_id"], payload["generation"]
    ) is True


def test_saved_builder_draft_can_be_loaded_in_a_new_python_process(tmp_path):
    payload = _payload()
    BuilderDraftStore(tmp_path).save(payload)
    code = (
        "import json, sys; from gaussianreadpro.services.builder_drafts import BuilderDraftStore; "
        "print(json.dumps(BuilderDraftStore(sys.argv[1]).load(sys.argv[2], sys.argv[3]), "
        "ensure_ascii=False, sort_keys=True))"
    )

    result = subprocess.run([sys.executable, "-c", code, str(tmp_path),
                             payload["project_id"], payload["path_id"]],
                            capture_output=True, text=True, timeout=15, check=True)

    assert json.loads(result.stdout) == payload


def test_controller_serializes_draft_requests_and_emits_correlated_results(tmp_path, qt_app):
    controller = ProjectController(tmp_path / "recovery", tmp_path / "preferences.ini")

    def settle(timeout=10):
        from PySide6.QtTest import QTest
        deadline = monotonic() + timeout
        while controller.busy:
            qt_app.processEvents()
            QTest.qWait(5)
            assert monotonic() < deadline, controller.operation
        qt_app.processEvents()
        assert controller.pool.waitForDone(5000)

    events = []
    controller.builderDraftFinished.connect(lambda *args: events.append(args))
    try:
        assert controller.new_project()
        settle()
        payload = _payload(project_id=controller.project.id)

        assert controller.save_builder_draft(payload)
        save_token = controller.active_task_token
        settle()
        assert events[-1][:3] == (save_token, "builder_draft_save", True)
        assert Path(events[-1][3]) == (tmp_path / "recovery" / "ux-drafts" /
                                       payload["project_id"] / f"{payload['path_id']}.json")

        assert controller.load_builder_draft(payload["project_id"], payload["path_id"])
        load_token = controller.active_task_token
        settle()
        assert events[-1][:3] == (load_token, "builder_draft_load", True)
        assert events[-1][3] == payload

        controller.read_only = True
        assert controller.save_builder_draft(payload) is False
        assert controller.remove_builder_draft(payload["project_id"], payload["path_id"],
                                               payload["generation"]) is True
        settle()
        assert events[-1][2:] == (True, True, "", "")
    finally:
        if not controller._closed and not controller.busy:
            assert controller.close(allow_recovery=True)
            settle()


@pytest.fixture(scope="module")
def qt_app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def builder_dialog_factory(tmp_path, qt_app, monkeypatch):
    controllers = []
    dialogs = []

    def create(path_count=1, *, revision=0, load_recovery=False, project=None,
               recovery_key=None, read_only=False):
        paths = project.paths if project else tuple(
            ReactionPath(new_id(), f"Path {index + 1}", ()) for index in range(path_count))
        controller = ProjectController(tmp_path / (recovery_key or f"recovery-{len(controllers)}"),
                                       tmp_path / f"preferences-{len(controllers)}.ini")
        controller.project = project or Project(new_id(), paths=paths, revision=revision)
        if not load_recovery:
            controller.load_builder_draft = lambda *_args: False
        controller.read_only = read_only
        controller.results = ()
        controller.connections = ()
        dialog = ReactionBuilderDialog(controller, path_id=paths[0].id)
        dialog._ask_draft_exit = lambda _reason: "discard"
        dialog.show()
        qt_app.processEvents()
        controllers.append(controller)
        dialogs.append(dialog)
        return dialog, controller, paths

    yield create
    for dialog in dialogs:
        dialog._allow_close = True
        dialog.close()
    for controller in controllers:
        controller._status_timer.stop()
        controller._workspace_timer.stop()
        if controller.pool.activeThreadCount():
            controller.pool.waitForDone(5000)


def _dirty(dialog):
    dialog.network["u6_test_edit"] = True
    if dialog.builder_draft is not None:
        dialog.builder_draft.network = dialog.network


def _wait_for_controller(controller, app, timeout=10):
    from PySide6.QtTest import QTest
    deadline = monotonic() + timeout
    while controller.busy:
        app.processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, controller.operation
    app.processEvents()
    assert controller.pool.waitForDone(5000)


def test_dirty_reject_continue_keeps_dialog_and_draft_open(builder_dialog_factory, qt_app, monkeypatch):
    dialog, _controller, _paths = builder_dialog_factory()
    _dirty(dialog)
    monkeypatch.setattr(dialog, "_ask_draft_exit", lambda _reason: "continue")

    dialog.reject()

    assert dialog.isVisible()
    assert dialog.network["u6_test_edit"] is True


@pytest.mark.parametrize("trigger", ["cancel", "escape", "window_close"])
def test_cancel_escape_and_window_close_share_the_same_dirty_guard(builder_dialog_factory,
                                                                  qt_app, monkeypatch, trigger):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog, _controller, _paths = builder_dialog_factory()
    _dirty(dialog)
    reasons = []
    monkeypatch.setattr(dialog, "_ask_draft_exit",
                        lambda reason: reasons.append(reason) or "continue")

    if trigger == "cancel":
        dialog.cancel_button.click()
    elif trigger == "escape":
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        dialog.close()

    assert reasons == ["close"]
    assert dialog.isVisible()
    assert dialog.network["u6_test_edit"] is True


def test_dirty_reject_keep_waits_for_persisted_draft_before_closing(builder_dialog_factory, qt_app,
                                                                  monkeypatch):
    dialog, controller, _paths = builder_dialog_factory()
    _dirty(dialog)
    monkeypatch.setattr(dialog, "_ask_draft_exit", lambda _reason: "keep")

    dialog.reject()
    _wait_for_controller(controller, qt_app)

    saved = controller.backend.load_builder_draft(controller.project.id, dialog.builder_draft.path_id)
    assert saved["network"]["u6_test_edit"] is True
    assert not dialog.isVisible()


def test_failed_keep_draft_write_does_not_close_dialog(builder_dialog_factory, qt_app, monkeypatch):
    dialog, controller, _paths = builder_dialog_factory()
    _dirty(dialog)
    monkeypatch.setattr(dialog, "_ask_draft_exit", lambda _reason: "keep")
    monkeypatch.setattr(controller.backend.builder_drafts, "save",
                        lambda _payload: (_ for _ in ()).throw(StorageError("builder_draft_write_failed")))

    dialog.reject()
    _wait_for_controller(controller, qt_app)

    assert dialog.isVisible()
    assert dialog.network["u6_test_edit"] is True
    assert "builder_draft_write_failed" in dialog.flow_status.text()


def test_dirty_path_switch_continue_restores_previous_selection(builder_dialog_factory, monkeypatch):
    dialog, _controller, _paths = builder_dialog_factory(path_count=2)
    _dirty(dialog)
    monkeypatch.setattr(dialog, "_ask_draft_exit", lambda _reason: "continue")

    dialog.path_combo.setCurrentIndex(1)

    assert dialog.path_combo.currentData() == _paths[0].id
    assert dialog.builder_draft.path_id == _paths[0].id
    assert dialog.network["u6_test_edit"] is True


def test_dirty_path_switch_discard_reverts_draft_before_loading_next_path(builder_dialog_factory,
                                                                          monkeypatch):
    dialog, _controller, paths = builder_dialog_factory(path_count=2)
    _dirty(dialog)
    monkeypatch.setattr(dialog, "_ask_draft_exit", lambda _reason: "discard")

    dialog.path_combo.setCurrentIndex(1)

    assert dialog.path_combo.currentData() == paths[1].id
    assert dialog.builder_draft.path_id == paths[1].id
    assert "u6_test_edit" not in dialog.network


def test_dirty_path_switch_keep_saves_before_changing_path(builder_dialog_factory, qt_app, monkeypatch):
    dialog, controller, paths = builder_dialog_factory(path_count=2)
    _dirty(dialog)
    monkeypatch.setattr(dialog, "_ask_draft_exit", lambda _reason: "keep")

    dialog.path_combo.setCurrentIndex(1)
    _wait_for_controller(controller, qt_app)

    saved = controller.backend.load_builder_draft(controller.project.id, paths[0].id)
    assert saved["network"]["u6_test_edit"] is True
    assert dialog.path_combo.currentData() == paths[1].id
    assert dialog.builder_draft.path_id == paths[1].id


def test_same_revision_recovery_is_restored_only_as_an_unapplied_draft(builder_dialog_factory,
                                                                       qt_app, monkeypatch):
    first_dialog, first_controller, paths = builder_dialog_factory(recovery_key="shared-recovery")
    payload = _payload(project_id=first_controller.project.id, path_id=paths[0].id,
                       revision=first_controller.project.revision)
    payload["network"] = empty_network()
    payload["network"]["species"].append({"id": new_id(), "name": "Recovered", "formula": "",
                                           "starred": False, "bindings": []})
    first_controller.backend.save_builder_draft(payload)
    first_project = first_controller.project
    first_dialog.close()
    qt_app.processEvents()
    monkeypatch.setattr(ReactionBuilderDialog, "_ask_recovery_draft",
                        lambda _self, _payload, _conflict: "restore")

    recovered_dialog, recovered_controller, _ = builder_dialog_factory(
        load_recovery=True, project=first_project, recovery_key="shared-recovery")
    recovered_dialog.restore_draft_button.click()
    _wait_for_controller(recovered_controller, qt_app)

    assert any(item["name"] == "Recovered" for item in recovered_dialog.network["species"]), (
        recovered_dialog.flow_status.text())
    assert recovered_dialog._flow_state == "draft"
    assert recovered_dialog._persisted_draft_generation == payload["generation"]
    assert not any(item["name"] == "Recovered" for item in read_reaction_network(recovered_controller.project)["species"])


def test_different_revision_recovery_is_flagged_until_fresh_preview(builder_dialog_factory,
                                                                    qt_app, monkeypatch):
    first_dialog, first_controller, paths = builder_dialog_factory(recovery_key="conflict-recovery")
    payload = _payload(project_id=first_controller.project.id, path_id=paths[0].id, revision=2)
    payload["network"] = empty_network()
    payload["network"]["species"].append({"id": new_id(), "name": "Conflicted", "formula": "",
                                           "starred": False, "bindings": []})
    first_controller.backend.save_builder_draft(payload)
    first_project = Project(first_controller.project.id, paths=paths, revision=4)
    first_dialog._allow_close = True
    first_dialog.close()
    qt_app.processEvents()
    monkeypatch.setattr(ReactionBuilderDialog, "_ask_recovery_draft",
                        lambda _self, _payload, conflict: "restore" if conflict else "discard")

    recovered_dialog, recovered_controller, _ = builder_dialog_factory(
        revision=4, load_recovery=True, project=first_project, recovery_key="conflict-recovery")
    recovered_dialog.restore_draft_button.click()
    _wait_for_controller(recovered_controller, qt_app)

    assert recovered_dialog._recovery_revision_conflict is True, recovered_dialog.flow_status.text()
    assert any(item["name"] == "Conflicted" for item in recovered_dialog.network["species"])
    assert "重新检查" in recovered_dialog.flow_status.text()
    assert recovered_dialog._flow_state == "draft"


def test_invalid_recovered_network_is_not_applied_or_removed(builder_dialog_factory, qt_app,
                                                              monkeypatch):
    first_dialog, first_controller, paths = builder_dialog_factory(recovery_key="invalid-recovery")
    payload = _payload(project_id=first_controller.project.id, path_id=paths[0].id,
                       revision=first_controller.project.revision)
    payload["network"] = {"not_a_network": []}
    first_controller.backend.save_builder_draft(payload)
    first_project = first_controller.project
    first_dialog._allow_close = True
    first_dialog.close()
    qt_app.processEvents()
    monkeypatch.setattr(ReactionBuilderDialog, "_ask_recovery_draft",
                        lambda _self, _payload, _conflict: "restore")

    dialog, controller, _ = builder_dialog_factory(load_recovery=True, project=first_project,
                                                    recovery_key="invalid-recovery")
    dialog.restore_draft_button.click()
    _wait_for_controller(controller, qt_app)

    assert dialog.network == read_reaction_network(controller.project)
    assert controller.backend.load_builder_draft(controller.project.id, paths[0].id) == payload
    assert "未恢复" in dialog.flow_status.text()


def test_revision_conflict_clears_only_after_matching_nonblocking_preview(builder_dialog_factory,
                                                                         monkeypatch):
    dialog, controller, paths = builder_dialog_factory(revision=4)
    dialog._recovery_revision_conflict = True
    dialog.builder_draft.base_revision = 2
    token = 77
    preview = SimpleNamespace(project_id=controller.project.id, path_id=paths[0].id,
                              base_revision=controller.project.revision,
                              draft_generation=dialog.builder_draft.generation, blocking=False)
    dialog._pending_token = token
    dialog._pending_operation = "preview"
    dialog._pending_preview_mode = "preview"
    dialog._accepted_preview = (token, preview)
    monkeypatch.setattr(controller, "discard_reaction_preview", lambda _token: None)

    dialog._operation_finished(token, "reaction_preview", True, controller.project.id,
                               controller.project.revision, None)

    assert dialog._recovery_revision_conflict is False
    assert dialog.builder_draft.base_revision == controller.project.revision
    assert dialog._flow_state == "preview_ready"


def _add_keyboard_stage(dialog, label, role="reactant"):
    dialog.species_name.setText(label)
    dialog._add_placeholder_species()
    species_id = next(item["id"] for item in dialog.network["species"] if item["name"] == label)
    dialog.stage_role.setCurrentIndex(dialog.stage_role.findData(role))
    dialog.stage_name.setText(label)
    dialog._add_stage([species_id])
    return dialog._current_stage()["id"]


def test_stage_list_arrows_enter_and_delete_are_keyboard_equivalents(builder_dialog_factory, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog, _controller, _paths = builder_dialog_factory()
    first = _add_keyboard_stage(dialog, "A")
    second = _add_keyboard_stage(dialog, "B")
    dialog.stage_list.setCurrentRow(0)
    dialog.stage_list.setFocus()

    QTest.keyClick(dialog.stage_list, Qt.Key.Key_Down)
    assert dialog.stage_list.currentItem().data(Qt.ItemDataRole.UserRole) == second
    QTest.keyClick(dialog.stage_list, Qt.Key.Key_Up)
    assert dialog.stage_list.currentItem().data(Qt.ItemDataRole.UserRole) == first
    QTest.keyClick(dialog.stage_list, Qt.Key.Key_Return)
    assert dialog.main_tabs.currentIndex() == 0
    assert dialog.stage_views.currentIndex() == 0
    assert qt_app.focusWidget() is dialog.stage_inspector.stage_name

    QTest.keyClick(dialog.stage_list, Qt.Key.Key_Delete)
    assert all(stage["id"] != first for stage in dialog._current_recipe()["stages"])
    assert dialog.undo_button.isEnabled()
    dialog.undo_button.click()
    assert any(stage["id"] == first for stage in dialog._current_recipe()["stages"])


def test_builder_ctrl_s_is_scoped_to_apply_and_save(builder_dialog_factory, qt_app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog, _controller, _paths = builder_dialog_factory()
    calls = []
    monkeypatch.setattr(dialog, "_apply_and_save", lambda: calls.append("builder"))
    dialog.path_name.setFocus()
    QTest.keyClick(dialog.path_name, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)

    assert calls == ["builder"]


def test_ctrl_z_in_text_field_does_not_undo_builder_stage(builder_dialog_factory, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog, _controller, _paths = builder_dialog_factory()
    _add_keyboard_stage(dialog, "A")
    undo_count = len(dialog.builder_draft._undo_states)
    generation = dialog.builder_draft.generation
    original = dialog.path_name.text()
    dialog.path_name.setFocus()
    dialog.path_name.selectAll()
    QTest.keyClicks(dialog.path_name, "Edited path")
    QTest.keyClick(dialog.path_name, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert dialog.path_name.text() == original
    assert len(dialog.builder_draft._undo_states) == undo_count
    assert dialog.builder_draft.generation == generation


def test_tab_chain_and_draft_actions_have_accessible_names(builder_dialog_factory, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    dialog, _controller, _paths = builder_dialog_factory()
    _add_keyboard_stage(dialog, "A")
    controls = (dialog.species_list, dialog.stage_list, dialog.stage_inspector.stage_name,
                dialog.diagnostics_list, dialog.apply_button, dialog.cancel_button,
                dialog.restore_draft_button)
    assert all(widget.accessibleName() for widget in controls)

    dialog.species_list.setFocus()
    QTest.keyClick(dialog.species_list, Qt.Key.Key_Tab)
    assert qt_app.focusWidget() is dialog.stage_list
    QTest.keyClick(dialog.stage_list, Qt.Key.Key_Tab)
    assert qt_app.focusWidget() is dialog.stage_inspector.stage_name


def test_preview_issue_navigation_scrolls_and_focuses_invalid_stage_field(
        builder_dialog_factory, qt_app):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import QListWidgetItem

    dialog, _controller, _paths = builder_dialog_factory()
    stage_id = _add_keyboard_stage(dialog, "Needs review")
    dialog.resize(840, 680)
    dialog.right_panel_scroll.verticalScrollBar().setValue(
        dialog.right_panel_scroll.verticalScrollBar().maximum())
    dialog.right_panel_scroll.horizontalScrollBar().setValue(
        dialog.right_panel_scroll.horizontalScrollBar().maximum())
    issue = QListWidgetItem("Invalid stage field")
    issue.setData(Qt.ItemDataRole.UserRole, {"path_id": dialog.builder_draft.path_id,
                                             "stage_id": stage_id})

    dialog._focus_preview_diagnostic(issue)
    qt_app.processEvents()

    field = dialog.stage_inspector.stage_name
    scroll = dialog.right_panel_scroll
    position = field.mapTo(scroll.viewport(), QPoint(0, 0))
    visible_field = field.rect().translated(position)
    assert visible_field.intersects(scroll.viewport().rect())
    assert qt_app.focusWidget() is field


def test_read_only_exit_can_export_draft_text_without_writing_project(builder_dialog_factory,
                                                                      qt_app, monkeypatch):
    dialog, controller, _paths = builder_dialog_factory(read_only=True)
    _dirty(dialog)
    monkeypatch.setattr(dialog, "_ask_draft_exit", lambda _reason: "export")

    dialog.reject()

    exported = json.loads(qt_app.clipboard().text())
    assert exported["network"]["u6_test_edit"] is True
    assert exported["format"] == "gaussianreadpro.builder-draft"
    assert controller.project.revision == 0
    assert not dialog.isVisible()


def test_language_theme_and_resize_changes_preserve_unapplied_builder_draft(
        builder_dialog_factory, qt_app):
    from PySide6.QtCore import Qt
    from gaussianreadpro.ui.theme import apply_theme

    dialog, _controller, paths = builder_dialog_factory()
    stage_id = _add_keyboard_stage(dialog, "Language check")
    dialog.stage_list.setCurrentRow(0)
    _dirty(dialog)
    dialog.network["layout_marker"] = {"x": 12, "y": 24}
    dialog.builder_draft.network = dialog.network
    draft = dialog.builder_draft
    before = dialog._draft_dirty_signature()
    path_id = draft.path_id

    dialog.set_language("en")
    assert dialog.language == "en"
    assert dialog.restore_draft_button.text() == "Check for a saved draft…"
    assert dialog.apply_menu_button.text() == "More actions"
    assert dialog.cancel_button.text() == "Cancel"
    dialog.resize(840, 680)
    apply_theme(qt_app, "dark", reduced=True, reduce_motion=True)
    qt_app.processEvents()
    dialog.resize(1100, 820)
    apply_theme(qt_app, "light", reduced=False, reduce_motion=False)
    qt_app.processEvents()
    dialog.set_language("zh_CN")

    assert dialog.path_combo.currentData() == paths[0].id == path_id
    assert dialog.builder_draft is draft
    assert dialog._draft_dirty_signature() == before
    assert dialog.network["layout_marker"] == {"x": 12, "y": 24}
    assert dialog.stage_list.currentItem().data(Qt.ItemDataRole.UserRole) == stage_id
    assert dialog.stage_inspector._selected_id == stage_id
    assert dialog.restore_draft_button.text() == "检查恢复草稿…"
    assert dialog.apply_menu_button.text() == "更多操作"
    assert dialog.cancel_button.text() == "取消"
