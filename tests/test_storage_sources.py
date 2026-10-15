from dataclasses import replace
from pathlib import Path
import shutil
import stat
import zipfile

import pytest

from gaussianreadpro.core import (EnergyRef, PathEntry, ProfileNode, Project, ReactionPath,
                                  calculate_path, compile_expression, parse_log)
from gaussianreadpro.storage import (ProjectRepository, StorageError, export_bundle, import_bundle,
                                    inspect_sources, reconnect_directory, reconnect_source, restore_session)
from gaussianreadpro.storage.preferences import LocalPreferences
from s2_helpers import identifier


def parsed_project(directory):
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / "真实 名称.log"
    log.write_text("SYNTHETIC S3 TEST\nEntering Gaussian System\n"
                   " SCF Done: E(RB3LYP) = -10.030000 A.U.\n"
                   " Thermal correction to Gibbs Free Energy= .03\n"
                   " Sum of electronic and thermal Free Energies= -10.0\n"
                   " Normal termination of Gaussian 16\n", encoding="utf-8")
    source = parse_log(log).source
    source = replace(source, relative_path=log.name)
    ref = EnergyRef(source.id, source.jobs[0].id)
    expression = compile_expression("@{R}", {"R": ref}).expression
    node = ProfileNode(identifier("s3-parsed-node"), "R", expression)
    path = ReactionPath(identifier("s3-parsed-path"), "Reaction",
                        (PathEntry(identifier("s3-parsed-entry"), node.id, 0),), reference_expression=expression)
    return Project(identifier("s3-parsed-project"), (source,), (node,), (path,), alias_bindings={"R": ref}), log


def test_relative_move_same_hash_reconnect_preserves_identity(tmp_path):
    old = tmp_path / "old"
    before, log = parsed_project(old)
    with ProjectRepository(old / "project.grproj", create=True) as repository:
        repository.save(before)
    new = tmp_path / "new"
    old.rename(new)
    with ProjectRepository(new / "project.grproj") as repository:
        session = restore_session(repository)
        assert session.snapshot == before
        assert session.connections[0].state == "available"
        assert session.connections[0].path == new / log.name
        assert calculate_path(session.calculation_project, before.paths[0].id).valid
        other = tmp_path / "relocated"
        other.mkdir()
        moved = other / "different-name.out"
        (new / log.name).rename(moved)
        missing = restore_session(repository)
        assert missing.connections[0].state == "missing"
        assert missing.snapshot == before
        assert not calculate_path(missing.calculation_project, before.paths[0].id).valid
        change = reconnect_source(before, before.source_files[0].id, moved, new)
        after = change.apply(before)
        assert after.revision == 1
        assert after.source_files[0].jobs == before.source_files[0].jobs
        assert after.nodes == before.nodes and after.alias_bindings == before.alias_bindings
        assert after.source_files[0].relative_path == "../relocated/different-name.out"
        repository.save(after)
        assert restore_session(repository).connections[0].state == "available"


def test_changed_same_name_unverified_and_snapshot_retention(tmp_path):
    before, log = parsed_project(tmp_path)
    before_hash = before.source_files[0].sha256
    with ProjectRepository(tmp_path / "project.grproj", create=True) as repository:
        repository.save(before)
        log.write_text("Different log with the same filename", encoding="utf-8")
        session = restore_session(repository)
        assert session.connections[0].state == "changed"
        assert session.snapshot.source_files[0].sha256 == before_hash
        assert session.snapshot.source_files[0].jobs == before.source_files[0].jobs
        assert not calculate_path(session.calculation_project, before.paths[0].id).valid
        with pytest.raises(StorageError, match="fingerprint_mismatch"):
            reconnect_source(before, before.source_files[0].id, log, tmp_path)
    unknown = replace(before, source_files=(replace(before.source_files[0], sha256=None),))
    assert inspect_sources(unknown, tmp_path)[0].state == "unverified"
    with pytest.raises(StorageError, match="fingerprint_unavailable"):
        reconnect_source(unknown, before.source_files[0].id, log, tmp_path)


def test_directory_scan_hashes_and_ambiguity(tmp_path):
    before, log = parsed_project(tmp_path / "old")
    target = tmp_path / "new"
    target.mkdir()
    new_log = target / "renamed.out"
    log.rename(new_log)
    plan = reconnect_directory(before, target, tmp_path)
    assert plan.change.project.revision == 1
    assert plan.unmatched == plan.ambiguous == ()
    shutil.copyfile(new_log, target / "duplicate.log")
    ambiguous = reconnect_directory(before, target, tmp_path)
    assert ambiguous.change is None and ambiguous.ambiguous == (before.source_files[0].id,)
    with pytest.raises(StorageError, match="source_scan_limit"):
        reconnect_directory(before, target, tmp_path, max_files=1)


@pytest.mark.parametrize("include", [False, True])
def test_portable_bundle_with_and_without_logs(tmp_path, include):
    base, log = parsed_project(tmp_path / "original")
    source_id = base.source_files[0].id
    with ProjectRepository(log.parent / "project.grproj", create=True) as repository:
        repository.save(base)
        bundle = export_bundle(repository, tmp_path / "travel.grpack",
                               include_source_ids=[source_id] if include else [])
        assert repository.load() == base
    log.unlink()
    project_path = import_bundle(bundle, tmp_path / "imported")
    with ProjectRepository(project_path, read_only=True) as repository:
        session = restore_session(repository)
        assert session.snapshot.nodes == base.nodes and session.snapshot.alias_bindings == base.alias_bindings
        assert session.connections[0].state == ("available" if include else "missing")
        assert calculate_path(session.calculation_project, base.paths[0].id).valid is include
        assert session.snapshot.revision == (1 if include else 0)
    with pytest.raises(StorageError, match="destination_exists"):
        import_bundle(bundle, tmp_path / "imported")


