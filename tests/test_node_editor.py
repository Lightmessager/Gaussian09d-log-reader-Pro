"""S6 scientific editing, persistent drafts, history and preview integration."""
from dataclasses import replace
from time import monotonic

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_workbench import app, workbench, settle, write_logs
from gaussianreadpro.core import compile_expression
from gaussianreadpro.core.expressions import components_expression, render_expression
from gaussianreadpro.services.expression_editor import component_form
from gaussianreadpro.ui.expression_editor import ExpressionDialog, TokenEdit
from gaussianreadpro.ui.batch_editor import BatchDialog
from gaussianreadpro.storage import ProjectRepository


def import_six(app, controller, tmp_path):
    values = {"R": -100., "A": -50., "TS1": -149.976, "I1": -140., "B": -10.008, "P": -150.025}
    paths = []
    for name, energy in values.items():
        path = tmp_path / (name + ".log")
        path.write_text("SYNTHETIC S6 DEMO\nEntering Gaussian System\n"
                        f" SCF Done: E(RB3LYP) = {energy - .03:.12f} A.U.\n"
                        " Thermal correction to Gibbs Free Energy= 0.030000000000\n"
                        f" Sum of electronic and thermal Free Energies= {energy:.12f}\n"
                        " Normal termination of Gaussian 16\n", encoding="utf-8")
        paths.append(path)
    controller.import_files(paths)
    settle(app, controller)
    return {n.label: n.id for n in controller.project.nodes}


def close_editor(app, controller, dialog):
    QTest.mouseClick(dialog.close_button, Qt.MouseButton.LeftButton)
    deadline = monotonic() + 10
    while dialog.isVisible() or controller.busy:
        app.processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline
    dialog.deleteLater()


def add_species(app, controller, dialog, name):
    QTest.mouseClick(dialog.add_button, Qt.MouseButton.LeftButton)
    row = dialog.rows[-1]
    source = next(s for s in controller.project.source_files if s.display_name == name)
    row["source"].setCurrentIndex(row["source"].findData(source.id))


def test_four_node_builder_reference_rename_order_units_and_reopen(app, workbench, tmp_path):
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    controller.remove_nodes([ids["A"], ids["B"]])
    settle(app, controller)
    for label, component in (("R", "A"), ("I1", "B")):
        dialog = ExpressionDialog(controller, node_id=ids[label], parent=window)
        dialog.show()
        add_species(app, controller, dialog, component)
        close_editor(app, controller, dialog)
    reference_editor = ExpressionDialog(controller, path_id=controller.selected_path.id, parent=window)
    reference_editor.show()
    assert reference_editor.tabs.currentIndex() == 0
    add_species(app, controller, reference_editor, "R")
    add_species(app, controller, reference_editor, "A")
    close_editor(app, controller, reference_editor)
    result = controller.results[0]
    assert [v.relative_hartree for v in result.nodes] == pytest.approx([0., .024, -.008, -.025])
    ast = controller.project.nodes[0].expression.ast
    controller.rename_node(ids["R"], "Reactants / 反应物", "reactant")
    settle(app, controller)
    controller.path_options(unit="kj_mol")
    settle(app, controller)
    controller.move_node(controller.selected_path.entries[-1].id, -1)
    settle(app, controller)
    assert controller.project.nodes[0].expression.ast == ast
    assert {v.node_id: v.relative_hartree for v in controller.results[0].nodes} == pytest.approx(
        {ids["R"]: 0., ids["TS1"]: .024, ids["I1"]: -.008, ids["P"]: -.025})
    destination = tmp_path / "four-nodes.grproj"
    controller.save(destination)
    settle(app, controller)
    with ProjectRepository(destination, read_only=True) as repository:
        restored = repository.load()
    assert restored.nodes == controller.project.nodes
    assert restored.paths == controller.project.paths


def test_invalid_expert_draft_is_autosaved_and_restored(app, workbench, tmp_path):
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    node_id = ids["TS1"]
    previous_ast = next(n for n in controller.project.nodes if n.id == node_id).expression.ast
    dialog = ExpressionDialog(controller, node_id=node_id, parent=window)
    dialog.show()
    dialog.tabs.setCurrentIndex(1)
    dialog.text.setPlainText("@{TS1} + (")
    QTest.qWait(450)
    settle(app, controller)
    assert next(n for n in controller.project.nodes if n.id == node_id).expression.draft_text == "@{TS1} + ("
    close_editor(app, controller, dialog)
    document = next(n for n in controller.project.nodes if n.id == node_id).expression
    assert document.ast == previous_ast and document.draft_text == "@{TS1} + ("
    assert document.draft_error.params["start"] >= 0
    assert next(v for v in controller.results[0].nodes if v.node_id == node_id).display_value is None
    destination = tmp_path / "invalid.grproj"
    controller.save(destination)
    settle(app, controller)
    with ProjectRepository(destination, read_only=True) as repository:
        assert next(n for n in repository.load().nodes if n.id == node_id).expression == document
    editor = ExpressionDialog(controller, node_id=node_id, parent=window)
    assert editor.text.toPlainText() == document.draft_text
    editor.deleteLater()


