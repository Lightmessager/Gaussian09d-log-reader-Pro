from dataclasses import replace

import pytest

from gaussianreadpro.core import EnergyKind, Project, ReactionPath, calculate_path, compile_expression, parse_log
from gaussianreadpro.core.expressions import edit_expression
from gaussianreadpro.core.models import (CalculationMode, EnergyRef, KindPolicy, NodeRole, PathEntry, ProfileNode,
                                         new_id)
from gaussianreadpro.core.reaction_network import (apply_path_recipe, empty_network,
                                                   read_reaction_network, reference_signature)
from gaussianreadpro.ui.reaction_builder_state import BuilderDraft
from gaussianreadpro.ui.workflow_state import derive_import_summary, derive_job_candidates, derive_workflow
from gaussianreadpro.storage.sources import SourceConnection


@pytest.fixture
def legacy_project(tmp_path):
    log = tmp_path / "single-job.log"
    log.write_text(
        "Entering Gaussian System\n"
        " SCF Done: E(RB3LYP) = -1.020000000000 A.U.\n"
        " Thermal correction to Gibbs Free Energy= 0.020000000000\n"
        " Sum of electronic and thermal Free Energies= -1.000000000000\n"
        " Normal termination of Gaussian 16\n", encoding="utf-8")
    source = parse_log(log).source
    job = source.jobs[0]
    ref = EnergyRef(source.id, job.id, KindPolicy.FOLLOW_PATH)
    expression = compile_expression("@{sample}", {"sample": ref}).expression
    node_id, entry_id, path_id = new_id(), new_id(), new_id()
    node = ProfileNode(node_id, "A", expression, NodeRole.UNSPECIFIED, {"x": 44.0, "y": 22.0})
    entry = PathEntry(entry_id, node_id, 0, {"color": "#123456"})
    path = ReactionPath(path_id, "legacy path", (entry,), EnergyKind.GIBBS_TOTAL,
                        expression, "relative")
    project = Project(new_id(), (source,), (node,), (path,), alias_bindings={"sample": ref})
    return project


def _conversion(draft, project, node, role="reactant"):
    return draft.conversion_preview(
        project,
        roles={node.id: role},
        confirmed_compositions={node.id},
        accept_reference_policy=True,
    )


def test_supported_legacy_conversion_preserves_values_and_ids(legacy_project):
    project = legacy_project
    path = project.paths[0]
    node = project.nodes[0]
    draft = BuilderDraft.from_project(project, path.id)

    assert draft.legacy_mode == "legacy_supported"
    preview = _conversion(draft, project, node)
    assert preview.identity_policy == "preserve_exclusive"
    assert preview.reference_policy_changed is True
    stage = preview.network["path_reactions"][0]["stages"][0]
    assert (stage["node_id"], stage["entry_id"]) == (node.id, path.entries[0].id)

    converted = apply_path_recipe(project, preview.network, path.id,
                                   identity_policy=preview.identity_policy)
    original_values = calculate_path(project, path.id).nodes[0]
    converted_values = calculate_path(converted, path.id).nodes[0]
    assert converted_values.absolute_hartree == pytest.approx(original_values.absolute_hartree)
    assert converted_values.reference_hartree == pytest.approx(original_values.reference_hartree)
    assert converted_values.relative_hartree == pytest.approx(original_values.relative_hartree)
    assert {(item.source_file_id, item.job_id) for item in converted_values.dependencies} == {
        (project.source_files[0].id, project.source_files[0].jobs[0].id)}
    assert converted.nodes[0].display == node.display
    assert converted.paths[0].entries[0].display_override == path.entries[0].display_override
    assert reference_signature(converted.paths[0].reference_expression) == read_reaction_network(converted)["path_reactions"][0]["reference_signature"]
    assert BuilderDraft.from_project(converted, path.id).legacy_mode == "existing_recipe"


def test_default_materialization_still_regenerates(legacy_project):
    project = legacy_project
    node = project.nodes[0]
    path = project.paths[0]
    preview = _conversion(BuilderDraft.from_project(project, path.id), project, node)

    converted = apply_path_recipe(project, preview.network, path.id)

    assert converted.paths[0].entries[0].id != path.entries[0].id
    assert converted.paths[0].entries[0].node_id != node.id


