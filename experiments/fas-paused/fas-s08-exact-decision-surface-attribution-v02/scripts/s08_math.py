from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from s08_common import PAIR_ORDER


CELL_RE = re.compile(r"^R_([MF])_C_([MF])_D_([MF])_W_([MF])$")


def effective_geometry(state: dict[str, np.ndarray]) -> dict[str, np.ndarray | int | float]:
    weights = state["weights"].astype(np.float64)
    bias = state["bias"].astype(np.float64)
    mean = state["replay_mean"].astype(np.float64)
    scale = state["replay_scale"].astype(np.float64)
    normals = weights / scale[None, :]
    intercepts = bias - normals @ mean
    pair_normals = np.stack([normals[a] - normals[b] for a, b in PAIR_ORDER])
    pair_intercepts = np.asarray([intercepts[a] - intercepts[b] for a, b in PAIR_ORDER])
    centered_bias_differences = np.asarray([bias[a] - bias[b] for a, b in PAIR_ORDER])
    _, singular, vh = np.linalg.svd(pair_normals, full_matrices=False)
    tol = max(pair_normals.shape) * np.finfo(np.float64).eps * (singular[0] if len(singular) else 0.0)
    rank = int(np.count_nonzero(singular > tol))
    basis = vh[:rank].copy()
    return {
        "class_normals": normals,
        "class_intercepts": intercepts,
        "pair_normals": pair_normals,
        "pair_intercepts": pair_intercepts,
        "centered_bias_differences": centered_bias_differences,
        "basis": basis,
        "singular_values": singular,
        "rank": rank,
        "rank_tolerance": float(tol),
    }


def affine_identity_residuals(
    hidden: np.ndarray,
    reference_margins: np.ndarray,
    pair_normals: np.ndarray,
    beta: np.ndarray,
    delta_b: np.ndarray,
    mean: np.ndarray,
) -> dict[str, float]:
    h = np.asarray(hidden, dtype=np.float64)
    reference = np.asarray(reference_margins, dtype=np.float64)
    normals = np.asarray(pair_normals, dtype=np.float64)
    affine_intercept = np.asarray(beta, dtype=np.float64)
    centered_bias = np.asarray(delta_b, dtype=np.float64)
    mu = np.asarray(mean, dtype=np.float64)
    if h.ndim != 2 or normals.ndim != 2:
        raise ValueError("Affine identity inputs have inconsistent ranks")
    if (reference.shape != (h.shape[0], normals.shape[0]) or normals.shape[1] != h.shape[1] or
            affine_intercept.shape != (normals.shape[0],) or
            centered_bias.shape != affine_intercept.shape or mu.shape != (h.shape[1],)):
        raise ValueError("Affine identity inputs have inconsistent shapes")
    raw = h @ normals.T + affine_intercept[None, :]
    centered = (h - mu[None, :]) @ normals.T + centered_bias[None, :]
    equivalent_beta = centered_bias - normals @ mu
    return {
        "raw_affine_max_abs_residual": float(np.max(np.abs(reference - raw))),
        "centered_max_abs_residual": float(np.max(np.abs(reference - centered))),
        "beta_equals_delta_minus_n_mu_max_abs_residual": float(np.max(np.abs(affine_intercept - equivalent_beta))),
    }


def subspace_comparison(m: dict[str, Any], f: dict[str, Any]) -> dict[str, Any]:
    qm = np.asarray(m["basis"], dtype=np.float64)
    qf = np.asarray(f["basis"], dtype=np.float64)
    cosine = np.linalg.svd(qm @ qf.T, compute_uv=False)
    cosine = np.clip(cosine, 0.0, 1.0)
    angles = np.degrees(np.arccos(cosine))
    denominator = min(int(m["rank"]), int(f["rank"]))
    overlap = float(np.square(cosine).sum())
    pm = np.asarray(m["pair_normals"], dtype=np.float64)
    pf = np.asarray(f["pair_normals"], dtype=np.float64)
    cosines = []
    for a, b in zip(pm, pf):
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        cosines.append(float(np.dot(a, b) / denom) if denom else 0.0)
    return {
        "principal_angle_degrees": angles.tolist(),
        "principal_cosines": cosine.tolist(),
        "projection_overlap_squared_cosine_sum": overlap,
        "projection_overlap_fraction": overlap / denominator if denominator else 0.0,
        "corresponding_pair_normal_cosines": cosines,
        "corresponding_pair_normal_angles_degrees": [float(np.degrees(np.arccos(np.clip(x, -1, 1)))) for x in cosines],
        "pair_normal_norms_M": np.linalg.norm(pm, axis=1).tolist(),
        "pair_normal_norms_F": np.linalg.norm(pf, axis=1).tolist(),
        "pair_intercepts_M": np.asarray(m["pair_intercepts"]).tolist(),
        "pair_intercepts_F": np.asarray(f["pair_intercepts"]).tolist(),
    }


def walsh_basis(cell_ids: list[str]) -> tuple[np.ndarray, list[str]]:
    masks = list(range(16))
    names = ["GRAND_MEAN"]
    names.extend("".join(f for bit, f in enumerate("RCDW") if mask & (1 << bit)) for mask in masks[1:])
    basis = np.empty((len(cell_ids), 16), dtype=np.float64)
    for i, cell in enumerate(cell_ids):
        match = CELL_RE.fullmatch(cell)
        if not match:
            raise ValueError(f"Bad S06 cell ID: {cell}")
        signs = np.asarray([1.0 if value == "F" else -1.0 for value in match.groups()])
        for mask in masks:
            basis[i, mask] = math.prod(signs[bit] for bit in range(4) if mask & (1 << bit))
    return basis, names


