"""S4 use cases and Qt interactions, using real services and actual widget events."""
from dataclasses import replace
import os
from pathlib import Path
import sqlite3
from threading import Event
from time import monotonic

import pytest

from gaussianreadpro.core import EnergyKind, Project, Unit
from gaussianreadpro.core.models import new_id
from gaussianreadpro.services.session import RecoveryOffer, SessionBackend, import_into
from gaussianreadpro.storage import ProjectRepository, RecoveryService, StorageError


def write_logs(directory, *, scf_only=False):
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for label, value in (("R", -150.), ("TS1", -149.976), ("I1", -150.008), ("P", -150.025)):
        path = directory / (label + ".log")
        path.write_text("SYNTHETIC S4 TEST\nEntering Gaussian System\n"
                        f" SCF Done: E(RB3LYP) = {value - .03:.12f} A.U.\n"
                        + ("" if scf_only else f" Thermal correction to Gibbs Free Energy= 0.030000000000\n"
                           f" Sum of electronic and thermal Free Energies= {value:.12f}\n")
                        + " Normal termination of Gaussian 16\n", encoding="utf-8")
        paths.append(path)
    return paths


def test_import_same_name_paths_identity_aliases_and_duplicate_detection(tmp_path):
    first = write_logs(tmp_path / "one")[0]
    second = write_logs(tmp_path / "two")[0]
    base = Project(new_id())
    after, _ = import_into(base, [first, first, second], lambda: False, lambda *args: None)
    assert len(after.source_files) == len(after.nodes) == 2
    assert len(set(s.id for s in after.source_files)) == 2
    assert set(after.alias_bindings) == {"R", "R (2)"}
    again, _ = import_into(after, [first, second], lambda: False, lambda *args: None)
    assert again is after


def test_import_cancellation_is_atomic(tmp_path):
    paths = write_logs(tmp_path)
    base = Project(new_id())
    cancellation = Event()
    def progress(done, *_):
        if done == 1:
            cancellation.set()
    after, _ = import_into(base, paths, cancellation.is_set, progress)
    assert after is base and not after.source_files and not after.alias_bindings


def test_directory_recursion_is_explicit(tmp_path):
    write_logs(tmp_path / "nested")
    (tmp_path / "not-a-log.txt").write_text("not imported")
    base = Project(new_id())
    flat, _ = import_into(base, [tmp_path], lambda: False, lambda *args: None)
    recursive, _ = import_into(base, [tmp_path], lambda: False, lambda *args: None, recursive=True)
    assert flat is base and len(recursive.source_files) == 4


def test_scf_only_is_bound_and_gibbs_stays_unavailable(tmp_path):
    backend = SessionBackend(tmp_path / "recovery", tmp_path / "prefs.ini")
    base = backend.new().project
    view = backend.import_files(base, write_logs(tmp_path / "logs", scf_only=True), lambda: False, lambda *args: None)
    assert len(view.project.nodes) == 4
    assert not view.results[0].valid
    path = replace(view.project.paths[0], energy_kind=EnergyKind.SCF, reference_expression=view.project.nodes[0].expression)
    project = replace(view.project, paths=(path,), revision=view.project.revision + 1)
    assert backend.update(project).results[0].valid
    backend.shutdown()


def test_backend_failed_open_preserves_active_session(tmp_path):
    backend = SessionBackend(tmp_path / "recovery", tmp_path / "prefs.ini")
    base = backend.new().project
    view = backend.import_files(base, write_logs(tmp_path / "logs"), lambda: False, lambda *args: None)
    with pytest.raises(StorageError):
        backend.open(tmp_path / "missing.grproj")
    assert backend.view(view.project).project == view.project
    assert backend.recovery.status.current_revision == view.project.revision
    backend.shutdown()


