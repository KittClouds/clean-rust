"""Pure inference primitives for frozen CΦ models; no optimizer is created."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np

REPO = Path(__file__).resolve().parents[4]
STUDY = REPO / "experiments" / "fly-reach-03"
for _path in (STUDY / "scripts", STUDY / "f4-invariant-01-impl-v2", STUDY / "f4-presentation-02-v2"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CPHI = load_module("f4_binding_stage_b_cphi_model", STUDY / "f4-presentation-02-v2" / "cphi_model.py")
GELU_SOURCE = load_module("f4_binding_stage_b_invariant_model", STUDY / "f4-invariant-01-impl-v2" / "f4_invariant_01_model.py")

PERMUTATIONS: dict[str, tuple[int, int, int, int]] = {
    "intact": (0, 1, 2, 3),
    "pair_swap": (1, 0, 2, 3),
    "cycle_4": (1, 2, 3, 0),
}


def parameter_hashes(values: list[np.ndarray]) -> dict[str, str]:
    if len(values) != len(CPHI.TENSOR_NAMES):
        raise RuntimeError("frozen CΦ tensor count mismatch")
    output: dict[str, str] = {}
    for name, shape, value in zip(CPHI.TENSOR_NAMES, CPHI.TENSOR_SHAPES, values, strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        if tuple(array.shape) != shape or not np.isfinite(array).all():
            raise RuntimeError(f"invalid frozen CΦ parameter {name}")
        output[name] = hashlib.sha256(array.tobytes(order="C")).hexdigest()
    return output


def h_from_normalized(base: np.ndarray, tuples: np.ndarray, tensors: list[np.ndarray]) -> np.ndarray:
    """Apply the frozen shared φ once to each row's D-canonical tuple sequence."""
    x = np.asarray(base, dtype=np.float32)
    raw = np.asarray(tuples, dtype=np.float32)
    if x.ndim != 2 or x.shape[1] != 66 or raw.shape != (len(x), 4, 6):
        raise ValueError("CΦ Stage B input shape mismatch")
    ordered = CPHI.sort_tuples_like_d(x, raw)
    phi_w, phi_b = tensors[0], tensors[1]
    flat = ordered.reshape(len(x) * 4, 6)
    zphi = CPHI.affine_six(flat, phi_w, phi_b)
    h = GELU_SOURCE.gelu(zphi).reshape(len(x), 4, 16).astype(np.float32, copy=False)
    if not np.isfinite(h).all():
        raise RuntimeError("nonfinite φ representation")
    return np.ascontiguousarray(h)


def rho_forward(base: np.ndarray, h: np.ndarray, tensors: list[np.ndarray], permutation: tuple[int, ...]) -> np.ndarray:
    """Run the frozen readout on an already-computed H and one fixed slot map."""
    x = np.asarray(base, dtype=np.float32)
    local_h = np.asarray(h, dtype=np.float32)
    if x.ndim != 2 or x.shape[1] != 66 or local_h.shape != (len(x), 4, 16):
        raise ValueError("CΦ Stage B readout input shape mismatch")
    if tuple(sorted(permutation)) != (0, 1, 2, 3):
        raise ValueError("role intervention is not a tuple permutation")
    presented = np.ascontiguousarray(local_h[:, permutation, :], dtype=np.float32)
    readout = np.concatenate((x, presented.reshape(len(x), 64)), axis=1).astype(np.float32, copy=False)
    _phi_w, _phi_b, w1, b1, w2, b2, w3, b3 = tensors
    z1 = readout @ w1 + b1
    a1 = GELU_SOURCE.gelu(z1)
    z2 = a1 @ w2 + b2
    a2 = GELU_SOURCE.gelu(z2)
    logits = ((a2 @ w3 + b3)[:, 0]).astype(np.float32, copy=False)
    if not np.isfinite(logits).all():
        raise RuntimeError("nonfinite CΦ Stage B logits")
    return logits


def tensor_bundle_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_tensor_bundle(path: Path) -> list[np.ndarray]:
    values = CPHI.deserialize_tensors(path.read_bytes())
    if CPHI.tensor_hash(values) == "":
        raise RuntimeError("empty CΦ tensor hash")
    return values


def h_identity_sha(row_keys: tuple[bytes, ...] | list[bytes], h: np.ndarray) -> str:
    array = np.ascontiguousarray(h, dtype="<f4")
    digest = hashlib.sha256()
    digest.update(b"F4-BINDING-01-STAGE-B/H-PANEL-v0.1\0")
    digest.update(len(row_keys).to_bytes(8, "little"))
    for key in row_keys:
        if len(key) != 18:
            raise ValueError("row key must contain 18 bytes")
        digest.update(key)
    digest.update(array.dtype.str.encode("ascii") + b"\0")
    digest.update(len(array.shape).to_bytes(4, "little"))
    for dim in array.shape:
        digest.update(int(dim).to_bytes(8, "little"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()
