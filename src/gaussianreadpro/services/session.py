"""Worker-side session lifecycle. No QWidget and no duplicated scientific math."""
from dataclasses import dataclass, replace
from pathlib import Path
import os
import tempfile
from uuid import uuid4

from ..core import (AliasIndex, EnergyKind, EnergyRef, PathEntry, ProfileNode, Project,
                    ReactionPath, calculate_path, compile_expression, parse_log, select_job)
from ..core.models import ImportState, new_id
from ..storage import (ProjectRepository, RecoveryService, StorageError, list_recoveries,
                       inspect_sources, calculation_snapshot, reconnect_source)
from ..storage.preferences import LocalPreferences
from ..core.plot_spec import build_plot_spec


@dataclass(frozen=True)
class SessionView:
    project: Project
    results: tuple
    connections: tuple
    path: Path | None
    read_only: bool
    status: object
    message: str = ""
    recent_projects: tuple[str, ...] = ()
    plot_spec: object = None


@dataclass(frozen=True)
class RecoveryOffer:
    project_path: Path
    recovery_path: Path
    saved_revision: int
    recovery_revision: int


def import_into(project, paths, cancel, progress, *, recursive=False):
    """Atomic import: cancel leaves the original project, aliases and order intact."""
    expanded = []
    seen = {os.path.normcase(str(Path(s.original_path).resolve())) for s in project.source_files}
    skipped = 0
    for raw in paths:
        path = Path(raw).resolve()
        candidates = ((path.rglob("*") if recursive else path.iterdir()) if path.is_dir() else (path,))
        for candidate in candidates:
            if cancel():
                return project, "已取消导入"
            if candidate.is_dir() or (path.is_dir() and candidate.suffix.lower() not in (".log", ".out")):
                continue
            key = os.path.normcase(str(candidate.resolve()))
            if key in seen:
                skipped += 1
                continue
            seen.add(key)
            expanded.append(candidate)
            if len(expanded) > 10000:
                raise StorageError("import_file_limit")
    sources, nodes, entries = list(project.source_files), list(project.nodes), []
    aliases = dict(project.alias_bindings)
    path = project.paths[0] if project.paths else ReactionPath(new_id(), "反应路径 1", ())
    selected_path = project.workspace_state.get("path_id")
    path = next((p for p in project.paths if p.id == selected_path), path)
    entries.extend(path.entries)
    for index, candidate in enumerate(expanded):
        if cancel():
            return project, "已取消导入"
        progress(index, len(expanded), candidate.name)
        source = parse_log(candidate, cancel=cancel).source
        if cancel() or source.import_state == ImportState.CANCELLED:
            return project, "已取消导入"
        sources.append(source)
        # Bind once to a real job, and never silently change this job on kind changes.
        selection = select_job(source, path.energy_kind)
        if selection.job is None and source.jobs:
            # A normal SCF-only job is a legitimate import; Gibbs remains unavailable.
            selection = select_job(source, EnergyKind.SCF)
        if selection.job is None:
            continue
        reference = EnergyRef(source.id, selection.job.id)
        unique = AliasIndex.with_unique_labels([*aliases.items(), (source.display_name, reference)])
        alias = unique.label_for(reference)
        aliases = dict(unique.bindings)
        expression = compile_expression("@{" + alias + "}", aliases).expression
        node = ProfileNode(new_id(), source.display_name, expression)
        nodes.append(node)
        entries.append(PathEntry(new_id(), node.id, len(entries)))
    if cancel():
        return project, "已取消导入"
    if not expanded:
        return project, f"没有新增文件 · 已跳过 {skipped} 个重复路径"
    path = replace(path, entries=tuple(entries))
    paths = tuple(path if old.id == path.id else old for old in project.paths) if project.paths else (path,)
    result = replace(project, source_files=tuple(sources), nodes=tuple(nodes), paths=paths,
                     alias_bindings=aliases, revision=project.revision + 1)
    progress(len(expanded), len(expanded), "完成")
    return result, f"已导入 {len(expanded)} 个文件 · 跳过 {skipped} 个重复路径"


