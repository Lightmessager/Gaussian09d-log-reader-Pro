"""Build and verify the marked RF0 synthetic two-path project fixture."""
from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path

from gaussianreadpro.core import EnergyKind, Unit
from gaussianreadpro.core.models import PathEntry, Project, ReactionPath, new_id
from gaussianreadpro.core.units import HARTREE_TO_KCAL
from gaussianreadpro.services.session import SessionBackend, import_into
from gaussianreadpro.storage import ProjectRepository


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "profile_replica"
OUTPUT = ROOT / "artifacts" / "rf0" / "profile-replica.grproj"
NODES = ("R", "TS1", "I1", "P")
TARGETS = {
    "A": (Decimal("0"), Decimal("15.060"), Decimal("-5.020"), Decimal("-15.688")),
    "B": (Decimal("0"), Decimal("11.420"), Decimal("-2.800"), Decimal("-12.400")),
}


def write_synthetic_logs():
    for path_label, targets in TARGETS.items():
        folder = FIXTURE / f"Path-{path_label}"
        folder.mkdir(parents=True, exist_ok=True)
        for node, kcal in zip(NODES, targets):
            absolute = Decimal("-150") + kcal / Decimal(str(HARTREE_TO_KCAL))
            content = (
                f"SYNTHETIC RF0 FIXTURE — Path {path_label} / {node}\n"
                "Entering Gaussian System\n"
                f" SCF Done: E(RB3LYP) = {absolute - Decimal('0.030'):.12f} A.U.\n"
                f" Sum of electronic and thermal Free Energies= {absolute:.12f}\n"
                " Normal termination of Gaussian 16\n"
            )
            (folder / f"{node}.log").write_text(content, encoding="utf-8")


def main():
    if OUTPUT.exists():
        with ProjectRepository(OUTPUT, read_only=True) as repository:
            existing = repository.load()
        print(f"Using existing synthetic fixture: {OUTPUT} ({len(existing.nodes)} nodes)")
        return
    write_synthetic_logs()
    project, _ = import_into(
        Project(new_id()),
        [FIXTURE / f"Path-{path}" / f"{node}.log" for path in ("A", "B") for node in NODES],
        lambda: False,
        lambda *_: None,
    )
    # Source order, not source labels, defines each independent four-node path.
    ordered_nodes = project.nodes
    paths = []
    renamed_by_path = {}
    for path_index, path_label in enumerate(("A", "B")):
        path_nodes = ordered_nodes[path_index * 4:(path_index + 1) * 4]
        renamed_nodes = [replace(node, label=label) for node, label in zip(path_nodes, NODES)]
        renamed_by_path[path_label] = renamed_nodes
        entries = tuple(PathEntry(new_id(), node.id, index) for index, node in enumerate(renamed_nodes))
        paths.append(ReactionPath(
            id=project.paths[0].id if path_index == 0 else new_id(),
            label=f"Path {path_label}",
            entries=entries,
            energy_kind=EnergyKind.GIBBS_TOTAL,
            reference_expression=renamed_by_path.get("A", renamed_nodes)[0].expression,
            unit=Unit.KCAL_MOL,
            color="#AD83FF" if path_label == "A" else "#FFA96C",
        ))
    project = replace(project, nodes=tuple(n for path in renamed_by_path.values() for n in path),
                      paths=tuple(paths), revision=project.revision + 1,
                      workspace_state={"path_id": paths[0].id, "node_id": paths[0].entries[1].node_id,
                                       "page": 2, "view": "3d", "language": "en", "theme": "dark"})
    backend = SessionBackend(ROOT / "artifacts" / "rf0" / "recovery")
    view = backend.view(project)
    expected = {key: [float(value) for value in values] for key, values in TARGETS.items()}
    actual = {path.label[-1]: [round(node.display_value, 3) if node.valid else None for node in result.nodes]
              for path, result in zip(project.paths, view.results)}
    if actual != expected:
        raise SystemExit(f"Fixture oracle mismatch: expected={expected}, actual={actual}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ProjectRepository(OUTPUT, create=True) as repository:
        repository.save(project)
    backend.shutdown()
    (OUTPUT.parent / "fixture-validation.json").write_text(json.dumps({
        "synthetic": True,
        "project": str(OUTPUT.relative_to(ROOT)),
        "node_ids_unique": len({node.id for node in project.nodes}) == 8,
        "display_values_kcal_mol": actual,
        "reference_ids": {path.label: path.entries[0].node_id for path in project.paths},
        "unit_constants_version": project.unit_constants_version,
    }, indent=2), encoding="utf-8")
    print(json.dumps(actual, indent=2))


if __name__ == "__main__":
    main()
