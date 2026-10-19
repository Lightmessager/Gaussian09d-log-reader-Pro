from pathlib import Path

import pytest

from gaussianreadpro.storage.recovery import SaveStatus
from gaussianreadpro.ui.workflow_state import derive_save_feedback, normalize_project_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  催化反应  ", "催化反应"),
        ("a ", "a"),
        ("Study.grproj", "Study"),
        ("Mixed.GRPROJ", "Mixed"),
        ("part.one", "part.one"),
    ],
)
def test_normalize_project_name_accepts_supported_names(raw, expected):
    assert normalize_project_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "", "   ", ".grproj", "x" * 121, "a/b", "a\\b", "a:b", "a?b",
        "a*b", "a|b", "a<b", 'a"b', "a\nb", "a.", "CON", "con.grproj",
        "PRN.txt", "COM1", "LPT9.log", "name.grproj.grproj",
    ],
)
def test_normalize_project_name_rejects_unsafe_or_ambiguous_names(raw):
    with pytest.raises(ValueError):
        normalize_project_name(raw)


@pytest.mark.parametrize(
    ("kwargs", "expected_state", "expected_recovery"),
    [
        ({"path": None, "status": None, "project_revision": 3}, "尚未保存", ""),
        ({"path": Path("x.grproj"), "status": SaveStatus(current_revision=3, saved_revision=2), "project_revision": 3}, "未保存更改", ""),
        ({"path": Path("x.grproj"), "status": SaveStatus(current_revision=3, saved_revision=2), "project_revision": 3, "busy_operation": "save"}, "保存中", ""),
        ({"path": Path("x.grproj"), "status": SaveStatus(current_revision=3, saved_revision=3), "project_revision": 3}, "已保存", ""),
        ({"path": Path("x.grproj"), "status": SaveStatus(current_revision=4, saved_revision=4), "project_revision": 3}, "已保存", ""),
        ({"path": Path("x.grproj"), "status": SaveStatus(current_revision=3, saved_revision=2, error_code="disk_full"), "project_revision": 3}, "保存失败", ""),
        ({"path": Path("x.grproj"), "status": SaveStatus(current_revision=3, saved_revision=2, recovery_revision=3), "project_revision": 3}, "未保存更改", "已保留恢复副本"),
        ({"path": Path("x.grproj"), "status": SaveStatus(current_revision=3, saved_revision=3), "project_revision": 3, "read_only": True}, "只读", ""),
        ({"path": None, "status": None, "project_revision": 3, "save_failed": True}, "保存失败", ""),
    ],
)
def test_derive_save_feedback_keeps_main_and_recovery_state_separate(kwargs, expected_state, expected_recovery):
    result = derive_save_feedback(**kwargs)
    assert result.state == expected_state
    assert result.recovery_hint == expected_recovery


def test_recovery_error_does_not_hide_successful_main_file_save():
    status = SaveStatus(current_revision=3, saved_revision=3, recovery_error_code="recovery_locked")
    result = derive_save_feedback(path=Path("x.grproj"), status=status, project_revision=3)
    assert result.state == "已保存"
    assert result.recovery_hint == "恢复副本保存失败"


def test_save_failure_takes_precedence_over_missing_target():
    result = derive_save_feedback(path=None, status=None, project_revision=3, save_failed=True)
    assert result.state == "保存失败"


@pytest.fixture(scope="module")
def qt_app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def _settle(app, controller, timeout=10):
    from time import monotonic
    from PySide6.QtTest import QTest
    deadline = monotonic() + timeout
    while controller.busy:
        app.processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, controller.operation
    app.processEvents()


@pytest.fixture
def controller(qt_app, tmp_path):
    from gaussianreadpro.services.controller import ProjectController
    instance = ProjectController(tmp_path / "recovery", tmp_path / "prefs.ini")
    instance.bootstrap()
    _settle(qt_app, instance)
    instance.new_project()
    _settle(qt_app, instance)
    yield instance
    instance._workspace_timer.stop()
    _settle(qt_app, instance)
    if not instance._closed:
        instance.close()
        _settle(qt_app, instance)


def test_controller_exposes_active_token_and_reports_save_completion(controller, qt_app, tmp_path):
    completed = []
    controller.operationFinished.connect(lambda *args: completed.append(args))
    destination = tmp_path / "named.grproj"
    assert controller.save(destination)
    token = controller.active_task_token
    assert token is not None
    _settle(qt_app, controller)
    assert controller.active_task_token is None
    assert completed == [(token, "save", True, controller.project.id, controller.project.revision, str(destination.resolve()))]