@pytest.mark.parametrize("member", ["../escape.log", "/absolute.log", "C:/escape.log", "sources\\escape.log",
                                     "sources/../../escape.log", "other.py", "sources/./escape.log"])
def test_import_rejects_traversal_and_unexpected_members(tmp_path, member):
    archive = tmp_path / "unsafe.grpack"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("project.grproj", b"not even sqlite")
        bundle.writestr(member, b"unsafe")
    with pytest.raises(StorageError):
        import_bundle(archive, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()
    assert not (tmp_path / "escape.log").exists()
    assert not list(tmp_path.glob(".grimport-*"))


def test_import_symlink_size_and_hash_validation(tmp_path):
    unsafe = tmp_path / "symlink.grpack"
    with zipfile.ZipFile(unsafe, "w") as bundle:
        info = zipfile.ZipInfo("sources/link.log")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, "../../outside")
        bundle.writestr("project.grproj", "x")
    with pytest.raises(StorageError, match="unsafe_bundle_path"):
        import_bundle(unsafe, tmp_path / "symlink-output")
    base, log = parsed_project(tmp_path / "original")
    with ProjectRepository(log.parent / "project.grproj", create=True) as repository:
        repository.save(base)
        good = export_bundle(repository, tmp_path / "good.grpack", include_source_ids=[base.source_files[0].id])
    with pytest.raises(StorageError, match="bundle_size_limit"):
        import_bundle(good, tmp_path / "too-big", max_bytes=10)
    bad = tmp_path / "bad.grpack"
    with zipfile.ZipFile(good) as input_file, zipfile.ZipFile(bad, "w") as output:
        for name in input_file.namelist():
            output.writestr(name, input_file.read(name) if name in ("project.grproj", "manifest.json") else b"changed")
    with pytest.raises(StorageError, match="bundle_fingerprint_mismatch"):
        import_bundle(bad, tmp_path / "bad-output")
    assert not (tmp_path / "bad-output").exists()


def test_local_preferences_language_and_state_are_separate(tmp_path):
    path = tmp_path / "preferences.ini"
    preferences = LocalPreferences(path)
    assert preferences.load()["language"] == "system"
    preferences.save(language="en", theme="dark", recent_projects=[str(tmp_path / "project.grproj")],
                     window_geometry="opaque-qt-geometry", default_export_directory=str(tmp_path))
    assert LocalPreferences(path).load() == preferences.load()
    with pytest.raises(StorageError, match="invalid_preferences"):
        preferences.save(language="invalid")
    assert LocalPreferences(path).load()["language"] == "en"
    preferences.remember_project(tmp_path / "first.grproj")
    preferences.remember_project(tmp_path / "second.grproj")
    preferences.remember_project(tmp_path / "first.grproj")
    assert preferences.last_project == tmp_path / "first.grproj"
    assert len(preferences.load()["recent_projects"]) == 3


def test_save_as_rebases_after_original_project_was_moved(tmp_path):
    before, log = parsed_project(tmp_path / "original")
    with ProjectRepository(log.parent / "project.grproj", create=True) as repository:
        repository.save(before)
    moved = tmp_path / "moved"
    log.parent.rename(moved)
    destination = tmp_path / "copies" / "copy.grproj"
    destination.parent.mkdir()
    with ProjectRepository(moved / "project.grproj") as repository:
        assert restore_session(repository).connections[0].state == "available"
        assert repository.save_as(destination) == destination
        assert repository.load() == before
        with ProjectRepository(destination) as copy:
            session = restore_session(copy)
            assert session.connections[0].state == "available"
            assert session.connections[0].path == moved / log.name
            assert session.snapshot.revision == 1
            assert session.snapshot.nodes == before.nodes
            assert session.snapshot.source_files[0].jobs == before.source_files[0].jobs
        with pytest.raises(StorageError, match="destination_exists"):
            repository.save_as(destination)


def test_reexport_imported_project_without_logs_does_not_infer_attachments(tmp_path):
    base, log = parsed_project(tmp_path / "original")
    with ProjectRepository(log.parent / "project.grproj", create=True) as repository:
        repository.save(base)
        first = export_bundle(repository, tmp_path / "first.grpack", include_source_ids=[base.source_files[0].id])
    imported = import_bundle(first, tmp_path / "first-import")
    with ProjectRepository(imported, read_only=True) as repository:
        second = export_bundle(repository, tmp_path / "second.grpack")
    log.unlink()
    second_import = import_bundle(second, tmp_path / "second-import")
    with ProjectRepository(second_import, read_only=True) as repository:
        session = restore_session(repository)
        assert session.connections[0].state == "missing"
        assert session.snapshot.nodes == base.nodes
    with zipfile.ZipFile(second) as archive:
        assert set(archive.namelist()) == {"project.grproj", "manifest.json"}


def test_bundle_declared_attachment_must_exist(tmp_path):
    base, log = parsed_project(tmp_path / "original")
    with ProjectRepository(log.parent / "project.grproj", create=True) as repository:
        repository.save(base)
        good = export_bundle(repository, tmp_path / "good.grpack", include_source_ids=[base.source_files[0].id])
    missing = tmp_path / "missing.grpack"
    with zipfile.ZipFile(good) as input_file, zipfile.ZipFile(missing, "w") as output:
        for name in ("project.grproj", "manifest.json"):
            output.writestr(name, input_file.read(name))
    with pytest.raises(StorageError, match="bundle_attachment_mismatch"):
        import_bundle(missing, tmp_path / "missing-output")
    assert not (tmp_path / "missing-output").exists()
