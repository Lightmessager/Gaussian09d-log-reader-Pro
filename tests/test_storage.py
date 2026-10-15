"""S3 persistence failures must preserve the last committed scientific revision."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest

from gaussianreadpro.core import calculate_path, edit_expression
from gaussianreadpro.core.models import ImportState, snapshot_to_dict
from gaussianreadpro.storage import (ProjectRepository, RecoveryService, StorageError,
                                    decode_project, list_recoveries, restore_session)
from gaussianreadpro.storage.codec import dumps
from gaussianreadpro.storage.repository import APPLICATION_ID, TABLES
from s2_helpers import identifier, project


def workspace_project():
    base, _, aliases = project()
    draft = replace(base.nodes[1], expression=edit_expression(base.nodes[1].expression, "@{TS1} + (", aliases),
                    display={"label_offset": [3, -2]})
    path = base.paths[0]
    second = replace(path, id=identifier("s3-path-2"), label="路径二", color="#abcdef",
                     entries=tuple(replace(e, id=identifier("s3-2-" + e.id), position=i,
                                           display_override={"label_offset": [i, 2]})
                                   for i, e in enumerate(reversed(path.entries))))
    return replace(base, revision=7, nodes=(base.nodes[0], draft, *base.nodes[2:]), paths=(path, second),
                   workspace_state={"selected_node": draft.id, "page": "advanced", "filter": "TS",
                                    "splitter": [240, 800], "sort": ["name", "asc"], "formula_draft": "@{TS1} + ("},
                   plot_state={"view": "3d", "camera": {"eye": {"x": 1.2, "y": 2, "z": .5}},
                               "range": [-20, 30]})


def test_roundtrip_every_field_and_two_paths(tmp_path):
    before = workspace_project()
    path = tmp_path / "中文 project.grproj"
    with ProjectRepository(path, create=True) as repository:
        assert repository.saved_revision is None
        assert repository.save(before) == 7
        assert repository.saved_revision == 7
        assert repository.load() == before
        assert repository.save(before) == 7
        assert not repository.load().nodes[1].expression.draft_error is None
        assert not calculate_path(repository.load(), before.paths[0].id).valid
    with ProjectRepository(path) as repository:
        assert repository.load() == before
        assert repository.save(before) == 7
        assert repository.saved_revision == 7
    with sqlite3.connect(path) as connection:
        assert {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == TABLES
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)


@pytest.mark.parametrize("phase", ["after_clear", "after_sources", "before_commit"])
def test_write_failure_rolls_back_and_can_retry(tmp_path, phase):
    base, _, _ = project()
    active = {"phase": None}
    def fail(stage):
        if stage == active["phase"]:
            raise sqlite3.OperationalError("injected disk full")
    with ProjectRepository(tmp_path / "project.grproj", create=True, fault_injector=fail) as repository:
        repository.save(base)
        active["phase"] = phase
        newer = replace(base, revision=1, workspace_state={"page": "advanced"})
        with pytest.raises(StorageError, match="storage_io_failed"):
            repository.save(newer)
        assert repository.saved_revision == 0
        assert repository.load() == base
        active["phase"] = None
        assert repository.save(newer) == 1
        assert repository.load() == newer


def test_real_sqlite_lock_failure_preserves_revision(tmp_path):
    base, _, _ = project()
    path = tmp_path / "locked.grproj"
    with ProjectRepository(path, create=True, timeout=.01) as repository:
        repository.save(base)
        with sqlite3.connect(path) as rival:
            rival.execute("BEGIN IMMEDIATE")
            with pytest.raises(StorageError, match="storage_io_failed"):
                repository.save(replace(base, revision=1))
            rival.rollback()
        assert repository.load() == base
        assert repository.saved_revision == 0


def test_revision_and_identity_conflicts(tmp_path):
    base = replace(project()[0], revision=2)
    with ProjectRepository(tmp_path / "revisions.grproj", create=True) as repository:
        repository.save(base)
        for candidate, code in ((replace(base, revision=1), "stale_project_revision"),
                                (replace(base, workspace_state={"changed": True}), "revision_content_conflict"),
                                (replace(base, id=identifier("other"), revision=3), "project_identity_conflict")):
            with pytest.raises(StorageError, match=code):
                repository.save(candidate)
        assert repository.load() == base


def test_second_instance_and_process_are_read_only(tmp_path):
    base, _, _ = project()
    path = tmp_path / "multi.grproj"
    with ProjectRepository(path, create=True) as first:
        first.save(base)
        with ProjectRepository(path) as second:
            assert second.read_only
            assert second.load() == base
            with pytest.raises(StorageError, match="project_read_only"):
                second.save(replace(base, revision=1))
            first.save(replace(base, revision=1))
            assert second.load().revision == 1
        code = "from gaussianreadpro.storage import ProjectRepository; import sys; " \
               "r=ProjectRepository(sys.argv[1]); print(r.read_only,r.load().revision); r.close()"
        result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, check=True)
        assert result.stdout.strip() == "True 1"
    with ProjectRepository(path) as reopened:
        assert not reopened.read_only


def legacy(path, base):
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        connection.execute("CREATE TABLE legacy_project(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_project VALUES(1,?)", (dumps(base),))


def test_migration_backup_and_failure_rollback(tmp_path):
    base = workspace_project()
    path = tmp_path / "legacy.grproj"
    legacy(path, base)
    def fail(stage):
        if stage == "before_migration_commit":
            raise sqlite3.OperationalError("injected migration failure")
    with pytest.raises(StorageError):
        ProjectRepository(path, fault_injector=fail)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute("SELECT payload FROM legacy_project").fetchone()[0] == dumps(base)
    backups = list(tmp_path.glob("*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute("SELECT payload FROM legacy_project").fetchone()[0] == dumps(base)
    with ProjectRepository(path) as repository:
        assert repository.load() == base
        assert repository.migration_backup.exists()
    assert len(list(tmp_path.glob("*.bak"))) == 2


def test_newer_database_and_unrelated_file_never_modified(tmp_path):
    path = tmp_path / "future.grproj"
    with ProjectRepository(path, create=True) as repository:
        repository.save(project()[0])
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=999")
    original = path.read_bytes()
    with pytest.raises(StorageError, match="newer_project_schema"):
        ProjectRepository(path)
    assert path.read_bytes() == original
    unrelated = tmp_path / "unrelated.grproj"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE important(value TEXT)")
    original = unrelated.read_bytes()
    with pytest.raises(StorageError, match="not_a_project_database"):
        ProjectRepository(unrelated, create=True)
    assert unrelated.read_bytes() == original


def test_backup_api_and_failed_publish(tmp_path):
    base = workspace_project()
    active = False
    def fail(stage):
        if active and stage == "before_backup_publish":
            raise OSError("injected backup failure")
    with ProjectRepository(tmp_path / "main.grproj", create=True, fault_injector=fail) as repository:
        repository.save(base)
        destination = repository.backup_to(tmp_path / "copy.grproj")
        with ProjectRepository(destination, read_only=True) as copy:
            assert copy.load() == base
        with pytest.raises(StorageError, match="destination_exists"):
            repository.backup_to(destination)
        active = True
        with pytest.raises(StorageError):
            repository.backup_to(tmp_path / "failed.grproj")
        assert not (tmp_path / "failed.grproj").exists()
        assert not list(tmp_path.glob(".grproj-*.tmp"))
        assert repository.load() == base


@pytest.mark.parametrize("edit", [
    lambda d: d.update(revision=True),
    lambda d: d.update(id=d["id"].upper()),
    lambda d: d.update(unknown_field=1),
    lambda d: d["paths"][0].update(visible=1),
    lambda d: d["source_files"][0].update(original_name=12),
    lambda d: d["source_files"][0]["jobs"][0]["energies"]["scf"].update(value_hartree=True),
    lambda d: d["source_files"][0]["jobs"][0]["metadata"].update(temperature_kelvin=float("nan")),
    lambda d: d["alias_bindings"]["R"].update(job_id="not-a-uuid"),
    lambda d: d["nodes"][0]["expression"].update(ast={"type": "call", "name": "evil"}),
], ids=["bool-revision", "uuid-case", "unknown-field", "bool-visible", "name-type", "bool-energy",
        "nan", "bad-ref", "unsafe-tree"])
def test_strict_decoder_rejects_malformed_snapshot(edit):
    data = snapshot_to_dict(project()[0])
    edit(data)
    with pytest.raises(StorageError, match="invalid_snapshot"):
        decode_project(json.dumps(data))


def test_duplicate_json_and_deep_json_rejected():
    for text in ('{"id":1,"id":2}', '{"x":Infinity}', '[' * 80 + '0' + ']' * 80):
        with pytest.raises(StorageError):
            decode_project(text)


def test_corrupt_rows_and_checksum_rejected(tmp_path):
    path = tmp_path / "corrupt.grproj"
    base, _, _ = project()
    with ProjectRepository(path, create=True) as repository:
        repository.save(base)
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE nodes SET payload=replace(payload,'TS1','tampered')")
    with pytest.raises(StorageError, match="snapshot_digest_mismatch"):
        ProjectRepository(path)


def test_autosave_debounce_close_and_named_save(tmp_path):
    base = workspace_project()
    phases = []
    with ProjectRepository(tmp_path / "main.grproj", create=True,
                           fault_injector=lambda stage: phases.append((stage, threading.get_ident()))) as main:
        service = RecoveryService(tmp_path / "recovery" / "session.grproj", repository=main, debounce_seconds=60)
        service.request(base)
        latest = replace(base, revision=8, plot_state={"view": "2d", "range": [0, 20]})
        service.request(latest)
        assert main.saved_revision is None and service.status.pending
        status = service.close()
        assert status.saved_revision == status.recovery_revision == 8
        assert not status.pending and status.error_code is None
        assert [stage for stage, _ in phases].count("before_commit") == 1
        assert len({ident for _, ident in phases}) == 1
        assert phases[0][1] != threading.get_ident()
        assert main.load() == latest
        with pytest.raises(StorageError, match="recovery_service_closed"):
            service.request(latest)
    candidates = list_recoveries(tmp_path / "recovery")
    assert len(candidates) == 1 and candidates[0].revision == 8
    with ProjectRepository(candidates[0].path, read_only=True) as recovery:
        session = restore_session(recovery)
        assert session.snapshot == latest
        assert all(c.state == "missing" for c in session.connections)
        assert session.snapshot.source_files[0].jobs
        assert not calculate_path(session.calculation_project, latest.paths[0].id).valid


def test_main_failure_has_separate_recoverable_revision_and_retry(tmp_path):
    base, _, _ = project()
    active = False
    def fail(stage):
        if active and stage == "before_commit":
            raise sqlite3.OperationalError("disk full")
    with ProjectRepository(tmp_path / "main.grproj", create=True, fault_injector=fail) as main:
        main.save(base)
        with RecoveryService(tmp_path / "recovery.grproj", repository=main, debounce_seconds=60) as service:
            active = True
            newer = replace(base, revision=1)
            service.request(newer)
            failed = service.flush()
            assert failed.saved_revision == 0 and failed.recovery_revision == 1
            assert failed.error_code == "storage_io_failed" and failed.pending
            assert main.load() == base
            active = False
            passed = service.flush()
            assert passed.saved_revision == 1 and not passed.pending and passed.error_code is None


def test_unnamed_project_and_interrupted_parse(tmp_path):
    base = workspace_project()
    base = replace(base, source_files=(replace(base.source_files[0], import_state=ImportState.READING),
                                       *base.source_files[1:]))
    with RecoveryService(tmp_path / "unnamed.grproj", debounce_seconds=60) as service:
        service.request(base)
        status = service.flush()
        assert status.saved_revision is None and status.recovery_revision == 7
    with ProjectRepository(tmp_path / "unnamed.grproj", read_only=True) as repository:
        restored = restore_session(repository)
        assert restored.snapshot == base
        assert restored.interrupted_source_ids == (base.source_files[0].id,)


def test_autosave_timer_runs(tmp_path):
    event = threading.Event()
    base, _, _ = project()
    with RecoveryService(tmp_path / "timer.grproj", debounce_seconds=.02,
                         recovery_fault_injector=lambda stage: event.set() if stage == "before_commit" else None) as service:
        service.request(base)
        assert event.wait(5)
    with ProjectRepository(tmp_path / "timer.grproj", read_only=True) as repository:
        assert repository.load() == base


def test_pure_stdlib_storage_import():
    root = str(Path(__file__).resolve().parents[1] / "src")
    code = "import sys; sys.path.insert(0,sys.argv[1]); import gaussianreadpro.storage; " \
           "assert not any(k.startswith(('PySide6','numpy','plotly')) for k in sys.modules)"
    subprocess.run([sys.executable, "-S", "-c", code, root], check=True)


def test_process_crash_in_transaction_restores_last_commit(tmp_path):
    base = workspace_project()
    path = tmp_path / "crash.grproj"
    with ProjectRepository(path, create=True) as repository:
        repository.save(base)
    code = """
