from dataclasses import replace
from pathlib import Path

import pytest

from gaussianreadpro.core.expressions import (AliasIndex, EnergyContext, ExpressionError,
    compile_expression, composite_gibbs_expression, components_expression, edit_expression,
    evaluate_expression, expression_references, render_expression)
from gaussianreadpro.core.models import (CombinationMode, EnergyKind, EnergyRef,
    ExpressionDocument, ImportState, KindPolicy)
from gaussianreadpro.core.parser import parse_log
from s2_helpers import dataset, expression, identifier


def context(sources, kind=EnergyKind.GIBBS_TOTAL, **options):
    return EnergyContext({s.id: s for s in sources}, kind, **options)


def codes(result):
    return {d.code for d in result.diagnostics}


def test_coefficients_parentheses_and_explicit_energy_offsets():
    sources, refs, aliases = dataset()
    expr = expression("+@{TS1} - (@{R} + 0.5 * 2 * @{A}) + 1[kcal/mol]", aliases)
    result = evaluate_expression(expr, context(sources))
    assert result.valid
    from gaussianreadpro.core.units import HARTREE_TO_KCAL
    assert result.value_hartree == pytest.approx(.024 + 1 / HARTREE_TO_KCAL, abs=1e-12)
    assert {d.source_file_id for d in result.dependencies} == {refs[n].source_file_id for n in ("R", "A", "TS1")}


@pytest.mark.parametrize("text", ["True", "False", "None", "NaN", "Infinity", "__import__('os')",
    "open('file')", "@{R}.__class__", "@{R}[0]", "@{R} ** 2", "@{R}//2", "lambda: 1", "[x for x in y]",
    "@{R}; 1[hartree]", "R", "1e999[hartree]"])
def test_python_or_nonfinite_syntax_is_never_executed(text):
    _, _, aliases = dataset()
    assert not compile_expression(text, aliases).valid


@pytest.mark.parametrize("text,code", [("@{R} * @{A}", "energy_multiplication_forbidden"),
    ("@{R} / @{A}", "energy_divisor_forbidden"), ("@{R} + 1", "dimension_mismatch"),
    ("1 + 2", "energy_expression_required"), ("@{R}/(2-2)", "division_by_zero"),
    ("@{R} + 1[eV]", "unknown_unit"), ("@{R} * (1e308 * 1e308)", "invalid_value_or_arithmetic")])
def test_dimension_and_constant_errors(text, code):
    _, _, aliases = dataset()
    result = compile_expression(text, aliases)
    assert not result.valid and code in codes(result)


def test_unknown_alias_is_exact_and_error_has_position():
    _, _, aliases = dataset()
    result = compile_expression("@{R_missing}", aliases)
    assert not result.valid and "unknown_alias" in codes(result)
    assert result.diagnostics[0].params["start"] == 0
    assert result.diagnostics[0].params["end"] == 12
    with pytest.raises(ValueError):
        AliasIndex.from_pairs([("R", aliases.bindings["R"]), ("R", aliases.bindings["A"])])


def test_same_file_names_are_disambiguated_without_covering_values():
    folder = Path(__file__).parent / "fixtures" / "logs"
    sources = tuple(parse_log(folder / name).source for name in ("目录 A/species.log", "目录 B/species.log"))
    pairs = [(s.display_name, EnergyRef(s.id, s.jobs[0].id)) for s in sources]
    aliases = AliasIndex.with_unique_labels(pairs)
    result = evaluate_expression(expression("@{species} - @{species (2)}", aliases), context(sources, EnergyKind.SCF))
    assert result.valid and result.value_hartree == 1
    safe = AliasIndex.with_unique_labels([("名字 } 空间", pairs[0][1])])
    assert tuple(safe.bindings) == ("species_1",)


