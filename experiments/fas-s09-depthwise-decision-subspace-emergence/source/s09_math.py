from __future__ import annotations

from typing import Any

import numpy as np
import torch


PAIR_ORDER = ((0, 1), (0, 2), (1, 2))


def layer_surface_vectors(hidden_states: tuple[torch.Tensor, ...], sequence_length: int, dimension: int = 2048) -> torch.Tensor:
    """Return [layer, surface(M/F), dimension] from HF states; index zero is embeddings."""
    if len(hidden_states) != 17:
        raise RuntimeError(f"expected embedding plus 16 block outputs; received {len(hidden_states)} states")
    vectors = []
    for layer in range(1, 17):
        state = hidden_states[layer]
        if tuple(state.shape) != (1, sequence_length, dimension) or state.dtype != torch.float32:
            raise RuntimeError(f"unexpected layer-{layer} hidden state shape/dtype: {tuple(state.shape)} {state.dtype}")
        sequence = state[0]
        vectors.append(torch.stack((sequence.mean(dim=0), sequence[sequence_length - 1]), dim=0))
    result = torch.stack(vectors, dim=0)
    if tuple(result.shape) != (16, 2, dimension) or result.dtype != torch.float32:
        raise RuntimeError("layer surface extraction produced the wrong tensor shape or dtype")
    return result


def effective_geometry(weights: np.ndarray, bias: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> dict[str, Any]:
    w = np.asarray(weights, dtype=np.float64)
    b = np.asarray(bias, dtype=np.float64)
    mu = np.asarray(mean, dtype=np.float64)
    sd = np.asarray(scale, dtype=np.float64)
    if w.ndim != 2 or w.shape[0] != 3 or b.shape != (3,) or mu.shape != (w.shape[1],) or sd.shape != mu.shape:
        raise ValueError("probe geometry arrays have incompatible shapes")
    if not np.isfinite(w).all() or not np.isfinite(b).all() or not np.isfinite(mu).all() or not np.isfinite(sd).all() or np.any(sd <= 0):
        raise ValueError("probe geometry contains invalid values")
    normals = w / sd[None, :]
    intercepts = b - normals @ mu
    pair_normals = np.stack([normals[a] - normals[c] for a, c in PAIR_ORDER])
    pair_intercepts = np.asarray([intercepts[a] - intercepts[c] for a, c in PAIR_ORDER])
    _, singular_full, vh = np.linalg.svd(pair_normals, full_matrices=False)
    tol = max(pair_normals.shape) * np.finfo(np.float64).eps * (singular_full[0] if len(singular_full) else 0.0)
    rank = int(np.count_nonzero(singular_full > tol))
    return {
        "class_normals": normals,
        "class_intercepts": intercepts,
        "pair_normals": pair_normals,
        "pair_intercepts": pair_intercepts,
        "basis": vh[:rank].copy(),
        "singular_values": singular_full,
        "rank": rank,
        "rank_tolerance": float(tol),
    }


def subspace_comparison(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    ql = np.asarray(left["basis"], dtype=np.float64)
    qr = np.asarray(right["basis"], dtype=np.float64)
    if ql.ndim != 2 or qr.ndim != 2 or ql.shape[1] != qr.shape[1]:
        raise ValueError("subspace bases are incompatible")
    cosines = np.linalg.svd(ql @ qr.T, compute_uv=False) if len(ql) and len(qr) else np.empty(0, dtype=np.float64)
    cosines = np.clip(cosines, 0.0, 1.0)
    angles = np.degrees(np.arccos(cosines))
    denom = min(int(left["rank"]), int(right["rank"]))
    overlap = float(np.square(cosines).sum())
    return {
        "left_rank": int(left["rank"]),
        "right_rank": int(right["rank"]),
        "principal_cosines": cosines.tolist(),
        "principal_angle_degrees": angles.tolist(),
        "projection_overlap_squared_cosine_sum": overlap,
        "projection_overlap_fraction": overlap / denom if denom else 0.0,
    }


def logits_from_standardized(x: torch.Tensor, weights: np.ndarray, bias: np.ndarray, batch_rows: int = 16384) -> np.ndarray:
    w = torch.as_tensor(weights, dtype=torch.float32, device=x.device)
    b = torch.as_tensor(bias, dtype=torch.float32, device=x.device)
    pieces = []
    with torch.no_grad():
        for start in range(0, len(x), batch_rows):
            pieces.append(torch.nn.functional.linear(x[start:start + batch_rows], w, b).cpu().numpy().astype("<f4", copy=True))
    return np.concatenate(pieces, axis=0) if pieces else np.empty((0, len(bias)), dtype="<f4")


def margin_summaries(logits: np.ndarray, labels: np.ndarray) -> dict[str, Any]:
    values = np.asarray(logits, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    if values.ndim != 2 or values.shape[1] != 3 or y.shape != (len(values),):
        raise ValueError("margin inputs have incompatible shapes")
    rival = values.copy()
    rival[np.arange(len(y)), y] = -np.inf
    target_margin = values[np.arange(len(y)), y] - rival.max(axis=1)
    result: dict[str, Any] = {"support": int(len(y)), "target_vs_best_rival": describe(target_margin)}
    pairs = {}
    for a, b in PAIR_ORDER:
        margin = values[:, a] - values[:, b]
        pairs[f"class_{a}_minus_class_{b}"] = describe(margin)
    result["pairwise_class_margins"] = pairs
    return result


def describe(values: np.ndarray) -> dict[str, float]:
    x = np.asarray(values, dtype=np.float64)
    return {
        "mean": float(np.mean(x)),
        "median": float(np.median(x)),
        "p10": float(np.quantile(x, 0.1)),
        "p90": float(np.quantile(x, 0.9)),
        "std": float(np.std(x, ddof=0)),
    }


def transition_table(y_true: np.ndarray, source: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y_true, dtype=np.int64)
    a = np.asarray(source, dtype=np.int64)
    b = np.asarray(target, dtype=np.int64)
    table = np.zeros((3, 3), dtype=np.int64)
    for before, after in zip(a, b, strict=True):
        table[before, after] += 1
    return {
        "support": int(len(y)),
        "prediction_transition_from_to": table.tolist(),
        "both_correct": int(np.count_nonzero((a == y) & (b == y))),
        "source_only_correct": int(np.count_nonzero((a == y) & (b != y))),
        "target_only_correct": int(np.count_nonzero((a != y) & (b == y))),
        "both_incorrect": int(np.count_nonzero((a != y) & (b != y))),
    }
