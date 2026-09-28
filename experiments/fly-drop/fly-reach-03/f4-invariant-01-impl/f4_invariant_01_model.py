"""Task-independent D/S model implementations for F4-INVARIANT-01.

This module deliberately contains no task generator, task IDs, task seeds, row
collection, fit orchestration, or outcome analysis. It is a literal float32
implementation of the frozen architectures and initializer contract.
"""
from __future__ import annotations

import hashlib
import itertools
import math
import os
import struct
import sys
from pathlib import Path
from typing import Iterable

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

from f4_symmetry_01_model import (  # noqa: E402
    BATCH,
    EPOCHS,
    LR,
    Encoder as FrozenDBase,
    gelu,
    gelu_grad,
)

INIT_DOMAIN = b"F4-INVARIANT-01-INIT-v1\0"
ARMS = ("D", "S")
FOLDS = tuple(range(12))
REPLICATES = tuple(range(3))
PARAMETERS = {
    "D": (("w1", (90, 128), 90), ("w2", (128, 64), 128), ("w3", (64, 1), 64)),
    "S": (
        ("phi.w", (6, 16), 6),
        ("rho.w1", (82, 128), 82),
        ("rho.w2", (128, 64), 128),
        ("rho.w3", (64, 1), 64),
    ),
}
TENSOR_NAMES = {
    "D": ("w1", "b1", "w2", "b2", "w3", "b3"),
    "S": ("phi.w", "phi.b", "rho.w1", "rho.b1", "rho.w2", "rho.b2", "rho.w3", "rho.b3"),
}
TENSOR_SHAPES = {
    "D": ((90, 128), (128,), (128, 64), (64,), (64, 1), (1,)),
    "S": ((6, 16), (16,), (82, 128), (128,), (128, 64), (64,), (64, 1), (1,)),
}
PARAMETER_COUNTS = {"D": 19_969, "S": 19_057}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tensor_hash(values: Iterable[np.ndarray], arm: str) -> str:
    names = TENSOR_NAMES[arm]
    materialized = tuple(values)
    require(len(materialized) == len(names), f"{arm} tensor count mismatch")
    digest = hashlib.sha256()
    for name, value, expected_shape in zip(names, materialized, TENSOR_SHAPES[arm], strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        require(tuple(array.shape) == expected_shape, f"{arm}.{name} tensor shape mismatch")
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(struct.pack("<I", array.ndim))
        for dimension in array.shape:
            digest.update(struct.pack("<I", dimension))
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def seed_payload(fold_index: int, replicate_index: int, arm: str, layer_name: str) -> bytes:
    require(0 <= fold_index < 12, "fold index outside frozen 0..11 namespace")
    require(0 <= replicate_index < 3, "replicate index outside frozen 0..2 namespace")
    require(arm in ARMS, "unknown arm")
    require((arm, layer_name) in {(a, row[0]) for a, rows in PARAMETERS.items() for row in rows}, "unknown weight layer")
    return (
        INIT_DOMAIN
        + struct.pack("<II", fold_index, replicate_index)
        + arm.encode("ascii")
        + b"\0"
        + layer_name.encode("utf-8")
    )


def derive_layer_seed(fold_index: int, replicate_index: int, arm: str, layer_name: str) -> tuple[bytes, int]:
    payload = seed_payload(fold_index, replicate_index, arm, layer_name)
    digest = hashlib.sha256(payload).digest()
    return digest, int.from_bytes(digest[:8], "little", signed=False)


def _draw_weight(shape: tuple[int, ...], fan_in: int, seed: int) -> np.ndarray:
    generator = np.random.Generator(np.random.PCG64(seed))
    values64 = generator.standard_normal(shape)
    scaled64 = values64 * math.sqrt(2.0 / fan_in)
    return scaled64.astype(np.float32)


def make_initial_tensors(fold_index: int, replicate_index: int, arm: str) -> tuple[list[np.ndarray], list[dict[str, object]]]:
    require(arm in ARMS, "unknown arm")
    layer_values: dict[str, np.ndarray] = {}
    layer_records: list[dict[str, object]] = []
    for layer_name, shape, fan_in in PARAMETERS[arm]:
        payload = seed_payload(fold_index, replicate_index, arm, layer_name)
        digest, seed = derive_layer_seed(fold_index, replicate_index, arm, layer_name)
        value = _draw_weight(shape, fan_in, seed)
        layer_values[layer_name] = value
        layer_records.append({
            "layer_name": layer_name,
            "payload_hex": payload.hex(),
            "sha256_digest": digest.hex(),
            "seed_u64": seed,
            "shape": list(shape),
            "fan_in": fan_in,
            "tensor_sha256": sha256(np.ascontiguousarray(value, dtype="<f4").tobytes(order="C")),
        })
    if arm == "D":
        values = [
            layer_values["w1"], np.zeros(128, dtype=np.float32),
            layer_values["w2"], np.zeros(64, dtype=np.float32),
            layer_values["w3"], np.zeros(1, dtype=np.float32),
        ]
    else:
        values = [
            layer_values["phi.w"], np.zeros(16, dtype=np.float32),
            layer_values["rho.w1"], np.zeros(128, dtype=np.float32),
            layer_values["rho.w2"], np.zeros(64, dtype=np.float32),
            layer_values["rho.w3"], np.zeros(1, dtype=np.float32),
        ]
    require(tensor_hash(values, arm) != "", "tensor hash unexpectedly empty")
    return values, layer_records


def parameter_count(arm: str) -> int:
    return sum(math.prod(shape) for shape in TENSOR_SHAPES[arm])


def initializer_manifest() -> dict[str, object]:
    cells: list[dict[str, object]] = []
    for fold_index in FOLDS:
        for replicate_index in REPLICATES:
            for arm in ARMS:
                values, layers = make_initial_tensors(fold_index, replicate_index, arm)
                cells.append({
                    "fold_index": fold_index,
                    "replicate_index": replicate_index,
                    "arm": arm,
                    "architecture_id": "sorted_tuple_mlp_v1" if arm == "D" else "shared_set_encoder_v1",
                    "parameter_count": parameter_count(arm),
                    "initial_tensor_sha256": tensor_hash(values, arm),
                    "layers": layers,
                })
    return {
        "schema": "F4-INVARIANT-01-initializer-seed-manifest-v1",
        "initializer_domain": "F4-INVARIANT-01-INIT-v1",
        "fold_indices": list(FOLDS),
        "replicate_indices": list(REPLICATES),
        "task_ids_or_task_seeds_used": False,
        "task_bank_created": False,
        "measured_namespace_created": False,
        "cells": cells,
    }


def d_input(base: np.ndarray, tuples: np.ndarray) -> np.ndarray:
    """Present the four tuples in D's canonical per-row sorted order."""
    x = np.asarray(base, dtype=np.float32)
    r = np.asarray(tuples, dtype=np.float32)
    require(x.ndim == 2 and x.shape[1] == 66, "D base must have shape (N,66)")
    require(r.shape == (len(x), 4, 6), "D tuples must have shape (N,4,6)")
    require(np.isfinite(x).all() and np.isfinite(r).all(), "D input contains nonfinite values")
    result = np.empty((len(x), 90), dtype=np.float32)
    result[:, :66] = x
    for row in range(len(x)):
        tuples_row = r[row].copy()
        tuples_row[tuples_row == 0] = np.float32(0.0)
        order = sorted(
            range(4),
            key=lambda cue: (
                int(tuples_row[cue, 0]), int(tuples_row[cue, 1]), int(tuples_row[cue, 2]),
                float(tuples_row[cue, 3]), float(tuples_row[cue, 4]), float(tuples_row[cue, 5]),
            ),
        )
        result[row, 66:] = tuples_row[order].reshape(24)
    return result


def s_input(base: np.ndarray, tuples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(base, dtype=np.float32)
    r = np.asarray(tuples, dtype=np.float32)
    require(x.ndim == 2 and x.shape[1] == 66, "S base must have shape (N,66)")
    require(r.shape == (len(x), 4, 6), "S tuples must have shape (N,4,6)")
    require(np.isfinite(x).all() and np.isfinite(r).all(), "S input contains nonfinite values")
    return x, np.ascontiguousarray(r)


def _f32_affine_six(rows: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """Six-feature affine with separate float32 multiply/add in ascending d."""
    acc = np.multiply(rows[:, 0:1], weight[0:1, :])
    for d in range(1, 6):
        product = np.multiply(rows[:, d:d + 1], weight[d:d + 1, :])
        acc = np.add(acc, product)
    return np.add(acc, bias)


def scalar_phi_and_pool(tuples: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Independent scalar implementation used only by the operation fixture."""
    n_rows = tuples.shape[0]
    pre = np.empty((n_rows, 4, 16), dtype=np.float32)
    pooled = np.empty((n_rows, 16), dtype=np.float32)
    for n in range(n_rows):
        hidden: list[np.ndarray] = []
        for cue in range(4):
            vector = np.empty(16, dtype=np.float32)
            for k in range(16):
                acc = np.float32(np.float32(tuples[n, cue, 0]) * np.float32(weight[0, k]))
                for d in range(1, 6):
                    product = np.float32(np.float32(tuples[n, cue, d]) * np.float32(weight[d, k]))
                    acc = np.float32(acc + product)
                vector[k] = np.float32(acc + np.float32(bias[k]))
            pre[n, cue] = vector
            value = gelu(vector)
            hidden.append(np.asarray(value, dtype=np.float32))
        h01 = np.add(hidden[0], hidden[1])
        h012 = np.add(h01, hidden[2])
        pooled[n] = np.add(h012, hidden[3])
    return pre, pooled


class DEncoder(FrozenDBase):
    """Frozen parent D training code with the new per-layer initialization."""

    def __init__(self, fold_index: int, replicate_index: int, values: list[np.ndarray] | None = None):
        initial, _ = make_initial_tensors(fold_index, replicate_index, "D")
        self.values = initial if values is None else [np.asarray(v, dtype=np.float32).copy() for v in values]
        require(tensor_hash(self.values, "D") != "", "invalid D tensor set")
        self.m = [np.zeros_like(value) for value in self.values]
        self.v = [np.zeros_like(value) for value in self.values]
        self.step = 0


class SEncoder:
    """Shared 6-to-16 tuple transform, sum pool, and frozen MLP readout."""

    def __init__(self, fold_index: int, replicate_index: int, values: list[np.ndarray] | None = None):
        initial, _ = make_initial_tensors(fold_index, replicate_index, "S")
        self.values = initial if values is None else [np.asarray(v, dtype=np.float32).copy() for v in values]
        require(tensor_hash(self.values, "S") != "", "invalid S tensor set")
        self.m = [np.zeros_like(value) for value in self.values]
        self.v = [np.zeros_like(value) for value in self.values]
        self.step = 0

    def forward(self, base: np.ndarray, tuples: np.ndarray):
        x, r = s_input(base, tuples)
        phi_w, phi_b, w1, b1, w2, b2, w3, b3 = self.values
        flat = r.reshape(len(x) * 4, 6)
        zphi = _f32_affine_six(flat, phi_w, phi_b)
        h = gelu(zphi).reshape(len(x), 4, 16)
        h01 = np.add(h[:, 0, :], h[:, 1, :])
        h012 = np.add(h01, h[:, 2, :])
        hset = np.add(h012, h[:, 3, :])
        readout = np.concatenate((x, hset), axis=1).astype(np.float32, copy=False)
        z1 = readout @ w1 + b1
        a1 = gelu(z1)
        z2 = a1 @ w2 + b2
        a2 = gelu(z2)
        logits = (a2 @ w3 + b3)[:, 0]
        cache = (x, r, zphi, hset, readout, z1, a1, z2, a2)
        return logits.astype(np.float32, copy=False), cache

    def gradients(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray) -> list[np.ndarray]:
        labels = np.asarray(y, dtype=np.float32)
        require(labels.ndim == 1 and len(labels) == len(base), "S target shape mismatch")
        require(np.isin(labels, (0.0, 1.0)).all(), "S fit target must be binary 0/1")
        logits, cache = self.forward(base, tuples)
        x, r, zphi, _hset, readout, z1, a1, z2, a2 = cache
        probability = np.float32(1.0) / (np.float32(1.0) + np.exp(-np.clip(logits, -30.0, 30.0)))
        d3 = ((probability - labels) / max(1, len(labels))).astype(np.float32)[:, None]
        d2 = (d3 @ self.values[6].T) * gelu_grad(z2)
        d1 = (d2 @ self.values[4].T) * gelu_grad(z1)
        grad_readout = d1 @ self.values[2].T
        grad_h = np.broadcast_to(grad_readout[:, 66:82][:, None, :], (len(x), 4, 16))
        dphi = (grad_h.reshape(len(x) * 4, 16) * gelu_grad(zphi)).astype(np.float32)
        flat_tuples = r.reshape(len(x) * 4, 6)
        gradients = [
            flat_tuples.T @ dphi,
            dphi.sum(axis=0),
            readout.T @ d1,
            d1.sum(axis=0),
            a1.T @ d2,
            d2.sum(axis=0),
            a2.T @ d3,
            d3.sum(axis=0),
        ]
        return [np.asarray(gradient, dtype=np.float32) for gradient in gradients]

    def update(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray) -> None:
        gradients = self.gradients(base, tuples, y)
        self.step += 1
        for index, (value, gradient) in enumerate(zip(self.values, gradients, strict=True)):
            self.m[index] = np.float32(0.9) * self.m[index] + np.float32(0.1) * gradient
            self.v[index] = np.float32(0.999) * self.v[index] + np.float32(0.001) * gradient * gradient
            m_hat = self.m[index] / (1.0 - 0.9 ** self.step)
            v_hat = self.v[index] / (1.0 - 0.999 ** self.step)
            value -= np.float32(LR) * m_hat / (np.sqrt(v_hat) + np.float32(1e-8))

    def fit(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray) -> None:
        labels = np.asarray(y, dtype=np.float32)
        for _ in range(EPOCHS):
            for start in range(0, len(labels), BATCH):
                stop = start + BATCH
                self.update(base[start:stop], tuples[start:stop], labels[start:stop])

    def logits(self, base: np.ndarray, tuples: np.ndarray) -> np.ndarray:
        return self.forward(base, tuples)[0]


def fixture_inputs() -> tuple[np.ndarray, np.ndarray]:
    base = np.asarray([(((k % 11) - 5) / 8) for k in range(66)], dtype=np.float32)[None, :]
    tuples = np.asarray([
        (1, +1, +1, -0.375, -0.375, -0.375),
        (0, -1, 0, -0.125, 0.000, +0.125),
        (1, -1, -1, +0.125, +0.125, -0.125),
        (0, +1, 0, +0.375, 0.000, +0.375),
    ], dtype=np.float32)[None, :, :]
    return base, tuples


def fixture_tensors() -> list[np.ndarray]:
    phi_w = np.empty((6, 16), dtype=np.float32)
    phi_b = np.empty((16,), dtype=np.float32)
    rho_w1 = np.empty((82, 128), dtype=np.float32)
    rho_b1 = np.zeros((128,), dtype=np.float32)
    rho_w2 = np.empty((128, 64), dtype=np.float32)
    rho_b2 = np.zeros((64,), dtype=np.float32)
    rho_w3 = np.empty((64, 1), dtype=np.float32)
    rho_b3 = np.zeros((1,), dtype=np.float32)
    for d in range(6):
        for k in range(16):
            phi_w[d, k] = np.float32((((11 * d + 5 * k) % 23) - 11) / 128)
    for k in range(16):
        phi_b[k] = np.float32(((k % 5) - 2) / 32)
    for i in range(82):
        for j in range(128):
            rho_w1[i, j] = np.float32((((7 * i + 3 * j) % 31) - 15) / 256)
    for i in range(128):
        for j in range(64):
            rho_w2[i, j] = np.float32((((5 * i + 11 * j) % 29) - 14) / 256)
    for i in range(64):
        rho_w3[i, 0] = np.float32((((3 * i + 13) % 17) - 8) / 128)
    return [phi_w, phi_b, rho_w1, rho_b1, rho_w2, rho_b2, rho_w3, rho_b3]


def all_tuple_permutations() -> tuple[tuple[int, int, int, int], ...]:
    return tuple(itertools.permutations(range(4)))