def test_explicit_expression_save_survives_fresh_controller_restart(app, workbench, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from gaussianreadpro.services.controller import ProjectController
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    node_id = ids["TS1"]
    destination = tmp_path / "explicit.grproj"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(destination), ""))
    editor = ExpressionDialog(controller, node_id=node_id, parent=window)
    editor.show()
    editor.tabs.setCurrentIndex(1)
    editor.text.setPlainText("@{TS1} + 0.25[kcal/mol]")
    QTest.mouseClick(editor.save_button, Qt.MouseButton.LeftButton)
    deadline = monotonic() + 10
    while editor._save_requested or controller.busy:
        app.processEvents()
        QTest.qWait(5)
        assert monotonic() < deadline
    assert controller.path == destination.resolve()
    assert str(destination) in editor.save_status.text()
    assert destination.exists()
    expected_expression = next(node for node in controller.project.nodes if node.id == node_id).expression
    editor.close()
    settle(app, controller)

    restarted = ProjectController(tmp_path / "restarted-recovery", tmp_path / "restarted-prefs.ini")
    restarted.open_project(destination)
    settle(app, restarted)
    restored = next(node for node in restarted.project.nodes if node.id == node_id)
    assert restored.expression == expected_expression
    restarted.close()
    settle(app, restarted)


def test_history_monotonic_revision_shared_path_and_import_barrier(app, workbench, tmp_path):
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    controller.rename_node(ids["R"], "renamed", "reactant")
    settle(app, controller)
    revision = controller.project.revision
    controller.undo()
    settle(app, controller)
    assert controller.project.revision > revision and controller.project.nodes[0].label == "R"
    controller.redo()
    settle(app, controller)
    assert controller.project.nodes[0].label == "renamed"
    original = controller.selected_path
    controller.edit_path("copy", "shared copy")
    settle(app, controller)
    copied = controller.selected_path
    assert copied.id != original.id
    assert copied.entries[0].id != original.entries[0].id
    assert copied.entries[0].node_id == original.entries[0].node_id
    controller.remove_nodes([ids["R"]])
    settle(app, controller)
    assert any(n.id == ids["R"] for n in controller.project.nodes)
    assert all(e.node_id != ids["R"] for e in controller.selected_path.entries)
    controller.import_files([tmp_path / "nonexistent.log"])
    settle(app, controller)
    assert not controller.undo_stack and not controller.redo_stack


def test_batch_preview_is_calculated_before_apply_and_undoable(app, workbench, tmp_path):
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    controller.reference_node(ids["R"])
    settle(app, controller)
    dialog = BatchDialog(controller, [ids["I1"]], parent=window)
    dialog.show()
    selected_ref = controller.project.alias_bindings["B"]
    for index in range(dialog.first.count()):
        if dialog.first.itemData(index) == selected_ref:
            dialog.first.setCurrentIndex(index)
            break
    before = controller.project
    QTest.mouseClick(dialog.preview_button, Qt.MouseButton.LeftButton)
    settle(app, controller)
    assert dialog.change is not None and dialog.apply_button.isEnabled()
    assert next(n for n in controller.project.nodes if n.id == ids["I1"]).expression == next(n for n in before.nodes if n.id == ids["I1"]).expression
    QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    settle(app, controller)
    modified = next(n for n in controller.project.nodes if n.id == ids["I1"]).expression
    assert "B" in render_expression(modified, controller.project.alias_bindings)
    controller.undo()
    settle(app, controller)
    assert next(n for n in controller.project.nodes if n.id == ids["I1"]).expression != modified
    dialog.deleteLater()


def test_component_roundtrip_and_expert_only_algebra(app, workbench, tmp_path):
    _, controller = workbench
    import_six(app, controller, tmp_path)
    aliases = controller.project.alias_bindings
    expression = components_expression([(aliases["R"], 1.), (aliases["A"], -2.)], offset=1.5,
                                       offset_unit="kcal_mol", aliases=aliases)
    terms, offset, unit = component_form(expression)
    assert terms == [(aliases["R"], 1.), (aliases["A"], -2.)]
    assert offset == 1.5 and unit == "kcal_mol"
    expert = compile_expression("2 * (@{R} + @{A})", aliases).expression
    assert component_form(expert) is None
    dialog = ExpressionDialog(controller, node_id=controller.project.nodes[0].id)
    dialog.text.setPlainText("2 * (@{R} + @{A})")
    dialog.tabs.setCurrentIndex(1)
    dialog.tabs.setCurrentIndex(0)
    assert dialog.tabs.currentIndex() == 1
    assert dialog.text.toPlainText() == "2 * (@{R} + @{A})"
    dialog._dirty = False
    dialog.timer.stop()
    dialog.deleteLater()