def test_active_task_token_stays_stable_while_worker_is_busy(controller, qt_app):
    from threading import Event
    entered, release = Event(), Event()
    completed = []
    controller.operationFinished.connect(lambda *args: completed.append(args))

    def slow():
        entered.set()
        assert release.wait(5)
        return "finished"

    assert controller._submit("test_wait", slow, guard=False)
    token = controller.active_task_token
    assert token is not None and entered.wait(2)
    qt_app.processEvents()
    assert controller.active_task_token == token
    assert not controller.save()
    assert controller.active_task_token == token
    release.set()
    _settle(qt_app, controller)
    assert completed == [(token, "test_wait", True, controller.project.id, controller.project.revision, None)]


def test_nested_ux_workspace_update_preserves_other_fields(controller):
    controller.workspace = {"page": 2, "ux_v2": {"version": 1, "builder_layouts": {"p": {"x": 1}}, "extension": "keep"}}
    controller.set_workspace(ux_v2={"pending_project_name": "New name"})
    assert controller.workspace == {
        "page": 2,
        "ux_v2": {"version": 1, "builder_layouts": {"p": {"x": 1}}, "extension": "keep", "pending_project_name": "New name"},
    }


def test_first_save_removes_only_pending_name_from_saved_workspace(controller, qt_app, tmp_path):
    from gaussianreadpro.storage import ProjectRepository
    controller.workspace = {"page": 2, "ux_v2": {"version": 1, "pending_project_name": "First name", "extension": "keep"}}
    controller._workspace_dirty = True
    destination = tmp_path / "first-name.grproj"
    assert controller.save(destination)
    _settle(qt_app, controller)
    assert "pending_project_name" not in controller.project.workspace_state["ux_v2"]
    assert controller.project.workspace_state["ux_v2"]["extension"] == "keep"
    with ProjectRepository(destination, read_only=True) as repository:
        persisted = repository.load()
    assert "pending_project_name" not in persisted.workspace_state["ux_v2"]
    assert persisted.workspace_state["ux_v2"]["extension"] == "keep"


def test_failed_save_completion_reports_submitted_identity(controller, qt_app, tmp_path, monkeypatch):
    from gaussianreadpro.storage import StorageError
    completed = []
    controller.operationFinished.connect(lambda *args: completed.append(args))

    def fail(*_args):
        raise StorageError("storage_io_failed")

    monkeypatch.setattr(controller.backend, "save", fail)
    target = tmp_path / "failed.grproj"
    project_id, revision = controller.project.id, controller.project.revision
    assert controller.save(target)
    token = controller.active_task_token
    _settle(qt_app, controller)
    assert completed == [(token, "save", False, project_id, revision, str(target.resolve()))]


@pytest.fixture
def window_controller(controller, qt_app):
    from gaussianreadpro.ui.main_window import MainWindow
    window = MainWindow(controller)
    window.show()
    qt_app.processEvents()
    yield window, controller
    controller._workspace_timer.stop()
    _settle(qt_app, controller)
    if not controller._closed:
        controller.close()
        _settle(qt_app, controller)
    window.deleteLater()
    qt_app.processEvents()


def test_recent_project_actions_are_visible_and_keyboard_reachable(window_controller, qt_app):
    window, _controller = window_controller
    assert window.home_layout.indexOf(window.home_welcome) < window.home_layout.indexOf(window.home_recent_card)
    window.resize(840, 680)
    window.navigation.setCurrentRow(0)
    qt_app.processEvents()
    assert window.home_layout.indexOf(window.home_recent_card) < window.home_layout.indexOf(window.home_welcome)
    buttons = (window.recent_open_button, window.recent_rename_button,
               window.recent_remove_button, window.recent_delete_button)
    action_buttons = buttons + (window.continue_button,)
    assert all(button.isVisible() for button in action_buttons)
    assert all(button.focusPolicy().value != 0 for button in action_buttons)
    viewport = window.home_scroll.viewport()
    assert all(viewport.rect().contains(button.mapTo(viewport, button.rect().center())) for button in action_buttons)
    window.language = "en"
    window.retranslate()
    assert window.recent_rename_button.text() == "Rename"
    assert all(button.fontMetrics().horizontalAdvance(button.text()) + 20 <= button.width()
               for button in action_buttons), [(button.text(), button.width(), button.fontMetrics().horizontalAdvance(button.text()))
                                               for button in action_buttons]
    window.resize(1440, 920)
    qt_app.processEvents()
    assert window.home_layout.indexOf(window.home_welcome) < window.home_layout.indexOf(window.home_recent_card)


