"""Shared tuple encoder with D-canonical ordering and concatenated tuple identity."""
from __future__ import annotations

import hashlib
import math
import struct
from pathlib import Path
from typing import Iterable

import numpy as np

from f4_invariant_01_model import gelu, gelu_grad
from f4_symmetry_01_model import BATCH, EPOCHS, LR


TENSOR_NAMES = ("phi.w", "phi.b", "rho1.w", "rho1.b", "rho2.w", "rho2.b", "rho3.w", "rho3.b")
TENSOR_SHAPES = ((6, 16), (16,), (130, 101), (101,), (101, 64), (64,), (64, 1), (1,))
PARAMETER_COUNT = sum(math.prod(shape) for shape in TENSOR_SHAPES)
INIT_DOMAIN = b"F4-PRESENTATION-02-CPHI-INIT-v1\0"


def tensor_hash(values: Iterable[np.ndarray]) -> str:
    values = tuple(values)
    if len(values) != len(TENSOR_NAMES):
        raise ValueError("Cphi tensor count mismatch")
    digest = hashlib.sha256()
    for name, shape, value in zip(TENSOR_NAMES, TENSOR_SHAPES, values, strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        if tuple(array.shape) != shape or not np.isfinite(array).all():
            raise ValueError(f"invalid Cphi tensor {name}")
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(struct.pack("<I", array.ndim))
        for dim in array.shape:
            digest.update(struct.pack("<I", dim))
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _seed(fold: int, replicate: int, layer: str) -> tuple[str, int]:
    payload = INIT_DOMAIN + struct.pack("<II", fold, replicate) + layer.encode("ascii") + b"\0"
    digest = hashlib.sha256(payload).digest()
    return digest.hex(), int.from_bytes(digest[:8], "little", signed=False)


def _weight(shape: tuple[int, ...], fan_in: int, seed: int) -> np.ndarray:
    rng = np.random.Generator(np.random.PCG64(seed))
    return (rng.standard_normal(shape) * math.sqrt(2.0 / fan_in)).astype(np.float32)


def make_initial_tensors(
    fold: int,
    replicate: int,
    phi_weight: np.ndarray,
    phi_bias: np.ndarray,
) -> tuple[list[np.ndarray], list[dict[str, object]]]:
    if not (0 <= fold < 12 and 0 <= replicate < 3):
        raise ValueError("Cphi initializer identity outside frozen fold/replicate grid")
    if phi_weight.shape != (6, 16) or phi_bias.shape != (16,):
        raise ValueError("S phi initializer shape mismatch")
    records: list[dict[str, object]] = []
    weight_by_layer: dict[str, np.ndarray] = {}
    for layer, shape, fan_in in (
        ("rho1.w", (130, 101), 130),
        ("rho2.w", (101, 64), 101),
        ("rho3.w", (64, 1), 64),
    ):
        digest, seed = _seed(fold, replicate, layer)
        value = _weight(shape, fan_in, seed)
        weight_by_layer[layer] = value
        records.append({"layer": layer, "seed_sha256": digest, "seed_u64": seed, "shape": list(shape), "fan_in": fan_in})
    values = [
        np.ascontiguousarray(phi_weight, dtype=np.float32).copy(),
        np.ascontiguousarray(phi_bias, dtype=np.float32).copy(),
        weight_by_layer["rho1.w"], np.zeros(101, dtype=np.float32),
        weight_by_layer["rho2.w"], np.zeros(64, dtype=np.float32),
        weight_by_layer["rho3.w"], np.zeros(1, dtype=np.float32),
    ]
    if PARAMETER_COUNT != 19_936:
        raise RuntimeError("Cphi parameter count changed")
    return values, records


def sort_tuples_like_d(base: np.ndarray, tuples: np.ndarray) -> np.ndarray:
    """Return normalized tuples in exactly D's lexicographic tuple order."""
    x = np.asarray(base, dtype=np.float32)
    values = np.ascontiguousarray(tuples, dtype=np.float32).copy()
    if x.ndim != 2 or x.shape[1] != 66 or values.shape != (len(x), 4, 6):
        raise ValueError("Cphi tuple canonicalization input shape mismatch")
    if not np.isfinite(x).all() or not np.isfinite(values).all():
        raise ValueError("Cphi tuple canonicalization input is nonfinite")
    values[values == np.float32(0.0)] = np.float32(0.0)
    # Match D exactly: its first three sort fields are int-cast, then fields 3..5
    # are compared as float. lexsort's final key is primary. Equal keys preserve
    # byte-identical tuple order under the stable parent sort.
    keys = (
        values[:, :, 5], values[:, :, 4], values[:, :, 3],
        values[:, :, 2].astype(np.int64), values[:, :, 1].astype(np.int64),
        values[:, :, 0].astype(np.int64),
    )
    order = np.lexsort(keys, axis=1)
    gather = np.broadcast_to(order[:, :, None], values.shape)
    return np.ascontiguousarray(np.take_along_axis(values, gather, axis=1), dtype=np.float32)


def affine_six(rows: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    acc = np.multiply(rows[:, 0:1], weight[0:1, :])
    for dim in range(1, 6):
        acc = np.add(acc, np.multiply(rows[:, dim:dim + 1], weight[dim:dim + 1, :]))
    return np.add(acc, bias)


class CPhiEncoder:
    def __init__(self, values: list[np.ndarray]):
        if tensor_hash(values) == "":
            raise ValueError("empty Cphi tensor hash")
        self.values = [np.ascontiguousarray(v, dtype=np.float32).copy() for v in values]
        self.m = [np.zeros_like(v) for v in self.values]
        self.v = [np.zeros_like(v) for v in self.values]
        self.step = 0

    def forward(self, base: np.ndarray, tuples: np.ndarray, *, canonical: bool = False):
        x = np.asarray(base, dtype=np.float32)
        ordered = np.asarray(tuples, dtype=np.float32) if canonical else sort_tuples_like_d(x, tuples)
        phi_w, phi_b, rho1_w, rho1_b, rho2_w, rho2_b, rho3_w, rho3_b = self.values
        flat = ordered.reshape(len(x) * 4, 6)
        zphi = affine_six(flat, phi_w, phi_b)
        h = gelu(zphi).reshape(len(x), 4, 16)
        rel = h.reshape(len(x), 64)
        readout = np.concatenate((x, rel), axis=1).astype(np.float32, copy=False)
        z1 = readout @ rho1_w + rho1_b
        a1 = gelu(z1)
        z2 = a1 @ rho2_w + rho2_b
        a2 = gelu(z2)
        logits = (a2 @ rho3_w + rho3_b)[:, 0]
        cache = (x, ordered, zphi, h, rel, readout, z1, a1, z2, a2)
        return logits.astype(np.float32, copy=False), cache

    def gradients(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray, *, canonical: bool = False) -> list[np.ndarray]:
        labels = np.asarray(y, dtype=np.float32)
        logits, cache = self.forward(base, tuples, canonical=canonical)
        x, ordered, zphi, _h, _rel, readout, z1, a1, z2, a2 = cache
        if labels.shape != (len(x),) or not np.isin(labels, (0.0, 1.0)).all():
            raise ValueError("Cphi batch labels must be one-dimensional binary values")
        probability = np.float32(1.0) / (np.float32(1.0) + np.exp(-np.clip(logits, -30.0, 30.0)))
        d3 = ((probability - labels) / max(1, len(labels))).astype(np.float32)[:, None]
        d2 = (d3 @ self.values[6].T) * gelu_grad(z2)
        d1 = (d2 @ self.values[4].T) * gelu_grad(z1)
        grad_input = d1 @ self.values[2].T
        dphi = (grad_input[:, 66:].reshape(len(x) * 4, 16) * gelu_grad(zphi)).astype(np.float32)
        flat = ordered.reshape(len(x) * 4, 6)
        gradients = [
            flat.T @ dphi,
            dphi.sum(axis=0),
            readout.T @ d1,
            d1.sum(axis=0),
            a1.T @ d2,
            d2.sum(axis=0),
            a2.T @ d3,
            d3.sum(axis=0),
        ]
        return [np.asarray(value, dtype=np.float32) for value in gradients]

    @staticmethod
    def _layer_norm(weight_grad: np.ndarray, bias_grad: np.ndarray) -> float:
        total = np.sum(np.square(weight_grad.astype(np.float64))) + np.sum(np.square(bias_grad.astype(np.float64)))
        return float(np.sqrt(total))

    def update(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray, *, canonical: bool = False) -> tuple[float, ...]:
        gradients = self.gradients(base, tuples, y, canonical=canonical)
        norms = tuple(self._layer_norm(gradients[i], gradients[i + 1]) for i in (0, 2, 4, 6))
        self.step += 1
        for index, (value, gradient) in enumerate(zip(self.values, gradients, strict=True)):
            self.m[index] = np.float32(0.9) * self.m[index] + np.float32(0.1) * gradient
            self.v[index] = np.float32(0.999) * self.v[index] + np.float32(0.001) * gradient * gradient
            m_hat = self.m[index] / (1.0 - 0.9 ** self.step)
            v_hat = self.v[index] / (1.0 - 0.999 ** self.step)
            value -= np.float32(LR) * m_hat / (np.sqrt(v_hat) + np.float32(1e-8))
        return norms

    def _training_metrics(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray) -> tuple[float, float]:
        logits_parts = [self.logits(base[start:start + BATCH], tuples[start:start + BATCH], canonical=True) for start in range(0, len(y), BATCH)]
        logits = np.concatenate(logits_parts).astype(np.float64)
        labels = y.astype(np.float64)
        bce = np.mean(np.maximum(logits, 0.0) - logits * labels + np.log1p(np.exp(-np.abs(logits))))
        signed = np.where(logits > 0.0, 1, -1)
        target = np.where(labels > 0.5, 1, -1)
        error = 0.5 * (np.mean(signed[target == 1] != 1) + np.mean(signed[target == -1] != -1))
        return float(bce), float(error)

    def fit_instrumented(self, base: np.ndarray, tuples: np.ndarray, y: np.ndarray) -> list[dict[str, float]]:
        trace: list[dict[str, float]] = []
        ordered_tuples = sort_tuples_like_d(base, tuples)
        for epoch in range(EPOCHS):
            sums = np.zeros(4, dtype=np.float64)
            maxima = np.zeros(4, dtype=np.float64)
            batches = 0
            for start in range(0, len(y), BATCH):
                stop = start + BATCH
                norms = np.asarray(self.update(base[start:stop], ordered_tuples[start:stop], y[start:stop], canonical=True), dtype=np.float64)
                sums += norms
                maxima = np.maximum(maxima, norms)
                batches += 1
            bce, error = self._training_metrics(base, tuples, y)
            record: dict[str, float] = {"epoch": float(epoch + 1), "training_bce": bce, "training_balanced_error": error}
            for index, layer in enumerate(("phi", "rho1", "rho2", "rho3")):
                record[f"{layer}_gradient_norm_mean"] = float(sums[index] / batches)
                record[f"{layer}_gradient_norm_max"] = float(maxima[index])
            trace.append(record)
        return trace

    def logits(self, base: np.ndarray, tuples: np.ndarray, *, canonical: bool = False) -> np.ndarray:
        return self.forward(base, tuples, canonical=canonical)[0]

    def heldout_state(self, base: np.ndarray, tuples: np.ndarray):
        logits, cache = self.forward(base, tuples)
        _x, ordered, _zphi, h, rel, _readout, _z1, _a1, _z2, a2 = cache
        h01 = np.add(h[:, 0, :], h[:, 1, :])
        h012 = np.add(h01, h[:, 2, :])
        summed = np.add(h012, h[:, 3, :])
        pair_dists = []
        for left in range(4):
            for right in range(left + 1, 4):
                pair_dists.append(np.linalg.norm(h[:, left] - h[:, right], axis=1))
        role_separation = np.mean(np.stack(pair_dists, axis=1), axis=1).astype(np.float32)
        return {
            "ordered_tuples": ordered,
            "phi_outputs": h,
            "relational_concat": rel,
            "posthoc_sum": summed,
            "penultimate_hidden": a2.astype(np.float32, copy=False),
            "role_separation": role_separation,
            "logits": logits,
        }

    def optimizer_summary(self) -> dict[str, object]:
        def norm(value: np.ndarray) -> float:
            return float(np.linalg.norm(value.astype(np.float64)))
        return {
            "step": self.step,
            "moment_norms": {name: norm(value) for name, value in zip(TENSOR_NAMES, self.m, strict=True)},
            "variance_norms": {name: norm(value) for name, value in zip(TENSOR_NAMES, self.v, strict=True)},
        }


def serialize_tensors(values: Iterable[np.ndarray]) -> bytes:
    parts: list[bytes] = [b"F4PRES02CPHITENS\0"]
    for name, shape, value in zip(TENSOR_NAMES, TENSOR_SHAPES, values, strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        if tuple(array.shape) != shape:
            raise ValueError(f"unexpected Cphi tensor shape: {name}")
        parts.append(name.encode("ascii") + b"\0")
        parts.append(struct.pack("<I", array.ndim))
        parts.append(struct.pack("<" + "I" * array.ndim, *array.shape))
        parts.append(array.tobytes(order="C"))
    return b"".join(parts)


def deserialize_tensors(raw: bytes) -> list[np.ndarray]:
    if not raw.startswith(b"F4PRES02CPHITENS\0"):
        raise ValueError("Cphi tensor bundle magic mismatch")
    offset = len(b"F4PRES02CPHITENS\0")
    values = []
    for name, expected_shape in zip(TENSOR_NAMES, TENSOR_SHAPES, strict=True):
        expected_name = name.encode("ascii") + b"\0"
        if raw[offset:offset + len(expected_name)] != expected_name:
            raise ValueError("Cphi tensor name mismatch")
        offset += len(expected_name)
        ndim = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        shape = struct.unpack_from("<" + "I" * ndim, raw, offset)
        offset += 4 * ndim
        if tuple(shape) != expected_shape or ndim != len(expected_shape):
            raise ValueError("Cphi tensor dimensions mismatch")
        size = math.prod(expected_shape) * 4
        value = np.frombuffer(raw, dtype="<f4", count=math.prod(expected_shape), offset=offset).reshape(expected_shape).copy()
        offset += size
        values.append(value)
    if offset != len(raw):
        raise ValueError("extra bytes in Cphi tensor bundle")
    return values
