"""Explicit synthetic scientific values for S2; not parsed Gaussian output."""
from uuid import NAMESPACE_URL, uuid5

from gaussianreadpro.core.expressions import AliasIndex, compile_expression
from gaussianreadpro.core.models import (CalculationMode, EnergyKind, EnergyRef, EnergyValue,
    ImportState, JobMetadata, JobRecord, PathEntry, ProfileNode, Project,
    ReactionPath, SCFConvergence, SourceFile, Termination)


def identifier(label):
    return str(uuid5(NAMESPACE_URL, "gaussianreadpro-s2-test:" + label))


def source(label, energy, **conditions):
    source_id, job_id = identifier(label), identifier(label + ":job")
    metadata = JobMetadata(**{"method": "B3LYP", "basis_set": "def2-SVP", "temperature_kelvin": 298.15,
                             "pressure_atm": 1, "solvent": "gas", **conditions})
    values = {EnergyKind.SCF: energy - .03, EnergyKind.GIBBS_CORRECTION: .03, EnergyKind.GIBBS_TOTAL: energy}
    energies = {kind: EnergyValue(kind, value, repr(value), line, job_id)
                for line, (kind, value) in enumerate(values.items(), 2)}
    job = JobRecord(job_id, source_id, 0, 1, 5, Termination.NORMAL, SCFConvergence.CONVERGED,
                    metadata, energies)
    return SourceFile(source_id, label + ".log", label, "/synthetic/" + label + ".log", 100, 0,
                      import_state=ImportState.READY, jobs=(job,))


def dataset():
    energies = {"R": -100., "A": -50., "TS1": -149.976, "I1": -140., "B": -10.008, "P": -150.025}
    sources = tuple(source(name, value) for name, value in energies.items())
    refs = {s.display_name: EnergyRef(s.id, s.jobs[0].id) for s in sources}
    return sources, refs, AliasIndex(refs)


def expression(text, aliases, **options):
    result = compile_expression(text, aliases, **options)
    assert result.valid, result.diagnostics
    return result.expression


def project():
    sources, refs, aliases = dataset()
    labels = ("R + A", "TS1", "I1 + B", "P")
    texts = ("@{R} + @{A}", "@{TS1}", "@{I1} + @{B}", "@{P}")
    nodes = tuple(ProfileNode(identifier("node:" + label), label, expression(text, aliases))
                  for label, text in zip(labels, texts))
    entries = tuple(PathEntry(identifier("entry:" + node.label), node.id, i) for i, node in enumerate(nodes))
    path = ReactionPath(identifier("path"), "Reaction", entries,
                        reference_expression=expression("@{R} + @{A}", aliases),
                        calculation_mode=CalculationMode.RELATIVE)
    return Project(identifier("project"), sources, nodes, (path,), alias_bindings=aliases.bindings), refs, aliases
