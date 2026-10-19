"""U7 end-to-end checks for the UX v2 workflow.

The desktop route uses the visible main-window, import-summary, job-candidate,
reaction-builder, analysis-page, profile, and export controls. Synthetic fixture
data is explicitly marked and only demonstrates a nonzero three-stage shape.
Real Gaussian reference outputs are read locally and are never copied.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools")]


def _affinity():
    if os.name != "nt":
        return None
    from diagnose_static_runtime import windows_affinity
    modes, _, select_affinity = windows_affinity()
    mask = modes["default"] & 0xFFFFFF3F
    select_affinity(mask)
    return mask


def _wait(app, predicate, label, seconds=90):
    from PySide6.QtTest import QTest
    deadline = monotonic() + seconds
    while not predicate():
        app.processEvents()
        QTest.qWait(10)
        if monotonic() >= deadline:
            raise TimeoutError(label)
    app.processEvents()


def _wait_idle(app, controller, seconds=90):
    _wait(app, lambda: (not controller.busy
                        and not getattr(controller, "_workspace_dirty", False)
                        and not getattr(controller, "_plot_dirty", False)),
          f"controller/workspace/plot settle: {controller.operation}", seconds)


def _click(widget, label):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    if widget is None or not widget.isVisible() or not widget.isEnabled():
        chain = []
        current = widget
        while current is not None and len(chain) < 6:
            chain.append({"class": type(current).__name__, "object": current.objectName(),
                          "visible": current.isVisible(), "hidden": current.isHidden(),
                          "enabled": current.isEnabled(), "geometry": [current.x(), current.y(),
                          current.width(), current.height()]})
            current = current.parentWidget()
        raise AssertionError(f"Visible action unavailable: {label}; chain={chain}")
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


def _type(widget, text):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    widget.setFocus()
    QTest.keyClick(widget, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(widget, text)


def _select_combo(combo, data):
    index = combo.findData(data)
    if index < 0:
        raise AssertionError(f"Combo item not found: {data!r} in {combo.objectName()}")
    combo.setCurrentIndex(index)


def _click_list_item(app, widget, data, label):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    for row in range(widget.count()):
        item = widget.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == data:
            widget.scrollToItem(item)
            app.processEvents()
            rect = widget.visualItemRect(item)
            if rect.isValid() and not rect.isNull() and rect.intersects(widget.viewport().rect()):
                QTest.mouseClick(widget.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
                app.processEvents()
                return
    raise AssertionError(f"List item not found or not visible: {label} {data}")


def _top_level(app, cls):
    return next((widget for widget in app.topLevelWidgets()
                 if isinstance(widget, cls) and widget.isVisible()), None)


def _handle_job_candidates(app, names_by_file, evidence):
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialogButtonBox
    from gaussianreadpro.ui.import_summary import JobCandidateDialog

    def handle():
        dialog = _top_level(app, JobCandidateDialog)
        if dialog is None:
            QTimer.singleShot(20, handle)
            return
        try:
            chosen = []
            for row_index, row in enumerate(dialog.rows):
                basename = Path(row.source_path).name
                if basename not in names_by_file:
                    continue
                name, formula = names_by_file[basename]
                dialog.name_edits[row_index].setText(name)
                dialog.formula_edits[row_index].setText(formula)
                item = dialog.table.item(row_index, 0)
                rect = dialog.table.visualItemRect(item)
                # Click the checkbox indicator near the left edge; a center-cell
                # click can select the row without changing its check state.
                QTest.mouseClick(dialog.table.viewport(), Qt.MouseButton.LeftButton,
                                 pos=rect.topLeft() + __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(18, rect.height() // 2))
                if item.checkState() != Qt.CheckState.Checked:
                    dialog.table.setCurrentItem(item)
                    QTest.keyClick(dialog.table, Qt.Key.Key_Space)
                if item.checkState() != Qt.CheckState.Checked:
                    raise AssertionError(f"Job candidate row {row_index} did not become checked")
                chosen.append({"source_file_id": row.source_file_id, "job_id": row.job_id,
                               "source_path": row.source_path, "source_label": row.source_label,
                               "job_ordinal": row.job_ordinal, "available_energy_kinds": list(row.available_energy_kinds),
                               "name": name, "formula": formula})
            if not chosen:
                raise AssertionError("No matching job candidates in visible candidate table")
            evidence["selected_candidates"] = chosen
            evidence["candidate_table_headers"] = [dialog.table.horizontalHeaderItem(i).text()
                                                      for i in range(dialog.table.columnCount())]
            _click(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), "加入搭建器草稿")
        except Exception as error:
            evidence["error"] = f"{type(error).__name__}: {error}"
            dialog.reject()

    QTimer.singleShot(0, handle)


def _stage(dialog, app, *, species_id, label, role, predecessor_id, energy_kind, fixture_note):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    _click_list_item(app, dialog.species_list, species_id, f"species for {label}")
    _type(dialog.stage_name, label)
    _select_combo(dialog.stage_role, role)
    _select_combo(dialog.predecessor_combo, predecessor_id)
    _click(dialog.add_stage_button, f"create {label} stage")
    stage = dialog._current_stage()
    if stage is None or stage["label"] != label or stage["role"] != role:
        raise AssertionError(f"Stage creation did not follow the visible controls: {label}")

    _click_list_item(app, dialog.species_list, species_id, f"energy species for {label}")
    _select_combo(dialog.kind_combo, energy_kind)
    _select_combo(dialog.system_mode, "complete_system")
    _type(dialog.reason, fixture_note)
    _click(dialog.add_terms_button, f"add {label} energy term")
    terms = dialog._current_stage()["terms"]
    if len(terms) != 1 or terms[0]["energy_kind"] != energy_kind:
        raise AssertionError(f"Energy term not created through the visible action: {label}")

    # Energy-ledger edits invalidate the previous normalization confirmation;
    # confirm only after the composition and its ledger are both visible.
    dialog.normalization_confirmed.setChecked(True)
    _type(dialog.normalization_note, fixture_note)
    _click(dialog.update_stage_button, f"confirm {label} composition and ledger")

    if predecessor_id is not None:
        if dialog.connection_list.count() != 1:
            raise AssertionError(f"Expected one visible incoming edge for {label}")
        dialog.connection_list.setCurrentRow(0)
        dialog.connection_confirmed.setChecked(True)
        _type(dialog.connection_note, fixture_note)
        _click(dialog.confirm_connection_button, f"confirm edge into {label}")
    return stage["id"]


def _build_path(dialog, app, species, *, name, color, energy_kind, fixture_note):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    # Use the visible detailed-edit tab and buttons; no private builder mutation
    # methods stand in for a user action.
    bar = dialog.stage_views.tabBar()
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(2).center())
    app.processEvents()
    _type(dialog.path_name, name)
    _type(dialog.path_color, color)
    species_by_name = {item["name"]: item["id"] for item in dialog.network["species"]}
    ids = [species_by_name[label] for label in species]
    if not ids:
        raise AssertionError("No imported job cards were available to build stages")

    # A visible selection plus the star action verifies that B-containing
    # material cards can be starred without changing source/job identity.
    starred = next(item for item in dialog.network["species"] if item["id"] == ids[0])
    if not starred["starred"]:
        _click_list_item(app, dialog.species_list, ids[0], "starred material")
        _click(dialog.star_button, "add/remove material star")
        starred = next(item for item in dialog.network["species"] if item["id"] == ids[0])
    if not starred["starred"]:
        raise AssertionError("The visible star action did not mark the selected material")

    roles = ("reactant", "transition_state", "product")
    previous = None
    stage_ids = []
    for index, (species_id, label, role) in enumerate(zip(ids, species, roles)):
        stage_id = _stage(dialog, app, species_id=species_id, label=label, role=role,
                          predecessor_id=previous, energy_kind=energy_kind,
                          fixture_note=fixture_note)
        stage_ids.append(stage_id)
        previous = stage_id
    zero_index = next((index for index in range(dialog.zero_combo.count())
                       if dialog.zero_combo.itemText(index).startswith("反应物总能量（默认零点）")), -1)
    if zero_index < 0:
        raise AssertionError("Visible zero-point selector has no reactant reference option")
    dialog.zero_combo.setCurrentIndex(zero_index)
    zero = dialog._current_recipe()["zero_point"]
    if zero.get("kind") != "reactant" or zero.get("stage_id") != stage_ids[0]:
        raise AssertionError(f"Reactant zero point did not bind to the first stage: {zero}")
    _wait_idle(app, dialog.controller)
    return stage_ids


def _run_builder(app, path_specs, energy_kind, build_errors):
    from PySide6.QtCore import QTimer
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog

    def work():
        try:
            dialog = _top_level(app, ReactionBuilderDialog)
            if dialog is None:
                QTimer.singleShot(20, work)
                return
            print("U7 builder shown", dialog.path_combo.currentData(), flush=True)
            for index, spec in enumerate(path_specs):
                print("U7 path start", spec["name"], flush=True)
                if index:
                    _click(dialog.new_path_button, "新建路径")
                    app.processEvents()
                    if dialog._draft_new_path is None:
                        raise AssertionError("The visible new-path action produced no draft")
                    print("U7 new path created", dialog._draft_new_path.id, flush=True)
                stage_ids = _build_path(dialog, app, spec["species"], name=spec["name"],
                                        color=spec["color"], energy_kind=energy_kind,
                                        fixture_note=spec["note"])
                print("U7 stages built", spec["name"], stage_ids, flush=True)
                _click(dialog.preview_button, "预览计算 / 能量预检")
                print("U7 preview clicked", spec["name"], flush=True)
                _wait(app, lambda: dialog._accepted_preview is not None or not dialog.controller.busy,
                      f"preview {spec['name']}")
                accepted = dialog._accepted_preview
                if not accepted:
                    state = {"flow_state": dialog._flow_state,
                             "controller_operation": dialog.controller.operation,
                             "preview_text": dialog.preview.text(),
                             "path_id": dialog.path_combo.currentData(),
                             "zero_data": dialog.zero_combo.currentData(),
                             "recipe": dialog._current_recipe(),
                             "draft_generation": getattr(dialog.builder_draft, "generation", None)}
                    raise AssertionError("Precheck did not return a current preview: " +
                                         json.dumps(state, ensure_ascii=True, default=str))
                preview = accepted[1]
                if preview.blocking:
                    raise AssertionError(f"Precheck blocked {spec['name']}: {dialog.preview.text()}")
                expected = (0.0, 0.02, -0.02) if energy_kind == "gibbs_total" else (0.0, 0.0, 0.0)
                values = tuple(point.relative_hartree for point in preview.path_result.nodes)
                if len(values) != 3 or any(value is None for value in values):
                    raise AssertionError(f"Expected three calculated points: {values}")
                if any(abs(actual - wanted) > 1e-8 for actual, wanted in zip(values, expected)):
                    raise AssertionError(f"Unexpected calculated energies: {values}, expected {expected}")
                spec["stage_ids"] = stage_ids
                spec["preview_relative_hartree"] = values
                spec["preview_relative_display"] = tuple(point.display_value for point in preview.path_result.nodes)
                print("U7 precheck ready", spec["name"], values, flush=True)

                _click(dialog.apply_button, "应用并保存")
                print("U7 apply/save clicked", spec["name"], flush=True)
                _wait(app, lambda: dialog._flow_state == "saved" or
                      (not dialog.controller.busy and dialog._flow_state not in {"previewing", "applying", "saving"}),
                      f"apply and save {spec['name']}")
                if dialog._flow_state != "saved":
                    raise AssertionError(f"Apply/save did not reach saved state: {dialog.flow_status.text()}")
                spec["saved_path_id"] = dialog.path_combo.currentData()
                spec["saved_flow_status"] = dialog.flow_status.text()
                print("U7 saved", spec["name"], spec["saved_path_id"], flush=True)
            _click(dialog.cancel_button, "close clean saved builder")
            print("U7 builder closed", flush=True)
        except Exception as error:  # preserve detailed evidence and leave the modal safely
            build_errors.append(f"{type(error).__name__}: {error}")
            print("U7 builder error", build_errors[-1], flush=True)
            try:
                dialog._allow_close = True
                dialog.reject()
            except Exception:
                pass

    QTimer.singleShot(0, work)


def _ui_workflow(app, *, run_dir, logs, candidate_names, project_names, path_specs, energy_kind):
    from unittest.mock import patch
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog,
                                   QDialogButtonBox)
    from gaussianreadpro.services.controller import ProjectController
    from gaussianreadpro.ui.import_summary import ImportSummaryDialog
    from gaussianreadpro.ui.main_window import MainWindow
    from gaussianreadpro.ui.reaction_builder import ReactionBuilderDialog
    from gaussianreadpro.ui.theme import apply_theme

    run_dir.mkdir(parents=True, exist_ok=True)
    recovery = run_dir / "recovery"
    controller = ProjectController(recovery, run_dir / "preferences.ini")
    window = MainWindow(controller)
    window.resize(1440, 900)
    window.show()
    controller.bootstrap()
    _wait_idle(app, controller)
    if window.navigation.currentRow() != 0 or controller.project is not None:
        raise AssertionError("Workflow did not begin at the default empty home")
    initial = {"home_row": window.navigation.currentRow(),
               "home_visible": window.isVisible(),
               "new_button_visible": window.new_button.isVisible(),
               "import_button_visible": window.import_button.isVisible()}

    text_values = iter(project_names)
    save_values = iter([str(run_dir / f"{project_names[1]}.grproj"), str(run_dir / "profile-html")])

    def get_text(*_args, **_kwargs):
        value = next(text_values)
        return value, True

    def get_save(*_args, **_kwargs):
        return next(save_values), ""

    with patch.object(QInputDialog, "getText", side_effect=get_text), \
         patch.object(QFileDialog, "getOpenFileNames", return_value=(list(map(str, logs)), "")), \
         patch.object(QFileDialog, "getSaveFileName", side_effect=get_save), \
         patch.object(QInputDialog, "getItem", side_effect=lambda _parent, _title, _label, items, *args, **kwargs:
                      (next((value for value in items if value == "HTML"), items[0]), True)
                      if "格式" in str(_label) else ("English", True)):
        _click(window.new_button, "新建项目")
        _wait_idle(app, controller)
        _click(window.project_name, "项目名重命名入口")
        _wait_idle(app, controller)

        if not initial["import_button_visible"]:
            raise AssertionError("Default home does not expose its import action")
        _click(window.import_button, "首页导入 Gaussian 日志")
        _wait_idle(app, controller)
        print("U7 import complete", len(controller.project.source_files), flush=True)
        _wait(app, lambda: isinstance(window._import_summary_dialog, ImportSummaryDialog), "post-import summary")
        summary = window._import_summary_dialog
        summary_text = "\n".join(label.text() for label in summary.findChildren(__import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
        summary.grab().save(str(run_dir / "import-summary.png"))

        candidates = {"selected_candidates": []}
        _handle_job_candidates(app, candidate_names, candidates)
        build_errors = []
        _run_builder(app, path_specs, energy_kind, build_errors)
        _click(summary.candidates_button, "打开作业候选表")
        _wait(app, lambda: not any(isinstance(item, __import__("gaussianreadpro.ui.import_summary", fromlist=["JobCandidateDialog"]).JobCandidateDialog)
                                   and item.isVisible() for item in app.topLevelWidgets()),
              "job candidate dialog close", 60)
        if candidates.get("error"):
            raise AssertionError(candidates["error"])
        print("U7 candidates accepted", len(candidates["selected_candidates"]), flush=True)
        _wait(app, lambda: bool(build_errors) or not any(isinstance(item, ReactionBuilderDialog) and item.isVisible()
                                                         for item in app.topLevelWidgets()),
              "builder completion", 180)
        builder = _top_level(app, ReactionBuilderDialog)
        # A successful click on Apply/Save keeps the modal open until the scheduled
        # callback closes it. Errors are captured by the callback and reported here.
        if builder is not None:
            raise AssertionError("Reaction builder remained open after workflow actions")
        if build_errors:
            raise AssertionError("; ".join(build_errors))
        _wait_idle(app, controller)

        # Exercise the Structures route with the actual imported B-containing
        # source/job and verify the user-facing element symbol in its table.
        structure_evidence = None
        if candidate_names and any(formula for _, formula in candidate_names.values()):
            print("U7 structure route start", flush=True)
            QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                             pos=window.navigation.visualItemRect(window.navigation.item(3)).center())
            app.processEvents()
            page = window.analysis_pages["结构"]
            chosen = candidates["selected_candidates"][0]
            _select_combo(page.source_combo, chosen["source_file_id"])
            _select_combo(page.job_combo, chosen["job_id"])
            _click(page.load_button, "结构页读取已选择作业")
            _wait(app, lambda: page.result is not None and page.result.get("status") == "available",
                  "B-containing structure read", 90)
            symbol = page.table.item(0, 1).text()
            if symbol != "B":
                raise AssertionError(f"Expected boron symbol B in structure table; observed {symbol!r}")
            page.grab().save(str(run_dir / "structure-boron.png"))
            structure_evidence = {"status": page.result["status"], "first_element_symbol": symbol,
                                  "atomic_number": page.table.item(0, 2).text(),
                                  "job_id": chosen["job_id"], "source_file_id": chosen["source_file_id"]}

        # Return to the energy page by clicking its visible sidebar item.
        QTest.mouseClick(window.navigation.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.navigation.visualItemRect(window.navigation.item(2)).center())
        app.processEvents()
        _wait_idle(app, controller)
        panel = window.profile
        print("U7 energy route start", flush=True)
        _wait(app, lambda: panel.last_payload is not None and panel.last_payload.get("project_id") == controller.project.id,
              "energy profile payload", 90)
        QTest.qWait(700)
        chart_screenshot = run_dir / "energy-profile.png"
        window.grab().save(str(chart_screenshot))
        chart_paths = [{"id": item.id, "label": item.label, "color": item.color,
                        "relative_hartree": [point.relative_hartree for point in item.points],
                        "display_values": [point.values[0] if point.values else None for point in item.points]}
                       for item in panel.spec.paths]
        _click(panel.export_button, "导出能量图")
        print("U7 export clicked", flush=True)
        _wait(app, lambda: (run_dir / "profile-html" / "profile.html").is_file(),
              "HTML export package", 90)
        exported = run_dir / "profile-html"
        if panel.failure and panel.stack.currentWidget() is not panel.native:
            raise AssertionError("Renderer failure did not expose the native chart fallback")

        project_path = run_dir / f"{project_names[1]}.grproj"
        if not project_path.is_file():
            raise AssertionError("Apply and Save did not write the named project file")
        project = controller.project
        from gaussianreadpro.core.models import snapshot_to_dict
        from gaussianreadpro.core.reaction_network import read_reaction_network
        network = read_reaction_network(project)
        project_state = _state_summary(project, network, panel.spec)
        expected_path = run_dir / "reopen-expected.json"
        expected_path.write_text(json.dumps(project_state, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        # Exercise the window's actual close guard. Export and debounced workspace
        # persistence can still be in flight after the HTML files appear.
        window.close()
        _wait(app, lambda: controller._closed, "close project before fresh-process reopen")
        _wait(app, lambda: not window.isVisible(), "finish window close before fresh-process reopen")
        window.deleteLater()
        app.processEvents()

    child = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--reopen",
                            str(project_path), str(expected_path), str(run_dir / "reopened.json")],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if child.returncode != 0:
        raise AssertionError(f"Fresh-process reopen failed ({child.returncode}): {child.stdout}\n{child.stderr}")
    reopened = json.loads((run_dir / "reopened.json").read_text(encoding="utf-8"))
    return {"default_home": initial, "renamed_project_name": project_names[1],
            "import_summary": summary_text, "job_candidates": candidates["selected_candidates"],
            "builder_paths": path_specs, "structure_boron": structure_evidence,
            "chart_paths": chart_paths, "chart_renderer_ready": bool(panel.ready),
            "chart_renderer": ("webengine" if panel.ready else
                               "native-fallback" if panel.failure else "pending"),
            "chart_renderer_failure": panel.failure or None,
            "chart_native_fallback_visible": panel.stack.currentWidget() is panel.native,
            "chart_screenshot": str(chart_screenshot), "export_dir": str(exported),
            "export_files": sorted(item.name for item in exported.iterdir()),
            "project_file": str(project_path), "fresh_process_reopen": reopened}


def _state_summary(project, network, plot_spec):
    from gaussianreadpro.core.models import snapshot_to_dict
    encode = lambda value: json.dumps(snapshot_to_dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    paths = [{"id": path.id, "label": path.label, "color": path.color,
              "entry_ids": [entry.id for entry in path.entries], "node_ids": [entry.node_id for entry in path.entries]}
             for path in project.paths]
    recipes = {item["path_id"]: item for item in network["path_reactions"]}
    chart = [{"id": path.id, "label": path.label, "color": path.color,
              "points": [{"entry_id": point.entry_id, "node_id": point.node_id,
                          "relative_hartree": point.relative_hartree, "valid": point.valid}
                         for point in path.points]}
             for path in plot_spec.paths]
    return {"project_id": project.id, "revision": project.revision,
            "paths": paths,
            "recipes": {identifier: hashlib.sha256(encode(recipe).encode("utf-8")).hexdigest()
                        for identifier, recipe in recipes.items()},
            "zero_points": {identifier: snapshotread(recipe.get("zero_point"))
                            for identifier, recipe in recipes.items()},
            "species": [{"id": item["id"], "name": item["name"], "formula": item.get("formula", ""),
                         "starred": item["starred"], "bindings": item["bindings"]}
                        for item in network["species"]],
            "expressions": {node.id: hashlib.sha256(encode(node.expression).encode("utf-8")).hexdigest()
                            for node in project.nodes},
            "chart": chart}


def snapshotread(value):
    from gaussianreadpro.core.models import snapshot_to_dict
    return snapshot_to_dict(value)


def _reopen(project_file, expected_file, output_file):
    from gaussianreadpro.core.models import snapshot_to_dict
    from gaussianreadpro.core.reaction_network import read_reaction_network
    from gaussianreadpro.services.session import SessionBackend
    backend = SessionBackend(Path(output_file).parent / "reopen-recovery",
                             Path(output_file).parent / "reopen-preferences.ini")
    try:
        view = backend.open(Path(project_file), ignore_recovery=True)
        actual = _state_summary(view.project, read_reaction_network(view.project), view.plot_spec)
        expected = json.loads(Path(expected_file).read_text(encoding="utf-8"))
        if actual != expected:
            raise AssertionError("Fresh-process project/AST/zero/species/chart state differs from pre-close state")
        Path(output_file).write_text(json.dumps(actual, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "project_id": view.project.id,
                          "path_ids": [path["id"] for path in actual["paths"]],
                          "recipe_count": len(actual["recipes"]),
                          "chart_path_count": len(actual["chart"])}, ensure_ascii=False))
    finally:
        backend.shutdown()


def _real_roundtrip(run_dir):
    from dataclasses import replace
    from gaussianreadpro.core import EnergyKind, parse_log, select_job
    from gaussianreadpro.core.expressions import expression_from_ast, ref_ast
    from gaussianreadpro.core.models import CalculationMode, EnergyRef, KindPolicy, Unit, snapshot_to_dict
    from gaussianreadpro.services.session import SessionBackend

    root = ROOT / "tests" / "fixtures" / "reference"
    manifest = json.loads((root / "expected.json").read_text(encoding="utf-8"))
    paths = [root / item["path"] for item in manifest["cases"]]
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError("Local Gaussian16 reference outputs are required; they are not copied by this check")
    parsed = []
    for case, path in zip(manifest["cases"], paths):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != case["sha256"]:
            raise AssertionError(f"Reference log SHA mismatch: {path.name}")
        source = parse_log(path).source
        selection = select_job(source, EnergyKind.SCF)
        if not selection.available or selection.energy.source_line != case["energies"]["scf"]["line"]:
            raise AssertionError(f"SCF selection/source line mismatch for {path.name}")
        parsed.append({"path": path, "source": source, "selection": selection,
                       "source_sha256": digest, "scf_line": selection.energy.source_line})

    run_dir.mkdir(parents=True, exist_ok=True)
    backend = SessionBackend(run_dir / "real-recovery", run_dir / "real-preferences.ini")
    fresh = None
    try:
        view = backend.new()
        imported = backend.import_files(view.project, paths, lambda: False, lambda *_args: None)
        project = imported.project
        by_name = {item.original_name: item for item in project.source_files}
        expressions = {}
        nodes = []
        for node_index, node in enumerate(project.nodes):
            source = next((item for item in project.source_files if item.id == getattr(node, "source_file_id", None)), None)
            if source is None:
                source = next((item for item in project.source_files
                               if item.original_name == node.label or item.display_name == node.label), None)
            if source is None:
                source = project.source_files[min(node_index, len(project.source_files) - 1)]
            job = source.jobs[0]
            expression = expression_from_ast(ref_ast(EnergyRef(source.id, job.id,
                                                               KindPolicy.FIXED, EnergyKind.SCF)))
            expressions[node.id] = expression
            nodes.append(replace(node, expression=expression))
        path = project.paths[0]
        updated_path = replace(path, label="Real source/job line check (not a reaction)",
                               energy_kind=EnergyKind.SCF, calculation_mode=CalculationMode.RELATIVE,
                               unit=Unit.KCAL_MOL, reference_expression=expressions[nodes[0].id],
                               color="#7450af")
        project = replace(project, nodes=tuple(nodes), paths=(updated_path,), revision=project.revision + 1)
        view = backend.update(project)
        values = [point.relative_hartree for point in view.results[0].nodes]
        if len(values) != 3 or any(abs(value or 0.0) > 1e-10 for value in values):
            raise AssertionError(f"Equal-energy real regression sample produced unexpected values: {values}")
        target = run_dir / "real-source-roundtrip.grproj"
        backend.save(project, target)
        fresh = SessionBackend(run_dir / "real-fresh-recovery", run_dir / "real-fresh-preferences.ini")
        reopened = fresh.open(target, ignore_recovery=True)
        if reopened.project.id != project.id or [item.relative_hartree for item in reopened.results[0].nodes] != values:
            raise AssertionError("Real-log project did not survive fresh SessionBackend reopen")
        source_evidence = []
        for item in parsed:
            name = item["path"].name
            loaded = by_name[name]
            source_evidence.append({"name": name, "source_id": loaded.id,
                                    "job_id": loaded.jobs[0].id,
                                    "sha256": item["source_sha256"],
                                    "scf_source_line": item["scf_line"],
                                    "scf_raw": item["selection"].energy.raw_text})
        return {"project_file": str(target), "project_id": project.id,
                "reference_commit": manifest["commit"], "upstream_directory": manifest["upstream_directory"],
                "license_readme": "tests/fixtures/reference/README.md",
                "local_only_ignored_outputs": True, "sources": source_evidence,
                "relative_hartree": values,
                "zero_energy_sample_is_not_barrier_evidence": True,
                "fresh_process_roundtrip": True}
    finally:
        backend.shutdown()
        if fresh:
            fresh.shutdown()


def main():
    if len(sys.argv) == 5 and sys.argv[1] == "--reopen":
        _reopen(sys.argv[2], sys.argv[3], sys.argv[4])
        return 0
    affinity = _affinity()
    from PySide6.QtWidgets import QApplication
    from gaussianreadpro.ui.theme import apply_theme
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    run_dir = ROOT / "artifacts" / "ux-v2" / "u7" / uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    fixture = ROOT / "tests" / "fixtures" / "ux_v2_u7"
    logs = [fixture / f"{name}.log" for name in ("R", "TS", "P")]
    specs = [
        {"name": "U7 Synthetic Alpha", "color": "#7450af", "species": ["R", "TS", "P"],
         "note": "SYNTHETIC U7 fixture; composition is intentionally held as BH3 for UI/energy checks."},
        {"name": "U7 Synthetic Beta", "color": "#52cdb8", "species": ["R", "TS", "P"],
         "note": "SYNTHETIC U7 fixture; this separate path reuses the same source-bound material cards."},
    ]
    candidates = {f"{name}.log": (name, "BH3") for name in ("R", "TS", "P")}
    ui = _ui_workflow(app, run_dir=run_dir / "synthetic-route", logs=logs,
                      candidate_names=candidates,
                      project_names=["U7 Synthetic", "U7 Synthetic Renamed", "U7 Synthetic Beta"],
                      path_specs=specs, energy_kind="gibbs_total")
    real = _real_roundtrip(run_dir / "real-roundtrip")
    output = {"passed": True, "captured_at_local": __import__("datetime").datetime.now().astimezone().isoformat(),
              "process_affinity": hex(affinity) if affinity is not None else None,
              "synthetic_fixture": {"path": str(fixture), "marker": "SYNTHETIC UX V2 U7 FIXTURE",
                                    "gibbs_totals_hartree": [-10.0, -9.98, -10.02],
                                    "expected_relative_hartree": [0.0, 0.02, -0.02]},
              "synthetic_visible_route": ui, "real_log_roundtrip": real}
    report = ROOT / "artifacts" / "ux-v2" / "u7" / "u7-validation.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": output["passed"], "report": str(report),
                      "synthetic_paths": len(ui["chart_paths"]),
                      "real_logs": len(real["sources"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
