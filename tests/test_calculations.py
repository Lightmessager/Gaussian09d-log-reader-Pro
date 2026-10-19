import json
from dataclasses import replace

import pytest

from gaussianreadpro.core.calculations import calculate_path
from gaussianreadpro.core.expressions import edit_expression
from gaussianreadpro.core.models import (CalculationMode, ExpressionPurpose, PathEntry, ProfileNode,
                                         Project, ReactionPath, Unit, snapshot_to_dict)
from gaussianreadpro.core.units import HARTREE_TO_KCAL, HARTREE_TO_KJ
from s2_helpers import expression, identifier, project


def test_four_node_oracle_absolute_reference_and_one_subtraction():
    data, refs, aliases = project()
    result = calculate_path(data, data.paths[0].id)
    assert result.valid and result.reference_hartree == -150
    expected_abs = (-150, -149.976, -150.008, -150.025)
    expected_rel = (0, .024, -.008, -.025)
    assert [n.absolute_hartree for n in result.nodes] == pytest.approx(expected_abs, abs=1e-12)
    assert [n.relative_hartree for n in result.nodes] == pytest.approx(expected_rel, abs=1e-12)
    assert [n.display_value for n in result.nodes] == pytest.approx(
        [v * HARTREE_TO_KCAL for v in expected_rel], abs=1e-9)
    assert result.nodes[1].reference_hartree == -150
    assert len(result.nodes[1].dependencies) == 2 and len(result.nodes[1].reference_dependencies) == 4
    json.dumps(snapshot_to_dict(result), allow_nan=False)


def test_direct_difference_equals_relative_path_without_another_reference():
    data, _, aliases = project()
    delta = ProfileNode(identifier("delta"), "TS1 - (R+A)",
                        expression("@{TS1} - (@{R}+@{A})", aliases, purpose=ExpressionPurpose.DIFFERENCE))
    direct = ReactionPath(identifier("direct"), "Difference", (PathEntry(identifier("direct-entry"), delta.id, 0),),
                           calculation_mode=CalculationMode.DIRECT_DIFFERENCE)
    updated = replace(data, nodes=data.nodes + (delta,), paths=data.paths + (direct,))
    relative = calculate_path(updated, data.paths[0].id)
    difference = calculate_path(updated, direct.id)
    assert difference.valid
    assert difference.nodes[0].absolute_hartree is None and difference.reference_hartree is None
    assert difference.nodes[0].display_value == relative.nodes[1].display_value
    with pytest.raises(ValueError):
        replace(direct, reference_expression=data.paths[0].reference_expression)


def test_difference_nodes_cannot_be_mixed_into_system_path():
    data, _, aliases = project()
    node = replace(data.nodes[1], expression=expression("@{TS1} - @{R}", aliases,
                                                        purpose=ExpressionPurpose.DIFFERENCE))
    updated = replace(data, nodes=(data.nodes[0], node, *data.nodes[2:]))
    result = calculate_path(updated, data.paths[0].id)
    assert not result.valid and not result.nodes[1].valid
    assert result.nodes[1].display_value is None and result.nodes[1].absolute_hartree is None
    assert "expression_purpose_mismatch" in {d.code for d in result.nodes[1].diagnostics}


def test_absolute_mode_and_unfinished_relative_reference_are_explicit():
    data, _, _ = project()
    absolute = replace(data.paths[0], calculation_mode=CalculationMode.ABSOLUTE,
                       reference_expression=None, unit=Unit.HARTREE)
    result = calculate_path(replace(data, paths=(absolute,)), absolute.id)
    assert result.valid and result.reference_hartree is None
    assert result.nodes[1].relative_hartree is None and result.nodes[1].display_value == -149.976
    unfinished = replace(absolute, calculation_mode=CalculationMode.RELATIVE)
    result = calculate_path(replace(data, paths=(unfinished,)), unfinished.id)
    assert not result.valid and all(n.display_value is None for n in result.nodes)
    assert "reference_required" in {d.code for d in result.diagnostics}


