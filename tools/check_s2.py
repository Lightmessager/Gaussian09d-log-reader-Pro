"""Reproducible S2 end-to-end demo with explicit synthetic Gaussian inputs."""
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gaussianreadpro.core import (AliasIndex, CalculationMode, EnergyKind, EnergyRef,
    ExpressionPurpose, PathEntry, ProfileNode, Project, ReactionPath, Unit,
    calculate_path, compile_expression, parse_log)
from gaussianreadpro.core.models import snapshot_to_dict
from gaussianreadpro.core.project_edits import add_component_to_nodes, set_reference_for_paths


def identifier(label):
    return str(uuid5(NAMESPACE_URL, "gaussianreadpro-s2-demo:" + label))


def main():
    out = ROOT / "artifacts/s2"
    logs = out / "demo-logs"
    logs.mkdir(parents=True, exist_ok=True)
    # Manual oracle: component system energies, all Hartree.
    values = {"R": -100.0, "A": -50.0, "TS1": -149.976,
              "I1": -140.0, "B": -10.008, "P": -150.025}
    sources = []
    for label, energy in values.items():
        path = logs / (label + ".log")
        path.write_text("SYNTHETIC S2 DEMO - not real Gaussian output\nEntering Gaussian System\n"
                        " #p B3LYP/def2-SVP opt freq\n ---------------------\n"
                        f" SCF Done: E(RB3LYP) = {energy - .03:.12f} A.U.\n"
                        " Temperature 298.150 Kelvin. Pressure 1.00000 Atm.\n"
                        " Thermal correction to Gibbs Free Energy= 0.030000000000\n"
                        f" Sum of electronic and thermal Free Energies= {energy:.12f}\n"
                        " Normal termination of Gaussian 16\n", encoding="utf-8")
        sources.append(parse_log(path, identifier("source:" + label)).source)
    aliases = AliasIndex({s.display_name: EnergyRef(s.id, s.jobs[0].id) for s in sources})
    def compiled(text, **options):
        result = compile_expression(text, aliases, **options)
        assert result.valid, result.diagnostics
        return result.expression
    labels = ("R + A", "TS1", "I1 + B", "P")
    texts = ("@{R} + @{A}", "@{TS1}", "@{I1} + @{B}", "@{P}")
    nodes = tuple(ProfileNode(identifier("node:" + label), label, compiled(text)) for label, text in zip(labels, texts))
    entries = tuple(PathEntry(identifier("entry:" + str(i)), node.id, i) for i, node in enumerate(nodes))
    path = ReactionPath(identifier("path"), "Synthetic reaction", entries,
                         reference_expression=compiled("@{R} + @{A}"))
    project = Project(identifier("project"), tuple(sources), nodes, (path,), alias_bindings=aliases.bindings)
    start = perf_counter()
    result = calculate_path(project, path.id)
    expected = [0.0, .024, -.008, -.025]
    assert result.valid
    assert all(abs(node.relative_hartree - value) < 1e-12 for node, value in zip(result.nodes, expected))
    delta = ProfileNode(identifier("delta-node"), "Direct difference",
                        compiled("@{TS1} - (@{R} + @{A})", purpose=ExpressionPurpose.DIFFERENCE))
    direct = ReactionPath(identifier("direct-path"), "Direct difference",
                           (PathEntry(identifier("direct-entry"), delta.id, 0),),
                           calculation_mode=CalculationMode.DIRECT_DIFFERENCE)
    expanded = replace(project, nodes=project.nodes + (delta,), paths=project.paths + (direct,))
    direct_result = calculate_path(expanded, direct.id)
    assert direct_result.valid and direct_result.nodes[0].display_value == result.nodes[1].display_value
    kj_path = replace(path, unit=Unit.KJ_MOL)
    kj_result = calculate_path(replace(project, paths=(kj_path,)), kj_path.id)
    preview = add_component_to_nodes(project, [nodes[1].id], aliases.bindings["B"], .5, aliases)
    reference_preview = set_reference_for_paths(project, [path.id], compiled("@{P}"))
    assert preview.calculate_preview()[0].valid and reference_preview.calculate_preview()[0].valid
    assert project.revision == 0 and preview.project.revision == 1
    many_nodes = tuple(replace(nodes[1], id=identifier("many-node:" + str(i)), label=f"Node {i}") for i in range(100))
    many_path = replace(path, entries=tuple(PathEntry(identifier("many-entry:" + str(i)), node.id, i)
                                          for i, node in enumerate(many_nodes)))
    many_project = replace(project, nodes=many_nodes, paths=(many_path,))
    many_start = perf_counter()
    many_result = calculate_path(many_project, many_path.id)
    many_elapsed_ms = (perf_counter() - many_start) * 1000
    assert many_result.valid and len(many_result.nodes) == 100
    report = {"stage": "S2", "passed": True, "data_kind": "synthetic demo only",
              "elapsed_ms": (perf_counter() - start) * 1000,
              "hundred_node_calculation_ms": many_elapsed_ms,
              "expected_relative_hartree": expected,
              "relative_path": snapshot_to_dict(result), "direct_difference": snapshot_to_dict(direct_result),
              "kj_path": snapshot_to_dict(kj_result),
              "component_preview": snapshot_to_dict(preview.calculate_preview()[0]),
              "reference_preview": snapshot_to_dict(reference_preview.calculate_preview()[0])}
    (out / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    (out / "project-snapshot.json").write_text(json.dumps(snapshot_to_dict(project), indent=2,
                                                          ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(json.dumps({"passed": True, "relative_hartree": [n.relative_hartree for n in result.nodes],
                      "relative_kcal_mol": [n.display_value for n in result.nodes],
                      "direct_difference_matches": True, "elapsed_ms": report["elapsed_ms"],
                      "hundred_node_calculation_ms": many_elapsed_ms,
                      "report": str(out / "validation.json")}, indent=2))


if __name__ == "__main__":
    main()
