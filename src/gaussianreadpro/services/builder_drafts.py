"""Safe persistence for unapplied reaction-builder drafts."""
from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile
from uuid import UUID

from ..storage import StorageError


FORMAT = "gaussianreadpro.builder-draft"
VERSION = 1
MAX_BUILDER_DRAFT_BYTES = 2 * 1024 * 1024
_PAYLOAD_KEYS = {
    "project_id", "base_revision", "path_id", "generation", "network", "layout",
    "path_options", "legacy_mode",
}
_MODES = {"existing_recipe", "empty", "legacy_supported", "legacy_expert", "legacy_invalid"}


def _uuid(value, field):
    if not isinstance(value, str):
        raise StorageError("invalid_builder_draft", f"{field} must be a UUID")
    try:
        parsed = str(UUID(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise StorageError("invalid_builder_draft", f"{field} must be a UUID") from exc
    if parsed != value:
        raise StorageError("invalid_builder_draft", f"{field} must be a canonical UUID")
    return parsed


def validate_builder_draft(payload):
    """Validate a JSON-safe BuilderDraft snapshot, returning a detached dict."""
    if not isinstance(payload, Mapping) or set(payload) != _PAYLOAD_KEYS:
        raise StorageError("invalid_builder_draft", "Unexpected draft fields")
    result = dict(payload)
    _uuid(result["project_id"], "project_id")
    _uuid(result["path_id"], "path_id")
    if type(result["base_revision"]) is not int or result["base_revision"] < 0:
        raise StorageError("invalid_builder_draft", "base_revision must be a non-negative integer")
    if type(result["generation"]) is not int or result["generation"] < 0:
        raise StorageError("invalid_builder_draft", "generation must be a non-negative integer")
    if not isinstance(result["network"], dict) or not isinstance(result["layout"], dict):
        raise StorageError("invalid_builder_draft", "network and layout must be objects")
    if (not isinstance(result["path_options"], dict) or
            not isinstance(result["legacy_mode"], str) or result["legacy_mode"] not in _MODES):
        raise StorageError("invalid_builder_draft", "Invalid path options or legacy mode")
    try:
        json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise StorageError("invalid_builder_draft", str(exc)) from exc
    return result


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


class BuilderDraftStore:
    """UUID-addressed drafts stored under a session recovery directory."""

    def __init__(self, recovery_directory):
        self.recovery_directory = Path(recovery_directory).resolve()

    @staticmethod
    def _identity(project_id, path_id):
        return _uuid(project_id, "project_id"), _uuid(path_id, "path_id")

    def _path(self, project_id, path_id):
        project_id, path_id = self._identity(project_id, path_id)
        return self.recovery_directory / "ux-drafts" / project_id / f"{path_id}.json"

    @staticmethod
    def _encoded(payload):
        validated = validate_builder_draft(payload)
        envelope = {**validated, "format": FORMAT, "version": VERSION}
        encoded = json.dumps(envelope, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_BUILDER_DRAFT_BYTES:
            raise StorageError("builder_draft_too_large")
        return validated, encoded

    def save(self, payload):
        validated, encoded = self._encoded(payload)
        target = self._path(validated["project_id"], validated["path_id"])
        temporary = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="wb", prefix=f".{target.name}.",
                    suffix=".tmp", dir=target.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
            return target
        except OSError as exc:
            raise StorageError("builder_draft_write_failed", str(exc)) from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def load(self, project_id, path_id):
        target = self._path(project_id, path_id)
        try:
            if not target.exists():
                return None
            if target.stat().st_size > MAX_BUILDER_DRAFT_BYTES:
                raise StorageError("builder_draft_too_large")
            encoded = target.read_bytes()
            if len(encoded) > MAX_BUILDER_DRAFT_BYTES:
                raise StorageError("builder_draft_too_large")
            envelope = json.loads(encoded.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs,
                                  parse_constant=_reject_constant)
            if not isinstance(envelope, dict) or envelope.get("format") != FORMAT or envelope.get("version") != VERSION:
                raise ValueError("Unsupported builder draft format or version")
            payload = {key: value for key, value in envelope.items() if key not in {"format", "version"}}
            payload = validate_builder_draft(payload)
            expected_project, expected_path = self._identity(project_id, path_id)
            if payload["project_id"] != expected_project or payload["path_id"] != expected_path:
                raise StorageError("builder_draft_identity_mismatch")
            return payload
        except StorageError:
            raise
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
            raise StorageError("builder_draft_corrupt", str(exc)) from exc

    def remove(self, project_id, path_id, generation):
        target = self._path(project_id, path_id)
        if type(generation) is not int or generation < 0:
            raise StorageError("invalid_builder_draft", "generation must be a non-negative integer")
        current = self.load(project_id, path_id)
        if current is None or current["generation"] != generation:
            return False
        try:
            target.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise StorageError("builder_draft_remove_failed", str(exc)) from exc
