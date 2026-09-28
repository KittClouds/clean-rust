"""Bounded admin intake for large local artifacts without HTTP byte uploads."""
from __future__ import annotations

from pathlib import Path

from .graph import SAFE
from .identity import require_id


MAX_LOCAL_IMPORT_BYTES = 8 * 1024 * 1024 * 1024


def import_local_artifact(ledger, body: dict) -> tuple[str, str, int]:
    expected = require_id(body["expected_sha256"])
    expected_bytes = body["expected_bytes"]
    if (type(expected_bytes) is not int or not 0 <= expected_bytes <= MAX_LOCAL_IMPORT_BYTES):
        raise ValueError("invalid local artifact size")
    if any(not isinstance(body[key], str) or not SAFE.fullmatch(body[key])
           for key in ("kind", "actor", "request_id")):
        raise ValueError("invalid local artifact identity fields")
    source = Path(body["path"])
    if not source.is_absolute() or not source.is_file() or source.is_symlink():
        raise ValueError("local artifact must be an absolute ordinary file")
    if source.stat().st_size != expected_bytes:
        raise ValueError("local artifact size differs from declared identity")
    source = source.resolve(strict=True)
    artifact_id, byte_count = ledger.cas.put_file(source)
    if artifact_id != expected or byte_count != expected_bytes:
        raise ValueError("local artifact bytes differ from declared identity")
    payload = {
        "artifact_id": artifact_id,
        "byte_count": byte_count,
        "kind": body["kind"],
        "media_type": "application/octet-stream",
        "schema_id": "raw-v1",
        "source_location": str(source),
    }
    with ledger.lock:
        event_id = ledger._emit("ArtifactRegistered", payload, body["actor"], body["request_id"])
    return artifact_id, event_id, byte_count
