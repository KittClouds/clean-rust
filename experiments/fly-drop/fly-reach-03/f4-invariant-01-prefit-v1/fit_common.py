"""Byte-level I/O shared by the F4-INVARIANT-01 fit and integrity tools."""
from __future__ import annotations

import hashlib
import json
import mmap
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "experiments" / "fly-reach-03"
RUN = STUDY / "runs" / "F4-INVARIANT-01-COLLECT2"
IMPL = STUDY / "f4-invariant-01-impl-v2"
SCRIPTS = STUDY / "scripts"
for _path in (str(IMPL), str(SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from f4_invariant_01_inputs import normalize_fold_inputs, shared_stream_hashes  # noqa: E402
from f4_invariant_01_model import (  # noqa: E402
    DEncoder, SEncoder, d_input, make_initial_tensors, parameter_count, tensor_hash,
)
from fit_contract import canonical_json, sha256_bytes  # noqa: E402

INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
INPUT_HEADER_BYTES = 32
TRUTH_HEADER_BYTES = 32
BLOCKS = tuple(range(306000, 306012))


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_new(path: Path, value: object) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


@dataclass(frozen=True)
class RawInputs:
    keys: list[bytes]
    blocks: np.ndarray
    base: np.ndarray
    tuples: np.ndarray


@dataclass(frozen=True)
class ScoringTruth:
    q: np.ndarray
    y: np.ndarray
    native_delta: np.ndarray
    preweight: np.ndarray
    reference: np.ndarray


def load_raw_inputs(path: Path | None = None) -> RawInputs:
    predictor_path = path or RUN / "native-collection" / "RAW-PREDICTORS.bin"
    stream = predictor_path.open("rb")
    mapping = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
    try:
        if len(mapping) < INPUT_HEADER_BYTES or mapping[:16] != INPUT_MAGIC:
            raise RuntimeError("raw predictor magic/header mismatch")
        version, width, count = struct.unpack_from("<IIQ", mapping, 16)
        if version != 1 or width != INPUT_WIDTH or len(mapping) != INPUT_HEADER_BYTES + count * INPUT_WIDTH:
            raise RuntimeError("raw predictor dimensions/length mismatch")
        key_matrix = np.ndarray((count, 18), dtype="u1", buffer=mapping, offset=32, strides=(INPUT_WIDTH, 1)).copy()
        base = np.ndarray((count, 66), dtype="<f4", buffer=mapping, offset=50, strides=(INPUT_WIDTH, 4)).copy()
        tuple_dtype = np.dtype(
            [("incidence", "u1"), ("role", "i1"), ("incidence_role", "i1"),
             ("delta", "<f4"), ("incidence_delta", "<f4"), ("role_delta", "<f4")],
            align=False,
        )
        packed = np.ndarray((count, 4), dtype=tuple_dtype, buffer=mapping, offset=314, strides=(INPUT_WIDTH, 15)).copy()
    finally:
        mapping.close()
        stream.close()

    tuples = np.empty((count, 4, 6), dtype=np.float32)
    tuples[:, :, 0] = packed["incidence"].astype(np.float32)
    tuples[:, :, 1] = packed["role"].astype(np.float32)
    tuples[:, :, 2] = packed["incidence_role"].astype(np.float32)
    tuples[:, :, 3] = packed["delta"]
    tuples[:, :, 4] = packed["incidence_delta"]
    tuples[:, :, 5] = packed["role_delta"]
    keys = [bytes(row) for row in key_matrix]
    if len(set(keys)) != count or not np.isfinite(base).all() or not np.isfinite(tuples).all():
        raise RuntimeError("duplicate key or nonfinite raw predictor value")
    blocks = np.fromiter((struct.unpack_from("<Q", key, 2)[0] for key in keys), dtype=np.uint64, count=count)
    if set(map(int, blocks)) != set(BLOCKS):
        raise RuntimeError("raw input does not cover all frozen blocks")
    return RawInputs(keys=keys, blocks=blocks, base=base, tuples=tuples)


def verify_truth_header(path: Path | None = None, expected_count: int | None = None) -> None:
    truth_path = path or RUN / "native-collection" / "RAW-SCORING-TRUTH.bin"
    with truth_path.open("rb") as stream:
        header = stream.read(32)
    if len(header) != 32 or header[:16] != TRUTH_MAGIC:
        raise RuntimeError("raw truth magic/header mismatch")
    version, width, count = struct.unpack_from("<IIQ", header, 16)
    if version != 1 or width != TRUTH_WIDTH or (expected_count is not None and count != expected_count):
        raise RuntimeError("raw truth schema/count mismatch")
    if truth_path.stat().st_size != 32 + count * TRUTH_WIDTH:
        raise RuntimeError("raw truth byte length mismatch")


def load_training_targets(keys: list[bytes], heldout_block: int, path: Path | None = None) -> np.ndarray:
    """Read Y only for training rows; held-out payloads are skipped after key checks."""
    truth_path = path or RUN / "native-collection" / "RAW-SCORING-TRUTH.bin"
    verify_truth_header(truth_path, len(keys))
    labels = np.empty(len(keys), dtype=np.float32)
    with truth_path.open("rb") as stream:
        stream.seek(32)
        for index, expected_key in enumerate(keys):
            key = stream.read(18)
            if key != expected_key:
                raise RuntimeError(f"predictor/truth key mismatch at row {index}")
            block = struct.unpack_from("<Q", key, 2)[0]
            if block == heldout_block:
                stream.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
                labels[index] = 0.0
                continue
            stream.seek(8, os.SEEK_CUR)  # inclusion weight is not a training input
            target_raw = stream.read(1)
            if len(target_raw) != 1:
                raise RuntimeError("truncated training target")
            target = struct.unpack("b", target_raw)[0]
            if target not in (-1, 1):
                raise RuntimeError(f"nonbinary training target at row {index}")
            labels[index] = np.float32(1.0 if target == 1 else 0.0)
            stream.seek(12, os.SEEK_CUR)  # scoring-only values are not read
        if stream.tell() != 32 + len(keys) * TRUTH_WIDTH:
            raise RuntimeError("training-label reader ended at unexpected offset")
    return labels


def load_scoring_truth(
    integrity_path: Path,
    path: Path | None = None,
    *,
    expected_keys: list[bytes] | None = None,
) -> ScoringTruth:
    integrity = read_json(integrity_path)
    if integrity.get("status") != "PASS" or integrity.get("heldout_truth_state") != "SEALED":
        raise RuntimeError("held-out truth is locked until independent integrity PASS")
    truth_path = path or RUN / "native-collection" / "RAW-SCORING-TRUTH.bin"
    raw = truth_path.read_bytes()
    if raw[:16] != TRUTH_MAGIC or len(raw) < 32:
        raise RuntimeError("raw scoring truth header mismatch after integrity PASS")
    version, width, count = struct.unpack_from("<IIQ", raw, 16)
    if version != 1 or width != TRUTH_WIDTH or len(raw) != 32 + count * TRUTH_WIDTH:
        raise RuntimeError("raw scoring truth dimensions mismatch after integrity PASS")
    if expected_keys is not None:
        if len(expected_keys) != count:
            raise RuntimeError("scoring truth key count mismatch after integrity PASS")
        for index, expected in enumerate(expected_keys):
            offset = 32 + index * TRUTH_WIDTH
            if raw[offset:offset + 18] != expected:
                raise RuntimeError(f"scoring truth key mismatch after integrity PASS at row {index}")
    q = np.ndarray(count, dtype="<f8", buffer=raw, offset=50, strides=(TRUTH_WIDTH,)).copy()
    y = np.ndarray(count, dtype="i1", buffer=raw, offset=58, strides=(TRUTH_WIDTH,)).copy()
    native = np.ndarray(count, dtype="<f4", buffer=raw, offset=59, strides=(TRUTH_WIDTH,)).copy()
    preweight = np.ndarray(count, dtype="<f4", buffer=raw, offset=63, strides=(TRUTH_WIDTH,)).copy()
    reference = np.ndarray(count, dtype="<f4", buffer=raw, offset=67, strides=(TRUTH_WIDTH,)).copy()
    if not np.isfinite(q).all() or (q <= 0).any() or not np.isin(y, (-1, 1)).all():
        raise RuntimeError("invalid scoring weights or target after integrity PASS")
    if not np.isfinite(native).all() or not np.isfinite(preweight).all() or not np.isfinite(reference).all():
        raise RuntimeError("nonfinite scoring sidecar after integrity PASS")
    return ScoringTruth(q=q, y=y, native_delta=native, preweight=preweight, reference=reference)


def normalized_folds(raw: RawInputs) -> dict[int, Any]:
    normalized: dict[int, Any] = {}
    for fold_index, heldout in enumerate(BLOCKS):
        train_mask = raw.blocks != np.uint64(heldout)
        normalized[fold_index] = normalize_fold_inputs(raw.base, raw.tuples, train_mask, fold_index)
    return normalized


def read_initial_bundle(path: Path, arm: str) -> list[np.ndarray]:
    from f4_invariant_01_model import TENSOR_NAMES, TENSOR_SHAPES
    raw = path.read_bytes()
    offset = 0
    values: list[np.ndarray] = []
    for name, shape in zip(TENSOR_NAMES[arm], TENSOR_SHAPES[arm], strict=True):
        name_bytes = name.encode("utf-8")
        ndim = struct.unpack_from("<I", raw, offset + len(name_bytes) + 1)[0]
        expected_dims = struct.unpack_from("<" + "I" * ndim, raw, offset + len(name_bytes) + 5)
        if raw[offset:offset + len(name_bytes)] != name_bytes or raw[offset + len(name_bytes)] != 0 or tuple(expected_dims) != shape or ndim != len(shape):
            raise RuntimeError(f"initial tensor bundle header mismatch for {name}")
        value_start = offset + len(name_bytes) + 5 + 4 * ndim
        nbytes = int(np.prod(shape, dtype=np.int64)) * 4
        end = value_start + nbytes
        if end > len(raw):
            raise RuntimeError(f"truncated initial tensor bundle for {name}")
        value = np.frombuffer(raw, dtype="<f4", count=int(np.prod(shape)), offset=value_start).reshape(shape).copy()
        values.append(value)
        offset = end
    if offset != len(raw):
        raise RuntimeError("extra bytes in initial tensor bundle")
    return values


def serialize_initial_bundle(values: list[np.ndarray], arm: str) -> bytes:
    from f4_invariant_01_model import TENSOR_NAMES, TENSOR_SHAPES
    if len(values) != len(TENSOR_NAMES[arm]):
        raise RuntimeError("initial tensor bundle tensor-count mismatch")
    parts = []
    for name, shape, value in zip(TENSOR_NAMES[arm], TENSOR_SHAPES[arm], values, strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        if tuple(array.shape) != shape:
            raise RuntimeError(f"initial tensor shape mismatch for {name}")
        parts.append(name.encode("utf-8") + b"\0" + struct.pack("<I", array.ndim))
        parts.extend(struct.pack("<I", dim) for dim in array.shape)
        parts.append(array.tobytes(order="C"))
    return b"".join(parts)


def validate_source_manifest(path: Path, expected_canonical: str | None = None, expected_file: str | None = None) -> dict[str, Any]:
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("schema") != "F4-INVARIANT-01-fit-execution-source-manifest-v1":
        raise RuntimeError("fit execution source-manifest schema mismatch")
    canonical_sha = sha256_bytes(canonical_json(manifest))
    file_sha = sha256_bytes(raw)
    if expected_canonical and canonical_sha != expected_canonical:
        raise RuntimeError("fit execution source-manifest canonical hash mismatch")
    if expected_file and file_sha != expected_file:
        raise RuntimeError("fit execution source-manifest file hash mismatch")
    verify_manifest_entries(manifest, REPO)
    return {"manifest": manifest, "canonical_sha256": canonical_sha, "file_sha256": file_sha}


def verify_manifest_entries(manifest: dict[str, Any], root: Path) -> None:
    """Verify path, byte length, and SHA for a frozen manifest entry list."""
    for item in manifest.get("entries", []):
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe source-manifest path: {relative}")
        source = root / relative
        if not source.is_file() or source.stat().st_size != item["byte_length"] or sha_file(source) != item["sha256"]:
            raise RuntimeError(f"fit execution source drift: {item['path']}")
