"""Streaming Gaussian SCF/Gibbs parser with explicit job and line provenance.

Ordinary internal links and optimization cycles stay in the same job. Runtime
Link1 step notices, fresh Gaussian startup and terminal records delimit jobs.
This is not a general correlated/composite-energy or molecular validation tool.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid5

from .models import (Diagnostic, EnergyKind, EnergyValue, ImportState, JobMetadata,
                     JobRecord, JobSelection, ParseResult, SCFConvergence, SelectionPolicy,
                     Severity, SourceFile, Termination, canonical_uuid, new_id)

PARSER_VERSION = "gaussian_scf_gibbs_v1"
MAX_DIAGNOSTICS = 64
MAX_ROUTE_CHARS = 8192
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?\Z")
SCF = re.compile(r"SCF Done:\s*E\(([^)]+)\)\s*=\s*(\S*)", re.I)
GIBBS_CORRECTION = re.compile(r"Thermal correction to Gibbs Free Energy\s*=\s*(\S*)", re.I)
GIBBS_TOTAL = re.compile(r"Sum of electronic and thermal Free Energies\s*=\s*(\S*)", re.I)
START = re.compile(r"^\s*Entering Gaussian System\b", re.I)
INTERNAL_LINK = re.compile(r"^\s*Entering Link 1\s*=", re.I)
NEXT_STEP = re.compile(r"^\s*Link1:\s*Proceeding to internal job step number\s+\d+", re.I)
NORMAL = re.compile(r"^\s*Normal termination of Gaussian\b", re.I)
ERROR = re.compile(r"^\s*Error termination\b", re.I)
CONVERGENCE_FAILURE = re.compile(r"Convergence failure|SCF has not converged|SCF failed to converge", re.I)
TEMPERATURE = re.compile(r"Temperature\s+(\S+)\s+Kelvin\.\s+Pressure\s+(\S+)\s+Atm\.", re.I)
CHARGE = re.compile(r"Charge\s*=\s*([+-]?\d+)\s+Multiplicity\s*=\s*(\d+)", re.I)
BASIS = re.compile(r"Standard basis:\s*(.+?)(?:\s+\(|$)", re.I)
SOLVENT = re.compile(r"Solvent\s*:\s*([^,]+)", re.I)
ROUTE_METHOD = re.compile(r"([A-Za-z][\w+,-]*(?:\([^()]*\))?)/([^\s]+)\Z")


class _Cancelled(Exception):
    pass


class _Diagnostics:
    def __init__(self):
        self.items = []
        self.omitted = 0

    def add(self, code, severity=Severity.WARNING, params=None, line=None):
        if len(self.items) < MAX_DIAGNOSTICS - 1:
            self.items.append(Diagnostic(code, severity, params or {}, line))
        else:
            self.omitted += 1

    def snapshot(self):
        extra = ((Diagnostic("diagnostics_truncated", Severity.WARNING, {"omitted": self.omitted}),)
                 if self.omitted else ())
        return tuple(self.items) + extra


@dataclass
class _Line:
    number: int
    text: str | None
    digest: bytes
    issue: str | None = None


class _Stream:
    def __init__(self, cancel, max_line_bytes, read_chunk_bytes):
        self.cancel = cancel
        self.max_line_bytes = max_line_bytes
        self.read_chunk_bytes = read_chunk_bytes
        self.digest = hashlib.sha256()
        self.bytes_read = 0
        self.lines_read = 0

    def lines(self, handle) -> Iterator[_Line]:
        buffer = bytearray()
        line_digest = hashlib.sha256()
        length = 0
        while True:
            if self.cancel():
                raise _Cancelled
            chunk = handle.readline(self.read_chunk_bytes)
            if not chunk:
                if length:
                    yield self._decode(buffer, length, line_digest)
                return
            self.bytes_read += len(chunk)
            self.digest.update(chunk)
            line_digest.update(chunk)
            length += len(chunk)
            if length <= self.max_line_bytes:
                buffer.extend(chunk)
            else:
                buffer.clear()
            if chunk.endswith(b"\n"):
                yield self._decode(buffer, length, line_digest)
                buffer = bytearray()
                line_digest = hashlib.sha256()
                length = 0

    def _decode(self, buffer, length, line_digest):
        self.lines_read += 1
        if length > self.max_line_bytes:
            return _Line(self.lines_read, None, line_digest.digest(), "line_too_long")
        encoding = "utf-8-sig" if self.lines_read == 1 else "utf-8"
        try:
            text = buffer.decode(encoding).rstrip("\r\n")
            issue = None
        except UnicodeDecodeError:
            text = buffer.decode(encoding, errors="replace").rstrip("\r\n")
            issue = "decode_replacement"
        return _Line(self.lines_read, text, line_digest.digest(), issue)


def _number(raw: str) -> float:
    if not NUMBER.fullmatch(raw):
        raise ValueError("invalid_energy_number")
    value = float(raw.replace("D", "E").replace("d", "e"))
    if not math.isfinite(value):
        raise ValueError("non_finite_energy")
    return value


@dataclass
class _Job:
    start: int
    explicit_start: bool
    end: int = 0
    convergence: SCFConvergence = SCFConvergence.UNKNOWN
    energy_data: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    metadata_lines: dict = field(default_factory=dict)
    route_lines: list = field(default_factory=list)
    route_start: int = 0
    collecting_route: bool = False
    route_chars: int = 0
    digest: object = field(default_factory=hashlib.sha256)
    diagnostics: _Diagnostics = field(default_factory=_Diagnostics)

    @property
    def has_payload(self):
        return bool(self.energy_data or self.metadata or self.route_lines)

    def set_metadata(self, key, value, line):
        self.metadata[key] = value
        self.metadata_lines[key] = line

    def finish_route(self):
        if not self.route_lines:
            return
        route = " ".join(self.route_lines)
        self.set_metadata("route", route, self.route_start)
        # Anchor each token and skip slash-free tokens; avoid quadratic searches
        # on a malformed route and avoid treating IOP(3/33=1) as method/basis.
        match = next((match for token in route.split() if "/" in token
                      and (match := ROUTE_METHOD.fullmatch(token)) is not None), None)
        if match:
            self.set_metadata("method", match.group(1), self.route_start)
            self.set_metadata("basis_set", match.group(2), self.route_start)
        solvent = re.search(r"solvent\s*=\s*([^,\s)]+)", route, re.I)
        if solvent:
            self.set_metadata("solvent", solvent.group(1), self.route_start)
        if re.search(r"\boniom\b", route, re.I):
            self.diagnostics.add("composite_energy_requires_review", line=self.route_start)
        self.collecting_route = False
        self.route_lines.clear()
        self.route_chars = 0

    def consume(self, line: _Line):
        self.end = line.number
        self.digest.update(line.digest)
        if line.issue:
            self.diagnostics.add(line.issue, Severity.ERROR if line.text is None else Severity.WARNING,
                                 line=line.number)
        if line.text is None:
            return
        text, stripped = line.text, line.text.strip()
        known = any(pattern.search(text) for pattern in (SCF, GIBBS_CORRECTION, GIBBS_TOTAL,
                                                        NORMAL, ERROR, START, NEXT_STEP))
        if self.collecting_route:
            if not stripped or stripped.startswith("---") or known or stripped.startswith("#"):
                self.finish_route()
            elif len(self.route_lines) >= 32 or self.route_chars + len(stripped) > MAX_ROUTE_CHARS:
                self.diagnostics.add("route_too_long", line=line.number)
                self.finish_route()
            else:
                self.route_lines.append(stripped)
                self.route_chars += len(stripped) + 1
                return
        if stripped.startswith("#"):
            self.route_lines = [stripped[:MAX_ROUTE_CHARS]]
            self.route_chars = len(self.route_lines[0])
            self.route_start = line.number
            self.collecting_route = True
            if len(stripped) > MAX_ROUTE_CHARS:
                self.diagnostics.add("route_too_long", line=line.number)
                self.finish_route()
        for kind, pattern in ((EnergyKind.SCF, SCF), (EnergyKind.GIBBS_CORRECTION, GIBBS_CORRECTION),
                              (EnergyKind.GIBBS_TOTAL, GIBBS_TOTAL)):
            match = pattern.search(text)
            if not match:
                continue
            raw = match.group(2) if kind == EnergyKind.SCF else match.group(1)
            try:
                value = _number(raw)
            except ValueError as exc:
                self.diagnostics.add(str(exc), Severity.ERROR, {"kind": kind.value, "raw": raw[:128]}, line.number)
                continue
            self.energy_data[kind] = (value, raw, line.number)
            if kind == EnergyKind.SCF:
                self.convergence = SCFConvergence.CONVERGED
                self.set_metadata("scf_method_label", match.group(1), line.number)
        if CONVERGENCE_FAILURE.search(text):
            self.convergence = SCFConvergence.FAILED
            self.diagnostics.add("scf_convergence_failed", Severity.ERROR, line=line.number)
        match = TEMPERATURE.search(text)
        if match:
            for key, raw in zip(("temperature_kelvin", "pressure_atm"), match.groups()):
                try:
                    value = _number(raw)
                    if value <= 0:
                        raise ValueError
                    self.set_metadata(key, value, line.number)
                except ValueError:
                    self.diagnostics.add("invalid_thermochemistry_conditions", params={"field": key}, line=line.number)
        match = CHARGE.search(text)
        if match:
            if any(len(raw) > 32 for raw in match.groups()):
                self.diagnostics.add("invalid_charge_or_multiplicity", line=line.number)
            else:
                self.set_metadata("charge", int(match.group(1)), line.number)
                if int(match.group(2)) >= 1:
                    self.set_metadata("multiplicity", int(match.group(2)), line.number)
                else:
                    self.diagnostics.add("invalid_multiplicity", line=line.number)
        match = BASIS.search(text)
        if match:
            self.set_metadata("basis_set", match.group(1).strip(), line.number)
        match = SOLVENT.search(text)
        if match:
            self.set_metadata("solvent", match.group(1).strip(), line.number)

    def freeze(self, source_id, ordinal, termination, end=None):
        self.finish_route()
        last_line = end if end is not None else self.end
        identifier = str(uuid5(UUID(source_id), f"{PARSER_VERSION}:{self.start}:{self.digest.hexdigest()}"))
        if not self.explicit_start:
            self.diagnostics.add("missing_job_start_marker", line=self.start)
        if termination != Termination.NORMAL:
            self.diagnostics.add("job_error_termination" if termination == Termination.ERROR else "job_incomplete",
                                 Severity.WARNING, line=last_line)
        energies = {kind: EnergyValue(kind, value, raw, line, identifier)
                    for kind, (value, raw, line) in self.energy_data.items()}
        return JobRecord(identifier, source_id, ordinal, self.start, last_line, termination,
                         self.convergence, JobMetadata(**self.metadata, source_lines=self.metadata_lines),
                         energies, self.diagnostics.snapshot())


class _Scanner:
    def __init__(self, source_id):
        self.source_id = source_id
        self.jobs = []
        self.current = None
        self.diagnostics = _Diagnostics()

    def close(self, termination, end=None):
        if self.current is not None:
            self.jobs.append(self.current.freeze(self.source_id, len(self.jobs), termination, end))
            self.current = None

    def consume(self, line):
        text = line.text or ""
        start = bool(START.search(text))
        next_step = bool(NEXT_STEP.search(text))
        if start or next_step:
            if self.current is not None:
                # A step-1 notice before any payload belongs to the startup header.
                if not next_step or self.current.has_payload:
                    self.close(Termination.INCOMPLETE, line.number - 1)
            if self.current is None:
                self.current = _Job(line.number, True)
        if self.current is None:
            signal = any(p.search(text) for p in (INTERNAL_LINK, SCF, GIBBS_CORRECTION,
                                                 GIBBS_TOTAL, NORMAL, ERROR, CONVERGENCE_FAILURE))
            if signal or text.lstrip().startswith("#"):
                self.current = _Job(line.number, False)
            elif line.issue:
                self.diagnostics.add(line.issue, Severity.WARNING, line=line.number)
        if self.current is not None:
            self.current.consume(line)
            if NORMAL.search(text):
                self.close(Termination.NORMAL)
            elif ERROR.search(text):
                self.close(Termination.ERROR)


def _stamp(stat):
    return stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev


def parse_log(path: Path | str, source_file_id: str | UUID | None = None,
              cancel: Callable[[], bool] | None = None, *,
              max_line_bytes: int = 65536, read_chunk_bytes: int = 65536) -> ParseResult:
    """Read bounded binary chunks, hash bytes and return a complete immutable snapshot.

    Unreadable files and cancellation are typed results, not false SCF failures.
    Job UUIDs are derived from file identity, line start and full job content hash;
    unchanged reparse preserves IDs, changed/shifted jobs require explicit rebind.
    """
    if max_line_bytes < 1 or read_chunk_bytes < 1:
        raise ValueError("Read and line limits must be positive")
    path = Path(path).absolute()
    source_id = canonical_uuid(source_file_id if source_file_id is not None else new_id())
    stream = _Stream(cancel or (lambda: False), max_line_bytes, read_chunk_bytes)
    scanner = _Scanner(source_id)
    before = None
    sha256 = None
    state = ImportState.FAILED
    try:
        if stream.cancel():
            raise _Cancelled
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            for line in stream.lines(handle):
                scanner.consume(line)
            scanner.close(Termination.INCOMPLETE)
            after_handle = os.fstat(handle.fileno())
            try:
                after_path = path.stat()
            except OSError:
                after_path = None
        changed = (after_path is None or _stamp(before) != _stamp(after_handle)
                   or _stamp(before) != _stamp(after_path) or stream.bytes_read != before.st_size)
        if changed:
            state = ImportState.STALE
            scanner.diagnostics.add("source_changed_during_read", Severity.ERROR)
        else:
            sha256 = stream.digest.hexdigest()
            any_energy = any(j.energies for j in scanner.jobs)
            damaged = (any(j.termination != Termination.NORMAL for j in scanner.jobs)
                       or any(d.severity == Severity.ERROR for j in scanner.jobs for d in j.diagnostics))
            state = (ImportState.PARTIAL if damaged else ImportState.READY) if any_energy else ImportState.FAILED
            if not any_energy:
                scanner.diagnostics.add("empty_file" if stream.bytes_read == 0 else "no_energy_fields",
                                        Severity.WARNING)
    except _Cancelled:
        scanner.close(Termination.INCOMPLETE)
        state = ImportState.CANCELLED
        scanner.diagnostics.add("parse_cancelled", Severity.INFO)
    except OSError as exc:
        scanner.close(Termination.INCOMPLETE)
        if isinstance(exc, FileNotFoundError):
            state, code = ImportState.MISSING, "file_not_found"
        else:
            state = ImportState.FAILED
            code = "file_permission_denied" if isinstance(exc, PermissionError) else "file_read_error"
        scanner.diagnostics.add(code, Severity.ERROR, {"errno": exc.errno})
    source = SourceFile(source_id, path.name, path.stem, str(path),
                        before.st_size if before else None, before.st_mtime_ns if before else None,
                        sha256=sha256, parser_version=PARSER_VERSION, import_state=state,
                        jobs=tuple(scanner.jobs))
    return ParseResult(source, scanner.diagnostics.snapshot(), stream.lines_read, stream.bytes_read)


def select_job(source: SourceFile, kind: EnergyKind | str,
               policy: SelectionPolicy | str = SelectionPolicy.LAST_NORMAL_WITH_ENERGY,
               *, job_id: str | UUID | None = None) -> JobSelection:
    """Default to last normal eligible job, or resolve exactly one explicit ID.

    Explicit selection never falls back to another job or borrows its fields.
    Failed/cancelled/stale source snapshots are not usable for fresh computation.
    """
    kind, policy = EnergyKind(kind), SelectionPolicy(policy)
    if source.import_state in {ImportState.PENDING, ImportState.READING, ImportState.FAILED,
                                ImportState.CANCELLED, ImportState.STALE, ImportState.MISSING}:
        return JobSelection(None, None, (Diagnostic("source_unavailable", params={"state": source.import_state.value}),))
    if job_id is not None:
        identifier = canonical_uuid(job_id)
        job = next((job for job in source.jobs if job.id == identifier), None)
        if job is None:
            return JobSelection(None, None, (Diagnostic("job_not_found", params={"job_id": identifier}),))
        diagnostics = list(job.diagnostics)
        energy = job.energies.get(kind)
        if energy is None:
            diagnostics.append(Diagnostic("missing_energy", params={"kind": kind.value, "job_id": identifier}))
        return JobSelection(job, energy, tuple(diagnostics))
    candidates = [job for job in source.jobs if job.termination == Termination.NORMAL and kind in job.energies]
    if not candidates:
        return JobSelection(None, None, (Diagnostic("no_normal_job_with_energy", params={"kind": kind.value}),))
    job = candidates[-1]
    diagnostics = list(job.diagnostics)
    later = [j for j in source.jobs[job.ordinal + 1:] if j.termination != Termination.NORMAL]
    if later:
        diagnostics.append(Diagnostic("later_job_not_normal", params={"job_ids": [j.id for j in later]}))
    return JobSelection(job, job.energies[kind], tuple(diagnostics))