def test_rename_changes_rendering_not_bound_reference_or_value():
    sources, refs, aliases = dataset()
    expr = expression("@{TS1} - @{R} - @{A}", aliases)
    renamed = aliases.renamed("R", "反应物-新名字")
    changed_sources = tuple(replace(s, display_name="new") if s.id == refs["R"].source_file_id else s for s in sources)
    before = evaluate_expression(expr, context(sources))
    after = evaluate_expression(expr, context(changed_sources))
    assert before.value_hartree == after.value_hartree
    assert "反应物-新名字" in render_expression(expr, renamed)
    assert refs["R"] in expression_references(expr)
    reparsed = expression(render_expression(expr, renamed), renamed)
    assert evaluate_expression(reparsed, context(sources)).value_hartree == before.value_hartree
    # UUID tokens remain exact and reversible even with no aliases.
    portable = expression(render_expression(expr), AliasIndex())
    assert evaluate_expression(portable, context(sources)).value_hartree == before.value_hartree


@pytest.mark.parametrize("text", ["x" * 8193, "(" * 40 + "@{R}" + ")" * 40,
                                "-" * 40 + "@{R}", "+".join(["@{R}"] * 150)],
                         ids=["length", "parentheses", "unary", "nodes"])
def test_complexity_limits_are_bounded(text):
    _, _, aliases = dataset()
    assert not compile_expression(text, aliases).valid


def test_direct_ast_is_validated_before_freezing_and_rejects_cycles():
    with pytest.raises(ExpressionError):
        ExpressionDocument({"type": "call", "name": "eval"}, "")
    with pytest.raises(ExpressionError):
        ExpressionDocument({"type": "energy_constant", "value": True, "unit": "hartree"}, "")
    cycle = {"type": "unary", "op": "neg"}
    cycle["operand"] = cycle
    with pytest.raises(ExpressionError):
        ExpressionDocument(cycle, "")
    _, refs, _ = dataset()
    from gaussianreadpro.core.expressions import ref_ast
    noncanonical = {**ref_ast(refs["R"]), "source_file_id": refs["R"].source_file_id.upper()}
    with pytest.raises(ExpressionError):
        ExpressionDocument(noncanonical, "")


def test_invalid_draft_never_returns_the_old_value():
    sources, refs, aliases = dataset()
    valid = expression("@{R}", aliases)
    draft = edit_expression(valid, "@{R} + ", aliases)
    assert draft.ast == valid.ast and draft.draft_text == "@{R} + "
    result = evaluate_expression(draft, context(sources))
    assert not result.valid and result.value_hartree is None
    assert "expression_has_invalid_draft" in codes(result)
    repaired = edit_expression(draft, "@{R} + @{A}", aliases)
    assert repaired.draft_error is None and evaluate_expression(repaired, context(sources)).value_hartree == -150
    initial = edit_expression(None, "@{not_found}", aliases)
    assert initial.ast is None and initial.draft_error is not None


@pytest.mark.parametrize("state", [ImportState.MISSING, ImportState.FAILED, ImportState.CANCELLED, ImportState.STALE])
def test_unavailable_sources_never_become_zero(state):
    sources, refs, aliases = dataset()
    unavailable = tuple(replace(s, import_state=state) if s.id == refs["R"].source_file_id else s for s in sources)
    result = evaluate_expression(expression("0 * @{R}", aliases), context(unavailable))
    assert not result.valid and result.value_hartree is None and "source_unavailable" in codes(result)


def test_deleted_or_reparsed_source_never_falls_back_to_another_job():
    sources, refs, aliases = dataset()
    expr = expression("@{R}", aliases)
    assert "source_not_found" in codes(evaluate_expression(expr, context(sources[1:])))
    missing_job = EnergyRef(sources[0].id, identifier("different job"))
    result = evaluate_expression(components_expression([(missing_job, 1)]), context(sources))
    assert not result.valid and "job_not_found" in codes(result)


def test_missing_field_and_standard_mixed_kinds_are_rejected():
    sources, refs, aliases = dataset()
    fixed_scf = EnergyRef(refs["R"].source_file_id, refs["R"].job_id, KindPolicy.FIXED, EnergyKind.SCF)
    mixed = AliasIndex({"E": fixed_scf, "G": refs["R"]})
    result = evaluate_expression(expression("@{E} + @{G}", mixed), context(sources))
    assert not result.valid and "energy_kind_mismatch" in codes(result)
    source = sources[0]
    job = replace(source.jobs[0], energies={EnergyKind.SCF: source.jobs[0].energies[EnergyKind.SCF]})
    result = evaluate_expression(expression("@{R}", aliases), context((replace(source, jobs=(job,)),)))
    assert not result.valid and "missing_energy" in codes(result)