class SessionBackend:
    """All methods are called serially by the controller's worker pool."""
    def __init__(self, recovery_directory, preferences_path=None):
        self.recovery_directory = Path(recovery_directory).resolve()
        self.preferences_path = preferences_path
        self.repository = None
        self.recovery = None
        self.directory = Path.cwd()

    def preferences(self):
        return LocalPreferences(self.preferences_path)

    def update_preferences(self, **changes):
        return self.preferences().save(**changes)

    def bootstrap(self):
        return self.preferences().load(), list_recoveries(self.recovery_directory)

    def _dispose(self, *, allow_recovery=False):
        if self.recovery:
            status = self.recovery.flush()
            if status.recovery_error_code or status.error_code and not allow_recovery:
                raise StorageError("session_save_failed", status.error_code or status.recovery_error_code)
            if status.error_code and status.recovery_revision != status.current_revision:
                raise StorageError("session_save_failed", "Latest recovery is unavailable")
            status = self.recovery.close()
            if status.recovery_error_code or status.error_code and not allow_recovery:
                raise StorageError("session_save_failed", status.error_code or status.recovery_error_code)
            self.recovery = None
        if self.repository:
            self.repository.close()
            self.repository = None

    def _prepare(self, project, repository=None, *, allow_recovery=False):
        self.recovery_directory.mkdir(parents=True, exist_ok=True)
        # A session suffix separates Save As branches and simultaneous views of one UUID.
        recovery_path = self.recovery_directory / f"{project.id}-{uuid4().hex}.grproj"
        recovery = RecoveryService(recovery_path, repository=repository if repository and not repository.read_only else None)
        try:
            self._dispose(allow_recovery=allow_recovery)
        except BaseException:
            recovery.close()
            raise
        self.repository, self.recovery = repository, recovery

    def new(self):
        project = Project(new_id())
        self._prepare(project)
        self.directory = Path.cwd()
        return self.view(project)

    def open(self, path, *, recovery_file=None, ignore_recovery=False):
        path = Path(path).resolve()
        if self.repository and self.repository.path == path:
            return self.view(self.repository.load())
        candidate = ProjectRepository(path)
        try:
            project = candidate.load()
            if not ignore_recovery and recovery_file is None:
                choices = [c for c in list_recoveries(self.recovery_directory)
                           if c.project_id == project.id and c.revision > project.revision]
                if choices:
                    latest = max(choices, key=lambda c: c.revision)
                    return RecoveryOffer(path, latest.path, project.revision, latest.revision)
            if recovery_file:
                with ProjectRepository(recovery_file, read_only=True) as recovery:
                    restored = recovery.load()
                if restored.id != project.id or restored.revision <= project.revision:
                    raise StorageError("recovery_project_mismatch")
                project = restored
            self._prepare(project, candidate)
            self.directory = path.parent
            candidate = None
            self.recovery.request(project)
            self.preferences().remember_project(path)
            return self.view(project)
        finally:
            if candidate:
                candidate.close()

    def recover(self, path):
        with ProjectRepository(path, read_only=True) as repository:
            project = repository.load()
        base = project.workspace_state.get("source_base_dir")
        directory = Path(base) if isinstance(base, str) and base and Path(base).is_absolute() else Path(path).parent
        self._prepare(project)
        self.directory = directory
        self.recovery.request(project)
        return self.view(project, "已恢复副本，请另存为项目")

    def update(self, project):
        if self.recovery is None:
            raise StorageError("no_active_session")
        self.recovery.request(project)
        return self.view(project)

    def view(self, project, message=""):
        connections = inspect_sources(project, self.directory)
        current = calculation_snapshot(project, connections)
        results = tuple(calculate_path(current, path.id) for path in current.paths)
        return SessionView(project, results, connections, self.repository.path if self.repository else None,
                           self.repository.read_only if self.repository else False,
                           self.recovery.status if self.recovery else None, message,
                           tuple(self.preferences().load()["recent_projects"]), build_plot_spec(project, results))

    def import_files(self, project, paths, cancel, progress, recursive=False):
        result, message = import_into(project, paths, cancel, progress, recursive=recursive)
        return self.update_with_message(result, message)

    def update_with_message(self, project, message):
        view = self.update(project)
        return replace(view, message=message)

    def save(self, project, destination=None):
        if destination is None:
            if self.repository and self.repository.read_only:
                raise StorageError("project_read_only")
            self.recovery.request(project)
            status = self.recovery.flush()
            if status.error_code or status.recovery_error_code:
                raise StorageError("session_save_failed", status.error_code or status.recovery_error_code)
            if self.repository is None:
                raise StorageError("project_needs_filename")
            self.preferences().remember_project(self.repository.path)
            return self.view(project, "项目已保存")
        destination = Path(destination).resolve()
        if self.repository and self.repository.path == destination:
            return self.save(project)
        # Stage the latest model, preserving the current project's source base directory.
        self.recovery.request(project)
        sources = []
        for source, connection in zip(project.source_files, inspect_sources(project, self.directory)):
            if connection.state == "available":
                try:
                    relative = Path(os.path.relpath(connection.path, destination.parent)).as_posix()
                except ValueError:
                    relative = None
                source = replace(source, original_path=str(connection.path), relative_path=relative)
            sources.append(source)
        copied = (replace(project, source_files=tuple(sources), revision=project.revision + 1)
                  if tuple(sources) != project.source_files else project)
        with tempfile.TemporaryDirectory(prefix="grpro-save-as-") as directory:
            with ProjectRepository(Path(directory) / "snapshot.grproj", create=True) as stage:
                stage.save(copied)
                destination_path = stage.backup_to(destination)
        candidate = ProjectRepository(destination_path)
        try:
            copied = candidate.load()
            # The explicitly requested Save As is also the escape hatch from a read-only main file.
            self._prepare(copied, candidate, allow_recovery=True)
        except BaseException:
            candidate.close()
            raise
        self.directory = destination.parent
        self.recovery.request(copied)
        self.preferences().remember_project(destination_path)
        return self.view(copied, "项目已另存")

    def reconnect(self, project, source_id, path):
        change = reconnect_source(project, source_id, path, self.directory)
        return self.update_with_message(change.apply(project), "来源指纹一致，连接已恢复")

    def shutdown(self, preferences=None, *, allow_recovery=False):
        if preferences:
            self.preferences().save(**preferences)
        self._dispose(allow_recovery=allow_recovery)
        return True