def test_unsaved_project_name_is_workspace_backed_and_nested_merge_is_preserved(window_controller, qt_app, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    window, controller = window_controller
    controller.workspace = {"page": 2, "ux_v2": {"version": 1, "last_builder_step": "materials", "extension": "keep"}}
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_args, **_kwargs: ("Renamed draft", True)))
    window.rename_current_project()
    assert controller.path is None
    assert controller.workspace["ux_v2"] == {
        "version": 1, "last_builder_step": "materials", "extension": "keep", "pending_project_name": "Renamed draft",
    }
    assert window.project_name.text() == "Renamed draft"


def test_saved_current_project_rename_updates_path_only_after_backend_success(window_controller, qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QInputDialog
    window, controller = window_controller
    source_file = tmp_path / "source.log"
    source_file.write_text(
        "Entering Gaussian System\n"
        " SCF Done: E(RB3LYP) = -100.000000000000 A.U.\n"
        " Thermal correction to Gibbs Free Energy= 0.001000000000\n"
        " Sum of electronic and thermal Free Energies= -99.999000000000\n"
        " Normal termination of Gaussian 16\n",
        encoding="utf-8",
    )
    assert controller.import_files([source_file])
    _settle(qt_app, controller)
    original = tmp_path / "Current.grproj"
    assert controller.save(original)
    _settle(qt_app, controller)
    project_id = controller.project.id
    before = controller.project
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_args, **_kwargs: ("Renamed current", True)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes))
    window.rename_current_project()
    assert controller.busy and controller.path == original.resolve()
    _settle(qt_app, controller)
    renamed = tmp_path / "Renamed current.grproj"
    assert controller.path == renamed.resolve()
    assert not original.exists() and renamed.exists()
    assert controller.project.id == project_id
    assert controller.project.nodes == before.nodes
    assert controller.project.paths == before.paths
    assert controller.project.source_files == before.source_files
    assert controller.project.alias_bindings == before.alias_bindings
    assert window.project_name.text() == "Renamed current"
    assert window.windowTitle().startswith("Renamed current")


def test_noncurrent_recent_rename_does_not_switch_current_project(window_controller, qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QInputDialog
    from gaussianreadpro.storage import ProjectRepository
    from gaussianreadpro.storage.preferences import LocalPreferences
    from gaussianreadpro.ui.tables import ID_ROLE
    window, controller = window_controller
    current = tmp_path / "current.grproj"
    assert controller.save(current)
    _settle(qt_app, controller)
    project_id = controller.project.id
    recent = tmp_path / "recent.grproj"
    with ProjectRepository(current, read_only=True) as repository:
        snapshot = repository.load()
    with ProjectRepository(recent, create=True) as repository:
        repository.save(snapshot)
    prefs = LocalPreferences(tmp_path / "prefs.ini")
    prefs.remember_project(recent)
    controller.preferences["recent_projects"] = prefs.load()["recent_projects"]
    controller.recentChanged.emit()
    qt_app.processEvents()
    window.navigation.setCurrentRow(0)
    for row in range(window.recent.count()):
        item = window.recent.item(row)
        data = item.data(ID_ROLE)
        if data and data[0] == "project" and Path(data[1]) == recent.resolve():
            window.recent.setCurrentItem(item)
            break
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_args, **_kwargs: ("recent-renamed", True)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes))
    window.recent_rename_button.click()
    _settle(qt_app, controller)
    renamed = tmp_path / "recent-renamed.grproj"
    assert controller.path == current.resolve()
    assert controller.project.id == project_id
    assert recent.exists() is False and renamed.exists()
    assert str(renamed.resolve()) in prefs.load()["recent_projects"]


def test_rename_conflict_and_case_only_change_keep_old_project(window_controller, qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QInputDialog
    window, controller = window_controller
    original = tmp_path / "study.grproj"
    conflict = tmp_path / "taken.grproj"
    conflict.write_text("occupied", encoding="utf-8")
    assert controller.save(original)
    _settle(qt_app, controller)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_args, **_kwargs: ("STUDY", True)))
    window.rename_current_project()
    assert controller.path == original.resolve() and original.exists()
    assert "大小写" in window.banner.text()

    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_args, **_kwargs: ("taken", True)))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes))
    window.rename_current_project()
    _settle(qt_app, controller)
    assert controller.path == original.resolve()
    assert original.exists() and conflict.exists()
    assert "已存在" in window.banner.text()


