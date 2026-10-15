"""Strict JSON decoding of the persisted model; never deserialize Python objects."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import StrEnum
import json
import math
import types
from typing import get_args, get_origin, get_type_hints

from ..core.models import Project, canonical_uuid, snapshot_to_dict

MAX_JSON_BYTES = 64 * 1024 * 1024


class StorageError(Exception):
    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _json_value(value, depth=0):
    if depth > 64:
        raise ValueError("JSON nesting limit exceeded")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, Mapping) and all(isinstance(k, str) for k in value):
        for item in value.values():
            _json_value(item, depth + 1)
        return
    raise ValueError("Expected bounded, finite JSON data")


def dumps(value):
    try:
        value = snapshot_to_dict(value)
        _json_value(value)
        result = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
        if len(result.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("JSON size limit exceeded")
        return result
    except (TypeError, ValueError, RecursionError) as exc:
        raise StorageError("invalid_snapshot", str(exc)) from exc


def loads(text):
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("JSON size limit exceeded")
        value = json.loads(text, object_pairs_hook=_pairs,
                           parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)))
        _json_value(value)
        return value
    except (TypeError, ValueError, RecursionError) as exc:
        raise StorageError("invalid_snapshot", str(exc)) from exc


def _decode(value, annotation):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is types.UnionType:
        if value is None and type(None) in args:
            return None
        for candidate in args:
            if candidate is type(None):
                continue
            try:
                return _decode(value, candidate)
            except (TypeError, ValueError):
                pass
        raise ValueError(f"Invalid union value for {annotation}")
    if annotation is Mapping or origin is Mapping:
        if type(value) is not dict:
            raise ValueError("Expected JSON object")
        if not args:
            return value
        return {_decode(k, args[0]): _decode(v, args[1]) for k, v in value.items()}
    if origin is tuple:
        if type(value) is not list:
            raise ValueError("Expected JSON array")
        return tuple(_decode(item, args[0]) for item in value)
    if annotation is float:
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError("Expected finite number, excluding bool")
        return float(value)
    if annotation in (str, int, bool):
        if type(value) is not annotation:
            raise ValueError(f"Expected {annotation.__name__}")
        return value
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if type(value) is not str:
            raise ValueError("Expected enum string")
        return annotation(value)
    if is_dataclass(annotation):
        if type(value) is not dict or set(value) != {f.name for f in fields(annotation)}:
            raise ValueError(f"Unexpected/missing fields in {annotation.__name__}")
        hints = get_type_hints(annotation)
        decoded = {key: _decode(item, hints[key]) for key, item in value.items()}
        for key in ("id", "node_id", "source_file_id", "job_id"):
            if key in decoded and canonical_uuid(decoded[key]) != decoded[key]:
                raise ValueError("Expected canonical lowercase UUID")
        return annotation(**decoded)
    raise ValueError(f"Unsupported persisted type: {annotation}")


def project_from_dict(value):
    try:
        _json_value(value)
        return _decode(value, Project)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise StorageError("invalid_snapshot", str(exc)) from exc


def decode_project(text):
    return project_from_dict(loads(text))
