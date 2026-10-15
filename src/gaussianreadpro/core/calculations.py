"""Path computation: preserve absolute system energy, apply one explicit reference."""
from __future__ import annotations

from .expressions import EnergyContext, evaluate_expression, unique_diagnostics
from .models import (CalculationMode, Diagnostic, EnergyKind, ExpressionPurpose, ExpressionResult,
                     NodeResult, PathResult, Project, Severity, canonical_uuid, finite_number)
from .units import CONSTANTS_VERSION, from_hartree


def _conditions(dependencies, energy_kind):
    diagnostics = []
    fields = ["method", "basis_set", "solvent"]
    if energy_kind != EnergyKind.SCF:
        fields += ["temperature_kelvin", "pressure_atm"]
    missing = []
    for field in fields:
        known, absent = {}, []
        for dep in dependencies:
            value = getattr(dep.metadata, field)
            if value is None:
                absent.append(dep.source_file_id)
            else:
                normalized = value.casefold() if isinstance(value, str) else value
                known.setdefault(normalized, []).append(dep.source_file_id)
        if len(known) > 1:
            diagnostics.append(Diagnostic("inconsistent_conditions", Severity.WARNING,
                                          {"field": field, "values": list(known), "source_ids": list(known.values())}))
        if absent:
            missing.append({"field": field, "source_ids": sorted(set(absent))})
    if missing:
        diagnostics.append(Diagnostic("conditions_not_fully_identified", Severity.INFO, {"missing": missing}))
    return tuple(diagnostics)


def calculate_path(project: Project, path_id, *, allow_abnormal_jobs=False):
    path_id = canonical_uuid(path_id)
    path = next((path for path in project.paths if path.id == path_id), None)
    if path is None:
        raise ValueError("Path does not belong to project")
    context = EnergyContext({source.id: source for source in project.source_files}, path.energy_kind, allow_abnormal_jobs)
    nodes = {node.id: node for node in project.nodes}
    common = []
    if project.unit_constants_version != CONSTANTS_VERSION:
        common.append(Diagnostic("unsupported_unit_constants_version", Severity.ERROR,
                                 {"version": project.unit_constants_version}))
    reference = ExpressionResult(None)
    if path.calculation_mode == CalculationMode.RELATIVE:
        if path.reference_expression is None:
            common.append(Diagnostic("reference_required", Severity.ERROR))
        else:
            reference = evaluate_expression(path.reference_expression, context)
            common.extend(reference.diagnostics)
    if not path.entries:
        common.append(Diagnostic("empty_path", Severity.ERROR))
    results, all_dependencies = [], list(reference.dependencies)
    for entry in path.entries:
        node = nodes[entry.node_id]
        evaluated = evaluate_expression(node.expression, context)
        diagnostics = list(common) + list(evaluated.diagnostics)
        expected = (ExpressionPurpose.DIFFERENCE if path.calculation_mode == CalculationMode.DIRECT_DIFFERENCE
                    else ExpressionPurpose.SYSTEM)
        if node.expression.purpose != expected:
            diagnostics.append(Diagnostic("expression_purpose_mismatch", Severity.ERROR,
                                          {"expected": expected.value, "actual": node.expression.purpose.value}))
        absolute = (evaluated.value_hartree if node.expression.purpose == ExpressionPurpose.SYSTEM
                    and path.calculation_mode != CalculationMode.DIRECT_DIFFERENCE else None)
        relative, display = None, None
        valid = evaluated.valid and not any(d.severity == Severity.ERROR for d in diagnostics)
        if path.calculation_mode == CalculationMode.RELATIVE and not reference.valid:
            valid = False
            diagnostics.append(Diagnostic("reference_unavailable", Severity.ERROR))
        if valid:
            try:
                if path.calculation_mode == CalculationMode.RELATIVE:
                    relative = finite_number(absolute - reference.value_hartree)
                    shown = relative
                elif path.calculation_mode == CalculationMode.DIRECT_DIFFERENCE:
                    relative = evaluated.value_hartree
                    shown = relative
                else:
                    shown = absolute
                display = from_hartree(shown, path.unit)
            except (ValueError, OverflowError):
                valid, relative, display = False, None, None
                diagnostics.append(Diagnostic("path_arithmetic_overflow", Severity.ERROR))
        all_dependencies.extend(evaluated.dependencies)
        results.append(NodeResult(entry.id, node.id, absolute, reference.value_hartree, relative, display,
                                  path.unit, evaluated.dependencies, reference.dependencies,
                                  unique_diagnostics(diagnostics), valid, project.revision))
    common.extend(_conditions(all_dependencies, path.energy_kind))
    # Condition warnings are path-level, not silently copied into every numeric cell.
    return PathResult(project.id, path.id, project.revision, path.calculation_mode, path.energy_kind,
                      path.unit, project.unit_constants_version, reference.value_hartree,
                      tuple(results), unique_diagnostics(common))
