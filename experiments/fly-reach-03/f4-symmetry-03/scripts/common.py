"""Byte-level helpers for the prospective F4-SYMMETRY-03 qualification run."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

for _key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"

REPO = Path(__file__).resolve().parents[4]
STUDY = REPO / "experiments/fly-reach-03"
BRANCH = STUDY / "f4-symmetry-03"
RUNS = REPO / "experiments/fly-reach-03/runs"
CONTRACT_SHA = "7c49b8419896dca4418de3497ecd8566b2167d1c6bf24d7860d904d70f87afe0"
PARENT_SHA = "cfef638aaeac1dfc0b768d13cc95afe7724861f74e3d3111d91401925bed6379"
INPUT_MAGIC = b"FLYREACH3SYMINP\0"
TRUTH_MAGIC = b"FLYREACH3SYMTRU\0"
PRED_MAGIC = b"F4SYMPREDv1\0\0\0\0\0"
INPUT_WIDTH = 342
TRUTH_WIDTH = 39
PRED_WIDTH = 22
ARMS = ("C", "D")
PATTERNS = ("0011", "0101", "0001", "0100")
TUPLE_DTYPE = np.dtype(
    [("incidence", "u1"), ("role", "i1"), ("incidence_role", "i1"),
     ("delta", "<f4"), ("incidence_delta", "<f4"), ("role_delta", "<f4")], align=False
)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def write_json(path: Path, value: object, *, create_new: bool = True) -> str:
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    mode = "xb" if create_new else "wb"
    with path.open(mode) as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return sha_bytes(raw)


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def input_header(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        header = f.read(32)
    require(len(header) == 32 and header[:16] == INPUT_MAGIC, "predictor header mismatch")
    version, width, count = struct.unpack_from("<IIQ", header, 16)
    require(version == 1 and width == INPUT_WIDTH, "predictor schema mismatch")
    require(path.stat().st_size == 32 + count * INPUT_WIDTH, "predictor byte length mismatch")
    return width, count


@dataclass
class RawData:
    keys: list[bytes]
    blocks: np.ndarray
    a: np.ndarray
    tuples: np.ndarray
    count: int
    truth_path: Path


def read_predictors(path: Path, truth_path: Path, expected_blocks: list[int]) -> RawData:
    _, count = input_header(path)
    require(count > 0, "empty common row population")
    with path.open("rb") as f:
        raw = f.read()
    require(len(raw) == 32 + count * INPUT_WIDTH, "predictor changed during read")
    keys_arr = np.ndarray((count, 18), dtype="u1", buffer=raw, offset=32, strides=(INPUT_WIDTH, 1)).copy()
    a = np.ndarray((count, 66), dtype="<f4", buffer=raw, offset=50, strides=(INPUT_WIDTH, 4)).copy()
    tuples = np.ndarray((count, 4), dtype=TUPLE_DTYPE, buffer=raw, offset=314, strides=(INPUT_WIDTH, 15)).copy()
    keys = [bytes(row) for row in keys_arr]
    require(len(set(keys)) == count, "duplicate common row keys")
    blocks = np.fromiter((struct.unpack_from("<Q", key, 2)[0] for key in keys), dtype=np.uint64, count=count)
    observed = set(int(x) for x in blocks)
    require(observed.issubset(set(expected_blocks)), "predictor rows contain an unaccepted task block")
    require(np.isfinite(a).all(), "nonfinite base feature")
    for field in ("delta", "incidence_delta", "role_delta"):
        require(np.isfinite(tuples[field]).all(), f"nonfinite tuple field {field}")
    require(truth_path.stat().st_size == 32 + count * TRUTH_WIDTH, "scoring truth length mismatch")
    with truth_path.open("rb") as f:
        header = f.read(32)
    require(header[:16] == TRUTH_MAGIC, "scoring truth magic mismatch")
    ver, width, n = struct.unpack_from("<IIQ", header, 16)
    require((ver, width, n) == (1, TRUTH_WIDTH, count), "scoring truth header mismatch")
    return RawData(keys, blocks, a, tuples, count, truth_path)


def training_labels(data: RawData, holdout: int) -> np.ndarray:
    labels = np.empty(data.count, dtype=np.float32)
    with data.truth_path.open("rb") as f:
        f.seek(32)
        for i, key in enumerate(data.keys):
            require(f.read(18) == key, f"predictor/truth key mismatch at {i}")
            if struct.unpack_from("<Q", key, 2)[0] == holdout:
                f.seek(TRUTH_WIDTH - 18, os.SEEK_CUR)
                labels[i] = 0.0
                continue
            f.seek(8, os.SEEK_CUR)
            target = struct.unpack("b", f.read(1))[0]
            require(target in (-1, 1), f"nonbinary training target at {i}")
            labels[i] = 1.0 if target == 1 else 0.0
            f.seek(12, os.SEEK_CUR)
    return labels


def training_hashes(keys: list[bytes], mask: np.ndarray) -> tuple[str, str]:
    ordered = [key for key, keep in zip(keys, mask, strict=True) if keep]
    return sha_bytes(b"".join(sorted(ordered))), sha_bytes(b"".join(ordered))


def normalize_f32(values: np.ndarray, train_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.asarray(values, dtype=np.float32)
    mean = x[train_mask].mean(axis=0, dtype=np.float32)
    scale = x[train_mask].std(axis=0, dtype=np.float32, ddof=0)
    scale = scale.copy()
    scale[scale < np.float32(1e-6)] = np.float32(1.0)
    normalized = ((x - mean) / scale).astype(np.float32)
    require(np.isfinite(normalized).all(), "nonfinite normalized input")
    return normalized, mean, scale


def tuple_bytes(row: np.void) -> bytes:
    return struct.pack("<Bbbfff", int(row["incidence"]), int(row["role"]), int(row["incidence_role"]), float(row["delta"]), float(row["incidence_delta"]), float(row["role_delta"]))


def sorted_tuples(tuples: np.ndarray) -> np.ndarray:
    out = np.empty_like(tuples)
    for r, row in enumerate(tuples):
        keys = []
        for item in row:
            vals = (float(item["delta"]), float(item["incidence_delta"]), float(item["role_delta"]))
            require(all(np.isfinite(vals)), "nonfinite tuple in canonical ordering")
            keys.append((int(item["incidence"]), int(item["role"]), int(item["incidence_role"]), *vals))
        out[r] = row[sorted(range(4), key=lambda i: keys[i])]
    return out


def sidecar(tuples: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    n = len(tuples)
    out = np.empty((n, 4, 6), dtype=np.float32)
    for c, field in enumerate(("incidence", "role", "incidence_role")):
        out[:, :, c] = tuples[field].astype(np.float32)
    for c, field in enumerate(("delta", "incidence_delta", "role_delta")):
        out[:, :, 3 + c] = ((tuples[field] - mean[c]) / scale[c]).astype(np.float32)
    return out.reshape(n, 24)


def write_matrix(path: Path, values: np.ndarray) -> str:
    x = np.ascontiguousarray(values, dtype="<f4")
    raw = b"F4SYMARMINPUTv1\0" + struct.pack("<IIQ", 1, x.shape[1], x.shape[0]) + x.tobytes()
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return sha_bytes(raw[32:])


def read_matrix(path: Path, width: int, count: int) -> np.ndarray:
    raw = path.read_bytes()
    require(raw[:16] == b"F4SYMARMINPUTv1\0", f"prepared matrix magic mismatch {path.name}")
    version, actual_width, actual_count = struct.unpack_from("<IIQ", raw, 16)
    require((version, actual_width, actual_count) == (1, width, count), f"prepared matrix dimensions mismatch {path.name}")
    require(len(raw) == 32 + count * width * 4, f"prepared matrix size mismatch {path.name}")
    x = np.frombuffer(raw, dtype="<f4", offset=32).reshape(count, width).copy()
    require(np.isfinite(x).all(), f"nonfinite prepared matrix {path.name}")
    return x


def runtime_description() -> dict[str, object]:
    import contextlib
    import io
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        np.show_config()
    pools: object = "unavailable"
    try:
        from threadpoolctl import threadpool_info
        pools = threadpool_info()
        require(all(p.get("num_threads") in (None, 1) for p in pools), "numerical runtime is not single-threaded")
    except ImportError:
        pass
    env = {k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")}
    require(all(v == "1" for v in env.values()), "thread environment drift")
    py = Path(sys.executable).resolve()
    return {"python_version": sys.version, "python_executable": str(py), "python_sha256": sha_file(py), "numpy_version": np.__version__, "numpy_config": buffer.getvalue(), "thread_environment": env, "threadpools": pools}


def prediction_path(run: Path, arm: str, holdout: int) -> Path:
    return run / "heldout-predictions" / f"{arm}-H{holdout}.bin"
