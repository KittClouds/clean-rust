"""Fixed float64 linear-probe mathematics for FAS-00 Phase 3."""

from __future__ import annotations

import hashlib
import math
import struct

import numpy as np
from scipy.optimize import minimize


LAMBDA = 1.0
GRADIENT_TOLERANCE = 1e-8
OPTIMIZER_OPTIONS = {
    "maxiter": 1000,
    "maxfun": 1_000_000,
    "maxcor": 10,
    "maxls": 20,
    "gtol": GRADIENT_TOLERANCE,
    "ftol": 0.0,
}


def scale_from_train(x_train: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Use population moments of this fit's training rows and no other rows."""
    x = np.asarray(x_train, dtype=np.float64).copy(order="C")
    mean = x.mean(axis=0)
    scale = np.maximum(x.std(axis=0, ddof=0), 1e-6)
    x -= mean
    x /= scale
    return x, mean, scale


def apply_scale(x: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    out = np.asarray(x, dtype=np.float64).copy(order="C")
    out -= mean
    out /= scale
    return out


def objective_and_gradient(
    parameters: np.ndarray, x: np.ndarray, y: np.ndarray, classes: int
) -> tuple[float, np.ndarray]:
    dimension = x.shape[1]
    weights = parameters[: classes * dimension].reshape(classes, dimension)
    bias = parameters[classes * dimension :]
    logits = x @ weights.T + bias
    maximum = logits.max(axis=1)
    shifted = logits - maximum[:, None]
    probabilities = np.exp(shifted)
    normalization = probabilities.sum(axis=1)
    loss = np.mean(maximum + np.log(normalization) - logits[np.arange(y.size), y])
    loss += 0.5 * LAMBDA * np.sum(weights * weights)
    probabilities /= normalization[:, None]
    probabilities[np.arange(y.size), y] -= 1.0
    probabilities /= y.size
    gradient_weights = probabilities.T @ x + LAMBDA * weights
    gradient_bias = probabilities.sum(axis=0)
    gradient = np.concatenate((gradient_weights.ravel(), gradient_bias))
    return float(loss), gradient


def fit(x: np.ndarray, y: np.ndarray, classes: int) -> dict:
    """One deterministic full-batch L-BFGS fit; no retry or alternate solver."""
    initial = np.zeros(classes * (x.shape[1] + 1), dtype=np.float64)
    result = minimize(
        objective_and_gradient,
        initial,
        args=(x, y, classes),
        method="L-BFGS-B",
        jac=True,
        bounds=None,
        options=OPTIMIZER_OPTIONS,
    )
    _, final_gradient = objective_and_gradient(result.x, x, y, classes)
    gradient_infinity = float(np.max(np.abs(final_gradient)))
    converged = bool(
        result.success
        and np.isfinite(result.fun)
        and np.all(np.isfinite(result.x))
        and np.all(np.isfinite(final_gradient))
        and gradient_infinity <= GRADIENT_TOLERANCE
    )
    dimension = x.shape[1]
    return {
        "weights": result.x[: classes * dimension].reshape(classes, dimension).copy(),
        "bias": result.x[classes * dimension :].copy(),
        "converged": converged,
        "iterations": int(result.nit),
        "function_evaluations": int(result.nfev),
        "gradient_infinity": gradient_infinity,
        "objective": float(result.fun),
        "solver_message": str(result.message),
    }


def predict(x: np.ndarray, weights: np.ndarray, bias: np.ndarray) -> np.ndarray:
    # NumPy argmax resolves exact ties to the lowest integer class.
    return np.argmax(x @ weights.T + bias, axis=1).astype(np.int16, copy=False)


def metrics(y: np.ndarray, prediction: np.ndarray, classes: int) -> dict:
    support = np.bincount(y, minlength=classes).astype(np.int64)
    correct = np.bincount(y[y == prediction], minlength=classes).astype(np.int64)
    recall = [float(correct[i] / support[i]) if support[i] else None for i in range(classes)]
    balanced = float(np.mean(recall)) if all(value is not None for value in recall) else None
    accuracy = float(np.mean(y == prediction)) if y.size else None
    return {
        "rows": int(y.size),
        "support": support.tolist(),
        "correct_by_class": correct.tolist(),
        "recall_by_class": recall,
        "balanced_accuracy": balanced,
        "accuracy": accuracy,
    }


def query_only_cluster_interval(per_seed_accuracy: np.ndarray) -> dict:
    if per_seed_accuracy.shape != (8,):
        raise ValueError("QUERY_ONLY_TARGET requires exactly eight test seed groups")
    bootstrap = np.empty(10_000, dtype=np.float64)
    prefix = b"FAS_SENSOR_CI_V01" + struct.pack("<I", 20260923)
    for replicate in range(10_000):
        indices = [
            int.from_bytes(
                hashlib.sha256(prefix + struct.pack("<I", replicate) + struct.pack("<I", draw)).digest()[:8],
                "little",
            )
            % 8
            for draw in range(8)
        ]
        bootstrap[replicate] = float(np.mean(per_seed_accuracy[indices]))
    bootstrap.sort()
    return {
        "point_estimate": float(np.mean(per_seed_accuracy)),
        "lower_95": float(bootstrap[249]),
        "upper_95": float(bootstrap[9749]),
        "replicates": 10_000,
        "cluster": "world_seed",
        "seed_group_accuracy": per_seed_accuracy.tolist(),
    }


def self_test() -> None:
    x = np.array([[1.0, -2.0], [0.0, 0.5], [-1.0, 1.5], [2.0, 0.25]] * 8)
    y = np.array([0, 1, 2, 0] * 8, dtype=np.int16)
    scaled, mean, scale = scale_from_train(x)
    if not np.allclose(apply_scale(x, mean, scale), scaled):
        raise AssertionError("Train and evaluation scaling differ")
    parameters = np.linspace(-0.1, 0.1, 9, dtype=np.float64)
    _, gradient = objective_and_gradient(parameters, scaled, y, 3)
    for index in range(parameters.size):
        shifted = parameters.copy()
        shifted[index] += 1e-6
        plus = objective_and_gradient(shifted, scaled, y, 3)[0]
        shifted[index] -= 2e-6
        minus = objective_and_gradient(shifted, scaled, y, 3)[0]
        if abs((plus - minus) / 2e-6 - gradient[index]) > 1e-6:
            raise AssertionError("Analytic softmax gradient mismatch")
    model = fit(scaled, y, 3)
    if not model["converged"]:
        raise AssertionError(f"Synthetic solver did not converge: {model['solver_message']}")
    if metrics(y, predict(scaled, model["weights"], model["bias"]), 3)["rows"] != 32:
        raise AssertionError("Synthetic metric row count mismatch")
    ci_a = query_only_cluster_interval(np.linspace(0.25, 0.39, 8))
    ci_b = query_only_cluster_interval(np.linspace(0.25, 0.39, 8))
    if ci_a != ci_b or not math.isfinite(ci_a["upper_95"]):
        raise AssertionError("Deterministic seed-cluster bootstrap mismatch")
