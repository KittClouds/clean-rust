"""CPU embeddings with pinned local model bytes; never an evidence authority."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path

from .identity import canonical, raw_id

DIMENSIONS = 384
MODEL_NAME = "BAAI/bge-small-en-v1.5"


class Embedder:
    def __init__(self, cache: Path) -> None:
        self.cache = cache.resolve()
        files = []
        for path in sorted(self.cache.rglob("*")):
            if path.is_file() and "snapshots" in path.parts and path.suffix in {".onnx", ".json", ".txt"}:
                with path.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                files.append({"path": path.relative_to(self.cache).as_posix(),
                              "sha256": digest, "bytes": path.stat().st_size})
        if not any(f["path"].endswith(".onnx") for f in files):
            raise ValueError("qualified embedding model is not installed locally")
        self.manifest = {"model": MODEL_NAME, "dimensions": DIMENSIONS, "files": files}
        self.identity = raw_id(canonical(self.manifest))
        self._model = None

    def encode(self, texts: list[str]) -> list[bytes]:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=MODEL_NAME, cache_dir=str(self.cache),
                                        local_files_only=True, threads=2)
        result = []
        for vector in self._model.embed(texts, batch_size=32):
            if len(vector) != DIMENSIONS:
                raise ValueError("unexpected embedding dimensions")
            result.append(struct.pack("<384f", *vector))
        return result


def unpack_vector(raw: bytes) -> list[float]:
    if len(raw) != DIMENSIONS * 4:
        raise ValueError("invalid embedding byte count")
    return list(struct.unpack("<384f", raw))
