from dataclasses import replace

from gaussianreadpro.core import calculate_path
from gaussianreadpro.ui.plot_inspector import build_plot_inspector_snapshot
from s2_helpers import project as sample_project
from test_workbench import app, workbench


def test_summary_resolves_same_named_nodes_by_path_entry_and_node_id():
    project, _, _ = sample_project()
    first, second, *_ = project.nodes
    project = replace(project, nodes=(first, replace(second, label=first.label), *project.nodes[2:]))
    path = project.paths[0]
    result = calculate_path(project, path.id)

    first_snapshot = build_plot_inspector_snapshot(project, path, result, first.id, path.entries[0].id)
    second_snapshot = build_plot_inspector_snapshot(project, path, result, second.id, path.entries[1].id)

    assert first_snapshot["node_label"] == second_snapshot["node_label"]
    assert first_snapshot["node_id"] != second_snapshot["node_id"]
    assert first_snapshot["entry_id"] != second_snapshot["entry_id"]
    assert first_snapshot["value"] == 0
    assert second_snapshot["value"] > 0


def test_stale_invalid_and_draft_results_never_show_numeric_values():
    project, _, _ = sample_project()
    path = project.paths[0]
    node = project.nodes[0]
    result = calculate_path(project, path.id)
    entry = path.entries[0]

    stale = replace(result, revision=project.revision - 1)
    assert build_plot_inspector_snapshot(project, path, stale, node.id, entry.id)["status"] == "pending"
    assert build_plot_inspector_snapshot(project, path, stale, node.id, entry.id)["value"] is None

    invalid_point = replace(result.nodes[0], valid=False, display_value=None)
    invalid_result = replace(result, nodes=(invalid_point, *result.nodes[1:]))
    invalid = build_plot_inspector_snapshot(project, path, invalid_result, node.id, entry.id)
    assert invalid["status"] == "invalid"
    assert invalid["value"] is None
    assert invalid["absolute_hartree"] is None

    draft_node = replace(node, expression=replace(node.expression, draft_text="@{unfinished}"))
    draft_project = replace(project, nodes=(draft_node, *project.nodes[1:]))
    draft = build_plot_inspector_snapshot(draft_project, path, result, node.id, entry.id)
    assert draft["status"] == "draft"
    assert draft["value"] is None
    assert draft["absolute_hartree"] is None


def test_direct_difference_hides_system_and_reference_energy_fields():
    project, _, _ = sample_project()
    path = project.paths[0]
    result = calculate_path(project, path.id)
    direct_path = replace(path, calculation_mode="direct_difference", reference_expression=None)
    direct_result = replace(result, calculation_mode="direct_difference")

    snapshot = build_plot_inspector_snapshot(project, direct_path, direct_result,
                                             project.nodes[0].id, path.entries[0].id)
    assert snapshot["direct_difference"]
    assert snapshot["value"] == result.nodes[0].display_value
    assert snapshot["absolute_hartree"] is None
    assert snapshot["reference_hartree"] is None


def test_snapshot_reports_source_file_job_and_line():
    project, _, _ = sample_project()
    path = project.paths[0]
    result = calculate_path(project, path.id)
    snapshot = build_plot_inspector_snapshot(project, path, result,
                                             project.nodes[0].id, path.entries[0].id)

    assert snapshot["sources"]
    dependency = snapshot["sources"][0]
    assert dependency["source_path"].endswith("R.log")
    assert dependency["job_ordinal"] == 1
    assert dependency["line"] >= 1


def test_expanded_profile_reuses_details_and_restores_workbench(app, workbench):
    window, _ = workbench
    panel, details = window.profile, window.plot_inspector
    panel.workbench = False  # Legacy/native panel keeps its original detail reparenting contract.
    original_parent = details.parentWidget()
    original_index = original_parent.layout().indexOf(details)
    browser = panel.webview
    panel.expand()
    dialog = panel._expanded
    assert dialog.details_scroll.widget() is details
    assert panel.webview is browser
    dialog.showNormal()
    dialog.resize(1300, 820); app.processEvents()
    assert dialog.details_scroll.isVisible()
    dialog.details_toggle.setChecked(False); app.processEvents()
    assert not dialog.details_scroll.isVisible()
    dialog.details_toggle.setChecked(True)
    dialog.resize(880, 680); app.processEvents()
    assert not dialog.details_scroll.isVisible() and not dialog.details_toggle.isVisible()
    panel.set_language("en")
    assert dialog.details_toggle.text() == "Node details"
    dialog.close(); app.processEvents()
    assert panel._expanded is None
    assert details.parentWidget() is original_parent
    assert original_parent.layout().indexOf(details) == original_index


def test_expanded_workbench_keeps_single_page_and_restores_parent(app, workbench):
    window, _ = workbench
    panel, details = window.profile, window.plot_inspector
    parent, details_parent = panel.parentWidget(), details.parentWidget()
    browser = panel.webview
    panel.expand()
    dialog = panel._expanded
    assert not hasattr(dialog, "details_scroll")
    assert panel.webview is browser
    assert details.parentWidget() is details_parent
    dialog.showNormal()
    dialog.resize(880, 680)
    app.processEvents()
    dialog.close()
    app.processEvents()
    assert panel._expanded is None
    assert panel.parentWidget() is parent
    assert details.parentWidget() is details_parent
