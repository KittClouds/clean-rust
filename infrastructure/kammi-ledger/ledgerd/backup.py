"""Projection-free snapshot/restore of immutable authority inputs."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from .identity import canonical, strict_json


def backup(ledger, destination: Path) -> dict:
    destination = destination.resolve()
    if destination == ledger.root or ledger.root in destination.parents:
        raise ValueError("backup must be outside the live store")
    if destination.exists():
        raise ValueError("backup destination must be new")
    with ledger.lock:
        memory_lock = ledger.memory.lock if ledger.memory else ledger.lock
        with memory_lock:
            destination.mkdir(parents=True)
            files = []
            for relative in ("objects/sha256", "journal", "memory/journal", "configuration"):
                source = ledger.root / relative
                if not source.exists():
                    continue
                for path in sorted(source.rglob("*")):
                    if path.is_symlink():
                        raise ValueError("backup cannot follow symlinks")
                    if not path.is_file():
                        continue
                    rel = path.relative_to(ledger.root).as_posix()
                    target = destination / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("rb") as src, target.open("xb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                        dst.flush()
                        os.fsync(dst.fileno())
                    with target.open("rb") as copied:
                        digest = hashlib.file_digest(copied, "sha256").hexdigest()
                    files.append({"path": rel, "sha256": digest, "bytes": target.stat().st_size})
            manifest = {"schema": "KAMMI_BACKUP_V1", "journal_head": ledger.journal.head,
                        "memory_head": ledger.memory.journal.head if ledger.memory else None,
                        "files": files}
            (destination / "BACKUP.json").write_bytes(canonical(manifest))
            return manifest


def restore(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError("restore destination must be new")
    manifest = strict_json((source / "BACKUP.json").read_bytes())
    if manifest.get("schema") != "KAMMI_BACKUP_V1":
        raise ValueError("unknown backup schema")
    verified = []
    for entry in manifest["files"]:
        path = source / entry["path"]
        if not path.resolve().is_relative_to(source) or path.is_symlink():
            raise ValueError("unsafe backup path")
        if path.stat().st_size != entry["bytes"]:
            raise ValueError("backup byte count mismatch")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError("backup digest mismatch")
        verified.append((path, entry["path"]))
    if len({rel for _, rel in verified}) != len(verified):
        raise ValueError("duplicate backup path")
    destination.mkdir(parents=True)
    for path, rel in verified:
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return manifest
