"""Fold normalization and shared stream hashing for task-free F4 inputs."""
from __future__ import annotations

import hashlib
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

PARENT_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(PARENT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PARENT_SCRIPTS))

from f4_symmetry_01_common import normalize_f32  # noqa: E402

NORM_MAGIC = b"F4INV01NORMv1\0\0\0"
STREAM_DOMAINS = {
    "base": b"F4-INV01-BASE-v1\0",
    "tuples": b"F4-INV01-TUPLES-v1\0",
    "paired": b"F4-INV01-PAIRINPUT-v1\0",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _positive_zero(array: np.ndarray) -> np.ndarray:
    result = np.ascontiguousarray(array, dtype=np.float32).copy()
    result[result == np.float32(0.0)] = np.float32(0.0)
    return result


def _little_f32(array: np.ndarray) -> bytes:
    value = _positive_zero(array)
    _require(np.isfinite(value).all(), "cannot serialize nonfinite normalized input")
    return np.ascontiguousarray(value, dtype="<f4").tobytes(order="C")


@dataclass(frozen=True)
class FoldNormalization:
    fold_index: int
    base_mean: np.ndarray
    base_scale: np.ndarray
    tuple_mean: np.ndarray
    tuple_scale: np.ndarray
    base: np.ndarray
    tuples: np.ndarray
    payload: bytes
    sha256: str


def normalize_fold_inputs(base_raw: np.ndarray, tuple_raw: np.ndarray, training_mask: np.ndarray, fold_index: int) -> FoldNormalization:
    """Fit training-only stats and apply them to all rows in frozen order."""
    base = np.asarray(base_raw, dtype=np.float32)
    tuples = np.asarray(tuple_raw, dtype=np.float32)
    train = np.asarray(training_mask, dtype=bool)
    _require(0 <= fold_index < 12, "fold index outside frozen abstract 0..11 range")
    _require(base.ndim == 2 and base.shape[1] == 66, "base input must have shape (N,66)")
    _require(tuples.shape == (len(base), 4, 6), "tuple input must have shape (N,4,6)")
    _require(train.shape == (len(base),) and train.any(), "training mask is empty or mis-shaped")
    _require(np.isfinite(base).all() and np.isfinite(tuples).all(), "raw input contains nonfinite values")

    normalized_base, base_mean, base_scale = normalize_f32(base, train)
    flat_tuple_floats = tuples[:, :, 3:6].reshape(len(base) * 4, 3)
    flat_training = np.repeat(train, 4)
    normalized_floats, tuple_mean, tuple_scale = normalize_f32(flat_tuple_floats, flat_training)
    normalized_tuples = tuples.copy()
    normalized_tuples[:, :, 3:6] = normalized_floats.reshape(len(base), 4, 3)
    normalized_base = _positive_zero(normalized_base)
    normalized_tuples = _positive_zero(normalized_tuples)

    parts = (base_mean, base_scale, tuple_mean, tuple_scale)
    payload = NORM_MAGIC + struct.pack("<II", 1, fold_index) + b"".join(_little_f32(part) for part in parts)
    _require(len(payload) == 576, f"normalization payload byte count changed: {len(payload)}")
    digest = hashlib.sha256(payload).hexdigest()
    return FoldNormalization(
        fold_index=fold_index,
        base_mean=_positive_zero(base_mean),
        base_scale=_positive_zero(base_scale),
        tuple_mean=_positive_zero(tuple_mean),
        tuple_scale=_positive_zero(tuple_scale),
        base=normalized_base,
        tuples=normalized_tuples,
        payload=payload,
        sha256=digest,
    )


def shared_stream_hashes(row_keys: list[bytes] | tuple[bytes, ...], base: np.ndarray, tuples: np.ndarray) -> dict[str, str]:
    """Hash pre-presentation streams in the supplied global row order."""
    x = np.asarray(base, dtype=np.float32)
    r = np.asarray(tuples, dtype=np.float32)
    _require(x.ndim == 2 and x.shape[1] == 66, "normalized base shape mismatch")
    _require(r.shape == (len(x), 4, 6), "normalized tuple shape mismatch")
    _require(len(row_keys) == len(x), "row key/input row count mismatch")
    _require(all(isinstance(key, bytes) and len(key) == 18 for key in row_keys), "each row key must be exactly 18 bytes")
    _require(len(set(row_keys)) == len(row_keys), "duplicate row key in shared stream")
    _require(np.isfinite(x).all() and np.isfinite(r).all(), "nonfinite shared model input")

    digests = {name: hashlib.sha256(domain) for name, domain in STREAM_DOMAINS.items()}
    for index, key in enumerate(row_keys):
        base_bytes = _little_f32(x[index])
        tuple_bytes = _little_f32(r[index])
        digests["base"].update(key)
        digests["base"].update(base_bytes)
        digests["tuples"].update(key)
        digests["tuples"].update(tuple_bytes)
        digests["paired"].update(key)
        digests["paired"].update(base_bytes)
        digests["paired"].update(tuple_bytes)
    return {name: digest.hexdigest() for name, digest in digests.items()}