def test_shared_node_can_have_different_path_references_and_order():
    data, _, aliases = project()
    second = replace(data.paths[0], id=identifier("second-path"),
                     reference_expression=expression("@{P}", aliases),
                     entries=tuple(PathEntry(identifier("second:" + node.id), node.id, i)
                                   for i, node in enumerate(reversed(data.nodes))))
    updated = replace(data, paths=data.paths + (second,))
    first = calculate_path(updated, data.paths[0].id)
    result = calculate_path(updated, second.id)
    assert result.valid and result.nodes[0].node_id == data.nodes[-1].id
    assert result.nodes[0].relative_hartree == 0
    assert result.nodes[2].node_id == first.nodes[1].node_id
    assert result.nodes[2].relative_hartree != first.nodes[1].relative_hartree
    assert result.nodes[2].absolute_hartree == first.nodes[1].absolute_hartree


@pytest.mark.parametrize("unit,factor", [(Unit.HARTREE, 1), (Unit.KCAL_MOL, HARTREE_TO_KCAL), (Unit.KJ_MOL, HARTREE_TO_KJ)])
def test_unit_changes_do_not_mutate_internal_energy(unit, factor):
    data, _, _ = project()
    path = replace(data.paths[0], unit=unit)
    result = calculate_path(replace(data, paths=(path,)), path.id)
    assert result.valid
    assert result.nodes[1].relative_hartree == pytest.approx(.024, abs=1e-12)
    assert result.nodes[1].display_value == pytest.approx(.024 * factor, abs=1e-9)
    assert data.nodes[1].expression.ast["type"] == "ref"


def test_invalid_reference_and_draft_never_export_previous_values():
    data, _, aliases = project()
    bad = edit_expression(data.paths[0].reference_expression, "@{R}+", aliases)
    path = replace(data.paths[0], reference_expression=bad)
    result = calculate_path(replace(data, paths=(path,)), path.id)
    assert not result.valid and all(n.display_value is None for n in result.nodes)
    assert result.nodes[1].absolute_hartree == -149.976
    bad_node = replace(data.nodes[1], expression=edit_expression(data.nodes[1].expression, "@{TS1}+", aliases))
    result = calculate_path(replace(data, nodes=(data.nodes[0], bad_node, *data.nodes[2:])), data.paths[0].id)
    assert result.nodes[1].display_value is None
    assert result.nodes[1].absolute_hartree is None


def test_known_inconsistent_conditions_warn_and_unknowns_are_not_equal():
    data, refs, _ = project()
    changed = []
    for source in data.source_files:
        if source.id == refs["TS1"].source_file_id:
            job = replace(source.jobs[0], metadata=replace(source.jobs[0].metadata, temperature_kelvin=310,
                                                           solvent=None))
            source = replace(source, jobs=(job,))
        changed.append(source)
    result = calculate_path(replace(data, source_files=tuple(changed)), data.paths[0].id)
    assert result.valid
    assert "inconsistent_conditions" in {d.code for d in result.diagnostics}
    assert "conditions_not_fully_identified" in {d.code for d in result.diagnostics}


def test_constants_version_mismatch_is_not_silently_recomputed():
    data, _, _ = project()
    result = calculate_path(replace(data, unit_constants_version="future-constants"), data.paths[0].id)
    assert not result.valid and all(n.display_value is None for n in result.nodes)
    assert "unsupported_unit_constants_version" in {d.code for d in result.diagnostics}


def test_zero_energy_reference_is_not_treated_as_absent():
    expr = expression("0[hartree]", {})
    node = ProfileNode(identifier("zero-node"), "zero", expr)
    path = ReactionPath(identifier("zero-path"), "zero", (PathEntry(identifier("zero-entry"), node.id, 0),),
                         reference_expression=expr)
    result = calculate_path(Project(identifier("zero-project"), nodes=(node,), paths=(path,)), path.id)
    assert result.valid and result.nodes[0].display_value == 0


def test_project_rejects_duplicate_ids_and_invalid_entry_permutations():
    data, _, _ = project()
    with pytest.raises(ValueError):
        replace(data, source_files=data.source_files + (data.source_files[0],))
    with pytest.raises(ValueError):
        replace(data.paths[0], entries=(replace(data.paths[0].entries[0], position=2),))
    with pytest.raises(ValueError):
        replace(data, paths=data.paths + (replace(data.paths[0], id=identifier("other-path")),))


def test_empty_path_is_invalid_and_unknown_path_is_parameter_error():
    data, _, _ = project()
    result = calculate_path(replace(data, paths=(replace(data.paths[0], entries=()),)), data.paths[0].id)
    assert not result.valid and "empty_path" in {d.code for d in result.diagnostics}
    with pytest.raises(ValueError):
        calculate_path(data, identifier("unknown-path"))
