"""The four zero-training score transforms of C-G1 (see PLAN.md), the threshold fit, and the gate. Pure functions over arrays of residual pairs.

`keys` identify the group a pair is normalised within: the world instance (one rendered input row), or the row and ordered type pair together.
"""
from __future__ import annotations

import numpy as np

METHODS = ("raw_logit", "world_percentile", "typepair_percentile", "robust_world_z")
GATE = {"0.01": {"pooled_loss": 0.02, "held_loss": 0.03}, "0.02": {"pooled_loss": 0.04, "held_loss": 0.05}}
GAIN_BAR = 0.05
IQR_FLOOR = 1e-6


def _groups(keys: np.ndarray, score: np.ndarray):
    """Sort by (key, score) and return the group structure of the sorted order."""
    order = np.lexsort((score, keys))
    k, s = keys[order], score[order]
    start_flag = np.r_[True, k[1:] != k[:-1]]
    group_id = np.cumsum(start_flag) - 1
    first = np.flatnonzero(start_flag)
    last = np.r_[first[1:] - 1, len(k) - 1]
    return order, k, s, group_id, first, last


def group_percentile(keys: np.ndarray, score: np.ndarray) -> np.ndarray:
    """For each pair, the fraction of its group's pairs with a score at or below its own (ties count as at-or-below, so a lone pair scores 1.0)."""
    order, k, s, group_id, first, last = _groups(keys, score)
    change = np.r_[True, (k[1:] != k[:-1]) | (s[1:] != s[:-1])]
    run_id = np.cumsum(change) - 1
    run_last = np.r_[np.flatnonzero(change)[1:] - 1, len(k) - 1]
    count = (last - first + 1)[group_id]
    at_or_below = run_last[run_id] - first[group_id] + 1
    out = np.empty(len(score))
    out[order] = at_or_below / count
    return out


def _interp(sorted_scores: np.ndarray, first: np.ndarray, count: np.ndarray, q: float) -> np.ndarray:
    """Linear-interpolated quantile q of each group's sorted scores (numpy's default method)."""
    position = q * (count - 1)
    lo = np.floor(position).astype(np.int64)
    hi = np.ceil(position).astype(np.int64)
    frac = position - lo
    return sorted_scores[first + lo] * (1 - frac) + sorted_scores[first + hi] * frac


def robust_z(keys: np.ndarray, score: np.ndarray) -> np.ndarray:
    """(score - group median) / group IQR, with the IQR floored."""
    order, k, s, group_id, first, last = _groups(keys, score)
    count = last - first + 1
    median = _interp(s, first, count, 0.5)
    iqr = np.maximum(_interp(s, first, count, 0.75) - _interp(s, first, count, 0.25), IQR_FLOOR)
    out = np.empty(len(score))
    out[order] = (s - median[group_id]) / iqr[group_id]
    return out


def transform(method: str, row: np.ndarray, pair_type: np.ndarray, score: np.ndarray) -> np.ndarray:
    """The transformed score of each residual pair. Lower means more clearly a non-edge."""
    if method == "raw_logit":
        return score.astype(np.float64)
    if method == "world_percentile":
        return group_percentile(row.astype(np.int64), score)
    if method == "typepair_percentile":
        return group_percentile(row.astype(np.int64) * 64 + pair_type.astype(np.int64), score)
    if method == "robust_world_z":
        return robust_z(row.astype(np.int64), score)
    raise KeyError(method)


def shuffle_within_rows(row: np.ndarray, score: np.ndarray, seed: int) -> np.ndarray:
    """Permute raw scores among each row's residual pairs (the leak control)."""
    rng = np.random.default_rng(seed)
    by_row = np.lexsort((np.arange(len(row)), row))
    permuted = np.lexsort((rng.random(len(row)), row))
    out = np.empty(len(score))
    out[by_row] = score[permuted]
    return out


def fit_threshold(transformed: np.ndarray, label: np.ndarray, total_edges: int, eps: float) -> float:
    """The largest threshold t (at a distinct transformed value) such that pruning every residual pair scoring at or below t loses at most floor(eps * total_edges) edges. -inf if none."""
    budget = int(np.floor(eps * total_edges + 1e-9))
    order = np.argsort(transformed, kind="stable")
    s, y = transformed[order], label[order].astype(np.int64)
    edges_below = np.cumsum(y)
    run_end = np.r_[s[1:] != s[:-1], True]
    ok = run_end & (edges_below <= budget)
    return float(s[np.flatnonzero(ok)[-1]]) if ok.any() else float("-inf")


def evaluate(transformed: np.ndarray, label: np.ndarray, threshold: float, total_edges: int, total_non_edges: int, t0_non_edges: int) -> dict:
    """Achieved edge loss, the pruned share of all non-edges (T0 + T1) and the gain over T0, in absolute points (as a fraction)."""
    pruned = transformed <= threshold
    lost = int((pruned & (label == 1)).sum())
    t1_non_edges = int((pruned & (label == 0)).sum())
    share = (t0_non_edges + t1_non_edges) / max(total_non_edges, 1)
    return {"edge_loss": lost / max(total_edges, 1), "pruned_share": share, "gain": share - t0_non_edges / max(total_non_edges, 1), "edges_lost": lost}


def gate(method_results: dict) -> dict:
    """method_results[eps] = {'pooled': eval, 'held': eval}. Passes iff every bound holds at both operating points."""
    checks = {}
    for eps, bounds in GATE.items():
        r = method_results[eps]
        checks[eps] = {"pooled_loss_ok": r["pooled"]["edge_loss"] <= bounds["pooled_loss"] + 1e-12, "held_loss_ok": r["held"]["edge_loss"] <= bounds["held_loss"] + 1e-12,
                       "gain_ok": r["pooled"]["gain"] >= GAIN_BAR - 1e-12}
    return {"checks": checks, "advances": all(all(c.values()) for c in checks.values())}
