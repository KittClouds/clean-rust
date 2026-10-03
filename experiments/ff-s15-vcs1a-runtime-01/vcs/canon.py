"""Canonical JSON and content-derived identity. Standard library only; no clock, no randomness.

Everything the runtime emits (authority ids, envelope ids, receipts) is a hash of canonical bytes, so the same inputs give byte-identical outputs."""
from __future__ import annotations

import hashlib
import json
import math


class VcsError(ValueError):
    """Base class: a malformed, tampered-with or incompatible record. Never turned into a disposition."""


class SchemaMismatch(VcsError):
    pass


class NotBound(VcsError):
    """A scientific runner was asked to run without a frozen, externally owned schema."""


def _check(obj):
    if isinstance(obj, float) and not math.isfinite(obj):
        raise VcsError("non-finite number")
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise VcsError("object keys must be strings")
            _check(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _check(v)
    elif not (obj is None or isinstance(obj, (bool, int, float, str))):
        raise VcsError(f"not a JSON value: {type(obj).__name__}")


def canonical(obj) -> bytes:
    _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def derive_id(domain: str, obj) -> str:
    return "sha256:" + hashlib.sha256(domain.encode("ascii") + b"\0" + canonical(obj)).hexdigest()


def without(record: dict, *keys: str) -> dict:
    return {k: v for k, v in record.items() if k not in keys}


def seal(domain: str, id_field: str, record: dict) -> dict:
    out = dict(record)
    out[id_field] = derive_id(domain, without(record, id_field))
    return out


def verify_id(domain: str, id_field: str, record: dict) -> None:
    if record.get(id_field) != derive_id(domain, without(record, id_field)):
        raise VcsError(f"{id_field} does not match the record's content")


def loads_strict(data: bytes | str) -> object:
    """JSON with duplicate keys and non-finite numbers rejected."""
    def no_dupes(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise VcsError(f"duplicate key {k!r}")
            d[k] = v
        return d

    def bad(tok):
        raise VcsError(f"non-finite number {tok}")
    return json.loads(data, object_pairs_hook=no_dupes, parse_constant=bad)
