"""Worker-side session lifecycle. No QWidget and no duplicated scientific math."""
from dataclasses import dataclass, replace
from collections.abc import Mapping
from pathlib import Path
import os
import stat
import tempfile
from uuid import uuid4

from ..core import (AliasIndex, EnergyKind, EnergyRef, PathEntry, ProfileNode, Project,
                    ReactionPath, calculate_path, compile_expression, parse_log, select_job)
from ..core.expressions import expression_references
from ..core.models import ImportState, Severity, new_id
from ..core.reaction_network import read_reaction_network
from ..storage import (ProjectRepository, RecoveryService, StorageError, list_recoveries,
                       inspect_sources, calculation_snapshot, reconnect_source)
from ..storage.preferences import LocalPreferences
from ..core.plot_spec import build_plot_spec
from .builder_drafts import BuilderDraftStore


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


@dataclass(frozen=True)
class PreviewDiagnostic:
    code: str
    severity: str
    path_id: str
    stage_id: str | None = None
    connection_id: str | None = None
    species_id: str | None = None
    source_file_id: str | None = None
    detail: str = ""
    params: object = None


@dataclass(frozen=True)
class ReactionRecipePreview:
    project_id: str
    path_id: str
    base_revision: int
    draft_generation: int
    network_digest: str
    options_digest: str
    new_path_id: str | None
    identity_policy: str
    prepared_project: Project | None
    path_result: object | None
    comparison_path_result: object | None
    connections: tuple
    diagnostics: tuple[PreviewDiagnostic, ...]
    blocking: bool


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
        self.builder_drafts = BuilderDraftStore(self.recovery_directory)
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

    def preview_reaction_recipe(self, project, path_id, *, base_revision, draft_generation,
                                network_digest, options_digest, new_path_id, identity_policy,
                                prepared_project=None, comparison_path_id=None, error=None,
                                draft_network=None):
        """Verify source fingerprints and calculate one prepared path on the session worker."""
        if error is not None:
            issues = self._reaction_recipe_error_diagnostics(path_id, draft_network, error)
            return ReactionRecipePreview(project.id, path_id, base_revision, draft_generation,
                network_digest, options_digest, new_path_id, identity_policy, None, None, None, (), issues, True)
        if prepared_project is None:
            issue = PreviewDiagnostic("recipe_invalid", "error", path_id,
                                      detail="Preview did not produce a materialized project")
            return ReactionRecipePreview(project.id, path_id, base_revision, draft_generation,
                network_digest, options_digest, new_path_id, identity_policy, None, None, None, (), (issue,), True)

        path = next((item for item in prepared_project.paths if item.id == path_id), None)
        if path is None:
            issue = PreviewDiagnostic("path_missing", "error", path_id)
            return ReactionRecipePreview(project.id, path_id, base_revision, draft_generation,
                network_digest, options_digest, new_path_id, identity_policy, prepared_project, None, None, (),
                (issue,), True)

        connections = inspect_sources(prepared_project, self.directory)
        checked_project = calculation_snapshot(prepared_project, connections)
        result = calculate_path(checked_project, path_id)
        comparison_result = (calculate_path(checked_project, comparison_path_id)
                             if comparison_path_id is not None and
                             any(item.id == comparison_path_id for item in checked_project.paths) else None)

        referenced_sources = set()
        node_by_id = {node.id: node for node in checked_project.nodes}
        for entry in path.entries:
            node = node_by_id.get(entry.node_id)
            if node is not None:
                referenced_sources.update(ref.source_file_id for ref in expression_references(node.expression))
        if path.reference_expression is not None:
            referenced_sources.update(ref.source_file_id
                                      for ref in expression_references(path.reference_expression))

        issues = []
        source_codes = {"changed": "source_changed", "missing": "source_missing",
                        "unreadable": "source_unreadable", "unverified": "source_unverified"}
        for connection in connections:
            if connection.source_file_id not in referenced_sources or connection.state == "available":
                continue
            issues.append(PreviewDiagnostic(
                source_codes.get(connection.state, "source_unavailable"), "error", path_id,
                source_file_id=connection.source_file_id, detail=connection.detail,
            ))

        raw = read_reaction_network(prepared_project)
        recipe = next((item for item in raw["path_reactions"] if item["path_id"] == path_id), None)
        stage_by_entry = {stage["entry_id"]: stage for stage in (recipe or {}).get("stages", [])
                          if stage.get("entry_id")}
        for node in result.nodes:
            stage = stage_by_entry.get(node.entry_id)
            if stage and stage.get("missing"):
                issues.append(PreviewDiagnostic("missing_transition_state", "warning", path_id,
                                                stage_id=stage["id"]))
                continue
            for diagnostic in node.diagnostics:
                if diagnostic.severity == Severity.ERROR:
                    issues.append(PreviewDiagnostic(diagnostic.code, "error", path_id,
                        stage_id=stage["id"] if stage else None,
                        source_file_id=diagnostic.params.get("source_file_id"),
                        params=dict(diagnostic.params)))
                elif diagnostic.severity == Severity.WARNING:
                    issues.append(PreviewDiagnostic(diagnostic.code, "warning", path_id,
                        stage_id=stage["id"] if stage else None, params=dict(diagnostic.params)))
            if not node.valid and not any(issue.severity == "error" and issue.stage_id == (stage or {}).get("id")
                                          for issue in issues):
                issues.append(PreviewDiagnostic("energy_unavailable", "error", path_id,
                                                stage_id=stage["id"] if stage else None))
        for diagnostic in result.diagnostics:
            issues.append(PreviewDiagnostic(diagnostic.code, diagnostic.severity.value, path_id,
                                            params=dict(diagnostic.params)))
        unique = {}
        for issue in issues:
            key = (issue.code, issue.severity, issue.stage_id, issue.connection_id,
                   issue.species_id, issue.source_file_id, issue.detail)
            unique.setdefault(key, issue)
        diagnostics = tuple(unique.values())
        blocking = any(item.severity == "error" for item in diagnostics)
        return ReactionRecipePreview(project.id, path_id, base_revision, draft_generation,
            network_digest, options_digest, new_path_id, identity_policy, prepared_project,
            result, comparison_result, tuple(connections), diagnostics, blocking)

    @staticmethod
    def _reaction_recipe_error_diagnostics(path_id, network, error):
        reactions = network.get("path_reactions", []) if isinstance(network, Mapping) else []
        recipe = next((item for item in reactions if isinstance(item, Mapping) and
                       item.get("path_id") == path_id), None)
        issues = []
        if recipe:
            stages = {item.get("id"): item for item in recipe.get("stages", [])
                      if isinstance(item, Mapping)}
            edges = [item for item in recipe.get("connections", []) if isinstance(item, Mapping)]
            pairs = {(item.get("source_stage_id"), item.get("target_stage_id")) for item in edges}
            for stage in stages.values():
                if not stage.get("missing") and not stage.get("normalization_confirmed"):
                    issues.append(PreviewDiagnostic("stage_review_required", "error", path_id,
                                                     stage_id=stage.get("id")))
                parents = stage.get("predecessor_stage_ids")
                if parents is None:
                    parents = [stage.get("predecessor_stage_id")] if stage.get("predecessor_stage_id") else []
                for parent_id in parents:
                    if (parent_id, stage.get("id")) not in pairs:
                        issues.append(PreviewDiagnostic("connection_missing", "error", path_id,
                                                         stage_id=stage.get("id")))
            for edge in edges:
                if not edge.get("confirmed") or not str(edge.get("note", "")).strip():
                    issues.append(PreviewDiagnostic("connection_review_required", "error", path_id,
                                                     connection_id=edge.get("id"),
                                                     stage_id=edge.get("target_stage_id")))
        if not issues:
            issues.append(PreviewDiagnostic("recipe_invalid", "error", path_id, detail=str(error)))
        return tuple(issues)

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
        workspace = dict(project.workspace_state)
        ux_v2 = workspace.get("ux_v2")
        if isinstance(ux_v2, Mapping) and "pending_project_name" in ux_v2:
            ux_v2 = dict(ux_v2)
            ux_v2.pop("pending_project_name", None)
            workspace["ux_v2"] = ux_v2
        changed = tuple(sources) != project.source_files or workspace != dict(project.workspace_state)
        copied = replace(project, source_files=tuple(sources), workspace_state=workspace,
                         revision=project.revision + 1 if changed else project.revision)
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

    def save_builder_draft(self, payload):
        return self.builder_drafts.save(payload)

    def load_builder_draft(self, project_id, path_id):
        return self.builder_drafts.load(project_id, path_id)

    def remove_builder_draft(self, project_id, path_id, generation):
        return self.builder_drafts.remove(project_id, path_id, generation)

    @staticmethod
    def _project_file(path):
        path = Path(path).resolve()
        if path.suffix.lower() != ".grproj":
            raise StorageError("invalid_project_path", str(path))
        if not path.exists():
            raise StorageError("project_not_found", str(path))
        if not path.is_file():
            raise StorageError("project_not_file", str(path))
        return path

    def remove_recent(self, path):
        return self.preferences().remove_recent_project(path)

    def rename_project(self, old_path, new_path, project=None):
        old = self._project_file(old_path)
        if not old.stat().st_mode & stat.S_IWUSR:
            raise StorageError("project_read_only", str(old))
        new = Path(new_path).resolve()
        if new.suffix.lower() != ".grproj" or new.parent != old.parent:
            raise StorageError("rename_same_directory_only", str(new))
        if new == old:
            return self.view(project) if project else self.preferences().load()
        if new.exists():
            raise StorageError("destination_exists", str(new))
        current = self.repository is not None and self.repository.path == old
        if current and (self.repository.read_only or project is None):
            raise StorageError("project_read_only")
        if current:
            self.recovery.request(project)
            status = self.recovery.flush()
            if status.error_code or status.recovery_error_code:
                raise StorageError("session_save_failed", status.error_code or status.recovery_error_code)
            self._dispose()
        preferences = self.preferences()
        old_recent = preferences.load()["recent_projects"]
        try:
            os.rename(old, new)
            preferences.replace_recent_project(old, new)
            if current:
                repository = ProjectRepository(new)
                self._prepare(repository.load(), repository)
                self.directory = new.parent
                return self.view(self.recovery._latest, "项目已重命名")
            return preferences.load()
        except BaseException:
            # Keep the old location and live session usable whenever publication fails.
            if new.exists() and not old.exists():
                try:
                    os.rename(new, old)
                except OSError:
                    pass
            try:
                preferences.save(recent_projects=old_recent)
            except StorageError:
                pass
            if current and self.repository is None and old.exists():
                repository = ProjectRepository(old)
                restored = repository.load()
                self._prepare(restored, repository, allow_recovery=True)
                self.directory = old.parent
                self.recovery.request(project)
            raise

    def delete_project_file(self, path, project=None):
        target = self._project_file(path)
        if not target.stat().st_mode & stat.S_IWUSR:
            raise StorageError("project_read_only", str(target))
        current = self.repository is not None and self.repository.path == target
        if current:
            if self.repository.read_only:
                raise StorageError("project_read_only")
            self.recovery.request(project)
            status = self.recovery.flush()
            if status.error_code or status.recovery_error_code:
                raise StorageError("session_save_failed", status.error_code or status.recovery_error_code)
            self._dispose()
        preferences = self.preferences()
        old_recent = preferences.load()["recent_projects"]
        try:
            preferences.remove_recent_project(target)
        except BaseException:
            if current and self.repository is None:
                repository = ProjectRepository(target)
                restored = repository.load()
                self._prepare(restored, repository, allow_recovery=True)
                self.directory = target.parent
                self.recovery.request(project)
            raise
        try:
            target.unlink()
        except OSError as exc:
            try:
                preferences.save(recent_projects=old_recent)
            except StorageError:
                pass
            if current and self.repository is None:
                repository = ProjectRepository(target)
                restored = repository.load()
                self._prepare(restored, repository, allow_recovery=True)
                self.directory = target.parent
                self.recovery.request(project)
            raise StorageError("project_delete_failed", str(exc)) from exc
        if current:
            self.repository = self.recovery = None
            return {"deleted_current": True, "preferences": self.preferences().load()}
        return self.preferences().load()

    def reconnect(self, project, source_id, path):
        change = reconnect_source(project, source_id, path, self.directory)
        return self.update_with_message(change.apply(project), "来源指纹一致，连接已恢复")

    def shutdown(self, preferences=None, *, allow_recovery=False):
        if preferences:
            self.preferences().save(**preferences)
        self._dispose(allow_recovery=allow_recovery)
        return True