def test_preserve_exclusive_reuses_only_valid_entry_node_pairs(legacy_project):
    project = legacy_project
    node, path = project.nodes[0], project.paths[0]
    preview = _conversion(BuilderDraft.from_project(project, path.id), project, node)

    converted = apply_path_recipe(project, preview.network, path.id,
                                  identity_policy="preserve_exclusive")

    assert converted.paths[0].entries[0].id == path.entries[0].id
    assert converted.paths[0].entries[0].node_id == node.id
    assert converted.nodes[0].display == node.display
    assert converted.paths[0].entries[0].display_override == path.entries[0].display_override


@pytest.mark.parametrize("mutation", ["partial", "dangling", "duplicate"])
def test_preserve_exclusive_rejects_invalid_entry_node_pairs(legacy_project, mutation):
    project = legacy_project
    node = project.nodes[0]
    path = project.paths[0]
    preview = _conversion(BuilderDraft.from_project(project, path.id), project, node)
    stage = preview.network["path_reactions"][0]["stages"][0]
    if mutation == "partial":
        stage["entry_id"] = None
    elif mutation == "dangling":
        stage["entry_id"] = new_id()
    else:
        stage["id"] = new_id()
        duplicate = dict(stage)
        duplicate["id"] = new_id()
        preview.network["path_reactions"][0]["stages"].append(duplicate)

    with pytest.raises(ValueError, match="identity|entry|stage|history"):
        apply_path_recipe(project, preview.network, path.id, identity_policy="preserve_exclusive")


def test_shared_node_conversion_requires_new_path(legacy_project):
    project = legacy_project
    path = project.paths[0]
    node = project.nodes[0]
    other_path = ReactionPath(new_id(), "shared", (PathEntry(new_id(), node.id, 0),),
                              EnergyKind.GIBBS_TOTAL, project.paths[0].reference_expression)
    project = replace(project, paths=(*project.paths, other_path))
    with pytest.raises(ValueError, match="shared|new path"):
        _conversion(BuilderDraft.from_project(project, path.id), project, node)
    target = ReactionPath(new_id(), "legacy path visual", (), path.energy_kind,
                          None, "relative")
    preview = BuilderDraft.from_project(project, path.id).conversion_preview(
        project, roles={node.id: "reactant"}, confirmed_compositions={node.id},
        accept_reference_policy=True, target_path=target)
    prepared_project = replace(project, paths=(*project.paths, target))
    converted = apply_path_recipe(prepared_project, preview.network, target.id,
                                  identity_policy=preview.identity_policy)
    assert converted.paths[0] == path
    assert converted.paths[1] == other_path
    assert converted.paths[2].entries[0].node_id != node.id
    assert calculate_path(converted, path.id).nodes[0].absolute_hartree == pytest.approx(
        calculate_path(project, path.id).nodes[0].absolute_hartree)


def test_complex_ast_is_not_silently_rebuilt(legacy_project):
    project = legacy_project
    node = project.nodes[0]
    complex_expression = compile_expression("@{sample} + @{sample}", project.alias_bindings).expression
    project = replace(project, nodes=(replace(node, expression=complex_expression),))
    draft = BuilderDraft.from_project(project, project.paths[0].id)

    assert draft.legacy_mode == "legacy_expert"
    with pytest.raises(ValueError):
        draft.conversion_preview(project, roles={node.id: "reactant"}, confirmed_compositions={node.id},
                                 accept_reference_policy=True)


def test_import_does_not_auto_confirm_reaction_edges(legacy_project):
    project = legacy_project
    draft = BuilderDraft.from_project(project, project.paths[0].id)
    candidate = {"source_file_id": project.source_files[0].id,
                 "job_id": project.source_files[0].jobs[0].id, "name": "candidate A"}

    network = draft.propose_imported_jobs(project, [candidate])

    assert network["path_reactions"] == draft.network["path_reactions"]
    assert network["edges"] == []
    assert network["species"][-1]["bindings"] == [{
        "source_file_id": candidate["source_file_id"],
        "job_id": candidate["job_id"], "historical": False,
    }]


