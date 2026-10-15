"""Qt orchestration: worker results carry generation/project/revision guards."""
from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from ..core import CalculationMode, EnergyKind, Unit
from ..core.models import NodeRole, ProfileNode, PathEntry, ReactionPath, new_id
from ..core.project_edits import reorder_path
from ..storage import StorageError
from .session import RecoveryOffer, SessionBackend, SessionView


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
    exported = Signal(str)

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

    def _submit(self, operation, function, *, guard=True):
        if self.busy or self._closed:
            return False
        self._counter += 1
        token = self._counter
        identity = (self.project.id, self.project.revision) if self.project and guard else None
        signals = TaskSignals(self)
        signals.completed.connect(self._completed)
        signals.progress.connect(self.progress)
        self._tasks[token] = (signals, identity)
        self._active = token
        self.busy, self.operation = True, operation
        self._cancel = Event()
        self.busyChanged.emit(True, operation)
        self.pool.start(Task(token, function, signals))
        return True

    @Slot(int, object, object)
    def _completed(self, token, data, error):
        record = self._tasks.pop(token, None)
        if record is None or token != self._active:
            return
        signals, identity = record
        signals.deleteLater()
        self.busy = False
        operation = self.operation
        self.operation = ""
        self._active = None
        if error is not None:
            self.failed.emit(getattr(error, "code", "operation_failed"), str(error))
            self._poll_status()
        elif identity and (self.project is None or identity != (self.project.id, self.project.revision)):
            self.message.emit("已忽略过期任务结果")
        elif isinstance(data, RecoveryOffer):
            self.recoveryOffered.emit(data)
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
        elif operation == "bootstrap":
            self.preferences, self.candidates = data
            self.bootstrapped.emit(*data)
        elif operation == "preferences":
            self.preferences = data
            self.preferencesChanged.emit(data)
        elif operation == "preview":
            change, results, base = data
            self.results, self.connections = base.results, base.connections
            self.plot_spec = base.plot_spec
            self.changed.emit()
            self.previewReady.emit((change, results))
        elif operation == "export":
            self.exported.emit(str(data))
        elif operation == "close":
            self._closed = True
            self._status_timer.stop()
            self._workspace_timer.stop()
            self.closed.emit()
        if not self.busy and not self._closed and self._pending_preferences:
            changes, self._pending_preferences = self._pending_preferences, {}
            self.update_preferences(**changes)
        if not self.busy:
            self.busyChanged.emit(False, operation)

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
        return self._submit("new", run, guard=False)

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
        return self._submit("open", run, guard=False)

    def recover_project(self, path):
        if self.busy:
            return False
        snapshot = self._snapshot()
        def run():
            if snapshot:
                self.backend.update(snapshot)
            return self.backend.recover(path)
        return self._submit("recover", run, guard=False)

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
        state = {**self.plot_state, **clean_view_state({**self.plot_state, **values}, spec)}
        if state != self.plot_state:
            self.plot_state = state
            self._plot_dirty = True
            self._workspace_timer.start(400)

    def set_workspace(self, **values):
        if self.read_only or not self.project or self._closed:
            return
        if any(self.workspace.get(key) != value for key, value in values.items()):
            self.workspace.update(values)
            self._workspace_dirty = True
            self._workspace_timer.start(400)

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
        return self._submit("save", lambda: self.backend.save(snapshot, destination))

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
        destination.append(self.project)
        previous = source.pop()
        self.set_workspace(expression_editor=previous.workspace_state.get("expression_editor", {}))
        return self._edit(replace(previous, revision=self.project.revision + 1,
                                  workspace_state=self.project.workspace_state), history=False)

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
        return self._edit(replace(self.project, revision=self.project.revision + 1, paths=paths,
                                  nodes=tuple(n for n in self.project.nodes if n.id not in selected or n.id in used)))

    def edit_path(self, action, label=None):
        if self.busy or self.read_only or not self.project:
            return False
        path = self.selected_path
        paths = list(self.project.paths)
        if action in ("new", "copy"):
            created = (replace(path, id=new_id(), label=label,
                       entries=tuple(replace(e, id=new_id()) for e in path.entries)) if action == "copy" and path
                       else ReactionPath(new_id(), label, ()))
            paths.append(created)
            self.workspace["path_id"] = created.id
            self._workspace_dirty = True
        elif action == "rename" and path:
            paths = [replace(p, label=label) if p.id == path.id else p for p in paths]
        elif action == "delete" and path:
            paths = [p for p in paths if p.id != path.id]
        elif action in ("color", "visible") and path:
            paths = [replace(p, **{action: label}) if p.id == path.id else p for p in paths]
        else:
            return False
        return self._edit(replace(self.project, paths=tuple(paths), revision=self.project.revision + 1))

    def apply_change(self, change):
        if self.busy or self.read_only or not self.project:
            return False
        return self._edit(change.apply(self.project))

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
