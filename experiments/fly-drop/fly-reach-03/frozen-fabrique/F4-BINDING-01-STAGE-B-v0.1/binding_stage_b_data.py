"""Binary row readers and saved parent-normalizer application for Stage B."""
from __future__ import annotations

import hashlib
import mmap
import os
import struct
from dataclasses import dataclass
from pathlib import Path

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

BLOCK_IDS = tuple(range(310000, 310024))
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
PRED_MAGIC = b"F4BINDPREDB01\0\0\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
PRED_WIDTH = 30
HEADER_WIDTH = 32
NORM_MAGIC = b"F4INV01NORMv1\0\0\0"
ASSIGNMENT_ORDER = ("1100", "1010", "0110", "1001", "0101", "0011")


@dataclass(frozen=True)
class PredictorPanel:
    keys: tuple[bytes, ...]
    blocks: np.ndarray
    substrates: np.ndarray
    sides: np.ndarray
    base: np.ndarray
    tuples: np.ndarray


@dataclass(frozen=True)
class ScoringTruth:
    inclusion_probability: np.ndarray
    y: np.ndarray
    native_delta: np.ndarray
    preweight: np.ndarray
    reference: np.ndarray


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def array_sha(value: np.ndarray) -> str:
    array = np.ascontiguousarray(value)
    identity = array.dtype.str.encode("ascii") + b"\0" + struct.pack("<I", array.ndim)
    identity += struct.pack("<" + "Q" * array.ndim, *array.shape)
    return sha_bytes(identity + array.tobytes(order="C"))


def _header(path: Path, magic: bytes, width: int) -> int:
    with path.open("rb") as stream:
        header = stream.read(HEADER_WIDTH)
    if len(header) != HEADER_WIDTH or header[:16] != magic:
        raise RuntimeError(f"binary header mismatch: {path.name}")
    version, actual_width, count = struct.unpack_from("<IIQ", header, 16)
    if version != 1 or actual_width != width or path.stat().st_size != HEADER_WIDTH + count * width:
        raise RuntimeError(f"binary dimensions mismatch: {path.name}")
    return int(count)


def load_predictors(path: Path, expected_blocks: tuple[int, ...] = BLOCK_IDS) -> PredictorPanel:
    count = _header(path, INPUT_MAGIC, INPUT_WIDTH)
    if count <= 0:
        raise RuntimeError("Stage B predictor panel is empty")
    with path.open("rb") as stream:
        mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            key_matrix = np.ndarray((count, 18), dtype="u1", buffer=mapping, offset=HEADER_WIDTH, strides=(INPUT_WIDTH, 1)).copy()
            base = np.ndarray((count, 66), dtype="<f4", buffer=mapping, offset=HEADER_WIDTH + 18, strides=(INPUT_WIDTH, 4)).copy()
            tuple_dtype = np.dtype([
                ("incidence", "u1"), ("role", "i1"), ("incidence_role", "i1"),
                ("delta", "<f4"), ("incidence_delta", "<f4"), ("role_delta", "<f4"),
            ], align=False)
            packed = np.ndarray((count, 4), dtype=tuple_dtype, buffer=mapping, offset=HEADER_WIDTH + 18 + 66 * 4, strides=(INPUT_WIDTH, 15)).copy()
        finally:
            mapping.close()
    keys = tuple(bytes(row) for row in key_matrix)
    if len(set(keys)) != count:
        raise RuntimeError("duplicate Stage B row keys")
    tuples = np.empty((count, 4, 6), dtype=np.float32)
    tuples[:, :, 0] = packed["incidence"].astype(np.float32)
    tuples[:, :, 1] = packed["role"].astype(np.float32)
    tuples[:, :, 2] = packed["incidence_role"].astype(np.float32)
    tuples[:, :, 3] = packed["delta"]
    tuples[:, :, 4] = packed["incidence_delta"]
    tuples[:, :, 5] = packed["role_delta"]
    substrates = key_matrix[:, 0].astype(np.uint8)
    sides = key_matrix[:, 1].astype(np.uint8)
    blocks = np.fromiter((struct.unpack_from("<Q", key, 2)[0] for key in keys), dtype=np.uint64, count=count)
    if not np.isfinite(base).all() or not np.isfinite(tuples).all():
        raise RuntimeError("nonfinite Stage B predictor feature")
    if set(map(int, blocks)) != set(expected_blocks) or (substrates > 8).any() or (sides > 1).any():
        raise RuntimeError("Stage B predictor domain mismatch")
    return PredictorPanel(keys, blocks, substrates, sides, base, tuples)