def test_builder_classifies_empty_recipe_direct_difference_and_invalid_drafts(legacy_project):
    project = legacy_project
    path = project.paths[0]
    node = project.nodes[0]
    empty = replace(project, paths=(replace(path, entries=()),))
    assert BuilderDraft.from_project(empty, path.id).legacy_mode == "empty"

    direct = replace(project, paths=(replace(path, calculation_mode="direct_difference",
                                             reference_expression=None),))
    assert BuilderDraft.from_project(direct, path.id).legacy_mode == "legacy_expert"

    invalid_node = replace(node, expression=edit_expression(node.expression, "@{sample} +"))
    invalid = replace(project, nodes=(invalid_node,))
    assert BuilderDraft.from_project(invalid, path.id).legacy_mode == "legacy_invalid"


def test_absolute_energy_legacy_path_requires_new_path_route(legacy_project):
    path = legacy_project.paths[0]
    absolute_path = replace(path, calculation_mode=CalculationMode.ABSOLUTE,
                            reference_expression=None)
    project = replace(legacy_project, paths=(absolute_path,))

    draft = BuilderDraft.from_project(project, absolute_path.id)

    assert draft.legacy_mode == "legacy_expert"
    assert "绝对能量" in draft.legacy_reason
    with pytest.raises(ValueError, match="绝对能量"):
        draft.conversion_preview(project, roles={project.nodes[0].id: "reactant"},
                                 confirmed_compositions={project.nodes[0].id},
                                 accept_reference_policy=True)


def test_import_summary_and_job_candidates_use_uuid_and_current_energy_availability(legacy_project):
    project = legacy_project
    summary = derive_import_summary(project)
    candidates = derive_job_candidates(project)
    job = project.source_files[0].jobs[0]
    newly_added = derive_import_summary(project, source_ids={project.source_files[0].id})

    assert (summary.source_count, summary.job_count) == (1, 1)
    assert summary.available("scf") == summary.available("gibbs_correction") == summary.available("gibbs_total") == 1
    assert len(candidates) == 1
    assert (candidates[0].source_file_id, candidates[0].job_id) == (project.source_files[0].id, job.id)
    assert candidates[0].source_path == project.source_files[0].original_path
    assert set(candidates[0].available_energy_kinds) == {"scf", "gibbs_correction", "gibbs_total"}
    assert newly_added.available("scf") == 1


def test_workflow_ignores_results_from_another_project_revision(legacy_project):
    project = legacy_project
    path = project.paths[0]
    result = calculate_path(project, path.id)
    available = (SourceConnection(project.source_files[0].id, "available", None),)
    changed = (SourceConnection(project.source_files[0].id, "changed", None),)
    current = derive_workflow(project, (result,), available, None, active_path_id=path.id,
                              busy=False, read_only=False, path=None)
    stale_project = replace(project, revision=project.revision + 1)
    stale = derive_workflow(stale_project, (result,), available, None, active_path_id=path.id,
                            busy=False, read_only=False, path=None)
    disconnected = derive_workflow(project, (result,), changed, None, active_path_id=path.id,
                                   busy=False, read_only=False, path=None)
    read_only_disconnected = derive_workflow(project, (result,), changed, None,
        active_path_id=path.id, busy=False, read_only=True, path=None)

    assert [step.state for step in current.steps] == ["ready", "ready", "ready", "pending"]
    assert current.next_action == "save_project"
    assert current.action_availability["calculate"].enabled is True
    assert stale.steps[2].state == "pending"
    assert stale.next_action == "calculate"
    assert disconnected.steps[2].state == "needs_attention"
    assert disconnected.steps[0].state == "needs_attention"
    assert disconnected.next_action == "reconnect_source"
    assert disconnected.action_availability["reconnect_source"].enabled is True
    assert read_only_disconnected.next_action == "show_sources"


