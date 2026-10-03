"""Frozen float32 MLP and tensor hashing used by the four F4-SYMMETRY arms."""
from __future__ import annotations

import hashlib
import math
import struct

import numpy as np

EPOCHS = 200
BATCH = 2048
LR = 0.001
HIDDEN = (128, 64)
BASE_SEED = 304000


def make_tensors(input_width: int, fold_index: int) -> list[np.ndarray]:
    rng = np.random.default_rng(BASE_SEED + fold_index)
    w1 = (rng.standard_normal((input_width, HIDDEN[0])) * math.sqrt(2.0 / input_width)).astype(np.float32)
    b1 = np.zeros(HIDDEN[0], dtype=np.float32)
    w2 = (rng.standard_normal((HIDDEN[0], HIDDEN[1])) * math.sqrt(2.0 / HIDDEN[0])).astype(np.float32)
    b2 = np.zeros(HIDDEN[1], dtype=np.float32)
    w3 = (rng.standard_normal((HIDDEN[1], 1)) * math.sqrt(2.0 / HIDDEN[1])).astype(np.float32)
    b3 = np.zeros(1, dtype=np.float32)
    return [w1, b1, w2, b2, w3, b3]


def tensor_hash(values: list[np.ndarray]) -> str:
    names = (b"w1", b"b1", b"w2", b"b2", b"w3", b"b3")
    digest = hashlib.sha256()
    for name, value in zip(names, values, strict=True):
        array = np.ascontiguousarray(value, dtype="<f4")
        digest.update(name + b"\0")
        digest.update(struct.pack("<I", array.ndim))
        for dimension in array.shape:
            digest.update(struct.pack("<I", dimension))
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def gelu(value: np.ndarray) -> np.ndarray:
    return np.float32(0.5) * value * (np.float32(1.0) + np.tanh(np.float32(0.79788456) * (value + np.float32(0.044715) * value * value * value)))


def gelu_grad(value: np.ndarray) -> np.ndarray:
    tanh_value = np.tanh(np.float32(0.79788456) * (value + np.float32(0.044715) * value * value * value))
    return np.float32(0.5) * (np.float32(1.0) + tanh_value) + np.float32(0.5) * value * (np.float32(1.0) - tanh_value * tanh_value) * np.float32(0.79788456) * (np.float32(1.0) + np.float32(3.0 * 0.044715) * value * value)


class Encoder:
    def __init__(self, input_width: int, fold_index: int):
        self.values = make_tensors(input_width, fold_index)
        self.m = [np.zeros_like(value) for value in self.values]
        self.v = [np.zeros_like(value) for value in self.values]
        self.step = 0

    def forward(self, x: np.ndarray):
        w1, b1, w2, b2, w3, b3 = self.values
        z1 = x @ w1 + b1
        a1 = gelu(z1)
        z2 = a1 @ w2 + b2
        a2 = gelu(z2)
        return (a2 @ w3 + b3)[:, 0], (x, z1, a1, z2, a2)

    def update(self, x: np.ndarray, y: np.ndarray) -> None:
        logits, (x, z1, a1, z2, a2) = self.forward(x)
        probability = np.float32(1.0) / (np.float32(1.0) + np.exp(-np.clip(logits, -30.0, 30.0)))
        d3 = ((probability - y) / max(1, len(y))).astype(np.float32)[:, None]
        d2 = (d3 @ self.values[4].T) * gelu_grad(z2)
        d1 = (d2 @ self.values[2].T) * gelu_grad(z1)
        gradients = [x.T @ d1, d1.sum(axis=0), a1.T @ d2, d2.sum(axis=0), a2.T @ d3, d3.sum(axis=0)]
        self.step += 1
        for index, (value, gradient) in enumerate(zip(self.values, gradients, strict=True)):
            self.m[index] = np.float32(0.9) * self.m[index] + np.float32(0.1) * gradient
            self.v[index] = np.float32(0.999) * self.v[index] + np.float32(0.001) * gradient * gradient
            m_hat = self.m[index] / (1.0 - 0.9 ** self.step)
            v_hat = self.v[index] / (1.0 - 0.999 ** self.step)
            value -= np.float32(LR) * m_hat / (np.sqrt(v_hat) + np.float32(1e-8))

    def fit(self, x: np.ndarray, y: np.ndarray) -> None:
        for _ in range(EPOCHS):
            for start in range(0, len(y), BATCH):
                self.update(x[start : start + BATCH], y[start : start + BATCH])

    def logits(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x)[0].astype(np.float32, copy=False)