def test_new_node_library_and_invalid_builder_choices_survive_reopen(app, workbench, tmp_path):
    window, controller = workbench
    import_six(app, controller, tmp_path)
    controller.add_node("new combination")
    settle(app, controller)
    node_id = controller.project.nodes[-1].id
    editor = ExpressionDialog(controller, node_id=node_id, parent=window)
    editor.show()
    assert editor.tabs.currentIndex() == 0
    item = editor.library.item(0)
    editor.library.scrollToItem(item)
    app.processEvents()
    QTest.mouseClick(editor.library.viewport(), Qt.MouseButton.LeftButton,
                     pos=editor.library.visualItemRect(item).center())
    QTest.mouseDClick(editor.library.viewport(), Qt.MouseButton.LeftButton,
                     pos=editor.library.visualItemRect(item).center())
    assert len(editor.rows) == 1
    editor.rows[0]["source"].setEditText("unfinished species")
    close_editor(app, controller, editor)
    node = next(n for n in controller.project.nodes if n.id == node_id)
    assert node.expression.draft_error
    reopened = ExpressionDialog(controller, node_id=node_id, parent=window)
    assert reopened.tabs.currentIndex() == 0
    assert reopened.rows[0]["source"].currentText() == "unfinished species"
    reopened.deleteLater()


def test_batch_preview_checks_current_fingerprints(app, workbench, tmp_path):
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    controller.reference_node(ids["R"])
    settle(app, controller)
    (tmp_path / "B.log").unlink()
    dialog = BatchDialog(controller, [ids["I1"]], parent=window)
    dialog.show()
    ref = controller.project.alias_bindings["B"]
    dialog.first.setCurrentIndex(next(i for i in range(dialog.first.count()) if dialog.first.itemData(i) == ref))
    QTest.mouseClick(dialog.preview_button, Qt.MouseButton.LeftButton)
    settle(app, controller)
    assert dialog.change is not None
    assert "source" in dialog.output.toPlainText()
    assert "—" in dialog.output.toPlainText()
    dialog.deleteLater()


def test_explicit_direct_difference_editor_subtracts_only_once(app, workbench, tmp_path):
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    controller.path_options(mode="direct_difference", unit="hartree")
    settle(app, controller)
    editor = ExpressionDialog(controller, node_id=ids["TS1"], parent=window)
    editor.show()
    editor.tabs.setCurrentIndex(1)
    editor.purpose.setCurrentIndex(editor.purpose.findData("difference"))
    editor.text.setPlainText("@{TS1} - (@{R} + @{A})")
    close_editor(app, controller, editor)
    result = next(v for v in controller.results[0].nodes if v.node_id == ids["TS1"])
    assert result.valid and result.relative_hartree == pytest.approx(.024)
    assert result.absolute_hartree is None and result.reference_hartree is None


def test_referenced_source_removal_cancel_keeps_dependencies(app, workbench, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    original = controller.project
    window.source_table.selectRow(0)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Cancel)
    QTest.mouseClick(window.remove_source_button, Qt.MouseButton.LeftButton)
    assert controller.project == original
    assert len(controller.project.source_files) == 6


def test_composite_template_has_fixed_low_job_and_explicit_approximation(app, workbench, tmp_path):
    window, controller = workbench
    ids = import_six(app, controller, tmp_path)
    controller.path_options(mode="absolute")
    settle(app, controller)
    editor = ExpressionDialog(controller, node_id=ids["R"], parent=window)
    editor.show()
    add_species(app, controller, editor, "A")
    QTest.mouseClick(editor.composite_button, Qt.MouseButton.LeftButton)
    assert editor.document.combination_mode == "composite_gibbs"
    assert editor.tabs.currentIndex() == 1
    close_editor(app, controller, editor)
    value = next(n for n in controller.results[0].nodes if n.node_id == ids["R"])
    assert value.valid and value.absolute_hartree == pytest.approx(-100.)
    assert any("composite" in diagnostic.code for diagnostic in value.diagnostics)


def test_token_completion_and_error_offsets_use_unicode_characters(app):
    editor = TokenEdit({"species 🧪": None})
    editor.setPlainText("@{species 🧪} + (")
    index = len(editor.toPlainText()) - 1
    editor.error_range = (index, index + 1)
    editor.highlight_brackets()
    assert editor.extraSelections()[-1].cursor.selectedText() == "("
    editor.setPlainText("@{spe")
    cursor = editor.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.insert_completion("@{species 🧪}")
    assert editor.toPlainText() == "@{species 🧪}"
    editor.deleteLater()
