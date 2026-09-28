"""Memory-mapped raw panel reader and fold-only normalization for v3."""
from __future__ import annotations

import hashlib
import mmap
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
for _path in (STUDY / "f4-invariant-01-impl-v2", STUDY / "f4-invariant-01-prefit-v2"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from f4_invariant_01_inputs import normalize_fold_inputs, shared_stream_hashes  # noqa: E402

BLOCKS = tuple(range(309000, 309012))
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
HEADER_BYTES = 32


@dataclass(frozen=True)
class RawPanel:
    keys: tuple[bytes, ...]
    blocks: np.ndarray
    base: np.ndarray
    tuples: np.ndarray


@dataclass(frozen=True)
class TruthPanel:
    inclusion_probability: np.ndarray
    y: np.ndarray
    native_delta: np.ndarray
    preweight: np.ndarray
    reference: np.ndarray


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_raw_panel(path: Path) -> RawPanel:
    with path.open("rb") as stream:
        mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            if len(mapping) < HEADER_BYTES or mapping[:16] != INPUT_MAGIC:
                raise RuntimeError("v3 predictor header mismatch")
            version, width, count = struct.unpack_from("<IIQ", mapping, 16)
            if version != 1 or width != INPUT_WIDTH or len(mapping) != HEADER_BYTES + count * INPUT_WIDTH:
                raise RuntimeError("v3 predictor dimensions mismatch")
            key_matrix = np.ndarray((count, 18), dtype="u1", buffer=mapping, offset=HEADER_BYTES, strides=(INPUT_WIDTH, 1)).copy()
            base = np.ndarray((count, 66), dtype="<f4", buffer=mapping, offset=HEADER_BYTES + 18, strides=(INPUT_WIDTH, 4)).copy()
            tuple_dtype = np.dtype([
                ("incidence", "u1"), ("role", "i1"), ("incidence_role", "i1"),
                ("delta", "<f4"), ("incidence_delta", "<f4"), ("role_delta", "<f4"),
            ], align=False)
            packed = np.ndarray((count, 4), dtype=tuple_dtype, buffer=mapping, offset=HEADER_BYTES + 18 + 66 * 4, strides=(INPUT_WIDTH, 15)).copy()
        finally:
            mapping.close()

    tuples = np.empty((count, 4, 6), dtype=np.float32)
    tuples[:, :, 0] = packed["incidence"].astype(np.float32)
    tuples[:, :, 1] = packed["role"].astype(np.float32)
    tuples[:, :, 2] = packed["incidence_role"].astype(np.float32)
    tuples[:, :, 3] = packed["delta"]
    tuples[:, :, 4] = packed["incidence_delta"]
    tuples[:, :, 5] = packed["role_delta"]
    keys = tuple(bytes(row) for row in key_matrix)
    if len(set(keys)) != count or not np.isfinite(base).all() or not np.isfinite(tuples).all():
        raise RuntimeError("v3 predictors contain duplicate keys or nonfinite values")
    blocks = np.fromiter((struct.unpack_from("<Q", key, 2)[0] for key in keys), dtype=np.uint64, count=count)
    if set(map(int, blocks)) != set(BLOCKS):
        raise RuntimeError("v3 predictor stream does not cover the frozen block panel")
    return RawPanel(keys=keys, blocks=blocks, base=base, tuples=tuples)


def _truth_header(path: Path, expected_count: int) -> int:
    with path.open("rb") as stream:
        header = stream.read(HEADER_BYTES)
    if len(header) != HEADER_BYTES or header[:16] != TRUTH_MAGIC:
        raise RuntimeError("v3 truth header mismatch")
    version, width, count = struct.unpack_from("<IIQ", header, 16)
    if version != 1 or width != TRUTH_WIDTH or count != expected_count or path.stat().st_size != HEADER_BYTES + count * TRUTH_WIDTH:
        raise RuntimeError("v3 truth dimensions mismatch")
    return count


def load_training_labels(keys: tuple[bytes, ...], heldout_block: int, truth_path: Path) -> np.ndarray:
    """Read labels only from training rows; skip all held-out truth payloads."""
    _truth_header(truth_path, len(keys))
    labels = np.empty(len(keys), dtype=np.float32)
    with truth_path.open("rb") as stream:
        stream.seek(HEADER_BYTES)
        for index, expected_key in enumerate(keys):
            key = stream.read(18)
            if key != expected_key:
                raise RuntimeError(f"v3 predictor/truth key mismatch at row {index}")
            if struct.unpack_from("<Q", key, 2)[0] == heldout_block:
                stream.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
                labels[index] = 0.0
                continue
            stream.seek(8, os.SEEK_CUR)
            target_raw = stream.read(1)
            if len(target_raw) != 1:
                raise RuntimeError("truncated v3 training target")
            target = struct.unpack("b", target_raw)[0]
            if target not in (-1, 1):
                raise RuntimeError(f"nonbinary v3 training target at row {index}")
            labels[index] = np.float32(target == 1)
            stream.seek(12, os.SEEK_CUR)
        if stream.tell() != HEADER_BYTES + len(keys) * TRUTH_WIDTH:
            raise RuntimeError("v3 training target reader offset mismatch")
    return labels


def load_scoring_truth(keys: tuple[bytes, ...], truth_path: Path) -> TruthPanel:
    """Read the full target/scoring stream after the caller's integrity gate."""
    _truth_header(truth_path, len(keys))
    raw = truth_path.read_bytes()
    for index, key in enumerate(keys):
        if raw[HEADER_BYTES + index * TRUTH_WIDTH:HEADER_BYTES + index * TRUTH_WIDTH + 18] != key:
            raise RuntimeError(f"v3 truth row key mismatch at row {index}")
    count = len(keys)
    inclusion_probability = np.ndarray(count, dtype="<f8", buffer=raw, offset=HEADER_BYTES + 18, strides=(TRUTH_WIDTH,)).copy()
    y = np.ndarray(count, dtype="i1", buffer=raw, offset=HEADER_BYTES + 26, strides=(TRUTH_WIDTH,)).copy()
    native = np.ndarray(count, dtype="<f4", buffer=raw, offset=HEADER_BYTES + 27, strides=(TRUTH_WIDTH,)).copy()
    preweight = np.ndarray(count, dtype="<f4", buffer=raw, offset=HEADER_BYTES + 31, strides=(TRUTH_WIDTH,)).copy()
    reference = np.ndarray(count, dtype="<f4", buffer=raw, offset=HEADER_BYTES + 35, strides=(TRUTH_WIDTH,)).copy()
    if not np.isfinite(inclusion_probability).all() or (inclusion_probability <= 0).any() or (inclusion_probability > 1.0).any() or not np.isin(y, (-1, 1)).all():
        raise RuntimeError("invalid v3 scoring weights or targets")
    if not np.isfinite(native).all() or not np.isfinite(preweight).all() or not np.isfinite(reference).all():
        raise RuntimeError("nonfinite v3 scoring sidecar")
    return TruthPanel(
        inclusion_probability=inclusion_probability,
        y=y,
        native_delta=native,
        preweight=preweight,
        reference=reference,
    )


def normalized_folds(raw: RawPanel) -> dict[int, Any]:
    output: dict[int, Any] = {}
    for fold, heldout in enumerate(BLOCKS):
        train_mask = raw.blocks != np.uint64(heldout)
        output[fold] = normalize_fold_inputs(raw.base, raw.tuples, train_mask, fold)
    return output


__all__ = [
    "BLOCKS", "INPUT_MAGIC", "INPUT_WIDTH", "RawPanel", "TRUTH_MAGIC", "TRUTH_WIDTH", "TruthPanel",
    "load_raw_panel", "load_scoring_truth", "load_training_labels", "normalized_folds", "sha_file",
    "shared_stream_hashes",
]