def test_project_rename_delete_and_recent_removal_are_scoped(tmp_path):
    from gaussianreadpro.storage.preferences import LocalPreferences
    recovery = tmp_path / "recovery"
    preferences = tmp_path / "prefs.ini"
    backend = SessionBackend(recovery, preferences)
    project = backend.new().project
    logs = write_logs(tmp_path / "logs")
    project = backend.import_files(project, logs, lambda: False, lambda *args: None).project
    original = tmp_path / "study.grproj"
    renamed = tmp_path / "study-renamed.grproj"
    backend.save(project, original)
    saved_id = backend.repository.load().id
    backend.rename_project(original, renamed, backend.recovery._latest)
    assert not original.exists() and renamed.exists()
    assert backend.repository.path == renamed
    with ProjectRepository(renamed, read_only=True) as repository:
        persisted = repository.load()
    assert persisted.id == saved_id and len(persisted.source_files) == len(logs)
    assert all(Path(source.original_path).exists() for source in persisted.source_files)
    assert LocalPreferences(preferences).load()["recent_projects"] == [str(renamed.resolve())]
    backend.shutdown()

    # Removing from Recent changes preferences only; deletion targets one file.
    other = tmp_path / "other.grproj"
    other_backend = SessionBackend(recovery, preferences)
    other_project = other_backend.new().project
    other_backend.save(other_project, other)
    other_backend.shutdown()
    prefs = LocalPreferences(preferences)
    prefs.remember_project(renamed)
    prefs.remove_recent_project(renamed)
    assert renamed.exists() and str(renamed.resolve()) not in prefs.load()["recent_projects"]
    prefs.remember_project(renamed)
    backend = SessionBackend(recovery, preferences)
    backend.delete_project_file(renamed)
    assert not renamed.exists() and other.exists()
    assert str(renamed.resolve()) not in LocalPreferences(preferences).load()["recent_projects"]
    backend.shutdown()


def test_controller_deleting_current_project_clears_session_and_recent(workbench, app, tmp_path):
    from gaussianreadpro.storage.preferences import LocalPreferences
    _window, controller = workbench
    target = tmp_path / "current.grproj"
    controller.save(target)
    settle(app, controller)
    assert controller.path == target.resolve()
    assert controller.delete_project_file(target)
    settle(app, controller)
    assert controller.project is None and controller.path is None
    assert not target.exists()
    assert str(target.resolve()) not in LocalPreferences(tmp_path / "prefs.ini").load()["recent_projects"]

def test_backend_explicit_recovery_choice(tmp_path):
    recovery_dir = tmp_path / "recovery"
    base = Project(new_id())
    path = tmp_path / "main.grproj"
    with ProjectRepository(path, create=True) as repository:
        repository.save(base)
    newer = replace(base, revision=2, workspace_state={"page": 2})
    recovery_dir.mkdir()
    with RecoveryService(recovery_dir / "old-session.grproj") as recovery:
        recovery.request(newer)
    backend = SessionBackend(recovery_dir, tmp_path / "prefs.ini")
    offer = backend.open(path)
    assert isinstance(offer, RecoveryOffer)
    assert backend.repository is None
    view = backend.open(path, recovery_file=offer.recovery_path)
    assert view.project == newer
    backend.shutdown()
    with ProjectRepository(path, read_only=True) as repository:
        assert repository.load() == newer


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.theme import apply_theme
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    apply_theme(application)
    yield application


def settle(app, controller, timeout=10):
    from PySide6.QtTest import QTest
    deadline = monotonic() + timeout
    while controller.busy:
        app.processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline, controller.operation
    app.processEvents()


@pytest.fixture
def workbench(app, tmp_path):
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.ui.main_window import MainWindow
    controller = ProjectController(tmp_path / "recovery", tmp_path / "prefs.ini")
    window = MainWindow(controller)
    window.show()
    app.processEvents()
    controller.bootstrap()
    settle(app, controller)
    controller.new_project()
    settle(app, controller)
    yield window, controller
    # Tests never bypass saving on teardown; close through the actual async controller.
    controller._workspace_timer.stop()
    settle(app, controller)
    if not controller._closed:
        controller.close()
        settle(app, controller)
    window.deleteLater()
    app.processEvents()


def import_four(app, controller, tmp_path):
    controller.import_files(write_logs(tmp_path / "logs"))
    settle(app, controller)
    return controller.project


