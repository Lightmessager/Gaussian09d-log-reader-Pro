"""U1 regressions for visible project actions and stable navigation."""

import pytest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from test_workbench import app, settle, workbench, write_logs


def _visible_through_ancestors(widget):
    current = widget
    while current is not None:
        if not current.isVisible():
            return False
        current = current.parentWidget()
    return True


def _record_builder(monkeypatch, window):
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    opened = []

    def fake_exec(dialog):
        opened.append(dialog.path_combo.currentData())
        return 0

    monkeypatch.setattr(ReactionBuilderDialog, "exec", fake_exec)
    return opened


def _add_path(app, controller):
    assert controller.edit_path("new", "U1 path", color="#7450af")
    settle(app, controller)


def test_default_energy_view_has_visible_builder_and_save_actions(workbench, app, monkeypatch, tmp_path):
    window, controller = workbench
    window.import_paths(write_logs(tmp_path / "logs"))
    settle(app, controller)
    window.resize(840, 680)
    app.processEvents()

    assert window.navigation.currentRow() == 2
    assert window.compact_tabs.currentIndex() == 1
    assert _visible_through_ancestors(window.builder_button)
    assert _visible_through_ancestors(window.save_button)
    assert _visible_through_ancestors(window.project_name)
    assert _visible_through_ancestors(window.saved)
    assert window.builder_button.isEnabled()
    assert window.save_button.isEnabled()
    topbar = window.findChild(type(window.builder_button.parentWidget()), "topbar")
    for widget in (window.builder_button, window.save_button, window.project_name, window.saved):
        assert widget.width() > 0
        center = widget.mapTo(topbar, widget.rect().center())
        assert topbar.rect().contains(center)

    opened = _record_builder(monkeypatch, window)
    QTest.mouseClick(window.builder_button, Qt.MouseButton.LeftButton)
    assert opened == [controller.selected_path.id]


def test_chart_fallback_keeps_native_builder_entry(workbench, app, monkeypatch):
    window, controller = workbench
    _add_path(app, controller)
    window.activate_route("energy")
    window.profile.fallback("test renderer failure")
    app.processEvents()

    button = window.profile.reaction_builder_button
    assert _visible_through_ancestors(button)
    assert button.isEnabled()
    opened = _record_builder(monkeypatch, window)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert opened == [controller.selected_path.id]


def test_activate_route_preserves_existing_page_indices_and_rejects_unknown(workbench, app):
    window, _ = workbench

    window.activate_route("home")
    assert window.navigation.currentRow() == 0
    assert window.stack.currentIndex() == 0

    window.activate_route("sources")
    assert not window.navigation.item(1).isHidden()
    assert window.navigation.currentRow() == 1
    assert window.stack.currentIndex() == 1

    window.activate_route("path_nodes")
    assert window.navigation.currentRow() == 2
    assert window.stack.currentIndex() == 2
    assert window.compact_tabs.currentIndex() == 0

    window.activate_route("energy")
    assert window.navigation.currentRow() == 2
    assert window.stack.currentIndex() == 2
    assert window.compact_tabs.currentIndex() == 1

    with pytest.raises(ValueError):
        window.activate_route("missing")


def test_project_actions_raise_for_unknown_keys_and_keep_shared_button_text(workbench):
    window, _ = workbench
    actions = window.project_actions
    save_action = actions.action("save_project")
    assert save_action.text() == window.save_button.text()
    assert window.builder_button.property("sharedProjectAction") == "edit_reaction_path"
    assert window.import_button.property("sharedProjectAction") == "import_logs"
    assert window.recalculate.property("sharedProjectAction") == "calculate"
    assert actions.action("import_logs").shortcut().toString() == "Ctrl+I"
    assert actions.action("calculate").shortcut().toString() == "F5"
    actions.set_availability("save_project", False, "暂不可保存")
    assert not window.save_button.isEnabled()
    assert save_action.toolTip() == "暂不可保存"
    actions.set_availability("save_project", True)
    assert window.save_button.isEnabled()
    actions.set_availability("import_logs", False, "当前项目为只读。")
    assert not actions.action("import_logs").isEnabled()
    assert not window.import_button.isEnabled()
    with pytest.raises(ValueError):
        actions.action("missing")


def test_new_reaction_path_action_opens_builder_with_new_path_draft(workbench, app, monkeypatch):
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    window, controller = workbench
    _add_path(app, controller)
    existing_path_id = controller.selected_path.id
    opened = []

    def capture(dialog):
        opened.append((dialog.path_combo.currentData(), dialog._draft_new_path))
        return 0

    monkeypatch.setattr(ReactionBuilderDialog, "exec", capture)
    controller.read_only = True
    window.update_actions()
    assert not window.project_actions.action("new_reaction_path").isEnabled()
    read_only_dialog = ReactionBuilderDialog(controller, existing_path_id, parent=window)
    assert not read_only_dialog.new_path_button.isEnabled()
    read_only_dialog._new_path(name="不可创建")
    assert read_only_dialog._draft_new_path is None
    read_only_dialog.close()
    window.project_actions.action("new_reaction_path").trigger()
    assert opened == []

    controller.read_only = False
    window.update_actions()
    window.project_actions.action("new_reaction_path").trigger()

    assert len(opened) == 1
    selected_path_id, draft = opened[0]
    assert draft is not None
    assert selected_path_id == draft.id
    assert selected_path_id != existing_path_id
    assert draft.label == "新建路径 2"

    window.language = "en"
    window.project_actions.action("new_reaction_path").trigger()
    assert opened[-1][1].label == "New path 2"


def test_sources_navigation_uses_calculation_log_label(workbench):
    window, _ = workbench
    assert window.nav_text[1] == "计算日志"
    assert window.navigation.item(1).data(Qt.ItemDataRole.AccessibleTextRole) == "计算日志"


def test_builder_action_without_project_opens_new_project_choice(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.ui.main_window import MainWindow
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    controller = ProjectController(tmp_path / "recovery", tmp_path / "prefs.ini")
    window = MainWindow(controller)
    window.show()
    controller.bootstrap()
    settle(app, controller)
    assert controller.project is None

    prompts = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: (prompts.append(args[1]) or "U1 project", True))
    opened = []
    monkeypatch.setattr(ReactionBuilderDialog, "exec", lambda dialog: opened.append(controller.project.id) or 0)
    QTest.mouseClick(window.builder_button, Qt.MouseButton.LeftButton)
    settle(app, controller)
    assert prompts == ["新建项目"]
    assert controller.project is not None
    assert opened == [controller.project.id]
    assert not window._pending_builder_after_new

    controller.close()
    settle(app, controller)
    window.deleteLater()
    app.processEvents()


def test_new_path_action_keeps_creation_intent_after_new_project_choice(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.ui.main_window import MainWindow
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    controller = ProjectController(tmp_path / "recovery", tmp_path / "prefs.ini")
    window = MainWindow(controller)
    window.show()
    controller.bootstrap()
    settle(app, controller)
    prompts = []
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: (prompts.append(args[1]) or "U1 project", True))
    opened = []
    monkeypatch.setattr(ReactionBuilderDialog, "exec", lambda dialog: opened.append(dialog._draft_new_path) or 0)

    window.project_actions.action("new_reaction_path").trigger()
    settle(app, controller)

    assert prompts == ["新建项目"]
    assert controller.project is not None
    assert len(opened) == 1
    assert opened[0] is not None
    assert opened[0].label == "新建路径 1"
    assert not window._pending_builder_after_new
    assert not window._pending_new_path_after_new

    controller.close()
    settle(app, controller)
    window.deleteLater()
    app.processEvents()