def walsh_transform(margins_by_cell: np.ndarray, basis: np.ndarray) -> tuple[np.ndarray, float]:
    # Input n × cell × pair; output n × pair × Walsh-term.
    coefficients = np.einsum("ncp,cs->nps", margins_by_cell, basis, optimize=True) / margins_by_cell.shape[1]
    reconstructed = np.einsum("nps,cs->ncp", coefficients, basis, optimize=True)
    residual = float(np.max(np.abs(reconstructed - margins_by_cell)))
    return coefficients, residual


def describe(values: np.ndarray) -> dict[str, float | int]:
    x = np.asarray(values, dtype=np.float64).reshape(-1)
    if x.size == 0 or not np.isfinite(x).all():
        raise ValueError("Cannot summarize empty or non-finite values")
    return {
        "n": int(x.size),
        "mean": float(x.mean()),
        "std_population": float(x.std()),
        "median": float(np.median(x)),
        "p10_nearest_rank": float(np.quantile(x, 0.10, method="inverted_cdf")),
        "p90_nearest_rank": float(np.quantile(x, 0.90, method="inverted_cdf")),
        "min": float(x.min()),
        "max": float(x.max()),
    }


def concentration_counts(abs_contributions: np.ndarray, fractions: tuple[float, ...] = (0.5, 0.8, 0.9, 0.95)) -> np.ndarray:
    x = np.asarray(abs_contributions, dtype=np.float64)
    if x.ndim < 1 or not np.isfinite(x).all() or np.any(x < 0):
        raise ValueError("Invalid coordinate contributions")
    ordered = np.sort(x, axis=-1)[..., ::-1]
    cumulative = np.cumsum(ordered, axis=-1)
    total = cumulative[..., -1]
    result = np.zeros(total.shape + (len(fractions),), dtype=np.uint16)
    for i, fraction in enumerate(fractions):
        threshold = total * fraction
        result[..., i] = np.where(total > 0, np.sum(cumulative < threshold[..., None], axis=-1) + 1, 0)
    return result


def top_indices(scores: np.ndarray, k: int) -> list[int]:
    values = np.asarray(scores, dtype=np.float64)
    if values.ndim != 1 or not np.isfinite(values).all() or not (0 < k <= values.size):
        raise ValueError("Invalid selector score vector or k")
    return sorted(range(values.size), key=lambda idx: (-values[idx], idx))[:k]


def matched_controls(selected: list[int], scores: np.ndarray, covariates: np.ndarray) -> list[int]:
    scores = np.asarray(scores, dtype=np.float64)
    covariates = np.asarray(covariates, dtype=np.float64)
    if covariates.ndim != 2 or covariates.shape[0] != scores.size or not np.isfinite(covariates).all():
        raise ValueError("Invalid matched-control covariates")
    center = covariates.mean(axis=0)
    scale = covariates.std(axis=0)
    scale[scale == 0] = 1.0
    standardized = (covariates - center) / scale
    selected_set = set(selected)
    available = set(range(scores.size)) - selected_set
    controls: list[int] = []
    for source in sorted(selected, key=lambda idx: (-scores[idx], idx)):
        if not available:
            raise ValueError("No unused control coordinate remains")
        distances = np.sum((standardized - standardized[source]) ** 2, axis=1)
        chosen = min(available, key=lambda idx: (distances[idx], idx))
        controls.append(chosen)
        available.remove(chosen)
    return controls


def classification_metrics(logits: np.ndarray, targets: np.ndarray) -> dict[str, Any]:
    scores = np.asarray(logits, dtype=np.float64)
    y = np.asarray(targets, dtype=np.int64)
    if scores.ndim != 2 or scores.shape != (y.size, 3) or y.size == 0:
        raise ValueError("Invalid logits or targets")
    pred = np.argmax(scores, axis=1)
    support = np.bincount(y, minlength=3)
    if np.any(support == 0):
        raise ValueError("A class is absent from the metric population")
    confusion = np.zeros((3, 3), dtype=np.int64)
    np.add.at(confusion, (y, pred), 1)
    recall = confusion.diagonal() / support
    margins = np.stack([scores[:, a] - scores[:, b] for a, b in PAIR_ORDER], axis=1)
    rival_logits = scores.copy()
    rival_logits[np.arange(y.size), y] = -np.inf
    target_margin = scores[np.arange(y.size), y] - rival_logits.max(axis=1)
    return {
        "n": int(y.size),
        "accuracy": float(np.mean(pred == y)),
        "balanced_accuracy": float(recall.mean()),
        "support_by_class": support.tolist(),
        "recall_by_class": recall.tolist(),
        "confusion_matrix_true_rows_predicted_columns": confusion.tolist(),
        "pairwise_margin_mean": margins.mean(axis=0).tolist(),
        "pairwise_margins": {
            f"class_{a}_minus_class_{b}": describe(margins[:, i])
            for i, (a, b) in enumerate(PAIR_ORDER)
        },
        "target_margin": describe(target_margin),
        "prediction_counts": np.bincount(pred, minlength=3).tolist(),
        "predictions": pred,
        "correct": pred == y,
    }


def transition_counts(before: np.ndarray, after: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    a = np.asarray(before, dtype=np.int64)
    b = np.asarray(after, dtype=np.int64)
    y = np.asarray(target, dtype=np.int64)
    confusion = np.zeros((3, 3), dtype=np.int64)
    np.add.at(confusion, (a, b), 1)
    ca, cb = a == y, b == y
    return {
        "prediction_transition_counts_rows_baseline_columns_intervened": confusion.tolist(),
        "correctness_transitions": {
            "both_correct": int(np.sum(ca & cb)),
            "baseline_only_correct": int(np.sum(ca & ~cb)),
            "intervention_only_correct": int(np.sum(~ca & cb)),
            "both_incorrect": int(np.sum(~ca & ~cb)),
        },
    }