def test_first_save_failure_keeps_name_and_retry_saves_it_as_filename(window_controller, qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog
    from gaussianreadpro.services.session import SessionBackend
    from gaussianreadpro.storage import ProjectRepository, StorageError
    window, controller = window_controller
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_args, **_kwargs: ("First draft", True)))
    window.new_project()
    _settle(qt_app, controller)
    controller._workspace_timer.stop()
    controller._persist_workspace()
    _settle(qt_app, controller)
    controller.backend.recovery.flush()
    recovered_draft = controller.backend.recovery.recovery.load()
    assert recovered_draft.workspace_state["ux_v2"]["pending_project_name"] == "First draft"
    target = tmp_path / "First draft.grproj"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_args, **_kwargs: (str(target), "")))
    original_save = controller.backend.save

    def fail(*_args, **_kwargs):
        raise StorageError("storage_io_failed", "injected disk error")

    monkeypatch.setattr(controller.backend, "save", fail)
    window.save_project()
    _settle(qt_app, controller)
    assert controller.path is None
    assert controller.workspace["ux_v2"]["pending_project_name"] == "First draft"
    assert window.project_name.text() == "First draft"
    assert window.saved.text() == "保存失败"

    monkeypatch.setattr(controller.backend, "save", original_save)
    window.save_project()
    _settle(qt_app, controller)
    assert controller.path == target.resolve()
    assert window.saved.text() == "已保存"
    assert "pending_project_name" not in controller.project.workspace_state["ux_v2"]
    with ProjectRepository(target, read_only=True) as repository:
        assert "pending_project_name" not in repository.load().workspace_state["ux_v2"]


def test_first_save_completion_clears_pending_name_after_workspace_changes_in_flight(
        window_controller, qt_app, tmp_path, monkeypatch):
    from threading import Event
    from PySide6.QtWidgets import QFileDialog, QInputDialog
    from gaussianreadpro.storage import ProjectRepository
    window, controller = window_controller
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_args, **_kwargs: ("First draft", True)))
    window.new_project()
    _settle(qt_app, controller)
    controller._workspace_timer.stop()
    controller._persist_workspace()
    _settle(qt_app, controller)
    controller.backend.recovery.flush()
    assert controller.backend.recovery.recovery.load().workspace_state["ux_v2"]["pending_project_name"] == "First draft"

    target = tmp_path / "First draft.grproj"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_args, **_kwargs: (str(target), "")))
    original_save = controller.backend.save
    entered, release = Event(), Event()

    def delayed_save(project, destination=None):
        entered.set()
        assert release.wait(5)
        return original_save(project, destination)

    monkeypatch.setattr(controller.backend, "save", delayed_save)
    window.save_project()
    assert entered.wait(2)
    window.navigation.setCurrentRow(1)
    qt_app.processEvents()
    assert controller.workspace["page"] == 1
    release.set()
    _settle(qt_app, controller)

    assert "pending_project_name" not in controller.workspace["ux_v2"]
    assert controller.workspace["page"] == 1
    controller._workspace_timer.stop()
    controller._persist_workspace()
    _settle(qt_app, controller)
    controller.backend.recovery.flush()
    assert "pending_project_name" not in controller.project.workspace_state["ux_v2"]
    assert "pending_project_name" not in controller.backend.recovery.recovery.load().workspace_state["ux_v2"]
    with ProjectRepository(target, read_only=True) as repository:
        saved = repository.load()
    assert "pending_project_name" not in saved.workspace_state["ux_v2"]
    assert saved.workspace_state["page"] == 1


def test_canceling_first_save_keeps_unsaved_name_without_claiming_failure(window_controller, qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog
    window, controller = window_controller
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *_args, **_kwargs: ("Keep this name", True)))
    window.new_project()
    _settle(qt_app, controller)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_args, **_kwargs: ("", "")))
    window.save_project()
    assert controller.path is None
    assert controller.workspace["ux_v2"]["pending_project_name"] == "Keep this name"
    assert window.project_name.text() == "Keep this name"
    assert window.saved.text() == "尚未保存"

