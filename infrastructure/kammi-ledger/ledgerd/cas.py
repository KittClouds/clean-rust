"""Immutable, streaming SHA-256 object store."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import BinaryIO

from .identity import require_id
from .faults import hit

COPY_BYTES = 1024 * 1024


class ContentStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / "objects" / "sha256"
        self.staging = root / "objects" / "staging"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

    def path_for(self, artifact_id: str) -> Path:
        digest = require_id(artifact_id)[7:]
        return self.objects / digest[:2] / digest[2:]

    def put_bytes(self, data: bytes) -> tuple[str, int]:
        from io import BytesIO

        return self.put_stream(BytesIO(data))

    def put_file(self, source: Path) -> tuple[str, int]:
        with source.open("rb") as stream:
            return self.put_stream(stream)

    def put_stream(self, stream: BinaryIO) -> tuple[str, int]:
        hit("cas.before_temp")
        digest = hashlib.sha256()
        size = 0
        fd, staged_name = tempfile.mkstemp(prefix="cas-", dir=self.staging)
        staged = Path(staged_name)
        try:
            with os.fdopen(fd, "wb") as output:
                while chunk := stream.read(COPY_BYTES):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
                    hit("cas.during_temp")
                output.flush()
                os.fsync(output.fileno())
            hit("cas.after_fsync")
            artifact_id = "sha256:" + digest.hexdigest()
            target = self.path_for(artifact_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not self.verify(artifact_id):
                    raise ValueError(f"existing CAS object is corrupt: {artifact_id}")
            else:
                os.replace(staged, target)
            hit("cas.after_rename")
            return artifact_id, size
        finally:
            staged.unlink(missing_ok=True)

    def get(self, artifact_id: str) -> bytes:
        if not self.verify(artifact_id):
            raise ValueError(f"missing or corrupt CAS object: {artifact_id}")
        return self.path_for(artifact_id).read_bytes()

    def verify(self, artifact_id: str) -> bool:
        path = self.path_for(artifact_id)
        if not path.is_file() or path.is_symlink():
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(COPY_BYTES):
                digest.update(chunk)
        return digest.hexdigest() == artifact_id[7:]

