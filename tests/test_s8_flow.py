"""S8 one-project flow through import, calculation, export, and fresh reopen."""

from dataclasses import replace
import csv
import json

import pytest

from gaussianreadpro.core import EnergyKind
from gaussianreadpro.core.plot_spec import plot_payload
from gaussianreadpro.services.plot_export import export_plot_bundle
from gaussianreadpro.services.session import SessionBackend


def test_s8_continuous_scientific_flow(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    paths = []
    values = (('R', -150.0), ('TS1', -149.976), ('I1', -150.008), ('P', -150.025))
    for name, gibbs in values:
        path = inputs / f"{name}.log"
        path.write_text(
            "SYNTHETIC S8 FLOW\nEntering Gaussian System\n"
            f" SCF Done: E(RB3LYP) = {gibbs - 0.03:.12f} A.U.\n"
            " Thermal correction to Gibbs Free Energy= 0.030000000000\n"
            f" Sum of electronic and thermal Free Energies= {gibbs:.12f}\n"
            " Normal termination of Gaussian 16\n", encoding="utf-8")
        paths.append(path)

    backend = SessionBackend(tmp_path / "recovery", tmp_path / "prefs.ini")
    try:
        project = backend.new().project
        imported = backend.import_files(project, paths, lambda: False, lambda *args: None)
        project = imported.project
        assert len(project.source_files) == len(project.nodes) == 4
        assert all(source.jobs[0].energies[EnergyKind.SCF].source_line == 3
                   for source in project.source_files)
        assert all(source.jobs[0].energies[EnergyKind.GIBBS_CORRECTION].source_line == 4
                   for source in project.source_files)
        path = replace(project.paths[0], reference_expression=project.nodes[0].expression)
        project = replace(project, paths=(path,), revision=project.revision + 1)
        view = backend.update(project)
        assert [point.relative_hartree for point in view.results[0].nodes] == pytest.approx(
            (0, 0.024, -0.008, -0.025), abs=1e-11)
        assert all(len(point.dependencies) >= 2 for point in view.results[0].nodes)

        payload = plot_payload(view.plot_spec, path.id, language="en")
        folder = export_plot_bundle(payload, tmp_path / "export", "html")
        exported = json.loads((folder / "plot.json").read_text(encoding="utf-8"))
        assert exported["paths"] == payload["paths"]
        with (folder / "sources.csv").open(encoding="utf-8-sig", newline="") as stream:
            source_rows = list(csv.DictReader(stream))
        assert source_rows and all(row.get("Source line") for row in source_rows)
        saved = backend.save(project, tmp_path / "study.grproj")
        project = saved.project
        project_id, node_ids = project.id, tuple(node.id for node in project.nodes)
    finally:
        backend.shutdown()

    fresh = SessionBackend(tmp_path / "fresh-recovery", tmp_path / "fresh-prefs.ini")
    try:
        reopened = fresh.open(tmp_path / "study.grproj", ignore_recovery=True)
        assert reopened.project.id == project_id
        assert tuple(node.id for node in reopened.project.nodes) == node_ids
        assert reopened.project.paths[0].reference_expression == project.paths[0].reference_expression
        assert [point.relative_hartree for point in reopened.results[0].nodes] == pytest.approx(
            (0, 0.024, -0.008, -0.025), abs=1e-11)
        assert reopened.plot_spec.project_id == project_id
    finally:
        fresh.shutdown()
