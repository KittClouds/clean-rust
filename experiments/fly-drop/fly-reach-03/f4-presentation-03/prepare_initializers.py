"""Create task-free D/Cphi/unshared/shuffled initialization bundles.

The D and Cphi tensors are exact copies of previously frozen initializers.
The two controlled Cphi variants derive their values mechanically from the
same Cphi bundle. No task IDs, task seeds, labels, or outcomes are read.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
REPO = STUDY.parents[1]
RUN_ID = "F4-PRESENTATION-03-ENG1"
RUN = STUDY / "runs" / RUN_ID
OUT = BRANCH / "implementation-artifacts" / "initial-tensors"
INIT_MANIFEST = BRANCH / "implementation-artifacts" / "INITIALIZER-MANIFEST.json"
OLD_RUN = STUDY / "runs" / "F4-INVARIANT-01-COLLECT2-EXEC2"
CPHI_RUN = STUDY / "runs" / "F4-PRESENTATION-02-CPHI-ENG1-V2"
THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_MAXIMUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

for _path in (STUDY / "f4-invariant-01-impl-v2", STUDY / "f4-invariant-01-prefit-v2", STUDY / "f4-presentation-02-v2", BRANCH):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import numpy as np  # noqa: E402

from f4_invariant_01_model import tensor_hash as d_hash  # noqa: E402
from cphi_model import deserialize_tensors, serialize_tensors, tensor_hash as cphi_hash  # noqa: E402
from presentation03_model import expand_shared_phi, unshared_tensor_hash  # noqa: E402

ARMS = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")
FOLDS = range(12)
REPLICATES = range(3)
D_NAMES = ("w1", "b1", "w2", "b2", "w3", "b3")
D_SHAPES = ((90, 128), (128,), (128, 64), (64,), (64, 1), (1,))


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def serialize_unshared(values: list[np.ndarray]) -> bytes:
    from presentation03_model import UNSHARED_TENSOR_NAMES, UNSHARED_TENSOR_SHAPES
    parts = [b"F4PRES03UNSHARED\0"]
    for name, shape, value in zip(UNSHARED_TENSOR_NAMES, UNSHARED_TENSOR_SHAPES, values, strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        if tuple(array.shape) != shape or not np.isfinite(array).all():
            raise RuntimeError(f"invalid Cphi-unshared initializer tensor {name}")
        parts.extend((name.encode("ascii") + b"\0", struct.pack("<I", array.ndim)))
        parts.extend(struct.pack("<I", dimension) for dimension in array.shape)
        parts.append(array.tobytes(order="C"))
    return b"".join(parts)


def read_d_bundle(path: Path) -> list[np.ndarray]:
    raw = path.read_bytes()
    offset = 0
    values: list[np.ndarray] = []
    for name, shape in zip(D_NAMES, D_SHAPES, strict=True):
        name_raw = name.encode("ascii") + b"\0"
        if raw[offset:offset + len(name_raw)] != name_raw:
            raise RuntimeError(f"D initializer tensor name mismatch for {name}")
        offset += len(name_raw)
        ndim = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        dimensions = struct.unpack_from("<" + "I" * ndim, raw, offset)
        offset += ndim * 4
        if ndim != len(shape) or tuple(dimensions) != shape:
            raise RuntimeError(f"D initializer tensor shape mismatch for {name}")
        count = int(np.prod(shape, dtype=np.int64))
        size = count * 4
        values.append(np.frombuffer(raw, dtype="<f4", count=count, offset=offset).reshape(shape).copy())
        offset += size
    if offset != len(raw):
        raise RuntimeError("D initializer has trailing bytes")
    return values


def _old_rows(path: Path, arm: str | None = None) -> dict[tuple[int, int], dict[str, Any]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in manifest.get("cells", []) if arm is None or row.get("arm") == arm]
    result = {(int(row["fold_index"]), int(row["replicate_index"])): row for row in rows}
    if len(result) != 36:
        raise RuntimeError(f"expected 36 rows in {path.name}")
    return result


def build() -> None:
    if RUN.exists() or OUT.exists() or INIT_MANIFEST.exists():
        raise RuntimeError("task/run or initializer namespace already exists; preserve and stop")
    d_manifest_path = OLD_RUN / "INITIAL-TENSOR-BUNDLE-MANIFEST.json"
    cphi_manifest_path = CPHI_RUN / "CPHI-INITIALIZER-MANIFEST.json"
    d_fit_path = OLD_RUN / "FIT-MANIFEST.csv"
    cphi_fit_path = CPHI_RUN / "FIT-MANIFEST.json"
    if not all(path.is_file() for path in (d_manifest_path, cphi_manifest_path, d_fit_path, cphi_fit_path)):
        raise RuntimeError("frozen parent initializer manifests are incomplete")
    d_rows = _old_rows(d_manifest_path, "D")
    cphi_rows = _old_rows(cphi_manifest_path)
    d_files: dict[tuple[int, int], Path] = {}
    for row in d_rows.values():
        key = (int(row["fold_index"]), int(row["replicate_index"]))
        d_files[key] = OLD_RUN / str(row["path"])
    cphi_files = {
        key: CPHI_RUN / "initial-tensors" / f"CPHI-H{306000 + key[0]}-I{key[1]}.bin"
        for key in cphi_rows
    }
    records: list[dict[str, Any]] = []
    for fold in FOLDS:
        for replicate in REPLICATES:
            key = (fold, replicate)
            d_path = d_files[key]
            cphi_path = cphi_files[key]
            if not d_path.is_file() or not cphi_path.is_file():
                raise RuntimeError(f"parent initializer bundle missing for fold={fold}, replicate={replicate}")
            d_raw = d_path.read_bytes()
            cphi_raw = cphi_path.read_bytes()
            d_values = read_d_bundle(d_path)
            cphi_values = deserialize_tensors(cphi_raw)
            if d_hash(d_values, "D") != d_rows[key]["initial_tensor_sha256"]:
                raise RuntimeError(f"frozen D initializer hash mismatch at {key}")
            if cphi_hash(cphi_values) != cphi_rows[key]["initial_tensor_sha256"]:
                raise RuntimeError(f"frozen Cphi initializer hash mismatch at {key}")
            unshared_values = expand_shared_phi(cphi_values)
            unshared_raw = serialize_unshared(unshared_values)
            bundle_values = {
                "D": (d_raw, d_hash(d_values, "D"), str(d_path.relative_to(REPO)).replace("\\", "/")),
                "Cphi": (cphi_raw, cphi_hash(cphi_values), str(cphi_path.relative_to(REPO)).replace("\\", "/")),
                "Cphi_unshared": (unshared_raw, unshared_tensor_hash(unshared_values), str(cphi_path.relative_to(REPO)).replace("\\", "/")),
                "Cphi_shuffled": (cphi_raw, cphi_hash(cphi_values), str(cphi_path.relative_to(REPO)).replace("\\", "/")),
            }
            for arm in ARMS:
                raw, tensor_digest, source_path = bundle_values[arm]
                fit_key = f"F{fold:02d}-R{replicate:02d}-{arm}"
                relative = f"initial-tensors/{fit_key}.bin"
                destination = OUT / f"{fit_key}.bin"
                write_new(destination, raw)
                records.append({
                    "fit_key": fit_key,
                    "fold_index": fold,
                    "replicate_index": replicate,
                    "arm": arm,
                    "parameter_count": {"D": 19969, "Cphi": 19936, "Cphi_unshared": 20272, "Cphi_shuffled": 19936}[arm],
                    "relative_path": relative,
                    "file_sha256": sha_bytes(raw),
                    "file_bytes": len(raw),
                    "tensor_sha256": tensor_digest,
                    "source_path": source_path,
                    "source_file_sha256": sha_file(Path(REPO / source_path)),
                    "shared_cphi_source_tensor_sha256": cphi_hash(cphi_values) if arm != "D" else None,
                    "task_ids_or_seeds_used": False,
                })
    manifest = {
        "schema": "F4-PRESENTATION-03-initializer-manifest-v1",
        "status": "PASS_TASK_INDEPENDENT_INITIALIZERS",
        "fold_indices": list(FOLDS),
        "replicate_indices": list(REPLICATES),
        "arms": list(ARMS),
        "initializer_cell_count": len(records),
        "task_ids_or_seeds_used": False,
        "parent_D_bundle_manifest_sha256": sha_file(d_manifest_path),
        "parent_Cphi_initializer_manifest_sha256": sha_file(cphi_manifest_path),
        "parent_D_fit_manifest_sha256": sha_file(d_fit_path),
        "parent_Cphi_fit_manifest_sha256": sha_file(cphi_fit_path),
        "cells": records,
    }
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_new(INIT_MANIFEST, manifest_raw)


if __name__ == "__main__":
    build()
