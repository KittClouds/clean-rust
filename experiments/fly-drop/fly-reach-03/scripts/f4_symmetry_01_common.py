"""Shared byte-exact I/O and numerical primitives for F4-SYMMETRY-01."""
from __future__ import annotations

import os

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
for _name, _value in THREAD_ENV.items():
    os.environ[_name] = _value

import csv
import hashlib
import io
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OUT_REL = Path("artifacts/f4-symmetry-01")
CONTRACT_SHA = "cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379"
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
PRED_MAGIC = b"F4SYMPREDv1\0\0\0\0\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
PRED_RECORD_WIDTH = 22
BLOCKS = (303000, 303001, 303002, 303003)
ARMS = ("A", "B", "C", "D")
FIT_HEADER = (
    "fit_id,arm,holdout_block,input_width,train_rows,heldout_rows,contract_sha256,"
    "source_manifest_sha256,implementation_executable_sha256,analysis_script_sha256,"
    "feature_hash,training_row_hash,training_order_hash,normalization_hash,"
    "initial_tensor_hash,expected_prediction_path"
)
TUPLE_DTYPE = np.dtype(
    [("incidence", "u1"), ("role", "i1"), ("incidence_role", "i1"),
     ("delta", "<f4"), ("incidence_delta", "<f4"), ("role_delta", "<f4")],
    align=False,
)


