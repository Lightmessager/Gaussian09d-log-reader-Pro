"""Transactional SQLite snapshots, one connection-owning executor per repository."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from hashlib import sha256
import os
import sqlite3
import tempfile
from time import monotonic
from uuid import uuid4

from ..core.models import snapshot_to_dict
from .codec import StorageError, dumps, loads, project_from_dict
from .locking import WriterLock

APPLICATION_ID = 0x47525052  # GRPR; unrelated SQLite files are never initialized/migrated.
SCHEMA_VERSION = 1
FORMAT = "gaussianreadpro.project"
TABLES = {"metadata", "source_files", "jobs", "energies", "nodes", "paths",
          "path_entries", "workspace_state"}
DDL = (
    "CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
    "CREATE TABLE source_files(id TEXT PRIMARY KEY,position INTEGER UNIQUE NOT NULL,payload TEXT NOT NULL)",
    "CREATE TABLE jobs(id TEXT PRIMARY KEY,source_file_id TEXT NOT NULL REFERENCES source_files(id),"
    "position INTEGER NOT NULL,payload TEXT NOT NULL,UNIQUE(source_file_id,position))",
    "CREATE TABLE energies(job_id TEXT NOT NULL REFERENCES jobs(id),kind TEXT NOT NULL,payload TEXT NOT NULL,"
    "PRIMARY KEY(job_id,kind))",
    "CREATE TABLE nodes(id TEXT PRIMARY KEY,position INTEGER UNIQUE NOT NULL,payload TEXT NOT NULL)",
    "CREATE TABLE paths(id TEXT PRIMARY KEY,position INTEGER UNIQUE NOT NULL,payload TEXT NOT NULL)",
    "CREATE TABLE path_entries(id TEXT PRIMARY KEY,path_id TEXT NOT NULL REFERENCES paths(id),"
    "position INTEGER NOT NULL,payload TEXT NOT NULL,UNIQUE(path_id,position))",
    "CREATE TABLE workspace_state(key TEXT PRIMARY KEY,payload TEXT NOT NULL)",
)


def publish_new_file(temporary, destination):
    """Atomic publish without replacing an existing destination, on local filesystems."""
    if os.name == "nt":
        os.rename(temporary, destination)  # Windows rename refuses an existing target.
    else:
        os.link(temporary, destination)  # POSIX rename would replace; link is exclusive.
        os.unlink(temporary)


class ProjectRepository:
    def __init__(self, path, *, create=False, read_only=False, timeout=.25, backup_timeout=5., fault_injector=None):
        self.path = Path(path).resolve()
        self.read_only = read_only
        self.saved_revision = None
        self.migration_backup = None
        self._fault_injector = fault_injector
        if backup_timeout <= 0:
            raise ValueError("Backup timeout must be positive")
        self._backup_timeout = backup_timeout
        self._connection = None
        self._lock = None
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="grproj-storage")
        try:
            self._call(self._open, create, timeout)
        except BaseException:
            self._call(self._dispose)
            self._executor.shutdown(wait=True)
            self._closed = True
            raise

    def _call(self, operation, *args):
        if self._closed:
            raise StorageError("repository_closed")
        try:
            return self._executor.submit(operation, *args).result()
        except StorageError:
            raise
        except (sqlite3.Error, OSError) as exc:
            raise StorageError("storage_io_failed", str(exc)) from exc

    def _fault(self, stage):
        if self._fault_injector:
            self._fault_injector(stage)

    def _open(self, create, timeout):
        exists = self.path.exists()
        if not exists and (not create or self.read_only):
            raise StorageError("project_not_found", str(self.path))
        if not self.read_only:
            self._lock = WriterLock(self.path)
            try:
                self._lock.acquire()
            except StorageError:
                if not exists:
                    raise
                self._lock = None
                self.read_only = True
        # mode=rw will not silently create a replacement if an existing file disappears.
        mode = "ro" if self.read_only else ("rwc" if not exists and create else "rw")
        self._connection = sqlite3.connect(self.path.as_uri() + "?mode=" + mode,
                                           uri=True, timeout=timeout, isolation_level=None)
        connection = self._connection
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        if self.read_only:
            connection.execute("PRAGMA query_only=ON")
        tables = self._tables()
        app_id = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if not exists:
            if tables or self.read_only:
                raise StorageError("invalid_project_database")
            with self._transaction():
                connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                self._create_schema()
        elif app_id != APPLICATION_ID:
            raise StorageError("not_a_project_database")
        elif version > SCHEMA_VERSION:
            raise StorageError("newer_project_schema", str(version))
        elif version < SCHEMA_VERSION:
            if self.read_only:
                raise StorageError("migration_requires_writer")
            self._migrate(version)
        if self._tables() != TABLES:
            raise StorageError("invalid_project_schema")
        if not self.read_only:
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
        if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
            raise StorageError("project_integrity_failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise StorageError("project_integrity_failed", "Foreign key violation")
        if connection.execute("SELECT count(*) FROM metadata").fetchone()[0]:
            self.saved_revision = self._load().revision
        elif any(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES):
            raise StorageError("incomplete_project_snapshot")

    def _tables(self):
        return {row[0] for row in self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    @contextmanager
    def _transaction(self):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._connection.execute("COMMIT")
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise

    def _create_schema(self):
        for statement in DDL:
            self._connection.execute(statement)
        self._connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _migrate(self, version):
        # Recognized pre-release v0 only; no guessing arbitrary SQLite/JSON schemas.
        if version != 0 or self._tables() != {"legacy_project"}:
            raise StorageError("unsupported_project_schema", str(version))
        rows = self._connection.execute("SELECT id,payload FROM legacy_project").fetchall()
        if len(rows) != 1 or rows[0][0] != 1:
            raise StorageError("invalid_legacy_project")
        project = project_from_dict(loads(rows[0][1]))
        backup = self.path.with_name(self.path.name + ".pre-v1-" + uuid4().hex + ".bak")
        self._backup_to(backup)
        self.migration_backup = backup
        with self._transaction():
            self._connection.execute("DROP TABLE legacy_project")
            self._create_schema()
            self._insert(project)
            self._fault("before_migration_commit")

    def load(self):
        """Load the exact persisted snapshot. File availability is a separate report."""
        return self._call(self._load)

    def _load(self):
        connection = self._connection
        # A single read transaction also protects against writers ignoring the sidecar lock.
        connection.execute("BEGIN")
        try:
            metadata = {k: loads(v) for k, v in connection.execute("SELECT key,value FROM metadata")}
            if not metadata:
                raise StorageError("empty_project")
            expected = {"format", "id", "schema_version", "revision", "unit_constants_version", "snapshot_digest"}
            if set(metadata) != expected or metadata.pop("format") != FORMAT:
                raise StorageError("invalid_project_metadata")
            digest = metadata.pop("snapshot_digest")
            state = {k: loads(v) for k, v in connection.execute("SELECT key,payload FROM workspace_state")}
            if set(state) != {"plot_state", "workspace_state", "alias_bindings"}:
                raise StorageError("invalid_workspace_state")
            metadata.update(state)
            sources = self._ordered("source_files")
            jobs = self._ordered("jobs", "source_file_id")
            energies = {}
            for job_id, kind, payload in connection.execute("SELECT job_id,kind,payload FROM energies"):
                energy = loads(payload)
                if energy.get("kind") != kind or energy.get("job_id") != job_id:
                    raise StorageError("invalid_energy_provenance")
                energies.setdefault(job_id, {})[kind] = energy
            for source in sources:
                source["jobs"] = jobs.pop(source["id"], [])
                for job in source["jobs"]:
                    job["energies"] = energies.pop(job["id"], {})
            paths = self._ordered("paths")
            entries = self._ordered("path_entries", "path_id")
            for path in paths:
                path["entries"] = entries.pop(path["id"], [])
            if jobs or entries or energies:
                raise StorageError("orphan_project_rows")
            metadata.update(source_files=sources, nodes=self._ordered("nodes"), paths=paths)
            project = project_from_dict(metadata)
            if digest != sha256(dumps(project).encode("utf-8")).hexdigest():
                raise StorageError("snapshot_digest_mismatch")
            return project
        except (TypeError, ValueError, AttributeError, KeyError) as exc:
            raise StorageError("invalid_snapshot", str(exc)) from exc
        finally:
            connection.execute("ROLLBACK")

    def _ordered(self, table, parent=None):
        # Table/column names are internal constants only.
        columns = "id,position,payload" + ("," + parent if parent else "")
        groups = {}
        for row in self._connection.execute(f"SELECT {columns} FROM {table} ORDER BY position"):
            identity, position, payload = row[:3]
            data = loads(payload)
            group_id = row[3] if parent else None
            group = groups.setdefault(group_id, [])
            if (type(data) is not dict or data.get("id") != identity or type(position) is not int
                    or position != len(group)):
                raise StorageError("invalid_project_order", table)
            if parent == "source_file_id" and (data.get(parent) != group_id or data.get("ordinal") != position):
                raise StorageError("invalid_job_provenance")
            if parent == "path_id" and data.get("position") != position:
                raise StorageError("invalid_project_order", table)
            # Nested children must come from their authoritative tables.
            forbidden = {"source_files": "jobs", "jobs": "energies", "paths": "entries"}.get(table)
            if forbidden in data:
                raise StorageError("duplicate_nested_data", table)
            group.append(data)
        return groups if parent else groups.get(None, [])

    def save(self, project):
        # Validate before taking a write transaction, even for manually constructed snapshots.
        checked = project_from_dict(snapshot_to_dict(project))
        return self._call(self._save, checked)

    def _save(self, project):
        if self.read_only:
            raise StorageError("project_read_only")
        with self._transaction():
            if self._connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise StorageError("not_a_project_database")
            version = self._connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise StorageError("newer_project_schema" if version > SCHEMA_VERSION else "unsupported_project_schema")
            row = self._connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()
            if row is not None:
                metadata = dict(self._connection.execute("SELECT key,value FROM metadata"))
                if loads(metadata["id"]) != project.id:
                    raise StorageError("project_identity_conflict")
                revision = loads(row[0])
                if project.revision < revision:
                    raise StorageError("stale_project_revision")
                if project.revision == revision:
                    # Equal revision only allowed for exact, idempotent snapshots.
                    if loads(metadata["snapshot_digest"]) != sha256(dumps(project).encode("utf-8")).hexdigest():
                        raise StorageError("revision_content_conflict")
                    return project.revision
                if revision != self.saved_revision:
                    raise StorageError("external_revision_conflict")
            self._clear()
            self._fault("after_clear")
            self._insert(project)
            self._fault("before_commit")
        self.saved_revision = project.revision
        return project.revision

    def _clear(self):
        for table in ("energies", "jobs", "source_files", "path_entries", "paths", "nodes",
                      "workspace_state", "metadata"):
            self._connection.execute(f"DELETE FROM {table}")

    def _insert(self, project):
        data = snapshot_to_dict(project)
        for key in ("plot_state", "workspace_state", "alias_bindings"):
            self._connection.execute("INSERT INTO workspace_state VALUES(?,?)", (key, dumps(data.pop(key))))
        for position, source in enumerate(data.pop("source_files")):
            jobs = source.pop("jobs")
            self._connection.execute("INSERT INTO source_files VALUES(?,?,?)", (source["id"], position, dumps(source)))
            for job in jobs:
                energies = job.pop("energies")
                self._connection.execute("INSERT INTO jobs VALUES(?,?,?,?)",
                                         (job["id"], source["id"], job["ordinal"], dumps(job)))
                for kind, energy in energies.items():
                    self._connection.execute("INSERT INTO energies VALUES(?,?,?)", (job["id"], kind, dumps(energy)))
        self._fault("after_sources")
        for position, node in enumerate(data.pop("nodes")):
            self._connection.execute("INSERT INTO nodes VALUES(?,?,?)", (node["id"], position, dumps(node)))
        for position, path in enumerate(data.pop("paths")):
            entries = path.pop("entries")
            self._connection.execute("INSERT INTO paths VALUES(?,?,?)", (path["id"], position, dumps(path)))
            for entry in entries:
                self._connection.execute("INSERT INTO path_entries VALUES(?,?,?,?)",
                                         (entry["id"], path["id"], entry["position"], dumps(entry)))
        data["format"] = FORMAT
        data["snapshot_digest"] = sha256(dumps(project).encode("utf-8")).hexdigest()
        self._connection.executemany("INSERT INTO metadata VALUES(?,?)", [(k, dumps(v)) for k, v in data.items()])

    def backup_to(self, destination):
        """Exact consistent backup via SQLite API, without overwriting a destination."""
        return self._call(self._backup_to, Path(destination).resolve())

    def save_as(self, destination):
        """Consistent Save As plus verified path rebasing. The source stays unchanged.

        The new snapshot gains one revision if transport paths change. Open the
        returned path in a new repository to continue working on the copy.
        """
        return self._call(self._save_as, Path(destination).resolve())

    def _save_as(self, destination):
        from .sources import inspect_sources
        if destination.exists():
            raise StorageError("destination_exists", str(destination))
        with tempfile.TemporaryDirectory(prefix="grproj-save-as-") as directory:
            staging = self._backup_to(Path(directory) / "snapshot.grproj")
            with ProjectRepository(staging) as copy:
                project = copy.load()
                connections = inspect_sources(project, self.path.parent)
                sources = []
                for source, connection in zip(project.source_files, connections):
                    if connection.state == "available":
                        try:
                            relative = Path(os.path.relpath(connection.path, destination.parent)).as_posix()
                        except ValueError:
                            relative = None
                        source = replace(source, original_path=str(connection.path), relative_path=relative)
                    sources.append(source)
                if tuple(sources) != project.source_files:
                    copy.save(replace(project, source_files=tuple(sources), revision=project.revision + 1))
                return copy.backup_to(destination)

    def _backup_to(self, destination):
        if destination == self.path or destination.exists():
            raise StorageError("destination_exists", str(destination))
        lock = WriterLock(destination)
        lock.acquire()
        temporary = None
        try:
            if destination.exists():
                raise StorageError("destination_exists", str(destination))
            fd, temporary = tempfile.mkstemp(prefix=".grproj-", suffix=".tmp", dir=destination.parent)
            os.close(fd)
            target = sqlite3.connect(temporary)
            try:
                deadline = monotonic() + self._backup_timeout
                def progress(_status, _remaining, _total):
                    if monotonic() > deadline:
                        raise StorageError("backup_timeout")
                self._connection.backup(target, pages=256, progress=progress, sleep=.05)
            finally:
                target.close()
            with open(temporary, "r+b") as handle:
                os.fsync(handle.fileno())
            self._fault("before_backup_publish")
            publish_new_file(temporary, destination)
            return destination
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
            lock.close()

    def _dispose(self):
        if self._connection:
            self._connection.close()
            self._connection = None
        if self._lock:
            self._lock.close()
            self._lock = None

    def close(self):
        if not self._closed:
            self._call(self._dispose)
            self._closed = True
            self._executor.shutdown(wait=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
