"""Immutable, provenance-aware snapshots for parsing and later calculations."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4


class EnergyKind(StrEnum):
    SCF = "scf"
    GIBBS_CORRECTION = "gibbs_correction"
    GIBBS_TOTAL = "gibbs_total"


class Unit(StrEnum):
    HARTREE = "hartree"
    KCAL_MOL = "kcal_mol"
    KJ_MOL = "kj_mol"


class ImportState(StrEnum):
    PENDING = "pending"
    READING = "reading"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STALE = "stale"
    MISSING = "missing"


class Termination(StrEnum):
    NORMAL = "normal"
    ERROR = "error"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


class SCFConvergence(StrEnum):
    CONVERGED = "converged"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class KindPolicy(StrEnum):
    FIXED = "fixed"
    FOLLOW_PATH = "follow_path"


class SelectionPolicy(StrEnum):
    LAST_NORMAL_WITH_ENERGY = "last_normal_with_energy"


class ExpressionPurpose(StrEnum):
    SYSTEM = "system"
    DIFFERENCE = "difference"


class CombinationMode(StrEnum):
    STANDARD = "standard"
    COMPOSITE_GIBBS = "composite_gibbs"


class CalculationMode(StrEnum):
    RELATIVE = "relative"
    ABSOLUTE = "absolute"
    DIRECT_DIFFERENCE = "direct_difference"


class NodeRole(StrEnum):
    REACTANT = "reactant"
    INTERMEDIATE = "intermediate"
    TRANSITION_STATE = "transition_state"
    PRODUCT = "product"
    UNSPECIFIED = "unspecified"


def canonical_uuid(value: str | UUID) -> str:
    return str(UUID(str(value)))


def new_id() -> str:
    return str(uuid4())


def finite_number(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("Expected an int or float, excluding bool")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError("Numeric value overflows a float") from exc
    if not math.isfinite(result):
        raise ValueError("Numeric values must be finite")
    return result


def _integer(value, minimum, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity = Severity.WARNING
    params: Mapping = field(default_factory=dict)
    source_line: int | None = None

    def __post_init__(self):
        if not self.code:
            raise ValueError("Diagnostic requires a code")
        if self.source_line is not None:
            _integer(self.source_line, 1, "source_line")
        object.__setattr__(self, "severity", Severity(self.severity))
        object.__setattr__(self, "params", _freeze(self.params))


@dataclass(frozen=True, slots=True)
class EnergyValue:
    kind: EnergyKind
    value_hartree: float
    raw_text: str
    source_line: int
    job_id: str

    def __post_init__(self):
        object.__setattr__(self, "kind", EnergyKind(self.kind))
        object.__setattr__(self, "value_hartree", finite_number(self.value_hartree))
        object.__setattr__(self, "job_id", canonical_uuid(self.job_id))
        _integer(self.source_line, 1, "source_line")
        if not self.raw_text:
            raise ValueError("Energy must retain its original value text and source line")


@dataclass(frozen=True, slots=True)
class JobMetadata:
    route: str | None = None
    method: str | None = None
    basis_set: str | None = None
    scf_method_label: str | None = None
    temperature_kelvin: float | None = None
    pressure_atm: float | None = None
    charge: int | None = None
    multiplicity: int | None = None
    solvent: str | None = None
    source_lines: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("temperature_kelvin", "pressure_atm"):
            value = getattr(self, name)
            if value is not None:
                value = finite_number(value)
                if value <= 0:
                    raise ValueError(f"{name} must be positive")
                object.__setattr__(self, name, value)
        if self.charge is not None and (isinstance(self.charge, bool) or not isinstance(self.charge, int)):
            raise TypeError("Charge must be an integer")
        if self.multiplicity is not None and (isinstance(self.multiplicity, bool)
                                             or not isinstance(self.multiplicity, int) or self.multiplicity < 1):
            raise ValueError("Multiplicity must be a positive integer")
        if any(not isinstance(line, int) or isinstance(line, bool) or line < 1
               for line in self.source_lines.values()):
            raise ValueError("Metadata source lines must be positive integers")
        object.__setattr__(self, "source_lines", _freeze(self.source_lines))


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    source_file_id: str
    ordinal: int
    start_line: int
    end_line: int
    termination: Termination
    scf_convergence: SCFConvergence
    metadata: JobMetadata = field(default_factory=JobMetadata)
    energies: Mapping[EnergyKind, EnergyValue] = field(default_factory=dict)
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "id", canonical_uuid(self.id))
        object.__setattr__(self, "source_file_id", canonical_uuid(self.source_file_id))
        object.__setattr__(self, "termination", Termination(self.termination))
        object.__setattr__(self, "scf_convergence", SCFConvergence(self.scf_convergence))
        _integer(self.ordinal, 0, "ordinal")
        _integer(self.start_line, 1, "start_line")
        _integer(self.end_line, self.start_line, "end_line")
        energies = {EnergyKind(kind): value for kind, value in self.energies.items()}
        for kind, value in energies.items():
            if value.job_id != self.id or value.kind != kind or not self.start_line <= value.source_line <= self.end_line:
                raise ValueError("Energy provenance does not belong to this job")
        object.__setattr__(self, "energies", _freeze(energies))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@dataclass(frozen=True, slots=True)
class SourceFile:
    id: str
    original_name: str
    display_name: str
    original_path: str
    size_bytes: int | None
    mtime_ns: int | None
    relative_path: str | None = None
    sha256: str | None = None
    parser_version: str | None = None
    import_state: ImportState = ImportState.PENDING
    jobs: tuple[JobRecord, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "id", canonical_uuid(self.id))
        object.__setattr__(self, "import_state", ImportState(self.import_state))
        object.__setattr__(self, "jobs", tuple(self.jobs))
        if self.size_bytes is not None:
            _integer(self.size_bytes, 0, "size_bytes")
        if self.sha256 is not None and (len(self.sha256) != 64
                                        or any(c not in "0123456789abcdef" for c in self.sha256)):
            raise ValueError("Expected lowercase SHA256")
        for index, job in enumerate(self.jobs):
            if job.source_file_id != self.id or job.ordinal != index:
                raise ValueError("Job identity/ordinal does not belong to this source")
            if index and self.jobs[index - 1].end_line >= job.start_line:
                raise ValueError("Jobs must have disjoint, increasing source ranges")
        if len({j.id for j in self.jobs}) != len(self.jobs):
            raise ValueError("Job IDs must be unique within a source")


@dataclass(frozen=True, slots=True)
class ParseResult:
    source: SourceFile
    diagnostics: tuple[Diagnostic, ...] = ()
    lines_read: int = 0
    bytes_read: int = 0

    def __post_init__(self):
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        _integer(self.lines_read, 0, "lines_read")
        _integer(self.bytes_read, 0, "bytes_read")


@dataclass(frozen=True, slots=True)
class JobSelection:
    job: JobRecord | None
    energy: EnergyValue | None
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if self.energy is not None and (self.job is None or self.energy.job_id != self.job.id):
            raise ValueError("Selected energy must belong to the selected job")

    @property
    def available(self) -> bool:
        return self.energy is not None


@dataclass(frozen=True, slots=True)
class EnergyRef:
    source_file_id: str
    job_id: str
    kind_policy: KindPolicy = KindPolicy.FOLLOW_PATH
    kind: EnergyKind | None = None

    def __post_init__(self):
        object.__setattr__(self, "source_file_id", canonical_uuid(self.source_file_id))
        object.__setattr__(self, "job_id", canonical_uuid(self.job_id))
        object.__setattr__(self, "kind_policy", KindPolicy(self.kind_policy))
        if self.kind_policy == KindPolicy.FIXED:
            if self.kind is None:
                raise ValueError("Fixed reference requires energy kind")
            object.__setattr__(self, "kind", EnergyKind(self.kind))
        elif self.kind is not None:
            raise ValueError("Follow-path reference must not fix a kind")


@dataclass(frozen=True, slots=True)
class ExpressionDocument:
    ast: Mapping | None
    display_text: str
    format_version: int = 1
    purpose: ExpressionPurpose = ExpressionPurpose.SYSTEM
    combination_mode: CombinationMode = CombinationMode.STANDARD
    draft_text: str | None = None
    draft_error: Diagnostic | None = None

    def __post_init__(self):
        _integer(self.format_version, 1, "format_version")
        if self.format_version != 1:
            raise ValueError("Unsupported expression format")
        object.__setattr__(self, "purpose", ExpressionPurpose(self.purpose))
        object.__setattr__(self, "combination_mode", CombinationMode(self.combination_mode))
        if not isinstance(self.display_text, str) or len(self.display_text) > 65536:
            raise ValueError("Invalid expression display text")
        if self.draft_text is not None and (not isinstance(self.draft_text, str) or len(self.draft_text) > 65536):
            raise ValueError("Draft exceeds supported size")
        if self.draft_error is not None and (not isinstance(self.draft_error, Diagnostic)
                                             or self.draft_text is None):
            raise ValueError("Draft error requires a draft and Diagnostic")
        if self.ast is None and self.draft_error is None:
            raise ValueError("Expression needs a valid tree or an invalid draft")
        if self.ast is not None:
            from .expressions import validate_ast
            validate_ast(self.ast)
            object.__setattr__(self, "ast", _freeze(self.ast))


@dataclass(frozen=True, slots=True)
class CompileResult:
    expression: ExpressionDocument | None
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def valid(self):
        return self.expression is not None and self.expression.draft_error is None


@dataclass(frozen=True, slots=True)
class EnergyDependency:
    source_file_id: str
    job_id: str
    kind: EnergyKind
    source_line: int
    value_hartree: float
    source_label: str
    source_sha256: str | None
    metadata: JobMetadata


@dataclass(frozen=True, slots=True)
class ExpressionResult:
    value_hartree: float | None
    dependencies: tuple[EnergyDependency, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def valid(self):
        return self.value_hartree is not None and not any(d.severity == Severity.ERROR for d in self.diagnostics)


@dataclass(frozen=True, slots=True)
class ProfileNode:
    id: str
    label: str
    expression: ExpressionDocument
    role: NodeRole = NodeRole.UNSPECIFIED
    display: Mapping = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "id", canonical_uuid(self.id))
        object.__setattr__(self, "role", NodeRole(self.role))
        if not isinstance(self.expression, ExpressionDocument) or not isinstance(self.label, str):
            raise TypeError("Node requires expression and label")
        object.__setattr__(self, "display", _freeze(self.display))


@dataclass(frozen=True, slots=True)
class PathEntry:
    id: str
    node_id: str
    position: int
    display_override: Mapping = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "id", canonical_uuid(self.id))
        object.__setattr__(self, "node_id", canonical_uuid(self.node_id))
        _integer(self.position, 0, "position")
        object.__setattr__(self, "display_override", _freeze(self.display_override))


@dataclass(frozen=True, slots=True)
class ReactionPath:
    id: str
    label: str
    entries: tuple[PathEntry, ...]
    energy_kind: EnergyKind = EnergyKind.GIBBS_TOTAL
    reference_expression: ExpressionDocument | None = None
    calculation_mode: CalculationMode = CalculationMode.RELATIVE
    unit: Unit = Unit.KCAL_MOL
    color: str = "#5367b8"
    visible: bool = True

    def __post_init__(self):
        object.__setattr__(self, "id", canonical_uuid(self.id))
        object.__setattr__(self, "energy_kind", EnergyKind(self.energy_kind))
        object.__setattr__(self, "calculation_mode", CalculationMode(self.calculation_mode))
        object.__setattr__(self, "unit", Unit(self.unit))
        entries = tuple(sorted(self.entries, key=lambda e: e.position))
        if [e.position for e in entries] != list(range(len(entries))):
            raise ValueError("Path positions must be a contiguous permutation from zero")
        if len({e.id for e in entries}) != len(entries):
            raise ValueError("Path entry IDs must be unique")
        object.__setattr__(self, "entries", entries)
        if self.calculation_mode != CalculationMode.RELATIVE and self.reference_expression is not None:
            raise ValueError("Only relative mode may have a reference")
        if (self.reference_expression is not None
                and self.reference_expression.purpose != ExpressionPurpose.SYSTEM):
            raise ValueError("Reference must represent a system energy")
        # Missing reference in relative mode can be an unfinished, savable project.
        # Calculation reports it as invalid instead of silently showing absolute values.


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    source_files: tuple[SourceFile, ...] = ()
    nodes: tuple[ProfileNode, ...] = ()
    paths: tuple[ReactionPath, ...] = ()
    schema_version: int = 1
    revision: int = 0
    unit_constants_version: str = "codata_2022_thermochemical_calorie_v1"
    plot_state: Mapping = field(default_factory=dict)
    workspace_state: Mapping = field(default_factory=dict)
    alias_bindings: Mapping[str, EnergyRef] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "id", canonical_uuid(self.id))
        _integer(self.schema_version, 1, "schema_version")
        _integer(self.revision, 0, "revision")
        if self.schema_version != 1:
            raise ValueError("Unsupported project schema")
        for name in ("source_files", "nodes", "paths"):
            items = tuple(getattr(self, name))
            if len({item.id for item in items}) != len(items):
                raise ValueError(f"Duplicate identity in {name}")
            object.__setattr__(self, name, items)
        node_ids = {node.id for node in self.nodes}
        entry_ids = []
        for path in self.paths:
            if any(entry.node_id not in node_ids for entry in path.entries):
                raise ValueError("Path refers to a missing node")
            entry_ids.extend(entry.id for entry in path.entries)
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("Entry IDs must be unique across paths")
        object.__setattr__(self, "plot_state", _freeze(self.plot_state))
        object.__setattr__(self, "workspace_state", _freeze(self.workspace_state))
        from .expressions import AliasIndex
        object.__setattr__(self, "alias_bindings", AliasIndex(self.alias_bindings).bindings)


@dataclass(frozen=True, slots=True)
class NodeResult:
    entry_id: str
    node_id: str
    absolute_hartree: float | None
    reference_hartree: float | None
    relative_hartree: float | None
    display_value: float | None
    unit: Unit
    dependencies: tuple[EnergyDependency, ...]
    reference_dependencies: tuple[EnergyDependency, ...]
    diagnostics: tuple[Diagnostic, ...]
    valid: bool
    revision: int


@dataclass(frozen=True, slots=True)
class PathResult:
    project_id: str
    path_id: str
    revision: int
    calculation_mode: CalculationMode
    energy_kind: EnergyKind
    unit: Unit
    unit_constants_version: str
    reference_hartree: float | None
    nodes: tuple[NodeResult, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def valid(self):
        return (bool(self.nodes) and all(node.valid for node in self.nodes)
                and not any(d.severity == Severity.ERROR for d in self.diagnostics))


def snapshot_to_dict(value):
    """JSON-compatible projection without mutating/copying Qt or storage objects."""
    if is_dataclass(value):
        return {f.name: snapshot_to_dict(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): snapshot_to_dict(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [snapshot_to_dict(v) for v in value]
    if isinstance(value, StrEnum):
        return value.value
    return value
