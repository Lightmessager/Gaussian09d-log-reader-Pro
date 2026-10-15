"""Debounced saving and independent recovery, with observable failure state."""
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock, RLock, Timer

from ..core.models import Project
from .codec import StorageError, dumps
from .repository import ProjectRepository
from .sources import SourceConnection, calculation_snapshot, inspect_sources


@dataclass(frozen=True)
class SaveStatus:
    current_revision: int | None = None
    saved_revision: int | None = None
    recovery_revision: int | None = None
    pending: bool = False
    saving: bool = False
    error_code: str | None = None
    recovery_error_code: str | None = None


class RecoveryService:
    """Call request on model changes; poll status from UI. No UI callbacks on workers.

    This service owns its recovery repository; the caller owns the optional main
    repository. close() drains the last request and returns the final SaveStatus.
    """
    def __init__(self, recovery_path, *, repository=None, debounce_seconds=1.0,
                 recovery_fault_injector=None):
        if debounce_seconds < 0:
            raise ValueError("Debounce must be nonnegative")
        self.repository = repository
        recovery_path = Path(recovery_path).resolve()
        if repository and recovery_path == repository.path:
            raise StorageError("recovery_requires_separate_file")
        recovery_path.parent.mkdir(parents=True, exist_ok=True)
        self.recovery = ProjectRepository(recovery_path, create=True, fault_injector=recovery_fault_injector)
        if self.recovery.read_only:
            self.recovery.close()
            raise StorageError("recovery_locked")
        self.debounce_seconds = debounce_seconds
        self._state_lock = RLock()
        self._flush_lock = Lock()
        self._timer = None
        self._pending = None
        self._latest = None
        self._closed = False
        self._closing = False
        self._status = SaveStatus(saved_revision=repository.saved_revision if repository else None,
                                  recovery_revision=self.recovery.saved_revision)
        try:
            if self.recovery.saved_revision is not None:
                self._latest = self.recovery.load()
            if repository and repository.saved_revision is not None:
                main = repository.load()
                if self._latest is not None:
                    if self._latest.id != main.id:
                        raise StorageError("recovery_project_mismatch")
                    if self._latest.revision == main.revision and dumps(self._latest) != dumps(main):
                        raise StorageError("recovery_revision_conflict")
                if self._latest is None or main.revision > self._latest.revision:
                    self._latest = main
        except BaseException:
            self.recovery.close()
            raise
        if self._latest:
            self._status = replace(self._status, current_revision=self._latest.revision)

    @property
    def status(self):
        with self._state_lock:
            return self._status

    def request(self, project):
        with self._state_lock:
            if self._closed or self._closing:
                raise StorageError("recovery_service_closed")
            if self._latest is not None:
                if self._latest.id != project.id:
                    raise StorageError("recovery_project_mismatch")
                if project.revision < self._latest.revision:
                    raise StorageError("stale_project_revision")
                if project.revision == self._latest.revision and dumps(project) != dumps(self._latest):
                    raise StorageError("revision_content_conflict")
            self._latest = project
            self._pending = project
            if self._timer:
                self._timer.cancel()
            self._status = replace(self._status, current_revision=project.revision, pending=True)
            self._timer = Timer(self.debounce_seconds, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self):
        with self._flush_lock:
            with self._state_lock:
                if self._closed:
                    return self._status
                if self._timer:
                    self._timer.cancel()
                    self._timer = None
                project = self._pending
                if project is None:
                    return self._status
                self._pending = None
                self._status = replace(self._status, saving=True)
            # Recovery first, so a main project save failure can still leave new work recoverable.
            recovery_revision, saved_revision = self.status.recovery_revision, self.status.saved_revision
            recovery_error = error = None
            try:
                recovery_revision = self.recovery.save(project)
            except StorageError as exc:
                recovery_error = exc.code
            if self.repository:
                try:
                    saved_revision = self.repository.save(project)
                except StorageError as exc:
                    error = exc.code
            with self._state_lock:
                # A request arriving during the write remains pending for the next write.
                if (error or recovery_error) and self._pending is None:
                    self._pending = project  # retry on explicit flush/request/close, no error spin.
                self._status = replace(self._status, saved_revision=saved_revision,
                                       recovery_revision=recovery_revision, saving=False,
                                       pending=self._pending is not None,
                                       error_code=error, recovery_error_code=recovery_error)
                return self._status

    def close(self):
        with self._state_lock:
            if self._closed:
                return self._status
            self._closing = True
            if self._timer:
                self._timer.cancel()
        status = self.flush()
        with self._flush_lock:
            with self._state_lock:
                self._closed = True
            self.recovery.close()
        return status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@dataclass(frozen=True)
class RecoveryCandidate:
    path: Path
    project_id: str | None
    revision: int | None
    error_code: str | None = None


def list_recoveries(directory):
    candidates = []
    for path in sorted(Path(directory).glob("*.grproj")):
        try:
            with ProjectRepository(path, read_only=True) as repository:
                project = repository.load()
            candidates.append(RecoveryCandidate(path, project.id, project.revision))
        except StorageError as exc:
            candidates.append(RecoveryCandidate(path, None, None, exc.code))
    return tuple(candidates)


@dataclass(frozen=True)
class RestoredSession:
    snapshot: Project
    connections: tuple[SourceConnection, ...]
    calculation_project: Project
    interrupted_source_ids: tuple[str, ...]


def restore_session(repository):
    """Restore state, verify sources, never resume interrupted parser tasks."""
    from ..core.models import ImportState
    project = repository.load()
    connections = inspect_sources(project, repository.path.parent)
    interrupted = tuple(source.id for source in project.source_files
                        if source.import_state in (ImportState.PENDING, ImportState.READING))
    return RestoredSession(project, connections, calculation_snapshot(project, connections), interrupted)
