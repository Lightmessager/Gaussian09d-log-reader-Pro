"""Portable project snapshots and selected logs; bounded, traversal-safe import."""
from dataclasses import replace
from pathlib import Path, PurePosixPath, PureWindowsPath
import os
import shutil
import stat
import tempfile
import zipfile

from .codec import StorageError, dumps, loads
from .repository import ProjectRepository, publish_new_file
from .sources import fingerprint, inspect_sources


def export_bundle(repository, destination, *, include_source_ids=()):
    destination = Path(destination).resolve()
    if destination.exists():
        raise StorageError("destination_exists", str(destination))
    temporary = None
    try:
        with tempfile.TemporaryDirectory(prefix="grproj-export-") as directory:
            root = Path(directory)
            project_path = repository.backup_to(root / "project.grproj")
            with ProjectRepository(project_path) as copy:
                project = copy.load()
                selected = set(include_source_ids)
                if not selected <= {source.id for source in project.source_files}:
                    raise StorageError("unknown_source")
                subset = replace(project, source_files=tuple(s for s in project.source_files if s.id in selected))
                connections = {item.source_file_id: item for item in inspect_sources(subset, repository.path.parent)}
                sources = []
                included = []
                for source in project.source_files:
                    if source.id not in selected:
                        sources.append(source)
                        continue
                    connection = connections[source.id]
                    if connection.state != "available":
                        raise StorageError("source_not_verified", source.id)
                    relative = "sources/" + source.id + ".log"
                    target = root / relative
                    target.parent.mkdir(exist_ok=True)
                    shutil.copyfile(connection.path, target)
                    digest, size, mtime = fingerprint(target)
                    if digest != source.sha256:
                        raise StorageError("source_changed_during_export", source.id)
                    sources.append(replace(source, relative_path=relative, size_bytes=size, mtime_ns=mtime))
                    included.append(relative)
                if selected:
                    # Path transport is a deliberate change of snapshot, not a same-revision overwrite.
                    copy.save(replace(project, source_files=tuple(sources), revision=project.revision + 1))
            fd, temporary = tempfile.mkstemp(prefix=".grpack-", suffix=".tmp", dir=destination.parent)
            os.close(fd)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", dumps({"format": "gaussianreadpro.bundle", "version": 1,
                                                        "source_ids": sorted(selected)}))
                for name in ["project.grproj", *included]:
                    archive.write(root / name, name)
            with open(temporary, "r+b") as handle:
                os.fsync(handle.fileno())
            publish_new_file(temporary, destination)
            return destination
    except (OSError, zipfile.BadZipFile) as exc:
        raise StorageError("bundle_export_failed", str(exc)) from exc
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def _safe_names(infos, max_bytes, max_files):
    if len(infos) > max_files or sum(info.file_size for info in infos) > max_bytes:
        raise StorageError("bundle_size_limit")
    seen = set()
    for info in infos:
        name = info.filename
        if name == "manifest.json" and info.file_size > 1024 * 1024:
            raise StorageError("bundle_size_limit")
        pure = PurePosixPath(name)
        mode = info.external_attr >> 16
        if (not name or "\\" in name or ":" in name or pure.is_absolute()
                or PureWindowsPath(name).drive or ".." in pure.parts
                or str(pure) != name or name.casefold() in seen
                or stat.S_ISLNK(mode) or info.is_dir()
                or info.flag_bits & 1):
            raise StorageError("unsafe_bundle_path", name)
        if name not in ("project.grproj", "manifest.json") and not (
                len(pure.parts) == 2 and pure.parts[0] == "sources" and pure.suffix == ".log"):
            raise StorageError("unexpected_bundle_member", name)
        seen.add(name.casefold())
    if "project.grproj" not in seen:
        raise StorageError("bundle_project_missing")
    if "manifest.json" not in seen:
        raise StorageError("bundle_manifest_missing")


def import_bundle(archive_path, destination, *, max_bytes=1024 * 1024 * 1024, max_files=10000):
    """Extract to a staging directory, validate fully, then publish an entire new directory."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise StorageError("destination_exists", str(destination))
    try:
        with tempfile.TemporaryDirectory(prefix=".grimport-", dir=destination.parent) as directory:
            staging = Path(directory) / "content"
            staging.mkdir()
            with zipfile.ZipFile(archive_path, "r") as archive:
                infos = archive.infolist()
                _safe_names(infos, max_bytes, max_files)
                remaining = max_bytes
                for info in infos:
                    target = staging / info.filename
                    target.parent.mkdir(exist_ok=True)
                    written = 0
                    with archive.open(info) as source, target.open("xb") as output:
                        while chunk := source.read(65536):
                            remaining -= len(chunk)
                            written += len(chunk)
                            if remaining < 0 or written > info.file_size:
                                raise StorageError("bundle_size_limit")
                            output.write(chunk)
            with ProjectRepository(staging / "project.grproj", read_only=True) as repository:
                project = repository.load()
            manifest = loads((staging / "manifest.json").read_text(encoding="utf-8"))
            if (type(manifest) is not dict or set(manifest) != {"format", "version", "source_ids"}
                    or manifest["format"] != "gaussianreadpro.bundle" or type(manifest["version"]) is not int
                    or manifest["version"] != 1 or type(manifest["source_ids"]) is not list
                    or any(type(identity) is not str for identity in manifest["source_ids"])
                    or len(manifest["source_ids"]) != len(set(manifest["source_ids"]))):
                raise StorageError("invalid_bundle_manifest")
            expected = {"sources/" + source.id + ".log": source for source in project.source_files}
            declared = {"sources/" + identity + ".log" for identity in manifest["source_ids"]}
            members = {info.filename for info in infos} - {"project.grproj", "manifest.json"}
            if members != declared or not declared <= set(expected):
                raise StorageError("bundle_attachment_mismatch")
            for info in infos:
                if info.filename in ("project.grproj", "manifest.json"):
                    continue
                source = expected.get(info.filename)
                if source is None or source.relative_path != info.filename:
                    raise StorageError("unexpected_bundle_source", info.filename)
                digest, size, _ = fingerprint(staging / info.filename)
                if source.sha256 != digest or source.size_bytes is not None and source.size_bytes != size:
                    raise StorageError("bundle_fingerprint_mismatch", source.id)
            if destination.exists():
                raise StorageError("destination_exists", str(destination))
            staging.rename(destination)
        return destination / "project.grproj"
    except (OSError, UnicodeError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise StorageError("bundle_import_failed", str(exc)) from exc
