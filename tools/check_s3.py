"""S3 end-to-end storage/recovery oracle; all generated logs are SYNTHETIC."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import sqlite3
import sys
from time import perf_counter
from uuid import NAMESPACE_URL, uuid4, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gaussianreadpro.core import (EnergyRef, PathEntry, ProfileNode, Project, ReactionPath,
                                  calculate_path, compile_expression, edit_expression, parse_log)
from gaussianreadpro.storage import (ProjectRepository, RecoveryService, StorageError, export_bundle,
                                    import_bundle, list_recoveries, reconnect_source, restore_session)
from gaussianreadpro.storage.codec import dumps
from gaussianreadpro.storage.preferences import LocalPreferences
from gaussianreadpro.storage.repository import APPLICATION_ID


def identifier(label):
    return str(uuid5(NAMESPACE_URL, "gaussianreadpro-s3-demo:" + label))


def main():
    start = perf_counter()
    output = ROOT / "artifacts/s3"
    run = output / "runs" / uuid4().hex
    logs = run / "logs"
    logs.mkdir(parents=True)
    values = {"R": -150., "TS1": -149.976, "I1": -150.008, "P": -150.025}
    sources = []
    for label, value in values.items():
        log = logs / (label + ".log")
        log.write_text("SYNTHETIC S3 DEMO - not real Gaussian output\nEntering Gaussian System\n"
                       f" SCF Done: E(RB3LYP) = {value - .03:.12f} A.U.\n"
                       " Thermal correction to Gibbs Free Energy= .030000\n"
                       f" Sum of electronic and thermal Free Energies= {value:.12f}\n"
                       " Normal termination of Gaussian 16\n", encoding="utf-8")
        source = parse_log(log, identifier(label)).source
        sources.append(replace(source, relative_path="logs/" + log.name))
    aliases = {s.display_name: EnergyRef(s.id, s.jobs[0].id) for s in sources}
    nodes = tuple(ProfileNode(identifier("node:" + s.display_name), s.display_name,
                              compile_expression("@{" + s.display_name + "}", aliases).expression) for s in sources)
    entries = tuple(PathEntry(identifier("entry:" + n.label), n.id, i) for i, n in enumerate(nodes))
    path = ReactionPath(identifier("path"), "Synthetic reaction", entries, reference_expression=nodes[0].expression)
    base = Project(identifier("project"), tuple(sources), nodes, (path,), alias_bindings=aliases)
    expected = [0., .024, -.008, -.025]
    oracle = calculate_path(base, path.id)
    assert oracle.valid and all(abs(n.relative_hartree - x) < 1e-12 for n, x in zip(oracle.nodes, expected))
    second = replace(path, id=identifier("path2"), label="Second path",
                     reference_expression=nodes[-1].expression,
                     entries=tuple(replace(e, id=identifier("second:" + e.id), position=i)
                                   for i, e in enumerate(reversed(entries))))
    draft = replace(nodes[1], expression=edit_expression(nodes[1].expression, "@{TS1} + (", aliases))
    edited = replace(base, revision=1, nodes=(nodes[0], draft, *nodes[2:]), paths=(path, second),
                     workspace_state={"page": "advanced", "selected_node": draft.id, "filter": "TS", "splitter": [260, 900]},
                     plot_state={"view": "3d", "camera": {"eye": {"x": 1.4, "y": 1.8, "z": .7}}, "range": [-20, 30]})
    preferences = LocalPreferences(run / "preferences.ini")
    preferences.save(language="en", theme="dark")
    project_path = run / "demo.grproj"
    preferences.remember_project(project_path)
    active_fault = False
    def fail(stage):
        if active_fault and stage == "before_commit":
            raise sqlite3.OperationalError("S3 injected disk full")
    with ProjectRepository(project_path, create=True, fault_injector=fail) as repository:
        repository.save(base)
        with RecoveryService(run / "recovery/session.grproj", repository=repository, debounce_seconds=60) as service:
            service.request(edited)
            status = service.flush()
            assert status.saved_revision == status.recovery_revision == 1
    with ProjectRepository(project_path, fault_injector=fail) as repository:
        restored = restore_session(repository)
        assert restored.snapshot == edited
        assert all(c.state == "available" for c in restored.connections)
        assert preferences.last_project == repository.path
        assert LocalPreferences(run / "preferences.ini").load()["language"] == "en"
        assert not calculate_path(restored.calculation_project, path.id).valid  # The restored draft stays invalid.
        moved = run / "relocated" / "renamed-R.out"
        moved.parent.mkdir()
        (logs / "R.log").rename(moved)
        missing = restore_session(repository)
        assert missing.connections[0].state == "missing" and missing.snapshot == edited
        reconnected = reconnect_source(edited, sources[0].id, moved, run).apply(edited)
        repository.save(reconnected)
        assert all(c.state == "available" for c in restore_session(repository).connections)
        with ProjectRepository(project_path) as reader:
            assert reader.read_only and reader.load() == reconnected
        copy_dir = run / "save-as"
        copy_dir.mkdir()
        copy_path = repository.save_as(copy_dir / "copy.grproj")
        with ProjectRepository(copy_path, read_only=True) as copy:
            assert all(c.state == "available" for c in restore_session(copy).connections)
        bundle = export_bundle(repository, run / "portable.grpack", include_source_ids=[s.id for s in sources])
        imported = import_bundle(bundle, run / "imported")
        with ProjectRepository(imported, read_only=True) as copy:
            session = restore_session(copy)
            assert all(c.state == "available" and c.path.parent.name == "sources" for c in session.connections)
            assert session.snapshot.nodes == reconnected.nodes
        with RecoveryService(run / "recovery/session.grproj", repository=repository, debounce_seconds=60) as service:
            newer = replace(reconnected, revision=3, workspace_state={**reconnected.workspace_state, "unsaved_edit": True})
            active_fault = True
            service.request(newer)
            failed_status = service.flush()
            assert failed_status.saved_revision == 2 and failed_status.recovery_revision == 3
            assert failed_status.error_code == "storage_io_failed"
            assert repository.load() == reconnected
            active_fault = False
            retry_status = service.flush()
            assert retry_status.saved_revision == 3 and retry_status.error_code is None
    legacy_path = run / "legacy-v0.grproj"
    with sqlite3.connect(legacy_path) as connection:
        connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
        connection.execute("CREATE TABLE legacy_project(id INTEGER PRIMARY KEY,payload TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_project VALUES(1,?)", (dumps(edited),))
    def fail_migration(stage):
        if stage == "before_migration_commit":
            raise sqlite3.OperationalError("S3 injected migration failure")
    try:
        ProjectRepository(legacy_path, fault_injector=fail_migration)
    except StorageError:
        pass
    else:
        raise AssertionError("Migration fault was not observed")
    with sqlite3.connect(legacy_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (0,)
        assert connection.execute("SELECT payload FROM legacy_project").fetchone()[0] == dumps(edited)
    with ProjectRepository(legacy_path) as repository:
        assert repository.load() == edited and repository.migration_backup.exists()
    report = {"stage": "S3", "passed": True, "data_kind": "synthetic demo only",
              "project": str(project_path), "run_directory": str(run),
              "checks": {"two_paths_draft_order_view_restored": True, "local_language_en_restored": True,
                         "missing_snapshot_retained": True, "hash_reconnection_preserved_ids": True,
                         "second_instance_read_only": True, "save_as_paths_verified": True,
                         "portable_logs_verified": True, "migration_rollback_and_backup": True},
              "golden_relative_hartree": [n.relative_hartree for n in oracle.nodes],
              "failed_save_status": asdict(failed_status), "retry_status": asdict(retry_status),
              "recovery_candidates": [{"revision": c.revision, "error_code": c.error_code}
                                      for c in list_recoveries(run / "recovery")],
              "elapsed_ms": (perf_counter() - start) * 1000}
    (output / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