def test_explicit_high_low_composite_template_and_same_low_job_constraint():
    sources, refs, _ = dataset()
    high = EnergyRef(refs["TS1"].source_file_id, refs["TS1"].job_id, KindPolicy.FIXED, EnergyKind.SCF)
    low_g = EnergyRef(refs["R"].source_file_id, refs["R"].job_id, KindPolicy.FIXED, EnergyKind.GIBBS_TOTAL)
    low_e = replace(low_g, kind=EnergyKind.SCF)
    expr = composite_gibbs_expression(high, low_g, low_e)
    result = evaluate_expression(expr, context(sources))
    assert result.valid and result.value_hartree == pytest.approx(-149.976, abs=1e-12)
    assert "composite_gibbs_approximation" in codes(result)
    assert len(result.dependencies) == 3
    assert not evaluate_expression(expr, context(sources, EnergyKind.SCF)).valid
    with pytest.raises(ValueError):
        composite_gibbs_expression(high, low_g, replace(low_e, job_id=identifier("other job")))
    with pytest.raises(ValueError):
        composite_gibbs_expression(refs["TS1"], low_g, low_e)


def test_abnormal_job_requires_explicit_policy_but_unconverged_always_fails():
    path = Path(__file__).parent / "fixtures/logs/last_job_failed.log"
    source = parse_log(path).source
    ref = EnergyRef(source.id, source.jobs[1].id)
    expr = components_expression([(ref, 1)])
    assert not evaluate_expression(expr, context((source,), EnergyKind.SCF)).valid
    allowed = evaluate_expression(expr, context((source,), EnergyKind.SCF, allow_abnormal_jobs=True))
    assert allowed.valid and "job_not_normal" in codes(allowed)
    from gaussianreadpro.core.models import SCFConvergence
    failed = replace(source.jobs[1], scf_convergence=SCFConvergence.FAILED)
    source = replace(source, jobs=(source.jobs[0], failed))
    assert not evaluate_expression(expr, context((source,), EnergyKind.SCF, allow_abnormal_jobs=True)).valid


def test_bad_current_field_is_blocked_while_other_kind_problem_is_a_warning():
    from gaussianreadpro.core.models import Diagnostic, Severity
    sources, refs, aliases = dataset()
    source = sources[0]
    job = replace(source.jobs[0], diagnostics=(Diagnostic("invalid_energy_number", Severity.ERROR,
                                                        {"kind": "gibbs_total"}),))
    source = replace(source, jobs=(job,), import_state=ImportState.PARTIAL)
    assert not evaluate_expression(expression("@{R}", aliases), context((source,))).valid
    assert evaluate_expression(expression("@{R}", aliases), context((source,), EnergyKind.SCF)).valid


def test_resolved_arithmetic_overflow_is_structured():
    sources, _, aliases = dataset()
    result = evaluate_expression(expression("@{R} * 1e308", aliases), context(sources))
    assert not result.valid and result.value_hartree is None
    assert "invalid_value_or_arithmetic" in codes(result)


def test_real_gaussian_sp_and_frequency_composite_reproduces_printed_gibbs():
    folder = Path(__file__).parent / "fixtures/reference"
    high = parse_log(folder / "dvb_sp.out").source
    low = parse_log(folder / "dvb_ir.out").source
    high_e = EnergyRef(high.id, high.jobs[0].id, KindPolicy.FIXED, EnergyKind.SCF)
    low_g = EnergyRef(low.id, low.jobs[0].id, KindPolicy.FIXED, EnergyKind.GIBBS_TOTAL)
    low_e = replace(low_g, kind=EnergyKind.SCF)
    result = evaluate_expression(composite_gibbs_expression(high_e, low_g, low_e), context((high, low)))
    assert result.valid and result.value_hartree == pytest.approx(-382.164914602, abs=1e-12)
    assert {(d.source_file_id, d.source_line) for d in result.dependencies} == {
        (high.id, 3857), (low.id, 457), (low.id, 2057)}