def audit_truth_keys(path: Path, expected_keys: tuple[bytes, ...]) -> dict[str, int | str]:
    count = _header(path, TRUTH_MAGIC, TRUTH_WIDTH)
    if count != len(expected_keys):
        raise RuntimeError("truth/predictor count mismatch")
    with path.open("rb") as stream:
        stream.seek(HEADER_WIDTH)
        for index, expected in enumerate(expected_keys):
            actual = stream.read(18)
            if actual != expected:
                raise RuntimeError(f"truth key differs from predictor at row {index}")
            stream.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
        if stream.tell() != HEADER_WIDTH + count * TRUTH_WIDTH:
            raise RuntimeError("truth-key audit ended at an unexpected offset")
    return {"row_count": count, "truth_file_sha256": sha_file(path), "truth_values_opened": False}


def load_scoring_truth(path: Path, expected_keys: tuple[bytes, ...]) -> ScoringTruth:
    count = _header(path, TRUTH_MAGIC, TRUTH_WIDTH)
    if count != len(expected_keys):
        raise RuntimeError("truth/predictor count mismatch")
    raw = path.read_bytes()
    for index, key in enumerate(expected_keys):
        start = HEADER_WIDTH + index * TRUTH_WIDTH
        if raw[start:start + 18] != key:
            raise RuntimeError(f"truth row key differs at row {index}")
    q = np.ndarray(count, dtype="<f8", buffer=raw, offset=HEADER_WIDTH + 18, strides=(TRUTH_WIDTH,)).copy()
    y = np.ndarray(count, dtype="i1", buffer=raw, offset=HEADER_WIDTH + 26, strides=(TRUTH_WIDTH,)).copy()
    native = np.ndarray(count, dtype="<f4", buffer=raw, offset=HEADER_WIDTH + 27, strides=(TRUTH_WIDTH,)).copy()
    preweight = np.ndarray(count, dtype="<f4", buffer=raw, offset=HEADER_WIDTH + 31, strides=(TRUTH_WIDTH,)).copy()
    reference = np.ndarray(count, dtype="<f4", buffer=raw, offset=HEADER_WIDTH + 35, strides=(TRUTH_WIDTH,)).copy()
    if not np.isfinite(q).all() or (q <= 0).any() or (q > 1).any() or not np.isin(y, (-1, 1)).all():
        raise RuntimeError("invalid scoring weight or target values")
    if not np.isfinite(native).all() or not np.isfinite(preweight).all() or not np.isfinite(reference).all():
        raise RuntimeError("nonfinite scoring sidecar")
    return ScoringTruth(q, y, native, preweight, reference)


def load_normalizer(path: Path, expected_fold: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = path.read_bytes()
    if len(raw) != 576 or raw[:16] != NORM_MAGIC:
        raise RuntimeError(f"normalization payload header/length mismatch: {path.name}")
    version, fold = struct.unpack_from("<II", raw, 16)
    if version != 1 or fold != expected_fold:
        raise RuntimeError(f"normalization payload identity mismatch: {path.name}")
    offset = 24
    arrays = []
    for count in (66, 66, 3, 3):
        value = np.frombuffer(raw, dtype="<f4", count=count, offset=offset).copy()
        offset += count * 4
        arrays.append(value)
    if offset != len(raw) or any(not np.isfinite(value).all() for value in arrays):
        raise RuntimeError("normalization payload has invalid numeric values")
    if np.any(arrays[1] == 0) or np.any(arrays[3] == 0):
        raise RuntimeError("normalization scale contains zero")
    return tuple(arrays)  # type: ignore[return-value]


def apply_normalizer(
    base: np.ndarray,
    tuples: np.ndarray,
    normalizer: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    base_mean, base_scale, tuple_mean, tuple_scale = normalizer
    x = ((np.asarray(base, dtype=np.float32) - base_mean) / base_scale).astype(np.float32)
    r = np.asarray(tuples, dtype=np.float32).copy()
    r[:, :, 3:6] = ((r[:, :, 3:6] - tuple_mean) / tuple_scale).astype(np.float32)
    x[x == 0] = np.float32(0.0)
    r[r == 0] = np.float32(0.0)
    if not np.isfinite(x).all() or not np.isfinite(r).all():
        raise RuntimeError("normalization produced nonfinite fresh inputs")
    return x, r
