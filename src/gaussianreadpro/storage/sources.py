"""Verify connections without reparsing or changing stable file/job identities."""
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path, PureWindowsPath
import os

from ..core.models import ImportState, canonical_uuid
from ..core.project_edits import ProjectChange, find_source_usage
from .codec import StorageError


@dataclass(frozen=True)
class SourceConnection:
    source_file_id: str
    state: str  # available, missing, changed, unverified, unreadable
    path: Path | None
    detail: str = ""


def fingerprint(path):
    """Bounded streaming SHA256; refuse a file that changes during verification."""
    path = Path(path)
    digest = sha256()
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        count = 0
        while chunk := handle.read(65536):
            count += len(chunk)
            digest.update(chunk)
        after = os.fstat(handle.fileno())
    current = path.stat()
    signature = lambda stat: (stat.st_size, stat.st_mtime_ns, stat.st_ino, stat.st_dev)
    if count != before.st_size or signature(before) != signature(after) or signature(after) != signature(current):
        raise StorageError("source_changed_during_verification", str(path))
    return digest.hexdigest(), after.st_size, after.st_mtime_ns


def _candidates(source, directory):
    paths = []
    if source.relative_path:
        relative = source.relative_path.replace("\\", "/")
        if not Path(relative).is_absolute() and not PureWindowsPath(relative).drive:
            paths.append((Path(directory) / relative).resolve())
    original = Path(source.original_path)
    if original.is_absolute():
        paths.append(original.resolve())
    return tuple(dict.fromkeys(paths))


def inspect_source(source, directory):
    failures = []
    for path in _candidates(source, directory):
        try:
            if not path.exists():
                continue
            if source.sha256 is None:
                failures.append(SourceConnection(source.id, "unverified", path, "fingerprint_unavailable"))
                continue
            digest, size, _ = fingerprint(path)
            if digest == source.sha256 and (source.size_bytes is None or source.size_bytes == size):
                return SourceConnection(source.id, "available", path)
            failures.append(SourceConnection(source.id, "changed", path, "fingerprint_mismatch"))
        except (OSError, StorageError) as exc:
            failures.append(SourceConnection(source.id, "unreadable", path, str(exc)))
    return failures[0] if failures else SourceConnection(source.id, "missing", None)


def inspect_sources(project, directory):
    return tuple(inspect_source(source, directory) for source in project.source_files)


def calculation_snapshot(project, connections):
    """Transient availability overlay. Persisted parse evidence is never overwritten."""
    by_id = {item.source_file_id: item for item in connections}
    sources = []
    for source in project.source_files:
        connection = by_id.get(source.id)
        if connection is None or connection.state != "available":
            state = ImportState.MISSING if connection is None or connection.state == "missing" else ImportState.STALE
            source = replace(source, import_state=state)
        elif source.import_state in (ImportState.PENDING, ImportState.READING):
            source = replace(source, import_state=ImportState.CANCELLED)
        sources.append(source)
    return replace(project, source_files=tuple(sources))


def reconnect_source(project, source_id, path, directory):
    source_id = canonical_uuid(source_id)
    source = next((item for item in project.source_files if item.id == source_id), None)
    if source is None:
        raise StorageError("unknown_source", source_id)
    if source.sha256 is None:
        raise StorageError("fingerprint_unavailable", source_id)
    path = Path(path).resolve()
    try:
        digest, size, mtime = fingerprint(path)
    except OSError as exc:
        raise StorageError("source_unreadable", str(exc)) from exc
    if digest != source.sha256 or (source.size_bytes is not None and size != source.size_bytes):
        raise StorageError("fingerprint_mismatch", source_id)
    try:
        relative = Path(os.path.relpath(path, Path(directory).resolve())).as_posix()
    except ValueError:  # Different Windows drives.
        relative = None
    updated = replace(source, original_path=str(path), relative_path=relative, size_bytes=size, mtime_ns=mtime)
    result = replace(project, source_files=tuple(updated if s.id == source_id else s for s in project.source_files),
                     revision=project.revision + 1)
    usage = find_source_usage(project, [source_id])
    return ProjectChange(project.id, project.revision, result, usage.node_ids, usage.reference_path_ids)


@dataclass(frozen=True)
class DirectoryReconnect:
    change: ProjectChange | None
    unmatched: tuple[str, ...]
    ambiguous: tuple[str, ...]


def reconnect_directory(project, directory, project_directory, *, max_files=10000):
    """Scan an explicitly chosen directory; hashes, never names, select candidates."""
    by_hash = {}
    sizes = {s.size_bytes for s in project.source_files if s.sha256 is not None}
    count = 0
    try:
        for path in Path(directory).rglob("*"):
            if not path.is_file():
                continue
            count += 1
            if count > max_files:
                raise StorageError("source_scan_limit")
            if None not in sizes and path.stat().st_size not in sizes:
                continue
            digest, _, _ = fingerprint(path)
            by_hash.setdefault(digest, []).append(path)
    except OSError as exc:
        raise StorageError("source_scan_failed", str(exc)) from exc
    updated = project
    unmatched, ambiguous = [], []
    affected_nodes, affected_paths = set(), set()
    for source in project.source_files:
        candidates = by_hash.get(source.sha256, [])
        if not candidates:
            unmatched.append(source.id)
        elif len(candidates) > 1:
            ambiguous.append(source.id)
        else:
            change = reconnect_source(updated, source.id, candidates[0], project_directory)
            updated = change.project
            affected_nodes.update(change.affected_node_ids)
            affected_paths.update(change.affected_path_ids)
    if updated is project:
        return DirectoryReconnect(None, tuple(unmatched), tuple(ambiguous))
    updated = replace(updated, revision=project.revision + 1)
    change = ProjectChange(project.id, project.revision, updated,
                           tuple(sorted(affected_nodes)), tuple(sorted(affected_paths)))
    return DirectoryReconnect(change, tuple(unmatched), tuple(ambiguous))