def test_reaction_network_star_undo_redo_preserves_project_metadata(app, workbench, tmp_path):
    from gaussianreadpro.core.reaction_network import empty_network, read_reaction_network
    _window, controller = workbench
    project = import_four(app, controller, tmp_path)
    source = project.source_files[0]
    network = empty_network()
    network["species"] = [{"id": new_id(), "name": "R", "starred": True,
                           "bindings": [{"source_file_id": source.id, "job_id": source.jobs[0].id,
                                         "historical": False}]}]
    assert controller.update_reaction_network(network)
    settle(app, controller)
    assert read_reaction_network(controller.project)["species"][0]["starred"]
    assert controller.undo()
    settle(app, controller)
    assert not read_reaction_network(controller.project)["species"]
    assert controller.redo()
    settle(app, controller)
    assert read_reaction_network(controller.project)["species"][0]["starred"]


def test_gui_import_reference_units_provenance_and_save(app, workbench, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    window, controller = workbench
    before = import_four(app, controller, tmp_path)
    window.navigation.setCurrentRow(2)
    node = before.nodes[0]
    window.select_node(node.id)
    QTest.mouseClick(window.reference_button, Qt.MouseButton.LeftButton)
    settle(app, controller)
    result = controller.results[0]
    assert result.valid
    assert [v.relative_hartree for v in result.nodes] == pytest.approx([0, .024, -.008, -.025])
    assert "行 4" in window.evidence.toPlainText()
    assert window.expression.toPlainText() == "@{R}"
    window.unit_combo.setCurrentIndex(window.unit_combo.findData("kj_mol"))
    settle(app, controller)
    assert controller.results[0].unit == Unit.KJ_MOL
    assert controller.results[0].nodes[1].display_value == pytest.approx(.024 * 2625.499639479163)
    path = tmp_path / "saved.grproj"
    controller.save(path)
    settle(app, controller)
    assert controller.path == path
    assert window.saved.text() == "已保存"
    with ProjectRepository(path, read_only=True) as repository:
        assert repository.load() == controller.project


def test_table_sort_search_selection_and_reorder_use_ids(app, workbench, tmp_path):
    from PySide6.QtCore import Qt
    window, controller = workbench
    before = import_four(app, controller, tmp_path)
    order = [e.node_id for e in before.paths[0].entries]
    window.navigation.setCurrentRow(2)
    window.node_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    app.processEvents()
    assert [e.node_id for e in controller.project.paths[0].entries] == order
    window.select_node(before.nodes[1].id)
    assert window.node_name.text() == "TS1"
    controller.move_node(before.paths[0].entries[1].id, 1)
    settle(app, controller)
    assert [e.node_id for e in controller.project.paths[0].entries] == [order[0], order[2], order[1], order[3]]
    window.search.setText("TS1")
    assert window.node_proxy.rowCount() == 1
    assert window.node_proxy.index(0, 0).data(Qt.ItemDataRole.UserRole) == before.nodes[1].id
    window.search.clear()
    window.file_filter.setCurrentIndex(3)
    assert window.source_proxy.rowCount() == 0


def test_responsive_layout_collapses_and_reopens_inspector(app, workbench, tmp_path):
    window, controller = workbench
    import_four(app, controller, tmp_path)
    window.navigation.setCurrentRow(2)
    window.resize(950, 740)
    app.processEvents()
    assert window.sidebar.width() == 64
    assert not window.inspector.isVisible()
    window.compact_tabs.setCurrentIndex(0)
    app.processEvents()
    assert window.node_table.viewport().width() > 450
    window.toggle_inspector()
    app.processEvents()
    assert window.inspector.isVisible()
    window.toggle_inspector()
    window.resize(1500, 930)
    app.processEvents()
    assert window.inspector.isVisible() and window.sidebar.width() == 196


def test_compact_reaction_view_switches_between_full_height_chart_and_nodes(app, workbench, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    window, controller = workbench
    import_four(app, controller, tmp_path)
    window.navigation.setCurrentRow(2)
    window.resize(860, 680)
    QTest.qWait(200)
    assert not window.compact_tabs.isVisible() and window.compact_tabs.currentIndex() == 1
    assert window.compact_tabs.tabText(0) == "路径节点" and window.compact_tabs.tabText(1) == "能量图"
    assert not window.path_card.isVisible() and window.energy_page.isVisible()
    assert window.profile.height() >= 220
    assert all(control.isVisible() for control in window.profile.dimension_buttons)
    assert not window.profile.expand_button.isVisible()
    for control in (window.profile.camera_combo, window.profile.dragmode_combo, window.profile.theme_combo):
        assert control.parentWidget() is window.profile and not control.isVisible()
    assert window.profile.reset_button.text() == "重置"
    assert window.profile.export_button.text() == "导出"
    assert window.unit_combo.currentText() == "kcal/mol"
    window.compact_tabs.setCurrentIndex(0)
    app.processEvents()
    assert window.path_card.isVisible() and not window.chart_card.isVisible()
    assert window.node_table.viewport().height() >= 180
    window.compact_tabs.setCurrentIndex(1)
    app.processEvents()
    assert window.energy_page.isVisible() and window.profile.height() >= 220
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    app.processEvents()
    assert window.compact_tabs.tabText(0) == "Path nodes" and window.compact_tabs.tabText(1) == "Energy chart"
    assert window.unit_combo.currentText() == "kcal/mol"
    assert window.profile.expand_button.accessibleName() == "Expand chart"
    window.language_combo.setCurrentIndex(window.language_combo.findData("zh_CN"))
    app.processEvents()
    window.resize(1440, 920)
    QTest.qWait(150)
    assert not window.path_card.isVisible() and window.energy_page.isVisible()
    assert not window.compact_tabs.isVisible()
    assert window.profile.height() > window.reaction_pages.height() * .9
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    assert window.navigation.item(2).text().strip() == "Energy Profile"
    assert window.navigation.item(2).toolTip() == "Energy Profile"
    assert window.node_table.model().headerData(3, Qt.Orientation.Horizontal) == "ΔG / kcal/mol"
    window.resize(860, 680)
    QTest.qWait(150)
    assert window.kind_combo.currentText() == "Gibbs"
    assert window.mode_combo.currentText() == "ΔG"
    assert window.unit_combo.currentText() == "kcal/mol"


def test_preview_mouse_selects_node_and_no_fake_values(app, workbench, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    window, controller = workbench
    import_four(app, controller, tmp_path)
    controller.reference_node(controller.project.nodes[0].id)
    settle(app, controller)
    window.navigation.setCurrentRow(2)
    window.preview.repaint()
    app.processEvents()
    assert len(window.preview.positions) == 4
    position, node, value = window.preview.positions[1]
    QTest.mouseClick(window.preview, Qt.MouseButton.LeftButton, pos=position.toPoint())
    assert window.node_name.text() == node.label
    assert value.display_value == pytest.approx(15.0602273775)


def test_gui_heartbeat_while_worker_waits_and_cancel(app, workbench, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    import gaussianreadpro.services.session as session_module
    window, controller = workbench
    entered, release = Event(), Event()
    real_parse = session_module.parse_log
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_parse(*args, **kwargs)
    monkeypatch.setattr(session_module, "parse_log", slow)
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    controller.import_files(write_logs(tmp_path / "logs"))
    assert entered.wait(2)
    QTest.qWait(75)
    assert len(ticks) >= 3 and window.cancel_button.isVisible()
    controller.cancel()
    release.set()
    settle(app, controller)
    timer.stop()
    assert not controller.project.source_files
    assert not window.cancel_button.isVisible()


def test_save_failure_banner_and_retry_do_not_claim_success(app, workbench, tmp_path):
    window, controller = workbench
    import_four(app, controller, tmp_path)
    path = tmp_path / "main.grproj"
    controller.save(path)
    settle(app, controller)
    saved_revision = controller.project.revision
    active = True
    def fail(stage):
        if active and stage == "before_commit":
            raise sqlite3.OperationalError("injected full disk")
    controller.backend.repository._fault_injector = fail
    controller.set_workspace(page=1)
    controller.save()
    settle(app, controller)
    assert controller.backend.repository.saved_revision == saved_revision
    assert window.banner.isVisible() and window.saved.text() == "保存失败"
    active = False
    controller.save()
    settle(app, controller)
    assert controller.backend.repository.saved_revision == controller.project.revision
    assert window.saved.text() == "已保存"


def test_open_missing_file_keeps_table_and_visible_error(app, workbench, tmp_path):
    window, controller = workbench
    before = import_four(app, controller, tmp_path)
    controller.open_project(tmp_path / "does-not-exist.grproj")
    settle(app, controller)
    assert controller.project.id == before.id
    assert window.source_model.rowCount() == 4
    assert window.banner.isVisible()


def test_workspace_close_and_reopen_restores_selection_and_filter(app, workbench, tmp_path):
    window, controller = workbench
    import_four(app, controller, tmp_path)
    node_id = controller.project.nodes[1].id
    window.navigation.setCurrentRow(2)
    window.select_node(node_id)
    window.search.setText("TS1")
    path = tmp_path / "restore.grproj"
    controller.save(path)
    settle(app, controller)
    controller.new_project()
    settle(app, controller)
    controller.open_project(path, ignore_recovery=True)
    settle(app, controller)
    assert window.navigation.currentRow() == 2
    assert window.search.text() == "TS1"
    assert window.node_name.text() == "TS1"
    assert window.node_proxy.rowCount() == 1


def test_outdated_completion_is_ignored(app, workbench):
    from gaussianreadpro.services.controller import TaskSignals
    from gaussianreadpro.services.session import SessionView
    window, controller = workbench
    before = controller.project
    signals = TaskSignals(controller)
    controller._tasks[999] = (signals, (before.id, before.revision - 1))
    controller._active = 999
    controller.busy = True
    controller._completed(999, SessionView(replace(before, revision=99), (), (), None, False, None), None)
    assert controller.project == before


def test_read_only_view_can_close_and_save_as_without_writing_main(app, workbench, tmp_path):
    window, controller = workbench
    base, _ = import_into(Project(new_id()), write_logs(tmp_path / "logs"), lambda: False, lambda *args: None)
    main = tmp_path / "readonly.grproj"
    with ProjectRepository(main, create=True) as writer:
        writer.save(base)
        controller.open_project(main, ignore_recovery=True)
        settle(app, controller)
        assert controller.read_only and not window.import_button.isEnabled()
        assert not window.kind_combo.isEnabled()
        assert window.saved.text() == "只读"
        copied = tmp_path / "editable-copy.grproj"
        controller.save(copied)
        settle(app, controller)
        assert not controller.read_only and controller.path == copied
        assert writer.load() == base
        assert window.continue_button.isEnabled()


def test_missing_sources_never_show_current_valid_numbers(app, workbench, tmp_path):
    from PySide6.QtCore import Qt
    window, controller = workbench
    import_four(app, controller, tmp_path)
    controller.reference_node(controller.project.nodes[0].id)
    settle(app, controller)
    original = controller.project.source_files[1]
    Path(original.original_path).unlink()
    controller.calculate()
    settle(app, controller)
    window.navigation.setCurrentRow(2)
    window.preview.repaint()
    assert not controller.results[0].nodes[1].valid
    assert window.node_model.index(1, 3).data(Qt.ItemDataRole.DisplayRole) == "—"
    assert len(window.preview.positions) == 3
    assert controller.project.source_files[1].jobs == original.jobs


def test_close_during_import_cancels_then_drains_without_freezing(app, workbench, tmp_path, monkeypatch):
    import gaussianreadpro.services.session as session_module
    from PySide6.QtTest import QTest
    window, controller = workbench
    entered, release = Event(), Event()
    original = session_module.parse_log
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)
    monkeypatch.setattr(session_module, "parse_log", slow)
    controller.import_files(write_logs(tmp_path / "logs"))
    assert entered.wait(2)
    window.close()
    assert window.isVisible() and controller._cancel.is_set()
    release.set()
    deadline = monotonic() + 10
    while not controller._closed:
        QTest.qWait(10)
        assert monotonic() < deadline
    assert not window.isVisible()


def test_failed_save_prevents_project_switch_and_keeps_work(app, workbench, tmp_path):
    window, controller = workbench
    import_four(app, controller, tmp_path)
    controller.save(tmp_path / "main.grproj")
    settle(app, controller)
    identity = controller.project.id
    active = True
    def fail(stage):
        if active and stage == "before_commit":
            raise OSError("injected write failure")
    controller.backend.repository._fault_injector = fail
    controller.set_workspace(filter="unsaved query")
    controller.new_project()
    settle(app, controller)
    assert controller.project.id == identity
    assert window.banner.isVisible()
    active = False
    controller.save()
    settle(app, controller)


def test_column_width_and_sort_restore_without_path_mutation(app, workbench, tmp_path):
    from PySide6.QtCore import Qt
    window, controller = workbench
    import_four(app, controller, tmp_path)
    path_order = controller.project.paths[0].entries
    window.node_table.setColumnWidth(1, 230)
    window.node_table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    destination = tmp_path / "layout.grproj"
    controller.save(destination)
    settle(app, controller)
    controller.new_project()
    settle(app, controller)
    controller.open_project(destination, ignore_recovery=True)
    settle(app, controller)
    assert window.node_table.columnWidth(1) == 230
    assert window.node_table.horizontalHeader().sortIndicatorSection() == 1
    assert window.node_table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert controller.project.paths[0].entries == path_order


def test_invalid_legacy_workspace_hints_fall_back_without_losing_data(app, workbench, tmp_path):
    window, controller = workbench
    before, _ = import_into(Project(new_id()), write_logs(tmp_path / "logs"), lambda: False, lambda *args: None)
    before = replace(before, workspace_state={"page": 1.5, "horizontal_splitter": 7,
                                              "vertical_splitter": "broken", "node_widths": ["bad"]})
    path = tmp_path / "old-hints.grproj"
    with ProjectRepository(path, create=True) as repository:
        repository.save(before)
    controller.open_project(path, ignore_recovery=True)
    settle(app, controller)
    assert len(controller.project.nodes) == 4
    assert window.navigation.currentRow() == 0
    assert not window.banner.isVisible()


def test_read_only_close_does_not_attempt_to_write_main(app, workbench, tmp_path):
    window, controller = workbench
    original = Project(new_id())
    path = tmp_path / "readonly.grproj"
    failures = []
    controller.failed.connect(lambda *args: failures.append(args))
    with ProjectRepository(path, create=True) as writer:
        writer.save(original)
        controller.open_project(path, ignore_recovery=True)
        settle(app, controller)
        window.close()
        settle(app, controller)
        assert controller._closed and not window.isVisible()
        assert not failures
        assert writer.load() == original


def test_failed_close_can_be_cancelled_then_retried(app, workbench, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    window, controller = workbench
    import_four(app, controller, tmp_path)
    controller.save(tmp_path / "main.grproj")
    settle(app, controller)
    active = True
    def fail(stage):
        if active and stage == "before_commit":
            raise OSError("injected disk full on close")
    controller.backend.repository._fault_injector = fail
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
    controller.set_workspace(filter="uncommitted closing state")
    window.close()
    settle(app, controller)
    assert window.isVisible() and not controller._closed
    assert controller.backend.recovery.status.saved_revision < controller.project.revision
    assert controller.backend.recovery.status.recovery_revision == controller.project.revision
    active = False
    window.close()
    settle(app, controller)
    assert controller._closed and not window.isVisible()


def test_language_and_theme_switches_preserve_science_and_workspace(workbench, app, tmp_path):
    window, controller = workbench
    controller.import_files(write_logs(tmp_path / "locale-logs"))
    settle(app, controller)
    window.navigation.setCurrentRow(2)
    node_id = controller.project.nodes[1].id
    window.select_node(node_id)
    window.search.setText("TS1")
    before_revision = controller.project.revision
    before_values = tuple(result.nodes[1].relative_hartree for result in controller.results)
    window.language_combo.setCurrentIndex(window.language_combo.findData("en"))
    settle(app, controller)
    assert window.title.text() == "Energy Profile"
    assert window.search.text() == "TS1"
    assert window._selected_node == node_id
    assert controller.project.revision == before_revision
    assert tuple(result.nodes[1].relative_hartree for result in controller.results) == before_values
    window.theme_combo.setCurrentIndex(window.theme_combo.findData("dark"))
    settle(app, controller)
    assert "#11101A" in app.styleSheet()
    assert window.preview.dark
    window.language_combo.setCurrentIndex(window.language_combo.findData("zh_CN"))
    settle(app, controller)
    assert window.title.text() == "能量剖面"
    assert controller.preferences["language"] == "zh_CN"
    assert controller.preferences["theme"] == "dark"


def test_locale_catalogs_have_matching_keys():
    from gaussianreadpro.ui.i18n import CATALOGS
    assert set(CATALOGS["zh_CN"]) == set(CATALOGS["en"])
    assert CATALOGS["en"]["搜索文件或节点…"] == "Search files or nodes…"
