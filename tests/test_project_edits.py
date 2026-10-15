from dataclasses import replace

import pytest

from gaussianreadpro.core.calculations import calculate_path
from gaussianreadpro.core.expressions import edit_expression, expression_references
from gaussianreadpro.core.models import CalculationMode, ExpressionPurpose
from gaussianreadpro.core.project_edits import (ReferencedSourceError, add_component_to_nodes,
    find_source_usage, remove_sources, reorder_path, replace_node_references, set_reference_for_paths)
from s2_helpers import expression, identifier, project


def test_batch_component_preview_is_pure_and_revision_guarded():
    data, refs, aliases = project()
    plan = add_component_to_nodes(data, [data.nodes[1].id], refs["B"], .5, aliases)
    assert data.revision == 0 and plan.project.revision == 1
    assert data.nodes[1].expression.ast["type"] == "ref"
    assert plan.affected_node_ids == (data.nodes[1].id,)
    assert plan.affected_path_ids == (data.paths[0].id,)
    assert plan.calculate_preview()[0].valid
    result = calculate_path(plan.apply(data), data.paths[0].id)
    assert result.nodes[1].absolute_hartree == pytest.approx(-149.976 + .5 * -10.008)
    with pytest.raises(ValueError):
        plan.apply(replace(data, revision=1))
    with pytest.raises(ValueError):
        plan.apply(replace(data, id=identifier("another-project")))


def test_batch_rebinding_is_exact_and_can_preview_missing_data():
    data, refs, aliases = project()
    plan = replace_node_references(data, [data.nodes[1].id], {refs["TS1"]: refs["P"]}, aliases)
    result = plan.calculate_preview()[0]
    assert result.nodes[1].absolute_hartree == -150.025
    assert expression_references(data.nodes[1].expression) == (refs["TS1"],)
    missing = replace(refs["P"], job_id=identifier("missing-job"))
    invalid = replace_node_references(data, [data.nodes[1].id], {refs["TS1"]: missing})
    assert not invalid.calculate_preview()[0].valid


def test_reference_change_is_path_wide_and_undo_can_retain_previous_snapshot():
    data, _, aliases = project()
    plan = set_reference_for_paths(data, [data.paths[0].id], expression("@{P}", aliases))
    assert plan.project.paths[0].reference_expression != data.paths[0].reference_expression
    assert plan.calculate_preview()[0].nodes[-1].relative_hartree == 0
    assert calculate_path(data, data.paths[0].id).nodes[0].relative_hartree == 0


def test_direct_difference_cannot_acquire_a_second_reference():
    data, _, aliases = project()
    node = replace(data.nodes[0], expression=expression("@{R}-@{A}", aliases,
                                                       purpose=ExpressionPurpose.DIFFERENCE))
    path = replace(data.paths[0], calculation_mode=CalculationMode.DIRECT_DIFFERENCE, reference_expression=None)
    direct = replace(data, nodes=(node, *data.nodes[1:]), paths=(path,))
    with pytest.raises(ValueError):
        set_reference_for_paths(direct, [path.id], expression("@{R}", aliases))


def test_reorder_uses_entry_identity_not_filename_or_table_row():
    data, _, _ = project()
    original = data.paths[0]
    plan = reorder_path(data, original.id, [e.id for e in reversed(original.entries)])
    result = plan.calculate_preview()[0]
    assert result.nodes[0].node_id == data.nodes[-1].id
    assert result.nodes[0].absolute_hartree == -150.025
    assert [e.position for e in plan.project.paths[0].entries] == [0, 1, 2, 3]
    assert original.entries[0].node_id == data.nodes[0].id
    with pytest.raises(ValueError):
        reorder_path(data, original.id, [original.entries[0].id] * 4)


def test_source_deletion_requires_dependency_review_or_explicit_cascade():
    data, refs, _ = project()
    usage = find_source_usage(data, [refs["R"].source_file_id])
    assert usage.node_ids == (data.nodes[0].id,)
    assert usage.reference_path_ids == (data.paths[0].id,)
    with pytest.raises(ReferencedSourceError) as caught:
        remove_sources(data, [refs["R"].source_file_id])
    assert caught.value.usage == usage
    plan = remove_sources(data, [refs["R"].source_file_id], cascade=True)
    assert plan.removed_path_ids == (data.paths[0].id,)
    assert plan.removed_node_ids == (data.nodes[0].id,)
    assert plan.project.paths == ()
    assert len(data.source_files) == 6
    # Removing a reference removes the dependent path; it never silently turns absolute.
    assert len(plan.project.source_files) == 5


def test_cascade_removes_node_entries_and_renumbers_remaining_path():
    data, refs, _ = project()
    plan = remove_sources(data, [refs["TS1"].source_file_id], cascade=True)
    assert not plan.removed_path_ids
    assert len(plan.project.paths[0].entries) == 3
    assert [e.position for e in plan.project.paths[0].entries] == [0, 1, 2]
    assert plan.calculate_preview()[0].valid


def test_batch_edits_fail_atomically_for_unknown_ids_or_invalid_drafts():
    data, refs, aliases = project()
    with pytest.raises(ValueError):
        add_component_to_nodes(data, [data.nodes[0].id, identifier("unknown")], refs["B"])
    draft = replace(data.nodes[1], expression=edit_expression(data.nodes[1].expression, "@{TS1}+", aliases))
    invalid = replace(data, nodes=(data.nodes[0], draft, *data.nodes[2:]))
    with pytest.raises(ValueError):
        add_component_to_nodes(invalid, [data.nodes[0].id, draft.id], refs["B"])
    assert data.revision == invalid.revision == 0


def test_deletion_guards_also_consider_the_last_ast_of_an_invalid_draft():
    data, refs, aliases = project()
    draft = replace(data.nodes[1], expression=edit_expression(data.nodes[1].expression, "@{TS1}+", aliases))
    invalid = replace(data, nodes=(data.nodes[0], draft, *data.nodes[2:]))
    with pytest.raises(ReferencedSourceError):
        remove_sources(invalid, [refs["TS1"].source_file_id])


def test_alias_namespace_is_immutable_persistable_and_protects_partial_draft_tokens():
    from gaussianreadpro.core.models import snapshot_to_dict
    from s2_helpers import source
    data, refs, aliases = project()
    spectator = source("spectator", -5)
    from gaussianreadpro.core.models import EnergyRef
    binding = EnergyRef(spectator.id, spectator.jobs[0].id)
    aliases = type(aliases)({**aliases.bindings, "spectator": binding})
    node = replace(data.nodes[1], expression=edit_expression(data.nodes[1].expression, "@{spectator}+", aliases))
    data = replace(data, nodes=(data.nodes[0], node, *data.nodes[2:]),
                   source_files=data.source_files + (spectator,), alias_bindings=aliases.bindings)
    with pytest.raises(TypeError):
        data.alias_bindings["spectator"] = refs["R"]
    assert snapshot_to_dict(data)["alias_bindings"]["spectator"]["source_file_id"] == spectator.id
    with pytest.raises(ReferencedSourceError):
        remove_sources(data, [spectator.id])
    plan = remove_sources(data, [spectator.id], cascade=True)
    assert "spectator" not in plan.project.alias_bindings
    assert node.id in plan.removed_node_ids