import os, sys
from dataclasses import replace
from gaussianreadpro.storage import ProjectRepository
def die(stage):
    if stage == 'before_commit':
        os._exit(23)
r = ProjectRepository(sys.argv[1], fault_injector=die)
p = r.load()
r.save(replace(p, revision=p.revision+1, workspace_state={'unfinished': True}))
"""
    result = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True)
    assert result.returncode == 23, result.stderr
    with ProjectRepository(path) as repository:
        assert not repository.read_only  # OS releases the crashed process's writer lock.
        assert repository.load() == base
        repository.save(replace(base, revision=8))


def test_process_crash_after_autosave_recovers_draft(tmp_path):
    base = workspace_project()
    source = tmp_path / "input.grproj"
    recovery = tmp_path / "recovery" / "session.grproj"
    with ProjectRepository(source, create=True) as repository:
        repository.save(base)
    code = """
import os, sys
from gaussianreadpro.storage import ProjectRepository, RecoveryService
r = ProjectRepository(sys.argv[1], read_only=True)
s = RecoveryService(sys.argv[2], debounce_seconds=60)
s.request(r.load())
assert s.flush().recovery_revision == 7
os._exit(24)
"""
    result = subprocess.run([sys.executable, "-c", code, str(source), str(recovery)], capture_output=True, text=True)
    assert result.returncode == 24, result.stderr
    assert list_recoveries(recovery.parent)[0].revision == 7
    with ProjectRepository(recovery) as repository:
        assert repository.load() == base


def test_request_arriving_during_save_is_not_lost(tmp_path):
    base, _, _ = project()
    reached = threading.Event()
    release = threading.Event()
    active = False
    def block(stage):
        if active and stage == "before_commit":
            reached.set()
            assert release.wait(5)
    with ProjectRepository(tmp_path / "main.grproj", create=True, fault_injector=block) as repository:
        repository.save(base)
        service = RecoveryService(tmp_path / "recovery.grproj", repository=repository, debounce_seconds=.01)
        active = True
        try:
            service.request(replace(base, revision=1))
            assert reached.wait(5)
            newest = replace(base, revision=2, workspace_state={"latest": True})
            service.request(newest)
            assert service.status.current_revision == 2 and service.status.pending
        finally:
            release.set()
            status = service.close()
        assert status.saved_revision == status.recovery_revision == 2
        assert not status.pending
        assert repository.load() == newest


def test_recovery_failure_does_not_claim_it_saved(tmp_path):
    base, _, _ = project()
    def fail(stage):
        if stage == "before_commit":
            raise OSError("recovery directory full")
    with ProjectRepository(tmp_path / "main.grproj", create=True) as repository:
        with RecoveryService(tmp_path / "recovery.grproj", repository=repository, debounce_seconds=60,
                             recovery_fault_injector=fail) as service:
            service.request(base)
            status = service.flush()
            assert status.saved_revision == 0 and status.recovery_revision is None
            assert status.recovery_error_code == "storage_io_failed" and status.pending
            assert repository.load() == base


def test_recovery_namespace_and_revision_conflicts(tmp_path):
    base, _, _ = project()
    path = tmp_path / "main.grproj"
    recovery_path = tmp_path / "recovery.grproj"
    with ProjectRepository(path, create=True) as repository:
        repository.save(base)
        with pytest.raises(StorageError, match="recovery_requires_separate_file"):
            RecoveryService(path, repository=repository)
        with ProjectRepository(recovery_path, create=True) as recovery:
            recovery.save(replace(base, workspace_state={"different": True}))
            with pytest.raises(StorageError, match="recovery_locked"):
                RecoveryService(recovery_path, repository=repository)
        with pytest.raises(StorageError, match="recovery_revision_conflict"):
            RecoveryService(recovery_path, repository=repository)


def test_schema_change_while_open_blocks_save(tmp_path):
    base, _, _ = project()
    path = tmp_path / "schema-change.grproj"
    with ProjectRepository(path, create=True) as repository:
        repository.save(base)
        with sqlite3.connect(path) as connection:
            connection.execute("PRAGMA user_version=2")
        with pytest.raises(StorageError, match="newer_project_schema"):
            repository.save(replace(base, revision=1))
        assert repository.saved_revision == 0


def test_empty_recovery_can_be_reused_after_close_or_first_save_failure(tmp_path):
    path = tmp_path / "empty.grproj"
    with RecoveryService(path) as service:
        assert service.status.current_revision is None
    assert list_recoveries(tmp_path)[0].error_code == "empty_project"
    with RecoveryService(path, debounce_seconds=60) as service:
        service.request(project()[0])
        assert service.flush().recovery_revision == 0


def test_read_only_main_still_recovers_unsaved_edits(tmp_path):
    base, _, _ = project()
    path = tmp_path / "main.grproj"
    with ProjectRepository(path, create=True) as writer:
        writer.save(base)
        with ProjectRepository(path) as reader:
            with RecoveryService(tmp_path / "recovery.grproj", repository=reader, debounce_seconds=60) as service:
                service.request(replace(base, revision=1))
                status = service.flush()
                assert status.saved_revision == 0 and status.error_code == "project_read_only"
                assert status.recovery_revision == 1
            assert writer.load() == base


def test_backup_lock_timeout_is_bounded(tmp_path):
    base, _, _ = project()
    path = tmp_path / "main.grproj"
    with ProjectRepository(path, create=True, timeout=.01, backup_timeout=.05) as repository:
        repository.save(base)
        with sqlite3.connect(path) as rival:
            rival.execute("BEGIN EXCLUSIVE")
            with pytest.raises(StorageError, match="backup_timeout"):
                repository.backup_to(tmp_path / "copy.grproj")
            rival.rollback()
        assert repository.load() == base
        assert not (tmp_path / "copy.grproj").exists()


@pytest.mark.parametrize("name", ["dvb_ir.out", "dvb_sp.out", "dvb_gopt.out"])
def test_real_log_parse_snapshot_roundtrip(tmp_path, name):
    from gaussianreadpro.core import Project, parse_log
    source_path = Path(__file__).parent / "fixtures/reference" / name
    if not source_path.exists():
        # Fixture filenames must match the fixed S1 manifest, never silently skip coverage.
        raise AssertionError(str(source_path))
    source = parse_log(source_path).source
    before = Project(identifier("real-" + name), source_files=(source,))
    with ProjectRepository(tmp_path / "real.grproj", create=True) as repository:
        repository.save(before)
        assert repository.load() == before
        assert restore_session(repository).connections[0].state == "available"