@dataclass
class RawData:
    keys: list[bytes]
    blocks: np.ndarray
    a: np.ndarray
    tuples: np.ndarray
    truth_path: Path
    count: int


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_json(path: Path, value: object, *, create_new: bool = True) -> bytes:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    mode = "xb" if create_new else "wb"
    with path.open(mode) as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def json_read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def sorted_tree_hashes(paths: Iterable[Path]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in paths:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(REPO.resolve()).as_posix()
        require("." not in relative.split("/") and ".." not in relative.split("/"), f"unsafe source path: {relative}")
        entries.append({"path": relative, "byte_length": resolved.stat().st_size, "sha256": sha_file(resolved)})
    entries.sort(key=lambda entry: str(entry["path"]).encode("utf-8"))
    require(len({str(item["path"]) for item in entries}) == len(entries), "duplicate source manifest paths")
    return entries


def verify_manifest_sources(manifest_path: Path, repo: Path = REPO) -> dict[str, object]:
    stored = json_read(manifest_path)
    require(isinstance(stored, dict) and stored.get("schema") == "F4-SYMMETRY-01-source-input-manifest-v1", "source manifest schema mismatch")
    expected = stored["entries"]
    actual: list[dict[str, object]] = []
    for entry in expected:
        rel = str(entry["path"])
        require(".." not in rel.split("/") and "." not in rel.split("/"), f"unsafe manifest path {rel}")
        path = repo / Path(rel)
        actual.append({"path": rel, "byte_length": path.stat().st_size, "sha256": sha_file(path)})
    actual.sort(key=lambda entry: str(entry["path"]).encode("utf-8"))
    require(actual == expected, "source artifact drift after preflight")
    canonical_sha = sha_bytes(canonical_json_bytes(stored))
    file_sha = sha_file(manifest_path)
    return {"canonical_sha256": canonical_sha, "file_sha256": file_sha, "entry_count": len(expected), "status": "PASS"}


def read_raw(path: Path, truth_path: Path) -> RawData:
    raw = path.read_bytes()
    require(raw[:16] == INPUT_MAGIC and len(raw) >= 32, "raw predictor magic/header mismatch")
    version, width, count = struct.unpack_from("<IIQ", raw, 16)
    require(version == 1 and width == INPUT_WIDTH and count == 13420, f"raw predictor dimensions mismatch: {version}/{width}/{count}")
    require(len(raw) == 32 + count * INPUT_WIDTH, "raw predictor byte length mismatch")
    keys_arr = np.ndarray((count, 18), dtype="u1", buffer=raw, offset=32, strides=(INPUT_WIDTH, 1)).copy()
    a = np.ndarray((count, 66), dtype="<f4", buffer=raw, offset=50, strides=(INPUT_WIDTH, 4)).copy()
    tuples = np.ndarray((count, 4), dtype=TUPLE_DTYPE, buffer=raw, offset=314, strides=(INPUT_WIDTH, 15)).copy()
    require(np.isfinite(a).all(), "nonfinite raw A features")
    require(np.isfinite(tuples["delta"]).all() and np.isfinite(tuples["incidence_delta"]).all() and np.isfinite(tuples["role_delta"]).all(), "nonfinite relation tuple")
    keys = [bytes(row) for row in keys_arr]
    require(len(set(keys)) == count, "duplicate raw row keys")
    blocks = np.fromiter((struct.unpack_from("<Q", key, 2)[0] for key in keys), dtype=np.uint64, count=count)
    require(set(int(x) for x in blocks) == set(BLOCKS), "raw rows do not cover all four frozen blocks")
    require(truth_path.stat().st_size == 32 + count * TRUTH_WIDTH, "raw truth length mismatch")
    with truth_path.open("rb") as truth:
        header = truth.read(32)
    require(header[:16] == TRUTH_MAGIC, "raw truth magic mismatch")
    t_version, t_width, t_count = struct.unpack_from("<IIQ", header, 16)
    require((t_version, t_width, t_count) == (1, TRUTH_WIDTH, count), "raw truth header mismatch")
    return RawData(keys=keys, blocks=blocks, a=a, tuples=tuples, truth_path=truth_path, count=count)


def read_training_labels(data: RawData, holdout_block: int) -> np.ndarray:
    """Read training labels only; skip all held-out truth record payloads."""
    labels = np.empty(data.count, dtype=np.float32)
    with data.truth_path.open("rb") as stream:
        stream.seek(32)
        for i, key in enumerate(data.keys):
            key_on_disk = stream.read(18)
            require(key_on_disk == key, f"truth/predictor key mismatch at row {i}")
            block = struct.unpack_from("<Q", key, 2)[0]
            if block == holdout_block:
                stream.seek(TRUTH_WIDTH - 18, io.SEEK_CUR)
                labels[i] = 0.0
                continue
            stream.seek(8, io.SEEK_CUR)
            target_raw = stream.read(1)
            require(len(target_raw) == 1, "truncated training target")
            target = struct.unpack("b", target_raw)[0]
            require(target in (-1, 1), f"nonbinary target in training row {i}")
            labels[i] = 1.0 if target == 1 else 0.0
            stream.seek(12, io.SEEK_CUR)
        require(stream.tell() == 32 + data.count * TRUTH_WIDTH, "training truth scan did not consume expected bytes")
    return labels


def load_truth_after_integrity(data: RawData, integrity_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    receipt = json_read(integrity_path)
    require(isinstance(receipt, dict) and receipt.get("status") == "PASS" and receipt.get("heldout_truth_state") == "SEALED", "integrity receipt must PASS before truth open")
    raw = data.truth_path.read_bytes()
    count = data.count
    q = np.ndarray(count, dtype="<f8", buffer=raw, offset=50, strides=(TRUTH_WIDTH,)).copy()
    y = np.ndarray(count, dtype="i1", buffer=raw, offset=58, strides=(TRUTH_WIDTH,)).copy()
    native = np.ndarray(count, dtype="<f4", buffer=raw, offset=59, strides=(TRUTH_WIDTH,)).copy()
    preweight = np.ndarray(count, dtype="<f4", buffer=raw, offset=63, strides=(TRUTH_WIDTH,)).copy()
    reference = np.ndarray(count, dtype="<f4", buffer=raw, offset=67, strides=(TRUTH_WIDTH,)).copy()
    key_matrix = np.ndarray((count, 18), dtype="u1", buffer=raw, offset=32, strides=(TRUTH_WIDTH, 1))
    require([bytes(row) for row in key_matrix] == data.keys, "truth keys changed before analysis")
    require(np.isfinite(q).all() and (q > 0).all(), "invalid inclusion weights")
    require(np.isin(y, (-1, 1)).all(), "nonbinary truth target")
    require(np.isfinite(native).all() and np.isfinite(preweight).all() and np.isfinite(reference).all(), "nonfinite scoring truth")
    return q, y, native, preweight, reference


def normalize_f32(values: np.ndarray, training_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.asarray(values, dtype=np.float32)
    mean = x[training_mask].mean(axis=0, dtype=np.float32)
    scale = x[training_mask].std(axis=0, dtype=np.float32, ddof=0)
    scale = scale.copy()
    scale[scale < np.float32(1e-6)] = np.float32(1.0)
    normalized = ((x - mean) / scale).astype(np.float32)
    require(np.isfinite(mean).all() and np.isfinite(scale).all() and np.isfinite(normalized).all(), "normalization produced nonfinite values")
    return normalized, mean, scale


def row_key_hash(keys: list[bytes]) -> str:
    return sha_bytes(b"".join(keys))


def training_hashes(keys: list[bytes], train_mask: np.ndarray) -> tuple[str, str]:
    ordered = [key for key, keep in zip(keys, train_mask, strict=True) if keep]
    return sha_bytes(b"".join(sorted(ordered))), sha_bytes(b"".join(ordered))


def runtime_description() -> dict[str, object]:
    import contextlib
    import io as _io

    output = _io.StringIO()
    with contextlib.redirect_stdout(output):
        np.show_config()
    thread_info: object = "threadpoolctl-unavailable"
    try:
        from threadpoolctl import threadpool_info
        thread_info = threadpool_info()
    except ImportError:
        pass
    for name, value in THREAD_ENV.items():
        require(os.environ.get(name) == value, f"numerical thread policy drift for {name}")
    if isinstance(thread_info, list):
        for runtime in thread_info:
            workers = runtime.get("num_threads")
            require(workers in (None, 1), f"loaded numerical runtime is not single threaded: {runtime}")
    return {
        "python_version": sys.version,
        "python_executable": str(Path(sys.executable).resolve()),
        "python_executable_sha256": sha_file(Path(sys.executable).resolve()),
        "numpy_version": np.__version__,
        "numpy_config": output.getvalue(),
        "thread_environment": {name: os.environ.get(name) for name in THREAD_ENV},
        "loaded_threadpools": thread_info,
    }


def ensure_output_dirs(out: Path) -> None:
    for name in ("normalization", "prepared-inputs", "fit-receipts", "heldout-predictions", "bin"):
        (out / name).mkdir(exist_ok=True)


def binary_matrix(path: Path, width: int) -> np.ndarray:
    raw = path.read_bytes()
    require(len(raw) >= 32 and raw[:16] == b"F4SYMARMINPUTv1\0", f"invalid prepared input header {path.name}")
    version, actual_width, count = struct.unpack_from("<IIQ", raw, 16)
    require(version == 1 and actual_width == width and count == 13420, f"prepared input dimensions mismatch {path.name}")
    require(len(raw) == 32 + count * width * 4, f"prepared input length mismatch {path.name}")
    result = np.frombuffer(raw, dtype="<f4", offset=32).reshape(count, width).copy()
    require(np.isfinite(result).all(), f"nonfinite prepared matrix {path.name}")
    return result


def write_matrix(path: Path, matrix: np.ndarray) -> bytes:
    x = np.ascontiguousarray(matrix, dtype="<f4")
    header = b"F4SYMARMINPUTv1\0" + struct.pack("<IIQ", 1, x.shape[1], x.shape[0])
    require(len(header) == 32, "prepared input header must be 32 bytes")
    raw = header + x.tobytes(order="C")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw
