"""Task-independent model components for F4-PRESENTATION-03.

This module adds the slot-specific CPhi control and deterministic row-wise
tuple presentation shuffle. The frozen D and Cphi implementations are imported
from their existing versioned modules and are not edited here.
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
import sys
from pathlib import Path
from typing import Iterable

THREAD_ENV = {
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    "BLIS_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_MAXIMUM_THREADS": "1",
}
for _key, _value in THREAD_ENV.items():
    os.environ[_key] = _value

import numpy as np  # noqa: E402

BRANCH = Path(__file__).resolve().parent
STUDY = BRANCH.parent
for _path in (
    STUDY / "f4-invariant-01-impl-v2",
    STUDY / "f4-presentation-02-v2",
    STUDY / "scripts",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from cphi_model import (  # noqa: E402
    CPhiEncoder,
    affine_six,
    sort_tuples_like_d,
    tensor_hash as cphi_tensor_hash,
)
from f4_invariant_01_model import DEncoder, d_input, tensor_hash as d_tensor_hash  # noqa: E402
from f4_symmetry_01_model import BATCH, EPOCHS, LR, gelu, gelu_grad  # noqa: E402


ARMS = ("D", "Cphi", "Cphi_unshared", "Cphi_shuffled")
CHECKPOINT_EPOCHS = (1, 2, 4, 8, 16, 32, 64, 128, 200)
SHUFFLE_DOMAIN = b"F4-PRESENTATION-03-ROW-PERMUTATION-v1\0"
UNSHARED_TENSOR_NAMES = (
    "phi.w", "phi.b", "rho1.w", "rho1.b", "rho2.w", "rho2.b", "rho3.w", "rho3.b",
)
UNSHARED_TENSOR_SHAPES = (
    (4, 6, 16), (4, 16), (130, 101), (101,), (101, 64), (64,), (64, 1), (1,),
)
UNSHARED_PARAMETER_COUNT = 20_272


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def row_permutation(row_key: bytes) -> tuple[int, int, int, int]:
    """Derive one deterministic Fisher-Yates permutation from an opaque row key."""
    if not isinstance(row_key, bytes) or not row_key:
        raise ValueError("row key must be nonempty bytes")
    digest = hashlib.sha256(SHUFFLE_DOMAIN + struct.pack("<I", len(row_key)) + row_key).digest()
    state = int.from_bytes(digest[:8], "little", signed=False)
    values = [0, 1, 2, 3]
    for end in range(3, 0, -1):
        state = (state + 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
        z = state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1)
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & ((1 << 64) - 1)
        random_u64 = z ^ (z >> 31)
        index = random_u64 % (end + 1)
        values[end], values[index] = values[index], values[end]
    return tuple(values)  # type: ignore[return-value]


def row_permutations(row_keys: Iterable[bytes]) -> np.ndarray:
    keys = tuple(row_keys)
    result = np.empty((len(keys), 4), dtype=np.uint8)
    for row, key in enumerate(keys):
        result[row] = row_permutation(key)
    return result


def shuffle_canonical_tuples(tuples: np.ndarray, permutations: np.ndarray) -> np.ndarray:
    values = np.asarray(tuples, dtype=np.float32)
    order = np.asarray(permutations, dtype=np.uint8)
    if values.ndim != 3 or values.shape[1:] != (4, 6):
        raise ValueError("canonical tuple stream must have shape (N,4,6)")
    if order.shape != (len(values), 4):
        raise ValueError("row permutation stream must have shape (N,4)")
    expected = np.arange(4, dtype=np.uint8)
    if any(not np.array_equal(np.sort(row), expected) for row in order):
        raise ValueError("a row permutation is not a permutation of 0..3")
    return np.ascontiguousarray(values[np.arange(len(values))[:, None], order], dtype=np.float32)


def unshared_tensor_hash(values: Iterable[np.ndarray]) -> str:
    arrays = tuple(values)
    if len(arrays) != len(UNSHARED_TENSOR_NAMES):
        raise ValueError("unshared Cphi tensor count mismatch")
    digest = hashlib.sha256()
    for name, shape, value in zip(UNSHARED_TENSOR_NAMES, UNSHARED_TENSOR_SHAPES, arrays, strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        if tuple(array.shape) != shape or not np.isfinite(array).all():
            raise ValueError(f"invalid unshared Cphi tensor {name}")
        digest.update(name.encode("ascii") + b"\0")
        digest.update(struct.pack("<I", array.ndim))
        for dim in array.shape:
            digest.update(struct.pack("<I", dim))
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def expand_shared_phi(shared_values: list[np.ndarray]) -> list[np.ndarray]:
    """Copy the frozen shared phi into four initially identical slot maps."""
    if cphi_tensor_hash(shared_values) == "":
        raise ValueError("invalid source Cphi tensor bundle")
    phi_w, phi_b, rho1_w, rho1_b, rho2_w, rho2_b, rho3_w, rho3_b = shared_values
    values = [
        np.repeat(np.asarray(phi_w, dtype=np.float32)[None, :, :], 4, axis=0),
        np.repeat(np.asarray(phi_b, dtype=np.float32)[None, :], 4, axis=0),
        np.asarray(rho1_w, dtype=np.float32).copy(), np.asarray(rho1_b, dtype=np.float32).copy(),
        np.asarray(rho2_w, dtype=np.float32).copy(), np.asarray(rho2_b, dtype=np.float32).copy(),
        np.asarray(rho3_w, dtype=np.float32).copy(), np.asarray(rho3_b, dtype=np.float32).copy(),
    ]
    if sum(math.prod(shape) for shape in UNSHARED_TENSOR_SHAPES) != UNSHARED_PARAMETER_COUNT:
        raise RuntimeError("unshared Cphi parameter count changed")
    return values


class DTrackedEncoder(DEncoder):
    """Frozen D update arithmetic with read-only per-layer gradient norms."""

    def update_tracked(self, x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
        labels = np.asarray(y, dtype=np.float32)
        logits, (features, z1, a1, z2, a2) = self.forward(np.asarray(x, dtype=np.float32))
        probability = np.float32(1.0) / (
            np.float32(1.0) + np.exp(-np.clip(logits, -30.0, 30.0))
        )
        d3 = ((probability - labels) / max(1, len(labels))).astype(np.float32)[:, None]
        d2 = (d3 @ self.values[4].T) * gelu_grad(z2)
        d1 = (d2 @ self.values[2].T) * gelu_grad(z1)
        gradients = [
            features.T @ d1, d1.sum(axis=0), a1.T @ d2, d2.sum(axis=0),
            a2.T @ d3, d3.sum(axis=0),
        ]
        norms = tuple(
            float(np.sqrt(np.sum(np.square(gradients[index].astype(np.float64))) +
                          np.sum(np.square(gradients[index + 1].astype(np.float64)))))
            for index in (0, 2, 4)
        )
        self.step += 1
        for index, (value, gradient) in enumerate(zip(self.values, gradients, strict=True)):
            self.m[index] = np.float32(0.9) * self.m[index] + np.float32(0.1) * gradient
            self.v[index] = np.float32(0.999) * self.v[index] + np.float32(0.001) * gradient * gradient
            m_hat = self.m[index] / (1.0 - 0.9 ** self.step)
            v_hat = self.v[index] / (1.0 - 0.999 ** self.step)
            value -= np.float32(LR) * m_hat / (np.sqrt(v_hat) + np.float32(1e-8))
        return norms  # type: ignore[return-value]

    def tensor_hash(self) -> str:
        return d_tensor_hash(self.values, "D")

    def optimizer_summary(self) -> dict[str, object]:
        def norm(value: np.ndarray) -> float:
            return float(np.linalg.norm(value.astype(np.float64)))
        names = ("w1", "b1", "w2", "b2", "w3", "b3")
        return {
            "step": self.step,
            "moment_norms": {name: norm(value) for name, value in zip(names, self.m, strict=True)},
            "variance_norms": {name: norm(value) for name, value in zip(names, self.v, strict=True)},
        }


class CphiUnsharedEncoder:
    """Four independent canonical-slot phi maps and the frozen Cphi readout."""

    def __init__(self, values: list[np.ndarray]):
        self.values = [np.ascontiguousarray(value, dtype=np.float32).copy() for value in values]
        self.hash = unshared_tensor_hash(self.values)
        self.m = [np.zeros_like(value) for value in self.values]
        self.v = [np.zeros_like(value) for value in self.values]
        self.step = 0

    def forward(self, base: np.ndarray, tuples: np.ndarray, *, canonical: bool = False):
        x = np.asarray(base, dtype=np.float32)
        ordered = np.asarray(tuples, dtype=np.float32) if canonical else sort_tuples_like_d(x, tuples)
        if x.ndim != 2 or x.shape[1] != 66 or ordered.shape != (len(x), 4, 6):
            raise ValueError("unshared Cphi input shape mismatch")
        phi_w, phi_b, rho1_w, rho1_b, rho2_w, rho2_b, rho3_w, rho3_b = self.values
        zphi = np.empty((len(x), 4, 16), dtype=np.float32)
        h = np.empty_like(zphi)
        for slot in range(4):
            zphi[:, slot] = affine_six(ordered[:, slot, :], phi_w[slot], phi_b[slot])
            h[:, slot] = gelu(zphi[:, slot])
        rel = h.reshape(len(x), 64)
        readout = np.concatenate((x, rel), axis=1).astype(np.float32, copy=False)
        z1 = readout @ rho1_w + rho1_b
        a1 = gelu(z1)
        z2 = a1 @ rho2_w + rho2_b
        a2 = gelu(z2)
        logits = (a2 @ rho3_w + rho3_b)[:, 0]
        return logits.astype(np.float32, copy=False), (x, ordered, zphi, h, rel, readout, z1, a1, z2, a2)

    def gradients(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray, *, canonical: bool = False):
        labels = np.asarray(y, dtype=np.float32)
        logits, cache = self.forward(base, tuples, canonical=canonical)
        x, ordered, zphi, _h, _rel, readout, z1, a1, z2, a2 = cache
        if labels.shape != (len(x),) or not np.isin(labels, (0.0, 1.0)).all():
            raise ValueError("unshared Cphi labels must be one-dimensional binary values")
        probability = np.float32(1.0) / (
            np.float32(1.0) + np.exp(-np.clip(logits, -30.0, 30.0))
        )
        d3 = ((probability - labels) / max(1, len(labels))).astype(np.float32)[:, None]
        d2 = (d3 @ self.values[6].T) * gelu_grad(z2)
        d1 = (d2 @ self.values[4].T) * gelu_grad(z1)
        grad_readout = d1 @ self.values[2].T
        dphi = (grad_readout[:, 66:].reshape(len(x), 4, 16) * gelu_grad(zphi)).astype(np.float32)
        grad_phi_w = np.empty_like(self.values[0])
        grad_phi_b = np.empty_like(self.values[1])
        for slot in range(4):
            grad_phi_w[slot] = ordered[:, slot, :].T @ dphi[:, slot, :]
            grad_phi_b[slot] = dphi[:, slot, :].sum(axis=0)
        gradients = [
            grad_phi_w, grad_phi_b, readout.T @ d1, d1.sum(axis=0),
            a1.T @ d2, d2.sum(axis=0), a2.T @ d3, d3.sum(axis=0),
        ]
        return [np.asarray(value, dtype=np.float32) for value in gradients]

    @staticmethod
    def _norm(weight_grad: np.ndarray, bias_grad: np.ndarray) -> float:
        total = np.sum(np.square(weight_grad.astype(np.float64)))
        total += np.sum(np.square(bias_grad.astype(np.float64)))
        return float(np.sqrt(total))

    def update(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray, *, canonical: bool = False):
        gradients = self.gradients(base, tuples, y, canonical=canonical)
        norms = (
            float(np.sqrt(np.sum(np.square(gradients[0].astype(np.float64))) + np.sum(np.square(gradients[1].astype(np.float64))))),
            self._norm(gradients[2], gradients[3]),
            self._norm(gradients[4], gradients[5]),
            self._norm(gradients[6], gradients[7]),
        )
        self.step += 1
        for index, (value, gradient) in enumerate(zip(self.values, gradients, strict=True)):
            self.m[index] = np.float32(0.9) * self.m[index] + np.float32(0.1) * gradient
            self.v[index] = np.float32(0.999) * self.v[index] + np.float32(0.001) * gradient * gradient
            m_hat = self.m[index] / (1.0 - 0.9 ** self.step)
            v_hat = self.v[index] / (1.0 - 0.999 ** self.step)
            value -= np.float32(LR) * m_hat / (np.sqrt(v_hat) + np.float32(1e-8))
        return norms

    def logits(self, base: np.ndarray, tuples: np.ndarray, *, canonical: bool = False) -> np.ndarray:
        return self.forward(base, tuples, canonical=canonical)[0]

    def tensor_hash(self) -> str:
        return unshared_tensor_hash(self.values)

    def optimizer_summary(self) -> dict[str, object]:
        def norm(value: np.ndarray) -> float:
            return float(np.linalg.norm(value.astype(np.float64)))
        return {
            "step": self.step,
            "moment_norms": {name: norm(value) for name, value in zip(UNSHARED_TENSOR_NAMES, self.m, strict=True)},
            "variance_norms": {name: norm(value) for name, value in zip(UNSHARED_TENSOR_NAMES, self.v, strict=True)},
        }


def d_present(base: np.ndarray, tuples: np.ndarray) -> np.ndarray:
    return d_input(base, tuples)


def cphi_present(base: np.ndarray, tuples: np.ndarray) -> np.ndarray:
    return sort_tuples_like_d(base, tuples)


def shuffle_present(base: np.ndarray, tuples: np.ndarray, row_keys: Iterable[bytes]) -> tuple[np.ndarray, np.ndarray]:
    canonical = sort_tuples_like_d(base, tuples)
    permutations = row_permutations(row_keys)
    if len(permutations) != len(canonical):
        raise ValueError("row keys do not align to tuple rows")
    return shuffle_canonical_tuples(canonical, permutations), permutations


def parameter_counts() -> dict[str, int]:
    return {"D": 19_969, "Cphi": 19_936, "Cphi_unshared": UNSHARED_PARAMETER_COUNT, "Cphi_shuffled": 19_936}


def _predict_training(model, arm: str, base: np.ndarray, tuples: np.ndarray) -> np.ndarray:
    parts: list[np.ndarray] = []
    for start in range(0, len(base), BATCH):
        stop = start + BATCH
        if arm == "D":
            parts.append(model.logits(tuples[start:stop]))
        elif arm == "Cphi_unshared":
            parts.append(model.logits(base[start:stop], tuples[start:stop], canonical=True))
        else:
            parts.append(model.logits(base[start:stop], tuples[start:stop], canonical=True))
    return np.concatenate(parts).astype(np.float32, copy=False)


def _training_metrics(logits: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    y = np.asarray(labels, dtype=np.float64)
    score = np.asarray(logits, dtype=np.float64)
    bce = np.mean(np.maximum(score, 0.0) - score * y + np.log1p(np.exp(-np.abs(score))))
    predicted = score > 0.0
    positive = y > 0.5
    error = 0.5 * (np.mean(predicted[positive] == 0) + np.mean(predicted[~positive] == 1))
    return float(bce), float(error)


def _copy_tensors(model) -> list[np.ndarray]:
    return [np.ascontiguousarray(value, dtype=np.float32).copy() for value in model.values]


def fit_checkpointed(
    arm: str,
    model,
    base: np.ndarray,
    tuples: np.ndarray,
    labels: np.ndarray,
    *,
    permutations: np.ndarray | None = None,
) -> tuple[list[dict[str, float]], dict[int, list[np.ndarray]]]:
    """Train exactly EPOCHS in fixed row order and retain the frozen checkpoints."""
    if arm not in ARMS:
        raise ValueError(f"unknown presentation arm: {arm}")
    x = np.asarray(base, dtype=np.float32)
    r = np.asarray(tuples, dtype=np.float32)
    y = np.asarray(labels, dtype=np.float32)
    if x.shape != (len(y), 66) or r.shape != (len(y), 4, 6):
        raise ValueError("training stream shape mismatch")
    if not np.isfinite(x).all() or not np.isfinite(r).all() or not np.isin(y, (0.0, 1.0)).all():
        raise ValueError("training stream has nonfinite features or invalid labels")

    if arm == "D":
        model_input = d_present(x, r)
        presented = None
    else:
        canonical = cphi_present(x, r)
        presented = shuffle_canonical_tuples(canonical, permutations) if arm == "Cphi_shuffled" and permutations is not None else canonical
        if arm == "Cphi_shuffled" and permutations is None:
            raise ValueError("Cphi-shuffled requires row-keyed permutations")
        model_input = None

    trace: list[dict[str, float]] = []
    checkpoints: dict[int, list[np.ndarray]] = {}
    for epoch in range(1, EPOCHS + 1):
        grad_sum: np.ndarray | None = None
        grad_max: np.ndarray | None = None
        batches = 0
        for start in range(0, len(y), BATCH):
            stop = start + BATCH
            if arm == "D":
                norms = np.asarray(model.update_tracked(model_input[start:stop], y[start:stop]), dtype=np.float64)
            else:
                norms = np.asarray(
                    model.update(x[start:stop], presented[start:stop], y[start:stop], canonical=True),
                    dtype=np.float64,
                )
            if not np.isfinite(norms).all():
                raise RuntimeError(f"nonfinite gradient norm in {arm} at epoch {epoch}")
            grad_sum = norms.copy() if grad_sum is None else grad_sum + norms
            grad_max = norms.copy() if grad_max is None else np.maximum(grad_max, norms)
            batches += 1

        logits = _predict_training(model, arm, x, model_input if arm == "D" else presented)
        bce, balanced_error = _training_metrics(logits, y)
        finite_state = all(np.isfinite(value).all() for value in model.values + model.m + model.v)
        if not finite_state or not math.isfinite(bce) or not math.isfinite(balanced_error):
            raise RuntimeError(f"nonfinite training state or metric in {arm} at epoch {epoch}")
        record: dict[str, float] = {
            "epoch": float(epoch), "training_bce": bce,
            "training_balanced_error": balanced_error, "finite_state": 1.0,
        }
        names = ("d1", "d2", "d3") if arm == "D" else ("phi", "rho1", "rho2", "rho3")
        if grad_sum is None or grad_max is None or batches == 0:
            raise RuntimeError("empty training fold reached update loop")
        for index, name in enumerate(names):
            record[f"{name}_gradient_norm_mean"] = float(grad_sum[index] / batches)
            record[f"{name}_gradient_norm_max"] = float(grad_max[index])
        trace.append(record)
        if epoch in CHECKPOINT_EPOCHS:
            checkpoints[epoch] = _copy_tensors(model)

    if tuple(checkpoints) != CHECKPOINT_EPOCHS:
        raise RuntimeError("checkpoint set differs from frozen schedule")
    if model.step != EPOCHS * ((len(y) + BATCH - 1) // BATCH):
        raise RuntimeError("optimizer update count differs from frozen schedule")
    if not all(np.isfinite(value).all() for value in model.values + model.m + model.v):
        raise RuntimeError("nonfinite trained model state")
    return trace, checkpoints
