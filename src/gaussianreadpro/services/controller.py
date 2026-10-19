"""Qt orchestration: worker results carry generation/project/revision guards."""
from dataclasses import replace
from collections.abc import Mapping
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from ..core import CalculationMode, EnergyKind, Unit
from ..core.models import NodeRole, ProfileNode, PathEntry, ReactionPath, new_id
from ..core.project_edits import reorder_path
from ..storage import StorageError
from .session import ReactionRecipePreview, RecoveryOffer, SessionBackend, SessionView


_UNSET = object()


class TaskSignals(QObject):
    completed = Signal(int, object, object)
    progress = Signal(int, int, str)


class Task(QRunnable):
    def __init__(self, token, function, signals):
        super().__init__()
        self.token, self.function, self.signals = token, function, signals

    def run(self):
        try:
            result = self.function()
            self.signals.completed.emit(self.token, result, None)
        except Exception as exc:
            self.signals.completed.emit(self.token, None, exc)


class ProjectController(QObject):
    changed = Signal()
    busyChanged = Signal(bool, str)
    progress = Signal(int, int, str)
    failed = Signal(str, str)
    message = Signal(str)
    statusChanged = Signal(object)
    bootstrapped = Signal(object, object)
    recentChanged = Signal()
    preferencesChanged = Signal(object)
    recoveryOffered = Signal(object)
    closed = Signal()
    previewReady = Signal(object)
    reactionPreviewReady = Signal(int, object)
    exported = Signal(str)
    structureReady = Signal(object)
    analysisReady = Signal(object)
    operationFinished = Signal(int, str, bool, object, object, object)
    builderDraftFinished = Signal(int, str, bool, object, str, str)

    def __init__(self, recovery_directory, preferences_path=None, parent=None):
        super().__init__(parent)
        self.backend = SessionBackend(recovery_directory, preferences_path)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.pool.setExpiryTimeout(-1)
        self.project = None
        self.results = ()
        self.connections = ()
        self.plot_spec = None
        self.plot_state = {}
        self._plot_dirty = False
        self.path = None
        self.read_only = False
        self.busy = False
        self.operation = ""
        self.workspace = {}
        self.preferences = {}
        self._pending_preferences = {}
        self.candidates = ()
        self._workspace_dirty = False
        self._counter = 0
        self._active = None
        self._tasks = {}
        self._task_targets = {}
        self._reaction_previews = {}
        self._cancel = Event()
        self._closed = False
        self._workspace_timer = QTimer(self)
        self._workspace_timer.setSingleShot(True)
        self._workspace_timer.timeout.connect(self._persist_workspace)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(250)
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start()
        self._last_status = None
        self.undo_stack = []
        self.redo_stack = []
        from .structure_preview import StructurePreviewService
        self.structure_service = StructurePreviewService()
        self._pending_structure = None
        self._pending_analysis = None

    @property
    def active_task_token(self):
        """Read-only identity of the worker task currently submitted."""
        return self._active

    def _submit(self, operation, function, *, guard=True, target_project_id=_UNSET,
                target_revision=_UNSET, target_path=_UNSET, request_context=None):
        if self.busy or self._closed:
            return False
        self._counter += 1
        token = self._counter
        identity = (self.project.id, self.project.revision) if self.project and guard else None
        signals = TaskSignals(self)
        signals.completed.connect(self._completed)
        signals.progress.connect(self.progress)
        self._tasks[token] = (signals, identity)
        self._task_targets[token] = {
            "operation": operation,
            "project_id": self.project.id if target_project_id is _UNSET and self.project else None if target_project_id is _UNSET else target_project_id,
            "revision": self.project.revision if target_revision is _UNSET and self.project else None if target_revision is _UNSET else target_revision,
            "path": self.path if target_path is _UNSET else target_path,
            "context": dict(request_context or {}),
        }
        self._active = token
        self.busy, self.operation = True, operation
        self._cancel = Event()
        self.busyChanged.emit(True, operation)
        self.pool.start(Task(token, function, signals))
        return True

    @Slot(int, object, object)
    def _completed(self, token, data, error):
        record = self._tasks.pop(token, None)
        target = self._task_targets.pop(token, {})
        if record is None:
            return
        signals, identity = record
        signals.deleteLater()
        operation = target.get("operation", self.operation if token == self._active else "")
        project_id = target.get("project_id")
        revision = target.get("revision")
        path = target.get("path")
        if token != self._active:
            self.operationFinished.emit(token, operation, False, project_id, revision,
                                        None if path is None else str(path))
            return
        self.busy = False
        self.operation = ""
        self._active = None
        succeeded = False
        if error is not None:
            self.failed.emit(getattr(error, "code", "operation_failed"), str(error))
            self._poll_status()
        elif identity and (self.project is None or identity != (self.project.id, self.project.revision)):
            self.message.emit("已忽略过期任务结果")
        elif isinstance(data, RecoveryOffer):
            self.recoveryOffered.emit(data)
            succeeded = True
        elif isinstance(data, SessionView):
            if operation in ("new", "open", "recover", "import", "reconnect"):
                self.undo_stack.clear()
                self.redo_stack.clear()
            same = self.project is not None and self.project.id == data.project.id
            self.project, self.results, self.connections = data.project, data.results, data.connections
            self.plot_spec = data.plot_spec
            if not same or not self._plot_dirty:
                self.plot_state = dict(data.project.plot_state)
            self.path, self.read_only = data.path, data.read_only
            if list(data.recent_projects) != self.preferences.get("recent_projects", []):
                self.preferences["recent_projects"] = list(data.recent_projects)
                self.recentChanged.emit()
            if not same or not self._workspace_dirty:
                self.workspace = dict(data.project.workspace_state)
            self.changed.emit()
            self.statusChanged.emit(data.status)
            if data.message:
                self.message.emit(data.message)
            succeeded = True
        elif operation == "bootstrap":
            self.preferences, self.candidates = data
            self.bootstrapped.emit(*data)
            succeeded = True
        elif operation == "preferences":
            self.preferences = data
            self.preferencesChanged.emit(data)
            succeeded = True
        elif operation in ("remove_recent", "rename_project", "delete_project_file"):
            if operation == "delete_project_file" and isinstance(data, dict) and data.get("deleted_current"):
                self.project = None
                self.results, self.connections, self.plot_spec = (), (), None
                self.path, self.read_only = None, False
                self.workspace, self.plot_state = {}, {}
                self.undo_stack.clear()
                self.redo_stack.clear()
                self.preferences.update(data["preferences"])
                self.changed.emit()
                self.statusChanged.emit(None)
            elif isinstance(data, SessionView):
                self.project, self.results, self.connections = data.project, data.results, data.connections
                self.plot_spec, self.path, self.read_only = data.plot_spec, data.path, data.read_only
                self.preferences["recent_projects"] = list(data.recent_projects)
                self.changed.emit()
                self.statusChanged.emit(data.status)
            else:
                self.preferences = data
            self.recentChanged.emit()
            succeeded = True
        elif operation == "preview":
            change, results, base = data
            self.results, self.connections = base.results, base.connections
            self.plot_spec = base.plot_spec
            self.changed.emit()
            self.previewReady.emit((change, results))
            succeeded = True
        elif operation == "reaction_preview":
            context = target.get("context", {})
            if (isinstance(data, ReactionRecipePreview) and
                    data.project_id == context.get("project_id") and
                    data.path_id == context.get("path_id") and
                    data.base_revision == context.get("base_revision") and
                    data.draft_generation == context.get("draft_generation")):
                self._reaction_previews[token] = data
                # Keep only a small number of recent previews; every commit still rechecks identity.
                for old_token in sorted(self._reaction_previews)[:-4]:
                    self._reaction_previews.pop(old_token, None)
                self.reactionPreviewReady.emit(token, data)
                succeeded = True
        elif operation == "export":
            self.exported.emit(str(data))
            succeeded = True
        elif operation == "structure":
            self.structureReady.emit(data)
            succeeded = True
        elif operation == "analysis":
            self.analysisReady.emit(data)
            succeeded = True
        elif operation == "close":
            self._closed = True
            self._status_timer.stop()
            self._workspace_timer.stop()
            self.closed.emit()
            succeeded = True
        elif operation.startswith("builder_draft_"):
            succeeded = error is None
        else:
            succeeded = error is None
        if succeeded and isinstance(data, SessionView):
            project_id, revision, path = data.project.id, data.project.revision, data.path
        self.operationFinished.emit(token, operation, succeeded, project_id, revision,
                                    None if path is None else str(path))
        if operation.startswith("builder_draft_"):
            code = getattr(error, "code", "") if error is not None else ""
            detail = getattr(error, "detail", str(error)) if error is not None else ""
            self.builderDraftFinished.emit(token, operation, succeeded, data, code, detail)
        if not self.busy and not self._closed and self._pending_preferences:
            changes, self._pending_preferences = self._pending_preferences, {}
            self.update_preferences(**changes)
        if not self.busy:
            self.busyChanged.emit(False, operation)
            if self._pending_structure and not self._closed:
                QTimer.singleShot(0, self._start_structure)
            if self._pending_analysis and not self._closed:
                QTimer.singleShot(0, self._start_analysis)

    def request_structure(self, request):
        """Latest request coalesces behind the existing single worker (including I/O)."""
        self._pending_structure = dict(request)
        if self.busy and self.operation == "structure":
            self._cancel.set()
        if not self.busy:
            self._start_structure()

    def _start_structure(self):
        if self.busy or self._closed or not self._pending_structure:
            return
        request, self._pending_structure = self._pending_structure, None
        project = self.project
        if not project or (request.get("project_id"),request.get("revision")) != (project.id,project.revision):
            return
        source = next((s for s in project.source_files if s.id == request.get("source_file_id")),None)
        job = next((j for j in source.jobs if j.id == request.get("job_id")),None) if source else None
        connection = next((c for c in self.connections if source and c.source_file_id == source.id),None)
        if not job:
            return
        def read():
            value = self.structure_service.read(source, job, connection, self._cancel.is_set, line=request.get("line") if request.get("purpose") == "source" else None)
            return {**request, "structure":value}
        self._submit("structure", read)

    def request_analysis(self, module, source_file_id, job_id):
        """Run a source bound RF8 reader on the worker with a latest-request guard."""
        if module not in {"vibrations", "thermochemistry", "nbo", "irc", "log"}:
            raise ValueError("Unsupported analysis module")
        self._pending_analysis = (module, source_file_id, job_id)
        if self.busy and self.operation == "analysis":
            self._cancel.set()
        if not self.busy:
            self._start_analysis()

    def _start_analysis(self):
        if self.busy or self._closed or not self._pending_analysis:
            return
        module, source_id, job_id = self._pending_analysis
        self._pending_analysis = None
        project = self.project
        if project is None:
            return
        source = next((item for item in project.source_files if item.id == source_id), None)
        job = next((item for item in source.jobs if item.id == job_id), None) if source else None
        connection = next((item for item in self.connections if item.source_file_id == source_id), None)
        if source is None or job is None:
            return

        def read():
            from .gaussian_analyses import (find_analysis_sections, parse_thermochemistry,
                                             parse_vibrations, read_verified_job)
            result = read_verified_job(source, connection, job, self._cancel.is_set)
            if result["status"] != "available":
                return {**result, "module": module}
            lines = result.pop("lines")
            base = {**result, "module": module}
            if module == "vibrations":
                data = parse_vibrations(lines, job.start_line, job.end_line)
            elif module == "thermochemistry":
                data = parse_thermochemistry(lines, job.start_line, job.end_line)
            elif module in {"nbo", "irc"}:
                data = find_analysis_sections(lines, job.start_line, job.end_line, module)
            else:
                data = {"status": "available", "text": "\n".join(
                    f"{number:>7}  {lines[number - 1]}" for number in range(job.start_line, job.end_line + 1))}
            return {**base, **data}

        self._submit("analysis", read)

    def bootstrap(self):
        return self._submit("bootstrap", self.backend.bootstrap, guard=False)

    def update_preferences(self, **changes):
        if self._closed:
            return False
        if self.busy:
            self._pending_preferences.update(changes)
            return True
        return self._submit("preferences", lambda: self.backend.update_preferences(**changes), guard=False)

    def new_project(self):
        if self.busy:
            return False
        snapshot = self._snapshot()
        def run():
            if snapshot:
                self.backend.update(snapshot)
            return self.backend.new()
        return self._submit("new", run, guard=False, target_project_id=None,
                            target_revision=None, target_path=None)

    def open_project(self, path, **options):
        if self.busy:
            return False
        if self.path and Path(path).resolve() == self.path:
            return self.calculate()
        snapshot = self._snapshot()
        def run():
            if snapshot:
                self.backend.update(snapshot)
            return self.backend.open(path, **options)
        return self._submit("open", run, guard=False, target_project_id=None,
                            target_revision=None, target_path=path)

    def recover_project(self, path):
        if self.busy:
            return False
        snapshot = self._snapshot()
        def run():
            if snapshot:
                self.backend.update(snapshot)
            return self.backend.recover(path)
        return self._submit("recover", run, guard=False, target_project_id=None,
                            target_revision=None, target_path=path)

    def _snapshot(self):
        if (self._workspace_dirty or self._plot_dirty) and self.project:
            self.project = replace(self.project, revision=self.project.revision + 1,
                                   workspace_state={**self.workspace, "source_base_dir": str(self.backend.directory)},
                                   plot_state=self.plot_state)
            self._workspace_dirty = False
            self._plot_dirty = False
        return self.project

    def set_plot_state(self, **values):
        if self.read_only or not self.project or self._closed:
            return
        from ..core.plot_spec import clean_view_state, build_plot_spec
        spec = self.plot_spec or build_plot_spec(self.project, ())
        # Project snapshots freeze JSON arrays to tuples. Compare canonical display
        # state on both sides so a Three viewport round-trip does not continuously
        # schedule workspace writes/revisions and invalidate genuine click events.
        current = clean_view_state(self.plot_state, spec)
        state = {**current, **clean_view_state({**current, **values}, spec)}
        if state != current:
            self.plot_state = state
            self._plot_dirty = True
            self._workspace_timer.start(400)

    def set_workspace(self, **values):
        if self.read_only or not self.project or self._closed:
            return
        values = dict(values)
        if isinstance(values.get("ux_v2"), dict):
            nested = dict(self.workspace.get("ux_v2", {}))
            nested.update(values["ux_v2"])
            values["ux_v2"] = nested
        if any(self.workspace.get(key) != value for key, value in values.items()):
            self.workspace.update(values)
            self._workspace_dirty = True
            self._workspace_timer.start(400)

    def clear_pending_project_name(self):
        """Remove the unsaved-name hint after Save As without discarding newer UI state."""
        if self.read_only or not self.project or self._closed:
            return False
        ux_v2 = self.workspace.get("ux_v2", {})
        if not isinstance(ux_v2, Mapping) or "pending_project_name" not in ux_v2:
            return False
        updated = dict(ux_v2)
        updated.pop("pending_project_name", None)
        self.workspace = {**self.workspace, "ux_v2": updated}
        self._workspace_dirty = True
        self._workspace_timer.start(400)
        return True

    def _persist_workspace(self):
        if self.busy:
            self._workspace_timer.start(200)
        elif self._workspace_dirty or self._plot_dirty:
            snapshot = self._snapshot()
            self._submit("workspace", lambda: self.backend.update(snapshot))

    def import_files(self, paths, *, recursive=False):
        if self.busy or not self.project or self.read_only:
            return False
        snapshot = self._snapshot()
        def run():
            signals = self._tasks[self._active][0]
            return self.backend.import_files(snapshot, paths, self._cancel.is_set, signals.progress.emit, recursive)
        return self._submit("import", run)

    def cancel(self):
        if self.operation == "import":
            self._cancel.set()
            self.message.emit("正在取消导入…")

    def calculate(self):
        if not self.project or self.busy:
            return False
        snapshot = self._snapshot()
        return self._submit("calculate", lambda: self.backend.update(snapshot))

    def save(self, destination=None):
        if self.busy or not self.project:
            return False
        snapshot = self._snapshot()
        return self._submit("save", lambda: self.backend.save(snapshot, destination),
                            target_project_id=snapshot.id, target_revision=snapshot.revision,
                            target_path=destination if destination is not None else self.path)

    def save_builder_draft(self, payload):
        if (self.busy or self._closed or not self.project or self.read_only or
                not isinstance(payload, Mapping) or payload.get("project_id") != self.project.id):
            return False
        snapshot = deepcopy(dict(payload))
        path_id = snapshot.get("path_id")
        context = {"project_id": self.project.id, "path_id": path_id,
                   "generation": snapshot.get("generation")}
        return self._submit("builder_draft_save", lambda: self.backend.save_builder_draft(snapshot),
                            target_project_id=self.project.id, target_revision=self.project.revision,
                            target_path=path_id, request_context=context)

    def load_builder_draft(self, project_id, path_id):
        if (self.busy or self._closed or not self.project or project_id != self.project.id):
            return False
        context = {"project_id": project_id, "path_id": path_id}
        return self._submit("builder_draft_load",
                            lambda: self.backend.load_builder_draft(project_id, path_id),
                            target_project_id=project_id, target_revision=self.project.revision,
                            target_path=path_id, request_context=context)

    def remove_builder_draft(self, project_id, path_id, generation):
        if (self.busy or self._closed or not self.project or project_id != self.project.id):
            return False
        context = {"project_id": project_id, "path_id": path_id, "generation": generation}
        return self._submit("builder_draft_remove",
                            lambda: self.backend.remove_builder_draft(project_id, path_id, generation),
                            target_project_id=project_id, target_revision=self.project.revision,
                            target_path=path_id, request_context=context)

    def remove_recent_project(self, path):
        if self.busy:
            return False
        current = bool(self.path and Path(path).resolve() == self.path)
        return self._submit("remove_recent", lambda: self.backend.remove_recent(path), guard=False,
                            target_project_id=self.project.id if current and self.project else None,
                            target_revision=self.project.revision if current and self.project else None,
                            target_path=path)

    def rename_project(self, old_path, new_path):
        if self.busy:
            return False
        current = bool(self.path and Path(old_path).resolve() == self.path)
        snapshot = self._snapshot() if current else self.project
        return self._submit("rename_project", lambda: self.backend.rename_project(old_path, new_path, snapshot), guard=False,
                            target_project_id=snapshot.id if current and snapshot else None,
                            target_revision=snapshot.revision if current and snapshot else None,
                            target_path=new_path)

    def delete_project_file(self, path):
        if self.busy:
            return False
        current = bool(self.path and Path(path).resolve() == self.path)
        snapshot = self._snapshot() if current else self.project
        return self._submit("delete_project_file", lambda: self.backend.delete_project_file(path, snapshot), guard=False,
                            target_project_id=snapshot.id if current and snapshot else None,
                            target_revision=snapshot.revision if current and snapshot else None,
                            target_path=path)

    def _edit(self, project, *, history=True):
        if self.busy or self.read_only:
            return False
        if history and self.project:
            self.undo_stack.append(self.project)
            del self.undo_stack[:-100]
            self.redo_stack.clear()
        if self._workspace_dirty or self._plot_dirty:
            project = replace(project, workspace_state={**self.workspace, "source_base_dir": str(self.backend.directory)}, plot_state=self.plot_state)
            self._workspace_dirty = False
            self._plot_dirty = False
        self._reaction_previews.clear()
        self.project = project
        self.results = ()
        self.plot_spec = None
        self.changed.emit()
        return self._submit("calculate", lambda: self.backend.update(project))

    def undo(self):
        return self._restore_history(self.undo_stack, self.redo_stack)

    def redo(self):
        return self._restore_history(self.redo_stack, self.undo_stack)

    def _restore_history(self, source, destination):
        if not source or self.busy or self.read_only or not self.project:
            return False
        current = self._snapshot()
        destination.append(current)
        previous = source.pop()
        return self._edit(replace(previous, revision=current.revision + 1), history=False)

    def set_expression(self, expression, *, node_id=None, path_id=None, editor_state=None):
        if self.busy or self.read_only or not self.project:
            return False
        if editor_state is not None:
            self.set_workspace(expression_editor=editor_state)
        if node_id:
            node = next(n for n in self.project.nodes if n.id == node_id)
            if node.expression == expression:
                return True
            updated = replace(self.project, nodes=tuple(replace(n, expression=expression) if n.id == node_id else n
                                                        for n in self.project.nodes))
        else:
            path = next(p for p in self.project.paths if p.id == path_id)
            if path.calculation_mode == CalculationMode.DIRECT_DIFFERENCE:
                raise ValueError("Direct differences cannot acquire another reference")
            if path.reference_expression == expression and path.calculation_mode == CalculationMode.RELATIVE:
                return True
            updated = replace(self.project, paths=tuple(replace(p, reference_expression=expression,
                        calculation_mode=CalculationMode.RELATIVE) if p.id == path_id else p for p in self.project.paths))
        return self._edit(replace(updated, revision=self.project.revision + 1))

    def add_node(self, label, *, copy_id=None):
        if self.busy or self.read_only or not self.project or not self.selected_path:
            return False
        from ..core.expressions import edit_expression
        original = next((n for n in self.project.nodes if n.id == copy_id), None)
        node = (replace(original, id=new_id(), label=label) if original else
                ProfileNode(new_id(), label, edit_expression(None, "", self.project.alias_bindings,
                    purpose="difference" if self.selected_path.calculation_mode == "direct_difference" else "system")))
        path = self.selected_path
        path = replace(path, entries=(*path.entries, PathEntry(new_id(), node.id, len(path.entries))))
        self.workspace["node_id"] = node.id
        self._workspace_dirty = True
        return self._edit(replace(self.project, nodes=(*self.project.nodes, node), revision=self.project.revision + 1,
                                  paths=tuple(path if p.id == path.id else p for p in self.project.paths)))

    def remove_nodes(self, node_ids):
        if self.busy or self.read_only or not self.selected_path:
            return False
        selected = set(node_ids)
        path = self.selected_path
        entries = [e for e in path.entries if e.node_id not in selected]
        path = replace(path, entries=tuple(replace(e, position=i) for i, e in enumerate(entries)))
        paths = tuple(path if p.id == path.id else p for p in self.project.paths)
        used = {e.node_id for p in paths for e in p.entries}
        updated = replace(self.project, revision=self.project.revision + 1, paths=paths,
                          nodes=tuple(n for n in self.project.nodes if n.id not in selected or n.id in used))
        if "reaction_network_v1" in updated.workspace_state:
            from ..core.reaction_network import reconcile_network, write_reaction_network
            updated = write_reaction_network(updated, reconcile_network(updated))
        return self._edit(updated)

    def edit_path(self, action, label=None, *, color=None, node_ids=None, path_id=None):
        if self.busy or self.read_only or not self.project:
            return False
        path = next((p for p in self.project.paths if p.id == path_id), None) if path_id else self.selected_path
        paths = list(self.project.paths)
        if path_id and path is None:
            return False
        if action in ("new", "copy", "rename"):
            if not isinstance(label, str) or not label.strip() or len(label.strip()) > 256:
                return False
            label = label.strip()
        requested_color = label if action == "color" else color
        if action == "color" and requested_color is None:
            return False
        if requested_color is not None and (not isinstance(requested_color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", requested_color)):
            return False
        if action == "color":
            label = label.lower()
        if action in ("new", "copy"):
            node_ids = [] if node_ids is None else list(node_ids)
            if not all(isinstance(n, str) for n in node_ids) or len(set(node_ids)) != len(node_ids) or not set(node_ids) <= {n.id for n in self.project.nodes}:
                return False
            created = (replace(path, id=new_id(), label=label,
                       entries=tuple(replace(e, id=new_id()) for e in path.entries)) if action == "copy" and path
                       else ReactionPath(new_id(), label, tuple(PathEntry(new_id(), node_id, i) for i, node_id in enumerate(node_ids)),
                           energy_kind=path.energy_kind if path else EnergyKind.GIBBS_TOTAL,
                           calculation_mode=path.calculation_mode if path else CalculationMode.RELATIVE,
                           reference_expression=path.reference_expression if path else None,
                           unit=path.unit if path else Unit.KCAL_MOL))
            if color is not None:
                created = replace(created, color=color.lower())
            paths.append(created)
            self.workspace["path_id"] = created.id
            self._workspace_dirty = True
            self.plot_state = {**self.plot_state, "compare": True}
            self._plot_dirty = True
        elif action == "rename" and path:
            paths = [replace(p, label=label) if p.id == path.id else p for p in paths]
        elif action == "delete" and path:
            paths = [p for p in paths if p.id != path.id]
        elif action in ("color", "visible") and path:
            paths = [replace(p, **{action: label}) if p.id == path.id else p for p in paths]
        else:
            return False
        updated = replace(self.project, paths=tuple(paths), revision=self.project.revision + 1)
        if action == "delete" and "reaction_network_v1" in updated.workspace_state:
            from ..core.reaction_network import reconcile_network, write_reaction_network
            updated = write_reaction_network(updated, reconcile_network(updated))
        return self._edit(updated)

    def apply_change(self, change):
        if self.busy or self.read_only or not self.project:
            return False
        return self._edit(change.apply(self.project))

    def update_reaction_network(self, network):
        if self.busy or self.read_only or not self.project:
            return False
        from ..core.reaction_network import write_reaction_network
        snapshot = self._snapshot()
        updated = write_reaction_network(snapshot, network)
        return self._edit(replace(updated, revision=snapshot.revision + 1))

    @staticmethod
    def _reaction_input_digest(value):
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
        return sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _prepare_reaction_recipe(project, network, path_id, new_path, path_options,
                                 identity_policy):
        from ..core.reaction_network import apply_path_recipe
        snapshot = project
        if new_path is not None:
            if any(path.id == new_path.id for path in snapshot.paths):
                raise ValueError("New reaction path identity already exists")
            snapshot = replace(snapshot, paths=(*snapshot.paths, new_path))
        if path_options is not None:
            label, color, unit = path_options.get("label"), path_options.get("color"), path_options.get("unit")
            if (not isinstance(label, str) or not label.strip() or len(label) > 256 or
                    not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color) or
                    unit not in {item.value for item in Unit} or
                    not any(path.id == path_id for path in snapshot.paths)):
                raise ValueError("Invalid reaction path label, color or unit")
            snapshot = replace(snapshot, paths=tuple(replace(path, label=label.strip(),
                color=color.lower(), unit=Unit(unit)) if path.id == path_id else path
                for path in snapshot.paths))
        return apply_path_recipe(snapshot, network, path_id, identity_policy=identity_policy)

    def preview_reaction_recipe(self, network, path_id, *, draft_generation, base_revision,
                                new_path=None, path_options=None, identity_policy="regenerate",
                                comparison_path_id=None):
        """Run source verification and one-path calculation on the existing serial worker."""
        if (self.busy or self._closed or not self.project or
                isinstance(draft_generation, bool) or not isinstance(draft_generation, int) or
                draft_generation < 0 or base_revision != self.project.revision):
            return False
        snapshot = self._snapshot()
        if not any(path.id == path_id for path in snapshot.paths) and new_path is None:
            return False
        network_snapshot = deepcopy(network)
        options_snapshot = deepcopy(path_options) if path_options is not None else None
        try:
            network_digest = self._reaction_input_digest(network_snapshot)
            options_digest = self._reaction_input_digest(options_snapshot or {})
        except (TypeError, ValueError):
            return False
        context = {"project_id": snapshot.id, "path_id": path_id,
                   "base_revision": snapshot.revision, "draft_generation": draft_generation}

        def run():
            try:
                prepared = self._prepare_reaction_recipe(snapshot, network_snapshot, path_id,
                    new_path, options_snapshot, identity_policy)
            except (ValueError, KeyError, TypeError) as error:
                return self.backend.preview_reaction_recipe(snapshot, path_id,
                    base_revision=snapshot.revision, draft_generation=draft_generation,
                    network_digest=network_digest, options_digest=options_digest,
                    new_path_id=new_path.id if new_path else None, identity_policy=identity_policy,
                    comparison_path_id=comparison_path_id, error=error,
                    draft_network=network_snapshot)
            return self.backend.preview_reaction_recipe(snapshot, path_id,
                base_revision=snapshot.revision, draft_generation=draft_generation,
                network_digest=network_digest, options_digest=options_digest,
                new_path_id=new_path.id if new_path else None, identity_policy=identity_policy,
                prepared_project=prepared, comparison_path_id=comparison_path_id)

        self._reaction_previews.clear()
        return self._submit("reaction_preview", run, target_project_id=snapshot.id,
            target_revision=snapshot.revision, target_path=path_id, request_context=context)

    def discard_reaction_preview(self, preview_token):
        self._reaction_previews.pop(preview_token, None)

    def apply_reaction_recipe(self, network, path_id, new_path=None, path_options=None, *,
                              identity_policy="regenerate", preview_token=None, draft_generation=None):
        if self.busy or self.read_only or not self.project:
            return False
        if preview_token is not None:
            preview = self._reaction_previews.get(preview_token)
            try:
                network_digest = self._reaction_input_digest(network)
                options_digest = self._reaction_input_digest(path_options or {})
            except (TypeError, ValueError):
                return False
            if (preview is None or preview.blocking or preview.prepared_project is None or
                    preview.project_id != self.project.id or preview.base_revision != self.project.revision or
                    preview.path_id != path_id or preview.draft_generation != draft_generation or
                    preview.network_digest != network_digest or preview.options_digest != options_digest or
                    preview.new_path_id != (new_path.id if new_path else None) or
                    preview.identity_policy != identity_policy):
                return False
            accepted = self._edit(preview.prepared_project)
            if accepted:
                self._reaction_previews.pop(preview_token, None)
            return accepted
        snapshot = self._snapshot()
        updated = self._prepare_reaction_recipe(snapshot, network, path_id, new_path,
                                                path_options, identity_policy)
        return self._edit(updated)

    def preview_change(self, change):
        if not self.project or self.project.revision != change.base_revision:
            return False
        snapshot = self.project
        def run():
            base = self.backend.update(snapshot)
            preview = self.backend.view(change.project)
            results = tuple(r for r in preview.results if r.path_id in change.affected_path_ids)
            return change, results, base
        return self._submit("preview", run)

    @property
    def selected_path(self):
        if not self.project or not self.project.paths:
            return None
        return next((p for p in self.project.paths if p.id == self.workspace.get("path_id")), self.project.paths[0])

    def path_options(self, *, kind=None, unit=None, mode=None):
        if not self.project or self.busy or self.read_only:
            return False
        path = self.selected_path
        if not path:
            return False
        changes = {}
        if kind is not None:
            changes["energy_kind"] = EnergyKind(kind)
        if unit is not None:
            changes["unit"] = Unit(unit)
        if mode is not None:
            changes["calculation_mode"] = CalculationMode(mode)
            if mode != CalculationMode.RELATIVE:
                changes["reference_expression"] = None
        updated = replace(path, **changes)
        return self._edit(replace(self.project, revision=self.project.revision + 1,
                                  paths=tuple(updated if p.id == path.id else p for p in self.project.paths)))

    def reference_node(self, node_id):
        if not self.project or self.busy or self.read_only or not self.selected_path:
            return False
        node = next(n for n in self.project.nodes if n.id == node_id)
        if node.expression.purpose != "system":
            self.failed.emit("expression_purpose_mismatch", "直接差值节点不能作为体系参考")
            return False
        path = replace(self.selected_path, calculation_mode=CalculationMode.RELATIVE,
                       reference_expression=node.expression)
        return self._edit(replace(self.project, revision=self.project.revision + 1,
                                  paths=tuple(path if p.id == path.id else p for p in self.project.paths)))

    def rename_node(self, node_id, label, role):
        if not label.strip() or not self.project or self.busy or self.read_only:
            return False
        nodes = tuple(replace(node, label=label.strip(), role=NodeRole(role)) if node.id == node_id else node
                      for node in self.project.nodes)
        if nodes == self.project.nodes:
            return True
        return self._edit(replace(self.project, nodes=nodes, revision=self.project.revision + 1))

    def move_node(self, entry_id, direction):
        if not self.project or not self.selected_path or self.busy or self.read_only:
            return False
        ids = [e.id for e in self.selected_path.entries]
        index = ids.index(entry_id)
        target = index + direction
        if not 0 <= target < len(ids):
            return False
        ids[index], ids[target] = ids[target], ids[index]
        return self._edit(reorder_path(self.project, self.selected_path.id, ids).project)

    def reconnect(self, source_id, path):
        if self.busy or not self.project or self.read_only:
            return False
        snapshot = self._snapshot()
        return self._submit("reconnect", lambda: self.backend.reconnect(snapshot, source_id, path))

    def close(self, preferences=None, *, allow_recovery=False):
        self._pending_structure = None
        if self.busy:
            return False
        snapshot = self._snapshot()
        def run():
            if snapshot:
                self.backend.update(snapshot)
            return self.backend.shutdown(preferences, allow_recovery=allow_recovery)
        return self._submit("close", run)

    def _poll_status(self):
        recovery = self.backend.recovery
        if recovery:
            status = recovery.status
            if status != self._last_status:
                self._last_status = status
                self.statusChanged.emit(status)

    def export_plot(self, payload, destination, format, raster=None):
        if self.busy or not self.project or payload.get("project_id") != self.project.id or payload.get("revision") != self.project.revision:
            return False
        snapshot = self.project
        def run():
            from .plot_export import export_plot_bundle, assert_current_payload
            current = self.backend.view(snapshot)
            assert_current_payload(payload, current.plot_spec)
            return export_plot_bundle(payload, destination, format, raster=raster)
        return self._submit("export", run)
