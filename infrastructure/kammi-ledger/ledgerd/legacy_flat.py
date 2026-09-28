"""Read-only verifier for a legacy flat path/size/SHA-256 seal format."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .cas import COPY_BYTES


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while chunk := stream.read(COPY_BYTES):
            count += len(chunk)
            digest.update(chunk)
    return count, digest.hexdigest()


def verify_flat_seal(
    workspace_root: Path,
    seal_path: Path,
    *,
    expected_seal_sha256: str,
    expected_root_sha256: str,
) -> dict:
    workspace_root = workspace_root.resolve(strict=True)
    seal_bytes = seal_path.read_bytes()
    seal_sha = hashlib.sha256(seal_bytes).hexdigest()
    if seal_sha != expected_seal_sha256:
        raise ValueError("legacy seal file hash mismatch")
    seal = json.loads(seal_bytes)
    entries = seal["entries"]
    if len(entries) != seal["entry_count"]:
        raise ValueError("legacy seal declared count mismatch")
    if len({e["artifact_id"] for e in entries}) != len(entries):
        raise ValueError("duplicate legacy artifact ID")
    if entries != sorted(entries, key=lambda e: e["artifact_id"].encode("utf-8")):
        raise ValueError("legacy entry order mismatch")
    builder = hashlib.sha256()
    checked = 0
    missing: list[str] = []
    mismatched: list[str] = []
    for entry in entries:
        line = (
            f"{entry['artifact_id']}\t{entry['path']}\t"
            f"{entry['bytes']}\t{entry['sha256']}\n"
        )
        builder.update(line.encode("utf-8"))
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("legacy path escapes workspace")
        target = (workspace_root / relative).resolve()
        if not target.is_relative_to(workspace_root):
            raise ValueError("legacy path resolves outside workspace")
        if not target.is_file():
            missing.append(entry["artifact_id"])
            continue
        byte_count, digest = _hash_file(target)
        if byte_count != entry["bytes"] or digest != entry["sha256"]:
            mismatched.append(entry["artifact_id"])
            continue
        checked += 1
    root = builder.hexdigest()
    if root != seal["root_sha256"] or root != expected_root_sha256:
        raise ValueError("legacy root mismatch")
    return {
        "schema": "KAMMI_LEGACY_FLAT_VERIFICATION_V1",
        "seal_file_sha256": seal_sha,
        "legacy_root_sha256": root,
        "declared_entries": seal["entry_count"],
        "verified_entries": checked,
        "missing_artifact_ids": missing,
        "mismatched_artifact_ids": mismatched,
        "status": "PASS" if checked == len(entries) else "FAIL",
    }

